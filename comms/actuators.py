"""Actuator transports: C1 (command) and C2 (heartbeat) from the AI to the MCU — docs/CONTRACTS.md v1.

    from comms.actuators import make_actuator
    act = make_actuator("serial", port="/dev/cu.usbmodem1101")   # or "sim"; "bridge" arrives in CM-M4
    act.send(c1)            # never blocks, never raises on link errors
    act.heartbeat(seq)      # every 100 ms: without it the firmware fails safe after 500 ms
    act.close()

Lines coming back from the MCU (C5) are appended to $MDGB_C3_DIR/mcu-*.jsonl (except "thermal")
and handed to an optional listener (set_listener).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable, Optional

from comms.jsonl import JsonlWriter, default_c3_dir

log = logging.getLogger("actuator")

MAX_LINE_BYTES = 512            # MCU receive buffer (C1 transport rules)
NOT_LOGGED_C5 = {"thermal"}     # 4 Hz: listener only, never written to disk
STALE_S = 1.0                   # a command older than this is not sent after a reconnection
POLL_S = 0.01                   # serial read polling while idle


def _dumps(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def encode_line(obj: dict) -> bytes:
    """One C1/C2 line without the trailing newline, at most MAX_LINE_BYTES.
    An over-long C1 gets its "reason" shortened; if it still does not fit -> ValueError."""
    if not isinstance(obj, dict):
        raise ValueError("C1/C2 must be a dict")
    data = _dumps(obj)
    reason = obj.get("reason")
    if len(data) > MAX_LINE_BYTES and isinstance(reason, str):
        trimmed = dict(obj)
        while len(data) > MAX_LINE_BYTES and reason:
            reason = reason[:len(reason) - max(1, len(data) - MAX_LINE_BYTES)]
            trimmed["reason"] = reason + "..."
            data = _dumps(trimmed)
    if len(data) > MAX_LINE_BYTES:
        raise ValueError(f"C1 line of {len(data)} bytes, max {MAX_LINE_BYTES}")
    return data


class Actuator:
    """Common interface (CONTRACTS.md v1). Subclasses implement send/heartbeat/close."""

    def __init__(self, listener: Optional[Callable[[dict], None]] = None,
                 mcu_log: bool = False, mcu_log_dir: Optional[str] = None, clock=time.time):
        self._listener = listener
        self._clock = clock
        self._mcu_log = JsonlWriter(mcu_log_dir or default_c3_dir(), "mcu", fsync=True) if mcu_log else None

    def send(self, cmd: dict) -> None:          # C1
        raise NotImplementedError

    def heartbeat(self, seq: int) -> None:      # C2
        raise NotImplementedError

    def close(self) -> None:
        if self._mcu_log is not None:
            self._mcu_log.close()

    def set_listener(self, cb: Optional[Callable[[dict], None]]) -> None:
        """cb(c5_dict) is called from the actuator thread for every C5 line (thermal included)."""
        self._listener = cb

    def _on_mcu_line(self, text: str) -> None:
        text = text.strip()
        if not text.startswith("{"):            # MCU debug output: ignored by contract
            if text:
                log.debug("mcu: %s", text)
            return
        try:
            obj = json.loads(text)
        except ValueError:
            log.warning("invalid C5 line: %r", text[:80])
            return
        if not isinstance(obj, dict):
            return
        obj.setdefault("ts", round(self._clock(), 3))     # the MCU has no wall clock
        if self._mcu_log is not None and obj.get("type") not in NOT_LOGGED_C5:
            self._mcu_log.write(obj)
        cb = self._listener
        if cb is not None:
            try:
                cb(obj)
            except Exception:
                log.exception("C5 listener failed")


class SimActuator(Actuator):
    """No hardware: keeps the last command and mimics the firmware heartbeat timeout (for the overlay and tests).
    feed_mcu_line() simulates a C5 line coming from the MCU."""

    HB_TIMEOUT_S = 0.5

    def __init__(self, verbose: bool = False, monotonic=time.monotonic, **kwargs):
        super().__init__(**kwargs)
        self.verbose = verbose
        self._mono = monotonic
        self.last_cmd: Optional[dict] = None
        self.n_cmds = 0
        self.last_hb: Optional[int] = None
        self._t_hb: Optional[float] = None

    def send(self, cmd: dict) -> None:
        encode_line(cmd)                         # same limits as the real transports
        changed = self.last_cmd is None or (cmd.get("state"), cmd.get("led")) != (
            self.last_cmd.get("state"), self.last_cmd.get("led"))
        self.last_cmd, self.n_cmds = cmd, self.n_cmds + 1
        if self.verbose and changed:
            log.info("[SIM] C1 state=%s led=%s req=%s", cmd.get("state"), cmd.get("led"), cmd.get("req"))

    def heartbeat(self, seq: int) -> None:
        self.last_hb, self._t_hb = int(seq), self._mono()

    @property
    def failsafe(self) -> bool:
        """True when the real firmware would be in fail-safe (no C2 for more than 500 ms)."""
        return self._t_hb is None or self._mono() - self._t_hb > self.HB_TIMEOUT_S

    def feed_mcu_line(self, text: str) -> None:
        self._on_mcu_line(text)


def _open_serial(port: str, baud: int):
    import serial  # pyserial; imported here so SimActuator works without it
    # serial_for_url also accepts plain device paths; timeout=0 -> non-blocking reads
    return serial.serial_for_url(port, baudrate=baud, timeout=0, write_timeout=0.2)


class SerialActuator(Actuator):
    """C1/C2 over a serial line (UNO R4 or any Arduino running firmware/serial_mcu), 115200 8N1.

    A background thread owns the port: it writes the latest C1 and the latest C2 (state, not a queue),
    reads C5 lines and reopens the port when it disappears (USB unplugged, board reset)."""

    def __init__(self, port: str, baud: int = 115200, reconnect_s: float = 1.0,
                 serial_factory=None, mcu_log: bool = True, **kwargs):
        super().__init__(mcu_log=mcu_log, **kwargs)
        self.port, self.baud, self.reconnect_s = port, baud, reconnect_s
        self._factory = serial_factory or _open_serial
        self._cv = threading.Condition()
        self._pending_cmd = None                 # (monotonic time, line)
        self._pending_hb = None
        self._closed = False
        self._next_try = 0.0
        self._warned = False
        self.connected = False
        self._thread = threading.Thread(target=self._run, name=f"actuator-{port}", daemon=True)
        self._thread.start()

    def send(self, cmd: dict) -> None:
        line = encode_line(cmd)
        with self._cv:
            self._pending_cmd = (time.monotonic(), line)
            self._cv.notify()

    def heartbeat(self, seq: int) -> None:
        line = encode_line({"v": 1, "hb": int(seq)})
        with self._cv:
            self._pending_hb = (time.monotonic(), line)
            self._cv.notify()

    def close(self) -> None:
        with self._cv:
            self._closed = True
            self._cv.notify()
        self._thread.join(timeout=2)
        super().close()

    # ---------- I/O thread ----------
    def _connect(self):
        now = time.monotonic()
        if now < self._next_try:
            return None
        self._next_try = now + self.reconnect_s
        try:
            ser = self._factory(self.port, self.baud)
        except Exception as e:                   # missing port, permission denied, busy...
            if not self._warned:
                log.warning("serial %s not available (%s): retrying every %.1f s", self.port, e, self.reconnect_s)
                self._warned = True
            return None
        log.info("serial %s open at %d baud", self.port, self.baud)
        self._warned, self.connected = False, True
        return ser

    def _run(self) -> None:
        ser, rx = None, bytearray()
        while True:
            with self._cv:
                if not self._closed and self._pending_cmd is None and self._pending_hb is None:
                    self._cv.wait(POLL_S)
                if self._closed:
                    break
                pending = [p for p in (self._pending_cmd, self._pending_hb) if p is not None]
                self._pending_cmd = self._pending_hb = None
            if ser is None:
                ser = self._connect()
                if ser is None:
                    continue
            try:
                now = time.monotonic()
                for t, line in pending:
                    if now - t <= STALE_S:
                        ser.write(line + b"\n")
                n = ser.in_waiting
                if n:
                    rx += ser.read(n)
                    *lines, rest = rx.split(b"\n")
                    rx = bytearray(rest if len(rest) <= 4 * MAX_LINE_BYTES else b"")   # drop endless garbage
                    for raw in lines:
                        self._on_mcu_line(raw.decode("utf-8", "replace"))
            except Exception as e:               # the thread must survive any serial error
                log.warning("serial %s lost (%s): reconnecting", self.port, e)
                try:
                    ser.close()
                except Exception:
                    pass
                ser, rx, self.connected = None, bytearray(), False
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
        self.connected = False


def make_actuator(kind: str = "sim", **kwargs) -> Actuator:
    """kind: "sim" | "serial" (port=...) | "bridge" (CM-M4)."""
    if kind == "sim":
        return SimActuator(**kwargs)
    if kind == "serial":
        return SerialActuator(**kwargs)
    if kind == "bridge":
        raise NotImplementedError("BridgeActuator arrives in CM-M4: use 'sim' or 'serial'")
    raise ValueError(f"unknown actuator kind: {kind!r}")
