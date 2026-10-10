"""Test end-to-end della resilienza offline (gira sul laptop, senza UNO Q).

Scenario:
  1. broker acceso  -> il nodo genera eventi e li pubblica
  2. broker SPENTO  -> il nodo continua a generare: eventi in coda nell'outbox, aggregati via "LoRa" (simulata)
  3. broker RIACCESO -> backfill automatico
  Verifica: il backend ha TUTTI gli eventi (nessun buco nei seq) e nessun doppione.

Requisiti: mosquitto installato (macOS: brew install mosquitto) + pip install paho-mqtt
Uso:       python tests/test_offline.py
"""
import os
import random
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "crosswalk-node", "python"))
sys.path.insert(0, os.path.join(ROOT, "backend"))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_mosquitto():
    for p in (shutil.which("mosquitto"), "/usr/sbin/mosquitto", "/opt/homebrew/sbin/mosquitto",
              "/usr/local/sbin/mosquitto"):
        if p and os.path.exists(p):
            return p
    raise SystemExit("mosquitto non trovato (macOS: brew install mosquitto)")


class Broker:
    def __init__(self, port, workdir):
        self.port, self.workdir, self.proc = port, workdir, None
        self.conf = os.path.join(workdir, "mosquitto.conf")
        with open(self.conf, "w") as f:
            f.write(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence true\n"
                    f"persistence_location {workdir}/\nmax_queued_messages 100000\n")

    def start(self):
        self.proc = subprocess.Popen([find_mosquitto(), "-c", self.conf],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)

    def stop(self):
        self.proc.terminate()
        self.proc.wait(5)


def wait_until(cond, timeout, step=0.2):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(step)
    return False


def test_payload_roundtrip():
    from payload import pack_aggregate, unpack_aggregate
    from decoder import decode
    counts = [[120, 3, 15, 4, 1], [98, 2, 11, 6, 0]]
    pkt = pack_aggregate(1760000000, counts, backlog=1234, disk_free_pct=87, online=False)
    assert len(pkt) == 28
    a, b = unpack_aggregate(pkt), decode(pkt)
    assert a == b, (a, b)
    assert b["dir0"]["wheelchair"] == 3 and b["dir1"]["stroller"] == 6
    assert b["offline"] is True and b["backlog"] == 1230 and b["disk_free_pct"] == 87
    print("OK  payload 28 byte: nodo e backend decodificano allo stesso modo")


def test_ble_roundtrip():
    """Nodo (aggregato 28 B -> frame BLE 27 B -> comando btmgmt) e ricevitore (frame -> 28 B) devono coincidere."""
    from payload import pack_aggregate
    from backup_link import SimulatedBle, BLE_COMPANY_ID
    from decoder import decode
    from ble_receiver import frame_to_message
    counts = [[120, 3, 15, 4, 1], [98, 2, 11, 6, 0]]
    pkt = pack_aggregate(1760000000, counts, backlog=1234, disk_free_pct=87, online=False)
    ble = SimulatedBle()
    assert ble.send(pkt)
    cmd = ble.commands[-1]
    assert cmd[:3] == ["btmgmt", "add-adv", "-d"]
    ad = bytes.fromhex(cmd[3])
    assert len(ad) == 31 and ad[1] == 0xFF and int.from_bytes(ad[2:4], "little") == BLE_COMPANY_ID
    port, payload = frame_to_message(ad[4:])
    assert port == 1
    a, b = decode(pkt), decode(payload, port)
    for k in ("window_start", "dir0", "dir1", "backlog", "offline"):
        assert a[k] == b[k], (k, a[k], b[k])
    ble.idle()
    assert ble.commands[-1] == ["btmgmt", "rm-adv", "1"]
    # allarme manomissione via BLE
    import struct
    ble.send(struct.pack("<IB", 1760000123, 2), port=10)
    port, payload = frame_to_message(bytes.fromhex(ble.commands[-1][3])[4:])
    assert decode(payload, port) == {"alarm": "tamper", "ts": 1760000123, "code": 2}
    print("OK  BLE: frame 27 byte nodo -> ricevitore -> decoder coerente (aggregato + allarme)")


