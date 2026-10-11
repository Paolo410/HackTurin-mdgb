"""Entry point: python -m smartcrossing.app --source 0|file.mp4|rtsp://... [--emulate-unoq] [--headless]

AI-M1: source + detector + tracker + overlay.
AI-M2: roles (pedestrian, cyclist, ...) and directional counting on the lines of calib.json.
AI-M3: metres and speeds from the calibration, pedestrian attributes, the explicit rule and the actuator.
AI-M4: animals, events from the trajectories and the C3 log for comms/ (metadata only, never frames).
AI-M5: optional thermal camera for the night (--thermal).
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import deque
from pathlib import Path
from time import perf_counter

import cv2

from .actuator import make_actuator
from .config import load_config, resolve_path
from .geometry import load_calib
from .health import Health
from .logger import C3Logger, c3_dir, flat_counts
from .mcu import C5FileTail, McuState
from .overlay import draw_hud, draw_lines, draw_state, draw_thermal, draw_tracks, draw_zones
from .pipeline import PHASES, LatencyStats, Pipeline
from .playlist import Playlist
from .sources import FrameSource, default_source
from .status_page import OperatorPage
from .thermal import ThermalFusion, make_thermal_source

_KEY_ESC = 27
_MIN_DT = 1e-6  # avoids a division by zero in the instantaneous FPS
_NO_FRAME_SLEEP_S = 0.05  # pause between two attempts when a live camera gives no frame
_HEALTH_PERIOD_S = 1.0    # check of the parts of the node, for the technician's page and the log


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m smartcrossing.app", description=__doc__.splitlines()[0])
    p.add_argument("--source", help="webcam index, video file or rtsp:// URL (default: first video in samples/, else 0)")
    p.add_argument("--profile", choices=["pc", "unoq"], default="pc")
    p.add_argument("--site", choices=["urbano", "lungofiume", "collina"])
    p.add_argument("--headless", action="store_true", help="no window, status lines on the terminal")
    p.add_argument("--emulate-unoq", action="store_true", help="UNO Q limits on the PC (FPS cap, threads, input size)")
    p.add_argument("--actuator", choices=["sim", "serial", "bridge"], default="sim")
    p.add_argument("--port", help="serial port of the firmware, with --actuator serial")
    p.add_argument("--thermal", choices=["none", "sim", "mlx90621", "mlx90640", "uvc"], default="none",
                   help="thermal camera: mlx90621 = the Grove 16x4 read by the MCU, sim = simulated")
    p.add_argument("--night", action="store_true", help="force night mode (to try the thermal fusion in daylight)")
    p.add_argument("--max-fps", type=float, help="override source.max_fps")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = until the source ends)")
    p.add_argument("--loop", action="store_true", help="play a video file again and again, in real time as if it "
                   "came from the camera (benchmark, live demo)")
    p.add_argument("--config", help="path to a config.yaml (default: ai/config.yaml)")
    p.add_argument("--calib", help="path to a calib.json (default: ai/calib.json, else ai/calib.example.json)")
    p.add_argument("--c3-dir", help="folder of the C3 event files (default: $MDGB_C3_DIR, else logs/c3 in the repo)")
    p.add_argument("--no-c3", action="store_true", help="do not write the C3 event files")
    p.add_argument("--operator-port", type=int, help="page for the technician on this port: after the badge and "
                                                     "a login it shows the numbers and, if enabled, a live view")
    return p.parse_args(argv)


def _fmt_ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config, args.profile, args.emulate_unoq)
    if args.max_fps is not None:
        cfg["source"]["max_fps"] = args.max_fps
    o = cfg["overlay"]

    try:
        calib, calib_path = load_calib(cfg, args.calib)
        actuator = make_actuator(args.actuator, cfg, **({"port": args.port} if args.port else {}))
        thermal_source = make_thermal_source(args.thermal, cfg, actuator)
        thermal = ThermalFusion(cfg, thermal_source, force_night=args.night) if thermal_source else None
        # Lines of the microcontroller (C5): from the Bridge through the actuator, and from the files of the
        # App Lab app of the sketch. The thermal camera, when there is one, reads the same lines.
        mcu = McuState(cfg)
        operator = None
        health = Health(on_change=lambda level, text: _health_changed(level, text, operator))

        def on_mcu_line(line: dict) -> None:
            """One C5 line: the state of the MCU, the check of the parts and the Registro of the page."""
            mcu.on_line(line)
            health.on_mcu_line(line)
            if operator is not None:
                _note_mcu_line(operator, line)

        handlers = [on_mcu_line] + ([thermal_source.on_mcu_line] if hasattr(thermal_source, "on_mcu_line") else [])
        actuator.set_listener(lambda line: [handle(line) for handle in handlers])
        events_dir = args.c3_dir or c3_dir(cfg)
        mcu_files = C5FileTail(events_dir, cfg["mcu"]["applab_series"], on_mcu_line, cfg["mcu"]["poll_s"])
        operator = OperatorPage(args.operator_port, mcu, cfg) if args.operator_port is not None else None
        source = FrameSource(args.source or default_source(cfg), cfg, loop=args.loop)
        pipeline = Pipeline(cfg, source.fps, calib, actuator, site=args.site, thermal=thermal)
        # A recorded video (tests, benchmarks): the technician's page can move to the previous / next video of
        # its folder or back / forward. Not with the camera.
        playlist = None if source.is_live else Playlist(source.name, args.calib)
        if operator is not None and playlist is not None:
            operator.video_control = playlist.request
    except (FileNotFoundError, RuntimeError, TypeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    stats = LatencyStats()
    log = C3Logger(cfg, args.c3_dir) if cfg["logger"]["enabled"] and not args.no_c3 else None

    threads = int(cfg["model"]["intra_op_num_threads"])
    setup = (f"source={source.name} profile={cfg['profile']} emulate_unoq={cfg['emulate_unoq']} "
             f"input_budget={pipeline.detector.input_size}px threads={threads or 'auto'} "
             f"max_fps={cfg['source']['max_fps'] or 'unlimited'} actuator={args.actuator} "
             f"site={pipeline.animals.site_name}")
    print(setup)
    print(f"c3={log.dir if log else 'off'}  mcu_files={events_dir}/{cfg['mcu']['applab_series']}-*.jsonl")
    if operator is not None:
        print(f"operator_page=:{operator.port} images={'on' if operator.share_images else 'off'} "
              f"login={'set' if operator.credentials else 'NOT SET (run scripts/operator_login.py): nobody can log in'}")
    metric = pipeline.geometry is not None and pipeline.geometry.metric
    print(f"calib={calib_path}" + ("" if metric else
                                  "  (no metric calibration: no speeds and no rule; run scripts/calibrate.py)"))
    if thermal is not None:
        print(f"thermal={args.thermal} zones={ {name: len(cols) for name, cols in thermal.zones.items()} }"
              + (" night forced" if args.night else ""))

    quit_keys = {ord(k) for k in o["quit_keys"]} | {_KEY_ESC}
    # Rate over the last frames, not between two frames: with the detector on one frame out of two the frames
    # arrive in pairs, and the time between the two of a pair says nothing.
    stamps: deque = deque(maxlen=int(o["fps_window_frames"]))
    fps = 0.0
    frames = 0
    last_state = None
    last_frame = None
    n_tracks = n_valid = 0
    page_lat = dict.fromkeys(PHASES, "-")
    # The clock starts at the first frame: opening the camera is not part of the frame rate.
    first = last = last_status = perf_counter()
    last_health = -float("inf")
    storage_error = None   # a C3 file that cannot be written must not stop the traffic light: only reported

    def annotate(view) -> None:
        """What the vision sees, drawn on the frame: for the window and for the technician's live view."""
        draw_zones(view, pipeline.geometry, cfg)
        draw_lines(view, pipeline.counter, cfg)
        draw_tracks(view, result, pipeline.tracker, cfg)
        draw_hud(view, [f"FPS {fps:.1f}   tracks {n_valid}/{n_tracks}", f"ms  {lat}", counts,
                        pipeline.events.summary(), setup], cfg)
        draw_thermal(view, pipeline.thermal, cfg)

    loops_seen, pass_frames, pass_t0, pass_dropped = 0, 0, perf_counter(), 0   # passes of a looped video
    pipeline.commander.start()   # heartbeat every 100 ms, only while this loop is alive
    mcu_files.start()
    def switch_video(step: int) -> None:
        """The previous / next video of the playlist with its calibration. Detector, link to the sketch, page and
        events stay; tracks, counts and rule start again for the new scene."""
        nonlocal source, pipeline, calib_path, setup, loops_seen, pass_frames, pass_t0, pass_dropped, stats
        video = playlist.move(step)
        try:
            example = resolve_path(cfg["counting"]["example_calib_path"])   # counting lines only: no metres
            new_calib, new_calib_path = load_calib(cfg, playlist.calib(video) or example)
            new_source = FrameSource(str(video), cfg, loop=args.loop)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"video {video.name}: cannot open ({exc}), staying on {source.name}")
            return
        new_pipeline = Pipeline(cfg, new_source.fps, new_calib, None, detector=pipeline.detector, site=args.site,
                                thermal=thermal)
        new_pipeline.detector.set_roi(new_calib.get("roi"))
        new_pipeline.commander = pipeline.commander          # the same heartbeat thread and link to the sketch
        loops_seen, pass_frames, pass_t0, pass_dropped, stats = 0, 0, perf_counter(), 0, LatencyStats()
        source.release()
        setup = setup.replace(f"source={source.name}", f"source={new_source.name}")   # the line on the image
        source, pipeline, calib_path = new_source, new_pipeline, new_calib_path
        print(f"video -> {video.name} ({playlist.index + 1}/{len(playlist.videos)}) calib={calib_path.name}")

    seek_s = float(cfg["operator"]["video_seek_s"])
    example_calib = resolve_path(cfg["counting"]["example_calib_path"]).resolve()

    def example_lines() -> bool:
        """True while the counting lines are those of the example calibration (no calibration for this view)."""
        return calib_path.resolve() == example_calib

    if example_lines():
        print("counting lines of the example calibration: crossings shown, NOT sent to the central (run calibrate.py)")
    try:
        while True:
            for action in playlist.take() if playlist is not None else []:   # commands of the technician's page
                if action in ("back", "fwd"):
                    source.seek(seek_s if action == "fwd" else -seek_s)
                else:
                    switch_video(1 if action == "next" else -1)
            pipeline.external_fault = mcu.fault()   # shock or lamp fault reported by the microcontroller
            # Technician at the node, from the badge to the logout: the sketch keeps the buzzer quiet.
            pipeline.technician = operator.technician_present() if operator is not None else mcu.unlocked()
            item = source.read()
            if item is None:
                if not source.is_live or frames == 0:
                    break
                # A live camera stopped giving frames: keep deciding (DEGRADED after the timeout) and retry.
                command = pipeline.no_frame(time.monotonic())
                result = None
                time.sleep(_NO_FRAME_SLEEP_S)
            else:
                frame, t = item
                if source.loops != loops_seen:   # a looped video started again: the numbers of the pass just ended
                    loops_seen, span = source.loops, perf_counter() - pass_t0
                    print(f"pass {loops_seen}: frames={pass_frames} in {span:.1f}s, FPS {max(pass_frames - 1, 0) / span:.1f}, "
                          f"late frames skipped {source.dropped - pass_dropped}")
                    print(stats.table(float(cfg["bench"]["percentile"])))
                    stats, pass_frames, pass_t0, pass_dropped = LatencyStats(), 0, perf_counter(), source.dropped
                pass_frames += 1
                result = pipeline.step(frame, t)
                command = result.command
                stats.add(result.lat_ms)
                frames += 1
                last_frame = frame

            now = perf_counter()
            if result is not None:
                if frames == 1:
                    first = last_status = now
                stamps.append(now)
                if len(stamps) > 1:
                    fps = (len(stamps) - 1) / max(stamps[-1] - stamps[0], _MIN_DT)
                last = now
                for event in result.events:
                    if event["type"] == "crossing":
                        print(f"t={now - first:6.1f}s crossing line={event['line']} dir={event['dir']} "
                              f"cls={event['cls']} track=#{event['track_id']}")
                    else:
                        details = " ".join(f"{k}={v}" for k, v in event.items() if k != "type")
                        print(f"t={now - first:6.1f}s {event['type']} {details}")
                    # With the example calibration the counting lines are not on the stripes of this scene: the
                    # crossings would reach the central as real ones. They stay on the screen only.
                    sent = not (event["type"] == "crossing" and example_lines())
                    if log and sent:
                        storage_error = _write_c3(log.write, event) or storage_error
                    if operator is not None:
                        operator.note(event["type"], _event_text(event, sent))
                for animal in pipeline.animals.new_sightings(pipeline.scene.animals):
                    print(f"t={now - first:6.1f}s animal track=#{animal.track_id} coco={animal.coco} size={animal.size} "
                          f"free={animal.free} on_road={animal.on_road}")
                if log and log.status_due():
                    storage_error = _write_c3(log.write_status, command["state"], fps, result.lat_ms,
                                              flat_counts(pipeline.counter.counts) if pipeline.counter else {})
                h, w = last_frame.shape[:2]
                health.seen("camera", {"w": w, "h": h, "fault": pipeline.fault, "lum": pipeline.luminance})
                if result.detected:
                    health.seen("vision", {"fps": fps, "detect_ms": result.lat_ms["detect"]})
            if command["state"] != last_state:
                last_state = command["state"]
                print(f"t={now - first:6.1f}s state={command['state']} led={command['led']} | {command['reason']}")
                if operator is not None:
                    operator.note("state", f"{command['state']}: {command['reason']}")
            link_failsafe = getattr(actuator, "connected", None) is False or bool(getattr(actuator, "failsafe", False))
            health.seen("link", {"failsafe": link_failsafe, "sim": args.actuator == "sim"})
            health.seen("storage", {"enabled": log is not None, "written": log.written if log else 0,
                                    "error": storage_error})
            if now - last_health >= _HEALTH_PERIOD_S:   # also without the page: the changes go in the log
                last_health = now
                report = health.evaluate()
                if operator is not None:
                    operator.health = report

            counts = pipeline.counter.summary() if pipeline.counter else "no counting lines"
            if result is not None:
                n_tracks, n_valid = len(result.tracked), int(result.valid.sum())
                lat = " ".join(f"{phase}={_fmt_ms(result.lat_ms[phase])}" for phase in PHASES)
            if operator is not None:   # also without frames: the page must say DEGRADED, not the last good state
                if result is not None:
                    page_lat = {phase: _fmt_ms(result.lat_ms[phase]) for phase in PHASES}
                operator.update({
                    "state": command["state"], "led": command["led"], "reason": command["reason"],
                    "green_s": command["green_s"], "fps": round(fps, 1), "tracks": n_valid, "counts": counts,
                    "lat_ms": page_lat,
                    "events": pipeline.events.summary(), "source": Path(source.name).name, "calib": calib_path.name,
                    "counts_sent": not example_lines(),
                    "video": None if playlist is None else {
                        "name": playlist.current.name, "index": playlist.index + 1, "total": len(playlist.videos),
                        "pos_s": round(source.position_s, 1), "dur_s": round(source.duration_s, 1),
                        "calib": calib_path.name if calib_path.parent.name == "calib" else None, "seek_s": seek_s},
                    "link_failsafe": link_failsafe,
                    "lines": _lines(pipeline.counter),
                    "stats": {"yield_rate": pipeline.events.yield_rate, "near_miss": pipeline.events.near_misses,
                              "incidents": pipeline.events.incidents},
                })
            # Live view for the technician: drawn only when a logged-in technician is watching and images are on.
            share = operator is not None and result is not None and operator.wants_frame()
            if args.headless:
                if result is not None and now - last_status >= float(o["status_every_s"]):
                    print(f"t={now - first:6.1f}s frame={frames} fps={fps:.1f} ms[{lat}] "
                          f"tracks={n_tracks} valid={n_valid} state={command['state']} | {counts}")
                    last_status = now
                if share:
                    annotate(last_frame)
                    draw_state(last_frame, command, cfg, failsafe=bool(getattr(actuator, "failsafe", False)))
                    operator.push_frame(last_frame)
            else:
                view = last_frame if result is not None else last_frame.copy()
                if result is not None:
                    annotate(view)
                draw_state(view, command, cfg, failsafe=bool(getattr(actuator, "failsafe", False)))
                if share:
                    operator.push_frame(view)
                cv2.imshow(o["window_name"], view)
                if cv2.waitKey(1) & 0xFF in quit_keys:
                    break
                if cv2.getWindowProperty(o["window_name"], cv2.WND_PROP_VISIBLE) < 1:
                    break
            if args.max_frames and frames >= args.max_frames:
                break
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.commander.close()
        mcu_files.close()
        if operator is not None:
            operator.close()
        source.release()
        if log:
            log.close()
        if not args.headless:
            cv2.destroyAllWindows()

    # Frame intervals between the first and the last frame.
    elapsed = last - first
    end_to_end = (frames - 1) / elapsed if frames > 1 and elapsed > 0 else 0.0
    print(f"\nframes={frames} elapsed={elapsed:.1f}s end-to-end FPS={end_to_end:.1f}")
    if not source.is_live:
        print(f"video  passes={source.loops + 1} late frames skipped={source.dropped}")
    print(stats.table(float(cfg["bench"]["percentile"])))
    print("counts  " + (pipeline.counter.summary() if pipeline.counter else "no counting lines"))
    print("events  " + pipeline.events.summary())
    if thermal is not None:
        print(thermal.summary())
        thermal_source.close()
    if log and log.written:
        print(f"c3  {log.written} lines, last file {log.path}")
    sent = len(getattr(actuator, "sent", []))
    if sent:
        print(f"actuator  C1 sent={sent} heartbeats={actuator.heartbeats}")
    return 0


