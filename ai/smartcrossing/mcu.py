"""What the microcontroller tells the vision: C5 lines of docs/CONTRACTS.md (shock, technician's badge,
environment, fail-safe, lamp fault).

The lines arrive from two places, and both end in McuState.on_line:
- the Bridge: lines the sketch sends with Bridge.notify("mcu_event", ...), handed over by the actuator
  (comms/actuators.py, Actuator.set_listener);
- the files applab-*.jsonl that the App Lab app of the sketch writes in the C3 folder
  (comms/applab/mdgb_link.py): C5FileTail follows them. This way the sensors, the shock alarm and the
  badge reach the vision with the sketch as it is, and nothing is reported twice to the central.

What the vision does with them:
- badge of the technician (tamper code 3): opens the technician's page for operator.unlock_s (then the
  technician logs in with user name and password, see status_page.py);
- shock or open case (tamper code 1, 2): it is the anti-theft alarm of the node. The vision keeps working
  as before and only shows it on the technician's page. Telling the central that the node was tampered
  with is the job of the network part (comms/), to be wired when the two parts are merged;
- lamp_fault: DEGRADED while the firmware keeps reporting it;
- env, failsafe: only shown on the technician's page.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable

BADGE_CODE = 3                       # (CONTRACTS, C5) tamper code of an authorised opening
_NOT_VALUES = ("v", "src", "type", "ts")


class McuState:
    def __init__(self, cfg: dict, monotonic: Callable[[], float] = time.monotonic):
        self.lamp_fault_hold_s = float(cfg["mcu"]["lamp_fault_hold_s"])
        self.unlock_s = float(cfg["operator"]["unlock_s"])
        self._monotonic = monotonic
        self._lock = threading.Lock()     # lines arrive from the Bridge thread and from the file reader
        self.env: dict = {}
        self.badges = 0
        self.window = 0                   # counts the periods opened by a badge: a session belongs to one of them
        self._shock_at: float | None = None
        self._lamp_fault_at: float | None = None
        self._unlocked_until = -float("inf")
        self._failsafe: tuple[float, str] | None = None

    def on_line(self, line: dict) -> None:
        """One C5 line, already parsed. Unknown types are ignored: the firmware may know more than we do."""
        if not isinstance(line, dict):
            return
        now = self._monotonic()
        kind = line.get("type")
        with self._lock:
            if kind == "env":
                self.env.update({k: v for k, v in line.items() if k not in _NOT_VALUES})
            elif kind == "tamper":
                if line.get("code") == BADGE_CODE:
                    self.badges += 1
                    if now >= self._unlocked_until:
                        self.window += 1          # a badge while still open only adds time
                    self._unlocked_until = now + self.unlock_s
                else:
                    self._shock_at = now
            elif kind == "lamp_fault":
                self._lamp_fault_at = now
            elif kind == "failsafe":
                self._failsafe = (now, str(line.get("reason", "")))

    def fault(self) -> str | None:
        """The reason for DEGRADED that comes from the microcontroller, None when there is none."""
        now = self._monotonic()
        with self._lock:
            if self._lamp_fault_at is not None and now - self._lamp_fault_at < self.lamp_fault_hold_s:
                return "lamp_fault"
        return None

    def unlocked(self) -> bool:
        """True for operator.unlock_s after the technician's badge."""
        return self._monotonic() < self._unlocked_until

    def lock(self) -> None:
        """Closes the technician's page until the next badge (too many wrong passwords)."""
        with self._lock:
            self._unlocked_until = -float("inf")

    def snapshot(self) -> dict:
        """What the status page shows about the microcontroller."""
        now = self._monotonic()
        fault = self.fault()
        with self._lock:
            return {
                "env": dict(self.env),
                "fault": fault,
                "shock_s_ago": round(now - self._shock_at) if self._shock_at is not None else None,
                "firmware_failsafe": ({"reason": self._failsafe[1], "s_ago": round(now - self._failsafe[0])}
                                      if self._failsafe else None),
                "unlock_s_left": round(max(0.0, self._unlocked_until - now)),
            }


class C5FileTail:
    """Follows the files <series>-*.jsonl of a folder and hands every NEW complete line to on_line.

    What was written before the start is skipped: an old badge must not open the page today.
    File names sort by time (CONTRACTS, C3 transport rules), files are only appended.
    """

    def __init__(self, directory: str | Path, series: str, on_line: Callable[[dict], None], poll_s: float):
        self.dir, self.series, self.on_line, self.poll_s = Path(directory), series, on_line, float(poll_s)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        files = self._files()
        # Cursor: the file being read and how many bytes of it were already handed over.
        self._file = files[-1].name if files else ""
        self._offset = files[-1].stat().st_size if files else 0

    def _files(self) -> list[Path]:
        try:
            return sorted(self.dir.glob(f"{self.series}-*.jsonl"))
        except OSError:
            return []

    def poll(self) -> int:
        """Reads what was appended since the last call. Returns the number of lines handed over."""
        handed = 0
        for path in self._files():
            if path.name < self._file:
                continue
            offset = self._offset if path.name == self._file else 0
            try:
                with open(path, "rb") as fh:
                    fh.seek(offset)
                    data = fh.read()
            except OSError:
                continue
            end = data.rfind(b"\n") + 1          # a line without its newline is still being written
            for raw in data[:end].splitlines():
                try:
                    self.on_line(json.loads(raw))
                    handed += 1
                except ValueError:
                    pass                         # a damaged line is not worth stopping for
            self._file, self._offset = path.name, offset + end
        return handed

    def start(self) -> None:
        def run() -> None:
            while not self._stop.wait(self.poll_s):
                self.poll()

        self._thread = threading.Thread(target=run, name="mdgb-c5-files", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
