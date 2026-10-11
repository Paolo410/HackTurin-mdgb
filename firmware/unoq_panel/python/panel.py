"""MDGB technician's panel for the App Lab app WITHOUT the vision inside (the mdgb app of code1.zip).

The vision runs as a separate service (ai/deploy/run_vision.sh or mdgb-ai) and keeps the camera. This module never
opens the camera and never talks to the vision. It only:
- receives from main.py the notifications of the sketch (sensors, traffic light phase, badge, shock alarm);
- reads the C3 lines that the vision writes in data/c3 of this app (status every 5 s, crossings, near misses),
  present when the vision was installed with `push_to_arduino.sh --applab mdgb`;
- sends the page (assets/) a "health" message once a second and a "vision" message without image.
It writes nothing to disk and does not register "mcu_event": the vision service already receives those lines,
and the router accepts one receiver per function.

The page, health.py and the sketch are the same files as firmware/unoq_mcu/ (copied by build_applab_zip.py --panel).
"""
from __future__ import annotations

import glob
import json
import os
import threading
import time
from collections import deque

from arduino.app_utils import Logger

from health import FAULT, Health, panel_parts

logger = Logger("mdgb-panel")

# Folder where the vision service writes its C3 lines: ~/ArduinoApps/mdgb/data/c3 seen from the app container.
# TODO(verify): /app is the folder of the app inside the App Lab container (as in comms/applab/mdgb_link.py).
C3_DIR = os.environ.get("MDGB_C3_DIR") or ("/app/data/c3" if os.path.isdir("/app") else os.path.join("data", "c3"))
C3_PATTERN = "c3-*.jsonl"          # files of the vision (ai/config.yaml, logger.prefix)
C3_TAIL_BYTES = 32768              # at start only the end of the newest file is read, for the last status line
VISION_PAGE_PORT = 8090            # technician's page of the vision service (ai/smartcrossing/status_page.py)
POLL_S = 0.5
HEALTH_PERIOD_S = 1.0
EVENT_LOG_LEN = 100                # last events kept for the page (memory only)
NOTE_REPEAT_S = 5.0                # the same log line again within this time is dropped


class C3Reader:
    """Follows the c3-*.jsonl files: returns the complete new lines since the last call."""

    def __init__(self, directory: str, pattern: str):
        self.directory, self.pattern = directory, pattern
        self._offsets: dict[str, int] = {}
        self._first = True

    def poll(self) -> list[dict]:
        files = sorted(glob.glob(os.path.join(self.directory, self.pattern)))
        lines: list[dict] = []
        if self._first:
            # The history is not replayed: only the last status line of the newest file, to fill the page at once.
            self._first = False
            for path in files:
                self._offsets[path] = os.path.getsize(path)
            if files:
                status = [d for d in self._parse(self._tail(files[-1])) if d.get("type") == "status"]
                lines += status[-1:]
            return lines
        for path in files:
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            offset = self._offsets.get(path, 0)
            if size < offset:          # file truncated or replaced
                offset = 0
            if size == offset:
                continue
            with open(path, "rb") as fh:
                fh.seek(offset)
                data = fh.read(size - offset)
            end = data.rfind(b"\n") + 1  # only complete lines; the rest is read next time
            self._offsets[path] = offset + end
            lines += self._parse(data[:end])
        self._offsets = {p: o for p, o in self._offsets.items() if p in files}
        return lines

    @staticmethod
    def _tail(path: str) -> bytes:
        with open(path, "rb") as fh:
            fh.seek(max(0, os.path.getsize(path) - C3_TAIL_BYTES))
            return fh.read()

    @staticmethod
    def _parse(data: bytes) -> list[dict]:
        out = []
        for raw in data.splitlines():
            try:
                item = json.loads(raw)
            except ValueError:
                continue                 # first partial line of a tail, or garbage
            if isinstance(item, dict):
                out.append(item)
        return out


def lines_from_counts(counts: dict) -> dict:
    """Flat counts of the status line ({"ped_in": 14, "car_in": 52}) -> rows for the page, by group and role."""
    lines: dict = {}
    for key, n in (counts or {}).items():
        role, _, direction = key.rpartition("_")
        if direction not in ("in", "out") or not role:
            continue
        role = "pedestrian" if role == "ped" else role
        line = lines.setdefault("Pedoni" if role == "pedestrian" else "Veicoli e bici", {"in": 0, "out": 0, "roles": {}})
        line[direction] += int(n)
        line["roles"].setdefault(role, {"in": 0, "out": 0})[direction] += int(n)
    return lines


