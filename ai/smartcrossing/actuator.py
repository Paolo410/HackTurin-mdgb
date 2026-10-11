"""Sends the commands (C1) and the heartbeat (C2) to the firmware through an Actuator.

The real transports (serial, Bridge) belong to comms/ (comms/actuators.py). Here:
- SimActuator: local stand-in with the same interface, it only remembers what it was sent;
- make_actuator: "sim" -> SimActuator, "serial" / "bridge" -> comms.actuators.make_actuator;
- Commander: builds the full C1 line (v, seq, t_ms), repeats it at least every second and keeps the
  heartbeat going from a background thread, but only while the vision loop is alive.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from typing import Callable

from .config import AI_DIR

C1_VERSION = 1
# Fields of C1 the sketch does not need to act, dropped in this order when the line is too long for the link.
# What the traffic light must do (state, req, tech) and v/seq always stay.
_DROP_WHEN_LONG = ("reason", "oled", "lcd", "led", "green_s", "t_ms")
_MIN_REASON = 20                       # a reason shorter than this says nothing: it is dropped instead


def _size(line: dict) -> int:
    """Bytes of the line on the link: the same compact UTF-8 JSON as comms/actuators.py."""
    return len(json.dumps(line, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def fit_line(line: dict, max_bytes: int) -> dict:
    """The C1 line as it goes to the firmware: at most max_bytes once encoded.

    On the UNO Q the arduino-router refuses longer mdgb_line calls ("message size exceeds the limit"),
    measured 238 bytes on 11/10: such a command never reached the sketch. First the reason is shortened,
    then the fields of _DROP_WHEN_LONG go, in order. The full command stays for logs, overlay and page."""
    if max_bytes <= 0 or _size(line) <= max_bytes:
        return line
    out = dict(line)
    reason = out.get("reason")
    if isinstance(reason, str):
        while len(reason) >= _MIN_REASON and _size(out) > max_bytes:
            reason = reason[:len(reason) - max(1, _size(out) - max_bytes)]
            out["reason"] = reason.rstrip() + "..."
        if _size(out) <= max_bytes:
            return out
    for key in _DROP_WHEN_LONG:
        out.pop(key, None)
        if _size(out) <= max_bytes:
            return out
    return out                         # still too long: comms/actuators.py logs the link error


class SimActuator:
    """No hardware: stores the last command and counts the heartbeats."""

    def __init__(self, failsafe_timeout_s: float = 0.5, monotonic: Callable[[], float] = time.monotonic):
        self.last_cmd: dict | None = None
        self.sent: list[dict] = []
        self.heartbeats = 0
        self.last_hb_seq: int | None = None
        self._last_hb_t: float | None = None
        self._timeout = failsafe_timeout_s
        self._monotonic = monotonic

    def send(self, cmd: dict) -> None:
        self.last_cmd = cmd
        self.sent.append(cmd)

    def heartbeat(self, seq: int) -> None:
        self.heartbeats += 1
        self.last_hb_seq = seq
        self._last_hb_t = self._monotonic()

    def set_listener(self, cb) -> None:
        pass   # no MCU: nothing comes back

    @property
    def failsafe(self) -> bool:
        """True when a real firmware would be in fail-safe: no heartbeat within the timeout."""
        return self._last_hb_t is None or self._monotonic() - self._last_hb_t > self._timeout

    def close(self) -> None:
        pass


def make_actuator(kind: str, cfg: dict, **kwargs):
    if kind == "sim":
        return SimActuator(failsafe_timeout_s=float(cfg["actuator"]["failsafe_timeout_s"]))
    # Real transports live in comms/ at the root of the repository.
    root = str(AI_DIR.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from comms.actuators import make_actuator as comms_make_actuator
    except ImportError as exc:
        raise RuntimeError(f"--actuator {kind} needs comms/actuators.py, which is not in this checkout ({exc})") from exc
    return comms_make_actuator(kind, **kwargs)


class Commander:
    def __init__(self, actuator, cfg: dict, wall_clock: Callable[[], float] = time.time,
                 monotonic: Callable[[], float] = time.monotonic):
        a = cfg["actuator"]
        self.actuator = actuator
        self.hb_period = float(a["heartbeat_period_s"])
        self.hb_stale = float(a["heartbeat_stale_s"])
        self.repeat_s = float(a["c1_repeat_s"])
        self.max_line_bytes = int(a["max_line_bytes"])
        self._wall_clock, self._monotonic = wall_clock, monotonic
        self.seq = 0
        self.last_line: dict | None = None
        self._last_fields: dict | None = None
        self._last_sent_t = -float("inf")
        self._last_alive = self._monotonic()
        self._lock = threading.Lock()   # the heartbeat thread and the vision loop share seq and the link
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Starts the heartbeat thread."""
        self._last_alive = self._monotonic()
        self._thread = threading.Thread(target=self._run, name="mdgb-heartbeat", daemon=True)
        self._thread.start()

    def alive(self) -> None:
        """Called by the vision loop on every iteration: proof that it is not stuck."""
        self._last_alive = self._monotonic()

    def update(self, fields: dict) -> bool:
        """Sends the command if it changed or if the last one is old. Returns True when something was sent."""
        self.alive()
        now = self._monotonic()
        # A new wording of the reason alone is not worth a line: it goes out with the next repeat.
        acts = {k: v for k, v in fields.items() if k != "reason"}
        if acts == self._last_fields and now - self._last_sent_t < self.repeat_s:
            return False
        with self._lock:
            self.seq += 1
            line = {"v": C1_VERSION, "seq": self.seq, "t_ms": int(self._wall_clock() * 1000), **fields}
            self.actuator.send(fit_line(line, self.max_line_bytes))
        self.last_line, self._last_fields, self._last_sent_t = line, acts, now
        return True

    def beat(self) -> bool:
        """One heartbeat, unless the vision loop has been silent for too long (then the firmware must fall back)."""
        if self._monotonic() - self._last_alive > self.hb_stale:
            return False
        with self._lock:
            self.seq += 1
            self.actuator.heartbeat(self.seq)
        return True

    def _run(self) -> None:
        while not self._stop.wait(self.hb_period):
            self.beat()

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self.actuator.close()
