"""Actuator transports (C1/C2 out, C5 in) without hardware: in-memory fakes and a pseudo-terminal."""
import glob
import json
import os
import sys
import threading
import time

import pytest

from comms.actuators import MAX_LINE_BYTES, SerialActuator, SimActuator, encode_line, make_actuator
from comms.jsonl import JsonlWriter

C1 = {"v": 1, "seq": 1842, "t_ms": 1739012345678, "state": "WARN_DRIVER", "led": "AMBER_BLINK_2HZ", "green_s": 19,
      "req": {"ped_green_extend_s": 7, "veh_red_hold": True, "flash": False},
      "lcd": "PEDONE  47 km/h", "oled": "ATTENDI auto 45km/h",
      "reason": "anziano 0.8 m/s; auto 50 km/h a 60 m; TTC 4.3 s < T_need 9.8 s"}


def wait_until(cond, timeout=3.0):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ---------- encoding ----------
def test_encode_line_contract_example():
    data = encode_line(C1)
    assert len(data) <= MAX_LINE_BYTES and b"\n" not in data
    assert json.loads(data) == C1


def test_encode_line_trims_reason_only():
    long_cmd = dict(C1, reason="x" * 2000)
    data = encode_line(long_cmd)
    assert len(data) <= MAX_LINE_BYTES
    out = json.loads(data)
    assert out["reason"].endswith("...")
    assert {k: v for k, v in out.items() if k != "reason"} == {k: v for k, v in C1.items() if k != "reason"}


def test_encode_line_rejects_what_cannot_fit():
    with pytest.raises(ValueError):
        encode_line(dict(C1, lcd="y" * 600))
    with pytest.raises(ValueError):
        encode_line(["not", "a", "dict"])


# ---------- SimActuator ----------
def test_sim_failsafe_follows_heartbeat():
    t = [100.0]
    sim = SimActuator(monotonic=lambda: t[0])
    assert sim.failsafe                       # no heartbeat yet: firmware in normal cycle / fail-safe
    sim.heartbeat(1)
    t[0] += 0.4
    assert not sim.failsafe
    t[0] += 0.2                               # 0.6 s without C2 > 500 ms
    assert sim.failsafe
    sim.send(C1)
    assert sim.last_cmd == C1 and sim.n_cmds == 1


def test_sim_c5_listener_and_log(tmp_path):
    got = []
    sim = SimActuator(listener=got.append, mcu_log=True, mcu_log_dir=str(tmp_path), clock=lambda: 1739012400.0)
    sim.feed_mcu_line('{"v":1,"src":"mcu","type":"env","t_c":14.2,"rh":81,"lux":120,"batt":87}')
    sim.feed_mcu_line('{"v":1,"src":"mcu","type":"thermal","t":[21.4,21.6]}')
    sim.feed_mcu_line("boot ok, firmware 0.1")            # debug line: ignored
    sim.feed_mcu_line("{broken json")                     # invalid: ignored
    sim.close()
    assert [o["type"] for o in got] == ["env", "thermal"]
    assert got[0]["ts"] == 1739012400.0                   # added by Linux
    files = glob.glob(str(tmp_path / "mcu-*.jsonl"))
    lines = [json.loads(l) for f in files for l in open(f)]
    assert [o["type"] for o in lines] == ["env"]          # thermal never written to disk


# ---------- SerialActuator with a fake port ----------
class FakeSerial:
    def __init__(self, fail_on_write=None):
        self.written = bytearray()
        self.rx = bytearray()
        self.fail_on_write = fail_on_write
        self.writes = 0
        self.closed = False
        self.lock = threading.Lock()

    def write(self, data):
        self.writes += 1
        if self.fail_on_write and self.writes >= self.fail_on_write:
            raise OSError("device disconnected")
        self.written += data

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, n):
        with self.lock:
            out, self.rx = bytes(self.rx[:n]), self.rx[n:]
        return out

    def close(self):
        self.closed = True


def lines_of(fake):
    return [json.loads(l) for l in bytes(fake.written).split(b"\n") if l]