def _health_changed(level: str, text: str, operator) -> None:
    """A part of the node changed status: on the terminal (journalctl) and in the Registro of the page."""
    print(f"diagnosi: {text}")
    if operator is not None:
        operator.note("diag", text)


def _note_mcu_line(operator, line: dict) -> None:
    """The lines of the MCU worth a line in the Registro: shock, badge, fail-safe of the sketch."""
    kind, code = line.get("type"), line.get("code")
    if kind == "tamper" and code == 3:
        operator.note("rfid", "badge del tecnico letto")
    elif kind == "tamper":
        operator.note("alarm", "urto o apertura: antifurto")
    elif kind == "failsafe":
        operator.note("link", f"lo sketch è passato in fail-safe ({line.get('reason', '?')})")
    elif kind == "lamp_fault":
        operator.note("alarm", "guasto della lampada")


def _event_text(event: dict, sent: bool) -> str:
    """An event of the vision for the Registro (the page turns it into Italian)."""
    if event["type"] == "crossing":
        return (f"{event['cls']} #{event['track_id']} {str(event['dir']).upper()} linea {event['line']}"
                + ("" if sent else ", non inviato alla centrale"))
    return " ".join(f"{k}={v}" for k, v in event.items() if k != "type")


def _lines(counter) -> dict:
    """IN/OUT of each counting line, in total and per role, for the page."""
    if counter is None:
        return {}
    return {name: {**counter.totals(name), "roles": counter.counts[name]} for name in counter.lines}


def _write_c3(write, *args) -> str | None:
    """Writes a C3 line. A full disk or a missing folder is reported to the technician, the vision goes on."""
    try:
        write(*args)
    except OSError as exc:
        return exc.strerror or str(exc)
    return None


if __name__ == "__main__":
    sys.exit(main())
