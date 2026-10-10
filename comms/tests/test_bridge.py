"""BridgeActuator with Arduino's real arduino-router-bridge library against a stand-in router (fake_router.py):
C1/C2 reach the sketch, C5 come back, and a missing router, a missing sketch or a rejected line never break
the vision loop."""
import glob
import json
import time

import pytest

pytest.importorskip("arduino.router_bridge")

from comms.actuators import BridgeActuator, make_actuator  # noqa: E402
from fake_router import FakeRouter  # noqa: E402
from test_actuators import C1, wait_until  # noqa: E402


@pytest.fixture
def router():
    r = FakeRouter().start()
    yield r
    r.stop()


def test_c1_c2_reach_the_sketch_and_c5_comes_back(router, tmp_path):
    got = []
    act = make_actuator("bridge", address=router.address, mcu_log_dir=str(tmp_path), port="ignored")
    try:
        assert isinstance(act, BridgeActuator) and act.connected
        act.set_listener(got.append)
        assert wait_until(lambda: "mcu_event" in router.routes), "the actuator must provide mcu_event to the MCU"
        act.send(C1)
        for seq in range(1843, 1848):
            act.heartbeat(seq)
            time.sleep(0.02)
        assert wait_until(lambda: C1 in router.lines and {"v": 1, "hb": 1847} in router.lines)

        router.mcu_notify("mcu_event", '{"v":1,"type":"env","t_c":14.2,"rh":81,"lux":120}')
        router.mcu_notify("mcu_event", '{"v":1,"type":"thermal","cols":[20.1,20.3]}')
        router.mcu_notify("mcu_event", "debug: not json, ignored by contract")
        assert wait_until(lambda: len(got) == 2)
        assert got[0]["type"] == "env" and "ts" in got[0] and got[1]["type"] == "thermal"
    finally:
        act.close()
    rows = [json.loads(line) for f in glob.glob(str(tmp_path / "mcu-*.jsonl")) for line in open(f)]
    assert [r["type"] for r in rows] == ["env"], "C5 on disk for comms/node, except thermal"


def test_router_down_at_start_then_up(tmp_path):
    router = FakeRouter()                  # socket not there yet: arduino-router not started
    t0 = time.monotonic()
    act = BridgeActuator(address=router.address, connect_timeout_s=0.3, mcu_log=False)
    try:
        assert time.monotonic() - t0 < 2 and not act.connected
        act.heartbeat(1)                   # never raises, never blocks
        router.start()
        assert wait_until(lambda: "mcu_event" in router.routes, 10), "registered as soon as the router is up"
        act.heartbeat(2)
        assert wait_until(lambda: {"v": 1, "hb": 2} in router.lines) and act.connected
    finally:
        act.close()
        router.stop()


def test_sketch_missing_then_loaded(router):
    router.sketch_loaded = False           # MCU without firmware/unoq_mcu: the router answers "method not available"
    act = BridgeActuator(address=router.address, mcu_log=False)
    try:
        act.heartbeat(1)
        time.sleep(0.3)
        assert not router.lines and not act.connected
        router.sketch_loaded = True
        act.heartbeat(2)
        assert wait_until(lambda: router.lines == [{"v": 1, "hb": 2}]) and act.connected
    finally:
        act.close()


def test_rejected_lines_are_counted_not_raised(router):
    act = BridgeActuator(address=router.address, mcu_log=False)
    try:
        act.send({"v": 2, "seq": 1, "state": "IDLE"})          # wrong version: the sketch answers false
        assert wait_until(lambda: act.rejected == 1)
        act.heartbeat(3)
        assert wait_until(lambda: {"v": 1, "hb": 3} in router.lines)
    finally:
        act.close()


def test_c1_send_tool_over_the_bridge(router, capsys):
    """The check to run on the board: python -m comms.tools.c1_send --port bridge."""
    from comms.tools.c1_send import main
    assert main(["--port", "bridge", "--bridge-address", router.address, "--duration", "0.6", "--period", "0.2"]) == 0
    assert "risponde a mdgb_line, righe rifiutate 0 -> OK" in capsys.readouterr().out
    states = [line.get("state") for line in router.lines if "state" in line]
    assert states[:3] == ["IDLE", "PRESENCE", "WARN_DRIVER"] and any("hb" in line for line in router.lines)
    router.sketch_loaded = False
    assert main(["--port", "bridge", "--bridge-address", router.address, "--duration", "0.3"]) == 1