def test_serial_reconnects_and_never_raises(tmp_path):
    first = FakeSerial(fail_on_write=2)       # second write fails: "USB unplugged"
    second = FakeSerial()
    opens = [OSError("no such port"), first, second]

    def factory(port, baud):
        item = opens.pop(0) if opens else second
        if isinstance(item, Exception):
            raise item
        return item

    act = SerialActuator("fake", serial_factory=factory, reconnect_s=0.05, mcu_log_dir=str(tmp_path))
    try:
        hb = 0
        while not second.written and hb < 200:   # keep sending as the AI would; must never raise
            hb += 1
            act.heartbeat(hb)
            time.sleep(0.01)
        assert first.closed, "the broken port must be closed"
        assert wait_until(lambda: lines_of(second))
        assert all("hb" in o for o in lines_of(second))
        act.send(C1)
        assert wait_until(lambda: any(o.get("state") == "WARN_DRIVER" for o in lines_of(second)))
        assert act.connected
    finally:
        act.close()
    assert second.closed and not act.connected


def test_serial_missing_port_does_not_block_or_raise(tmp_path):
    act = SerialActuator("/dev/this-port-does-not-exist", reconnect_s=0.05, mcu_log_dir=str(tmp_path))
    t0 = time.monotonic()
    for i in range(20):
        act.send(C1)
        act.heartbeat(i)
    assert time.monotonic() - t0 < 0.1
    assert not act.connected
    act.close()


def test_serial_reads_c5_lines_split_across_reads(tmp_path):
    fake = FakeSerial()
    got = []
    act = SerialActuator("fake", serial_factory=lambda p, b: fake, listener=got.append, mcu_log_dir=str(tmp_path))
    try:
        for chunk in (b'dbg: boot\n{"v":1,"src":"mcu","type":"tam', b'per","code":2}\n{"v":1,"src":"mcu",',
                      b'"type":"failsafe","reason":"hb_timeout"}\n'):
            with fake.lock:
                fake.rx += chunk
            time.sleep(0.03)
        assert wait_until(lambda: len(got) == 2)
        assert [(o["type"], o.get("code")) for o in got] == [("tamper", 2), ("failsafe", None)]
    finally:
        act.close()
    logged = [json.loads(l) for f in glob.glob(str(tmp_path / "mcu-*.jsonl")) for l in open(f)]
    assert [o["type"] for o in logged] == ["tamper", "failsafe"]


# ---------- SerialActuator on a real pseudo-terminal (pyserial end to end) ----------
@pytest.mark.skipif(sys.platform.startswith("win"), reason="pty is POSIX only")
def test_serial_on_pty(tmp_path):
    pytest.importorskip("serial")
    import pty
    import select

    master, slave = pty.openpty()
    got = []
    act = SerialActuator(os.ttyname(slave), listener=got.append, mcu_log_dir=str(tmp_path))
    try:
        act.send(C1)
        act.heartbeat(7)
        buf = b""
        t0 = time.monotonic()
        while buf.count(b"\n") < 2 and time.monotonic() - t0 < 3:
            if select.select([master], [], [], 0.1)[0]:
                buf += os.read(master, 4096)
        sent = [json.loads(l) for l in buf.split(b"\n") if l]
        assert C1 in sent and {"v": 1, "hb": 7} in sent
        os.write(master, b'{"v":1,"src":"mcu","type":"env","t_c":21.0}\n')
        assert wait_until(lambda: got)
        assert got[0]["type"] == "env" and "ts" in got[0]
    finally:
        act.close()
        os.close(master)
        os.close(slave)


# ---------- factory, JSONL, tool ----------
def test_make_actuator():
    assert isinstance(make_actuator("sim"), SimActuator)
    with pytest.raises(NotImplementedError):
        make_actuator("bridge")
    with pytest.raises(ValueError):
        make_actuator("carrier-pigeon")


def test_jsonl_rotation_keeps_time_order(tmp_path):
    t = [1739012400.0]
    w = JsonlWriter(str(tmp_path), "c3", rotate_s=60, clock=lambda: t[0])
    w.write({"n": 1})
    t[0] += 61
    w.write({"n": 2})
    w.write({"n": 3})
    w.close()
    files = sorted(glob.glob(str(tmp_path / "c3-*.jsonl")))
    assert [os.path.basename(f) for f in files] == ["c3-20250208-110000.jsonl", "c3-20250208-110101.jsonl"]
    assert [[json.loads(l)["n"] for l in open(f)] for f in files] == [[1], [2, 3]]


def test_c1_send_tool_runs_without_hardware(capsys):
    from comms.tools.c1_send import main
    assert main(["--port", "sim", "--duration", "0.5", "--period", "0.2", "--stop-hb-at", "0.3"]) == 0
    out = capsys.readouterr().out
    assert "C1 -> IDLE" in out and "C2 fermato" in out
