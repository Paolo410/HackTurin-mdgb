"""MDGB vision inside the App Lab app: camera -> smartcrossing (the package of ai/) -> sketch and web page.

Same pipeline as `python -m smartcrossing.app --profile unoq --actuator bridge`, but in the container of the app:
- the camera is read with the Camera peripheral of App Lab, so no other process may hold it;
- C1/C2 go to the sketch with Bridge.call("mdgb_line", line) of arduino.app_utils, the C5 lines of the sketch
  ("mcu_event") come back through main.py;
- the web page (assets/) gets, a few times a second, the frame as JPEG plus the boxes of the tracks, and draws
  the boxes itself. Frames are never written to disk and are encoded only while a browser is connected.

The smartcrossing package, config.yaml, the calibration and the model are copied next to this file by
firmware/tools/build_applab_zip.py: the code stays in ai/, here there is only the glue.

App Lab APIs (checked in https://github.com/arduino/app-bricks-py):
- Bridge.call(method, *params, timeout=10), Bridge.provide(method, handler)   src/arduino/app_utils/bridge.py
- Camera(source, resolution, fps); start(), capture() -> np.ndarray | None    src/arduino/app_peripherals/camera
- WebUI.send_message(type, message), on_connect(cb(sid)), on_disconnect(cb(sid))   src/arduino/app_bricks/web_ui
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import traceback

import cv2

# C3 events in the data folder of the app (~/ArduinoApps/<app>/data/c3 on the board), where comms/ reads them.
os.environ.setdefault("MDGB_C3_DIR", "/app/data/c3" if os.path.isdir("/app") else os.path.join("data", "c3"))

from arduino.app_peripherals.camera import Camera  # noqa: E402
from arduino.app_utils import Bridge, Logger  # noqa: E402

from smartcrossing.config import load_config  # noqa: E402
from smartcrossing.geometry import load_calib  # noqa: E402
from smartcrossing.logger import C3Logger, flat_counts  # noqa: E402
from smartcrossing.mcu import McuState  # noqa: E402
from smartcrossing.overlay import KMH, ROLE_GROUP  # noqa: E402
from smartcrossing.pipeline import PHASES, Pipeline  # noqa: E402

logger = Logger("mdgb-vision")

PROFILE = "unoq"                                     # ai/config.yaml: detector one frame out of two, 3 threads
# None = first free camera (USB first, then CSI). "csi:0" = the IMX219 of the Media Carrier.
CAMERA_SOURCE = os.environ.get("MDGB_CAMERA") or None
CAMERA_RESOLUTION = (640, 480)                       # the full 1920x1080 alone takes ~85% of a core
CAMERA_FPS = 15
NO_FRAME_SLEEP_S = 0.05                              # pause between two attempts when the camera gives no frame
RESTART_S = 5.0                                      # the vision restarts after a crash (fail-safe meanwhile)
STATUS_LOG_S = 10.0                                  # period of the status line in the App Lab console
LIVE_VIEW = os.environ.get("MDGB_LIVE_VIEW", "1") != "0"   # 0 = the page gets only numbers, no image
VIEW_FPS = 5
VIEW_JPEG_QUALITY = 70
FPS_WINDOW = 20                                      # frames used for the FPS shown


class AppLabActuator:
    """C1/C2 to the sketch over the Bridge of App Lab (sketch: Bridge.provide_safe("mdgb_line", ...)).

    Like comms/actuators.py BridgeActuator: a background thread sends the latest C1 and the latest C2, so the
    vision loop and the heartbeat thread never wait for the MCU. "reason" is not sent: the sketch does not use
    it and the request buffer of the MCU is small (firmware/DECISIONS.md, Bridge)."""

    LINE_METHOD = "mdgb_line"
    CALL_TIMEOUT_S = 0.3        # a C2 goes out every 100 ms: a later answer is useless anyway
    STALE_S = 0.5               # a line older than this is not sent any more
    FAILSAFE_S = 0.5            # same timeout as the sketch: without accepted heartbeats it is in fail-safe
    WARN_EVERY_S = 10.0

    def __init__(self):
        self.sent = 0
        self.heartbeats = 0
        self.rejected = 0
        self._last_hb_ok: float | None = None
        self._cv = threading.Condition()
        self._pending_cmd: tuple[float, str] | None = None
        self._pending_hb: tuple[float, str] | None = None
        self._closed = False
        self._last_warn = 0.0
        self._thread = threading.Thread(target=self._run, name="mdgb-bridge", daemon=True)
        self._thread.start()

    @property
    def failsafe(self) -> bool:
        return self._last_hb_ok is None or time.monotonic() - self._last_hb_ok > self.FAILSAFE_S

    @property
    def connected(self) -> bool:
        return not self.failsafe

    def send(self, cmd: dict) -> None:
        line = json.dumps({k: v for k, v in cmd.items() if k != "reason"}, separators=(",", ":"), ensure_ascii=True)
        with self._cv:
            self._pending_cmd = (time.monotonic(), line)
            self._cv.notify()

    def heartbeat(self, seq: int) -> None:
        with self._cv:
            self._pending_hb = (time.monotonic(), json.dumps({"v": 1, "hb": int(seq)}, separators=(",", ":")))
            self._cv.notify()

    def set_listener(self, cb) -> None:
        pass   # the C5 lines come from main.py (Bridge.provide("mcu_event", ...)), not from here

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify()
        self._thread.join(timeout=1.0)

    def _run(self) -> None:
        while True:
            with self._cv:
                while not self._closed and self._pending_cmd is None and self._pending_hb is None:
                    self._cv.wait()
                if self._closed:
                    return
                pending = [p for p in (self._pending_cmd, self._pending_hb) if p is not None]
                self._pending_cmd = self._pending_hb = None
            for t, line in pending:
                if time.monotonic() - t > self.STALE_S:
                    continue
                try:
                    ok = Bridge.call(self.LINE_METHOD, line, timeout=self.CALL_TIMEOUT_S)
                except Exception as exc:        # timeout or router down: the sketch falls back by itself
                    self._warn(f"{self.LINE_METHOD} not delivered: {exc!r}")
                    continue
                if ok is False:
                    self.rejected += 1
                    self._warn(f"the sketch rejected: {line}")
                elif '"hb"' in line:
                    self.heartbeats += 1
                    self._last_hb_ok = time.monotonic()
                else:
                    self.sent += 1

    def _warn(self, msg: str) -> None:
        now = time.monotonic()
        if now - self._last_warn >= self.WARN_EVERY_S:
            logger.warning(msg)
            self._last_warn = now


def boxes_of(result, tracker) -> list[dict]:
    """Boxes of the tracks for the web page: pixel corners, track ID, role and a label like the overlay of ai/."""
    tracked = result.tracked
    if tracked.tracker_id is None:
        return []
    boxes = []
    for i, (xyxy, score, track_id, valid) in enumerate(
            zip(tracked.xyxy, tracked.confidence, tracked.tracker_id, result.valid)):
        state = tracker.tracks.get(int(track_id))
        role = result.roles[i] if i < len(result.roles) else (state.class_name if state else "?")
        label = f"#{int(track_id)} {role} {float(score):.2f}"
        if state is not None and state.speed_samples > 0:
            label += f" {state.speed * KMH:.0f} km/h"
            flags = [flag for flag in ("child", "slow") if state.attrs.get(flag)]
            if state.attrs.get("aid") not in (None, "normal"):
                flags.append(state.attrs["aid"])
            if flags:
                label += " " + "+".join(flags)
        x1, y1, x2, y2 = (round(float(v), 1) for v in xyxy)
        boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "id": int(track_id), "role": role,
                      "group": ROLE_GROUP.get(role, "animal") if valid else "pending", "label": label})
    return boxes


class VisionService:
    def __init__(self, ui):
        self.ui = ui
        self.cfg = load_config(profile=PROFILE)
        self.mcu = McuState(self.cfg)
        self._viewers: set[str] = set()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run_forever, name="mdgb-vision", daemon=True)
        ui.on_connect(self._on_connect)
        ui.on_disconnect(lambda sid: self._viewers.discard(sid))

    def start(self) -> None:
        self._thread.start()

    def on_mcu_line(self, line) -> None:
        """One C5 line of the sketch (Bridge "mcu_event"). Runs in the Bridge thread: only parse and store."""
        try:
            self.mcu.on_line(json.loads(line.decode("utf-8") if isinstance(line, bytes) else str(line)))
        except (ValueError, TypeError):
            logger.warning(f"C5 line not valid: {line!r}")

    def _on_connect(self, sid: str) -> None:
        self._viewers.add(sid)
        self.ui.send_message("config", {"live": LIVE_VIEW, "profile": PROFILE})

    def _run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self._run()
            except Exception:
                logger.error("vision stopped, restarting in %.0f s:\n%s" % (RESTART_S, traceback.format_exc()))
                self._publish({"state": "DEGRADED", "reason": "vision restarting", "boxes": []})
                self._stop.wait(RESTART_S)

    def _run(self) -> None:
        cfg = self.cfg
        calib, calib_path = load_calib(cfg)
        actuator = AppLabActuator()
        pipeline = Pipeline(cfg, float(cfg["source"]["max_fps"]) or CAMERA_FPS, calib, actuator)
        log = C3Logger(cfg) if cfg["logger"]["enabled"] else None
        camera = Camera(CAMERA_SOURCE, resolution=CAMERA_RESOLUTION, fps=CAMERA_FPS)
        camera.start()
        logger.info(f"vision on: camera={CAMERA_SOURCE or 'auto'} {CAMERA_RESOLUTION} profile={PROFILE} "
                    f"input={pipeline.detector.input_size}px calib={calib_path.name} c3={log.dir if log else 'off'}")

        max_fps = float(cfg["source"]["max_fps"])
        resize_width = int(cfg["source"]["resize_width"])
        stamps: list[float] = []
        fps, frames, last_state = 0.0, 0, None
        last_view = last_log = 0.0
        pipeline.commander.start()   # heartbeat every 100 ms, only while this loop is alive
        try:
            while not self._stop.is_set():
                loop_t = time.monotonic()
                pipeline.external_fault = self.mcu.fault()
                pipeline.technician = self.mcu.unlocked()
                frame = camera.capture()
                if frame is None:
                    command, result = pipeline.no_frame(time.monotonic()), None
                    time.sleep(NO_FRAME_SLEEP_S)
                else:
                    # TODO(verify): channel order of Camera.capture() on the board; BGR expected (OpenCV inside).
                    h, w = frame.shape[:2]
                    if resize_width > 0 and w > resize_width:
                        frame = cv2.resize(frame, (resize_width, round(h * resize_width / w)),
                                           interpolation=cv2.INTER_AREA)
                    result = pipeline.step(frame, time.monotonic())
                    command = result.command
                    frames += 1
                    stamps = (stamps + [time.monotonic()])[-FPS_WINDOW:]
                    if len(stamps) > 1:
                        fps = (len(stamps) - 1) / max(stamps[-1] - stamps[0], 1e-6)
                    for event in result.events:
                        logger.info("event " + " ".join(f"{k}={v}" for k, v in event.items()))
                        if log:
                            log.write(event)
                    if log and log.status_due():
                        log.write_status(command["state"], fps, result.lat_ms,
                                         flat_counts(pipeline.counter.counts) if pipeline.counter else {})

                if command["state"] != last_state:
                    last_state = command["state"]
                    logger.info(f"state={command['state']} led={command['led']} | {command['reason']}")
                now = time.monotonic()
                if now - last_log >= STATUS_LOG_S and result is not None:
                    last_log = now
                    logger.info(f"frames={frames} fps={fps:.1f} tracks={int(result.valid.sum())} "
                                f"C1={actuator.sent} C2={actuator.heartbeats} failsafe={actuator.failsafe}")
                if self._viewers and now - last_view >= 1.0 / VIEW_FPS:
                    last_view = now
                    self._publish(self._view(command, result, frame, pipeline, actuator, fps))

                if max_fps > 0:   # same cap as the unoq profile of ai/
                    wait = 1.0 / max_fps - (time.monotonic() - loop_t)
                    if wait > 0:
                        time.sleep(wait)
        finally:
            pipeline.commander.close()   # stops the heartbeat: the sketch goes back to the normal cycle
            camera.stop()
            if log:
                log.close()

    def _view(self, command, result, frame, pipeline, actuator, fps) -> dict:
        req = command.get("req", {})
        msg = {
            "state": command["state"], "led": command["led"], "reason": command["reason"],
            "green_s": command.get("green_s"), "req": req, "lcd": command.get("lcd"), "oled": command.get("oled"),
            "fps": round(fps, 1), "failsafe": actuator.failsafe,
            "counts": pipeline.counter.summary() if pipeline.counter else "",
            "events": pipeline.events.summary(), "boxes": [],
        }
        if result is not None:
            msg["boxes"] = boxes_of(result, pipeline.tracker)
            msg["lat_ms"] = {p: (None if result.lat_ms[p] is None else round(result.lat_ms[p], 1)) for p in PHASES}
            h, w = frame.shape[:2]
            msg["w"], msg["h"] = w, h
            if LIVE_VIEW:
                ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, VIEW_JPEG_QUALITY])
                if ok:
                    msg["jpg"] = base64.b64encode(jpg.tobytes()).decode("ascii")
        return msg

    def _publish(self, msg: dict) -> None:
        try:
            self.ui.send_message("vision", msg)
        except Exception as exc:     # the page is optional: the traffic light must not depend on it
            logger.warning(f"web page not updated: {exc!r}")
