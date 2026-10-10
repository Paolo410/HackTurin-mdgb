"""The node as it runs on the board (comms/node/main.py, class Node): C3 files written like ai/ does and C5 files
written like comms/actuators.py does -> real Mosquitto -> central. Plus: BLE requested where it cannot work
-> the node refuses to start instead of pretending."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (ROOT, os.path.join(ROOT, "comms", "node"), os.path.join(ROOT, "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

from comms.jsonl import JsonlWriter  # noqa: E402
from comms.tools.c3_sim import SimulatedSource  # noqa: E402
from test_offline import Broker, _start_central, free_port, need_mosquitto, wait_until  # noqa: E402


def test_node_reads_the_real_files_and_delivers_everything(monkeypatch):
    need_mosquitto()
    import config as cfg
    work = tempfile.mkdtemp(prefix="mdgb-node-")
    os.chmod(work, 0o777)
    port = free_port()
    broker = Broker(port, work)
    broker.start()
    store, ing_client = _start_central(port, work)
    c3 = os.path.join(work, "c3")
    for k, v in dict(NODE_ID="nodo-main", MQTT_HOST="127.0.0.1", MQTT_PORT=port, MQTT_TLS=False, BACKUP_LINK="none",
                     DB_PATH=os.path.join(work, "outbox.db"), C3_DIR=c3, HB_PERIOD_S=1, AGG_PERIOD_S=2).items():
        monkeypatch.setattr(cfg, k, v)
    import main
    node = main.Node()
    node.start()
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            node.loop_once()
            time.sleep(0.05)

    threading.Thread(target=loop, daemon=True).start()
    try:
        ai, mcu, sim = JsonlWriter(c3, "c3"), JsonlWriter(c3, "mcu"), SimulatedSource(seed=4)
        ai.write({"v": 1, "ts": time.time(), "type": "status", "state": "PRESENCE", "fps": 9.5})
        for _ in range(200):
            ai.write(sim.make_event())
        mcu.write({"v": 1, "ts": time.time(), "type": "env", "t_c": 14.2, "rh": 81, "lux": 120, "batt": 87})

        def report():
            r = [x for x in store.report() if x["node"] == "nodo-main"]
            return r[0] if r else {"events": 0}

        assert wait_until(lambda: report()["events"] == 200, 20), f"centrale incompleta: {store.report()}"
        assert report()["gaps"] == 0

        def hb():
            row = store.db.execute("SELECT data FROM hb WHERE node='nodo-main'").fetchone()
            return json.loads(row[0]) if row else {}

        assert wait_until(lambda: hb().get("mode") == "normal" and hb().get("batt") == 87, 10), hb()
        assert hb()["fps"] == 9.5 and hb()["queue"] == 0

        mcu.write({"v": 1, "ts": time.time(), "type": "failsafe", "reason": "no_heartbeat"})   # C5 from the MCU
        assert wait_until(lambda: hb().get("mode") == "failsafe", 10), "a C5 failsafe must show up in hb.mode"
        assert wait_until(lambda: report()["events"] == 201, 10), "the failsafe line is also an event"
        assert report()["gaps"] == 0 and report()["by_type"]["failsafe"] == 1
        ai.close()
        mcu.close()
    finally:
        stop.set()
        node.stop()
        ing_client.loop_stop()
        broker.stop()
        shutil.rmtree(work, ignore_errors=True)


def test_node_refuses_to_start_with_ble_but_no_bluez(tmp_path):
    empty = tmp_path / "bin"
    empty.mkdir()                       # PATH without btmgmt, as on a board where bluez is missing
    env = dict(os.environ, PATH=str(empty), BACKUP_LINK="ble", DB_PATH=str(tmp_path / "o.db"),
               MDGB_C3_DIR=str(tmp_path / "c3"), MQTT_HOST="127.0.0.1", MQTT_PORT="1")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "comms", "node", "main.py")], env=env,
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "apt install bluez" in r.stderr, r.stderr