def test_offline_end_to_end():
    work = tempfile.mkdtemp(prefix="xw-test-")
    os.chmod(work, 0o777)        # se mosquitto gira come root scende all'utente "mosquitto": deve poter scrivere
    port = free_port()
    os.environ.update({"MQTT_PORT": str(port), "MQTT_HOST": "127.0.0.1",
                       "INGEST_DB": os.path.join(work, "backend.db")})

    import ingest
    ingest.MQTT_PORT, ingest.MQTT_HOST, ingest.DB_PATH = port, "127.0.0.1", os.environ["INGEST_DB"]
    from aggregator import Aggregator
    from backup_link import McuLoraBackup, SimulatedMcu
    from outbox import Outbox
    from payload import CATEGORIES, cat_id
    from uplink_mqtt import MqttUplink

    broker = Broker(port, work)
    broker.start()
    store = ingest.Store(ingest.DB_PATH)
    ing_client = ingest.main_loop(store)

    ob = Outbox(os.path.join(work, "outbox.db"))
    mcu = SimulatedMcu()
    up = MqttUplink(ob, "xw-test", "torino/crosswalk", "127.0.0.1", port, batch=50, ack_timeout_s=5)
    agg = Aggregator(ob, up, McuLoraBackup(mcu), period_s=2, disk_path=work)
    assert wait_until(up.online, 5), "il nodo non si connette al broker"

    stop = threading.Event()          # ferma la generazione di eventi
    stop_node = threading.Event()     # ferma il loop del nodo (solo a fine test)
    rng = random.Random(1)

    def generate():                                    # ~40 eventi/s
        while not stop.is_set():
            ob.put(time.time(), cat_id(rng.choice(CATEGORIES)), rng.randint(0, 1), 0.9)
            time.sleep(0.025)

    def node_loop():
        while not stop_node.is_set():
            up.pump()
            agg.tick()
            time.sleep(0.05)

    threading.Thread(target=generate, daemon=True).start()
    threading.Thread(target=node_loop, daemon=True).start()

    time.sleep(4)
    print(f"... fase ONLINE: backlog={ob.backlog()}")
    broker.stop()
    print("... broker SPENTO (simulazione guasto di rete)")
    time.sleep(7)
    backlog_offline = ob.backlog()
    lora_pkts = len(mcu.sent)
    print(f"... durante l'offline: backlog={backlog_offline}, aggregati passati alla LoRa simulata={lora_pkts}")
    assert backlog_offline > 100, "gli eventi offline dovrebbero accumularsi nell'outbox"
    assert lora_pkts >= 2, "durante l'offline gli aggregati devono uscire sul canale di backup"

    broker.start()
    print("... broker RIACCESO: backfill")
    assert wait_until(up.online, 40), "il nodo non si riconnette"
    time.sleep(2)
    stop.set()
    assert wait_until(lambda: ob.backlog() == 0, 60), f"backlog non svuotato: {ob.backlog()}"

    def complete():
        r = store.report()
        return r and r[0]["events"] == total

    total = ob._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert wait_until(complete, 30), f"backend incompleto: {store.report()} vs {total}"
    rep = store.report()[0]
    print(f"OK  eventi generati={total}, ricevuti={rep['events']}, buchi={rep['gaps']}, "
          f"duplicati scartati={rep['duplicates_dropped']}")
    assert rep["gaps"] == 0

    stop_node.set()
    up.stop()
    ing_client.loop_stop()
    broker.stop()
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    test_payload_roundtrip()
    test_ble_roundtrip()
    test_offline_end_to_end()
    print("TUTTI I TEST SUPERATI")