class Panel:
    def __init__(self):
        self.health = Health(panel_parts(), on_change=self._health_changed)
        self.log: deque = deque(maxlen=EVENT_LOG_LEN)
        self.ui = None
        self._viewers: set[str] = set()
        self._status: dict | None = None     # last status line of the vision
        self._status_t = 0.0
        self._counters = {"near_miss": 0, "incident": 0}
        self._started = time.time()
        self._reader = C3Reader(C3_DIR, C3_PATTERN)

    # ---------- called by main.py (Bridge threads): store only ----------

    def seen(self, key: str, value) -> None:
        self.health.seen(key, value)

    def led_status(self, msg: str) -> None:
        """Traffic light phase and vision link, from the led_status messages of the sketch."""
        for word, lamp in (("VERDE", "green"), ("GIALLO", "yellow"), ("ROSSO", "red")):
            if f"LED {word}" in msg:
                self.health.seen("lamp", lamp)
        if "VISIONE" in msg:
            self.health.seen("link", "connected")
            self.note("link", msg)
        elif "FAIL-SAFE" in msg:
            self.health.seen("link", "failsafe")
            self.note("link", msg)

    def badge(self, tag_id: str) -> None:
        tail = f"...{str(tag_id)[-4:]}"          # never the full code on the page
        self.note("rfid", f"badge letto: {tail}")
        self.health.seen("rfid", f"badge {tail}")

    def note(self, kind: str, text: str) -> None:
        """One line of the log of the page. The same line within NOTE_REPEAT_S is dropped (the shock alarm repeats)."""
        now = time.time()
        last = self.log[-1] if self.log else None
        if last and last["type"] == kind and last["text"] == text and now - last["ts"] < NOTE_REPEAT_S:
            return
        self.log.append({"ts": round(now, 1), "type": kind, "text": text})

    # ---------- page ----------

    def start(self, ui) -> None:
        self.ui = ui
        ui.on_connect(self._on_connect)
        ui.on_disconnect(lambda sid: self._viewers.discard(sid))
        threading.Thread(target=self._loop, name="mdgb-panel", daemon=True).start()
        logger.info(f"technician's panel on, vision events read from {C3_DIR}/{C3_PATTERN}")

    def _on_connect(self, sid: str) -> None:
        self._viewers.add(sid)
        self.ui.send_message("config", {"mode": "panel", "live": False, "vision_port": VISION_PAGE_PORT})

    def _health_changed(self, level: str, text: str) -> None:
        (logger.warning if level == "warning" else logger.info)(f"diagnosi: {text}")
        self.note("diag", text)

    def _loop(self) -> None:
        next_health = 0.0
        while True:
            try:
                for line in self._reader.poll():
                    self._on_c3(line)
            except OSError as exc:
                logger.warning(f"C3 files not readable in {C3_DIR}: {exc}")
            now = time.monotonic()
            if now >= next_health:
                next_health = now + HEALTH_PERIOD_S
                report = self.health.evaluate()   # also when nobody watches: the changes go in the log
                if self._viewers:
                    self._publish("health", {**report, "log": list(self.log),
                                             "uptime_s": round(time.time() - self._started)})
                    self._publish("vision", self._vision(report))
            time.sleep(POLL_S)

    def _on_c3(self, line: dict) -> None:
        kind = line.get("type")
        if kind == "status":
            self._status, self._status_t = line, time.monotonic()
            self.health.seen("camera", line)
            self.health.seen("ai", line)
        elif kind == "crossing":
            self.note("crossing", f"{line.get('cls')} #{line.get('track_id')} {str(line.get('dir')).upper()} "
                                  f"linea {line.get('line')}")
        elif kind:
            if kind in self._counters:
                self._counters[kind] += 1
            self.note(kind, " ".join(f"{k}={v}" for k, v in line.items() if k not in ("v", "ts", "type")))

    def _vision(self, report: dict) -> dict:
        """What the page shows about the vision, from its last status line (no image, no boxes)."""
        checks = {c["key"]: c for c in report["checks"]}
        fresh = self._status is not None and checks["camera"]["status"] != FAULT
        st = self._status or {}
        return {
            "state": st.get("state", "UNKNOWN") if fresh else "UNKNOWN",
            "reason": ("Motivo e richieste alla centralina: sulla pagina della visione." if fresh
                       else "Nessuna notizia recente dalla visione: vedi Controllo sensori."),
            "failsafe": checks["link"]["value"] == "failsafe", "boxes": [],
            "fps": st.get("fps") if fresh else None, "lat_ms": st.get("lat_ms") if fresh else None,
            "lines": lines_from_counts(st.get("counts")),
            "stats": {"yield_rate": None, "near_miss": self._counters["near_miss"],
                      "incidents": self._counters["incident"]},
            "link": {},
        }

    def _publish(self, kind: str, msg: dict) -> None:
        try:
            self.ui.send_message(kind, msg)
        except Exception as exc:     # the page is optional: the traffic light must not depend on it
            logger.warning(f"web page not updated: {exc!r}")
