"""Test della rete (docs/CONTRACTS.md v1). Girano sul laptop, senza UNO Q.

Unitari:
  - C4-B: nodo (payload.py) e centrale (decoder.py) codificano/decodificano allo stesso modo, anche via BLE;
  - "online" basato sui PUBACK positivi, PUBACK negativo che NON marca inviato;
  - lettura dei file C3/C5: niente perdite né doppioni anche dopo un riavvio, righe incomplete, rotazione.
End-to-end con Mosquitto (si saltano se manca):
  - broker acceso -> SPENTO -> RIACCESO: backlog che cresce, aggregati sul backup, backfill, 0 buchi, 0 doppioni;
  - PUBACK negativo vero (ACL di Mosquitto, 0x87): gli eventi restano in coda; ACL corretta -> arrivano tutti.

Requisiti: pip install -r comms/requirements.txt ; per gli end-to-end mosquitto (macOS: brew install mosquitto)
Uso:       python -m pytest comms/tests/test_offline.py -q      oppure      python comms/tests/test_offline.py
"""
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (ROOT, os.path.join(ROOT, "comms", "node"), os.path.join(ROOT, "app")):
    if p not in sys.path:
        sys.path.insert(0, p)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_mosquitto():
    for p in (shutil.which("mosquitto"), "/usr/sbin/mosquitto", "/opt/homebrew/sbin/mosquitto",
              "/usr/local/sbin/mosquitto"):
        if p and os.path.exists(p):
            return p
    return None


def need_mosquitto():
    if find_mosquitto() is None:
        try:
            import pytest
            pytest.skip("mosquitto non trovato (macOS: brew install mosquitto)")
        except ImportError:
            raise SystemExit("mosquitto non trovato (macOS: brew install mosquitto)")


class Broker:
    def __init__(self, port, workdir, acl=None):
        self.port, self.workdir, self.proc = port, workdir, None
        self.conf = os.path.join(workdir, "mosquitto.conf")
        self.acl = os.path.join(workdir, "acl")
        with open(self.conf, "w") as f:
            f.write(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence true\n"
                    f"persistence_location {workdir}/\nmax_queued_messages 100000\n")
            if acl is not None:
                f.write(f"acl_file {self.acl}\n")
        if acl is not None:
            self.set_acl(acl, reload=False)

    def set_acl(self, text, reload=True):
        with open(self.acl, "w") as f:
            f.write(text)
        if reload:
            self.proc.send_signal(signal.SIGHUP)          # mosquitto rilegge l'ACL

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


# ---------------------------------------------------------------- C4-B
def test_c4b_node_and_central_agree():
    import payload as p
    from decoder import decode
    evs = ([{"type": "crossing", "cls": "pedestrian", "dir": "in", "attrs": {"slow": True}}] * 3
           + [{"type": "crossing", "cls": "pedestrian", "dir": "out", "attrs": {"aid": "normal"}}] * 11
           + [{"type": "crossing", "cls": "cyclist", "dir": "in"}] * 6
           + [{"type": "crossing", "cls": "car", "dir": "in"}] * 50 + [{"type": "crossing", "cls": "bus", "dir": "out"}] * 2
           + [{"type": "crossing", "cls": "animal", "dir": "in", "coco": "dog"}, {"type": "near_miss"}]
           + [{"type": "yield", "yielded": True}] * 2 + [{"type": "yield", "yielded": False}] * 3)
    agg = p.summarize(evs, 1739011500, 1739012400, "nodo07", env={"t_c": 14.2, "rh": 81, "lux": 120}, queue=7)
    assert agg["counts"]["pedestrian"] == {"in": 3, "out": 11} and agg["vulnerable"] == 3
    assert agg["yield_rate"] == 0.4 and agg["near_miss"] == 1
    pkt = p.pack_agg(agg, backlog=1234, batt=87, degraded=True)
    assert len(pkt) == 26
    d = decode(p.TYPE_AGG, pkt)
    assert (d["t0"], d["t1"], d["pedestrian"], d["cyclist"], d["vehicles"], d["animals"]) == \
           (1739011500, 1739012400, {"in": 3, "out": 11}, 6, 52, 1)
    assert (d["vulnerable"], d["near_miss"], d["yield_rate"], d["backlog"], d["batt"], d["degraded"]) == \
           (3, 1, 0.4, 1230, 87, True)
    assert d["env"] == {"t_c": 14, "rh": 81, "lux": 120}
    hb = decode(p.TYPE_HB, p.pack_hb(1739012400, "failsafe", "WARN_DRIVER", 55, None, 87, 3))
    assert (hb["mode"], hb["state"], hb["backlog"], hb["batt"], hb["disk_free_pct"], hb["offline_min"]) == \
           ("failsafe", "WARN_DRIVER", 50, None, 87, 3)
    al = decode(p.TYPE_INCIDENT, p.pack_alarm(1739012399, p.INCIDENT_CODES["person_down"]))
    assert al == {"kind": "alarm", "alarm": "incident", "ts": 1739012399, "code": 1, "detail": "person_down"}
    # esempi di docs/CONTRACTS.md
    assert p.pack_hb(1739012400, "normal", "PRESENCE", 1234, None, 87, 2).hex().upper() == "103039A767017B00FF570200"
    print("OK  C4-B: nodo e centrale coerenti (AGG 26 byte, HB 12 byte, allarmi)")


def test_ble_frame_roundtrip():
    """Nodo (C4-B -> frame BLE 27 B -> comando btmgmt) e ricevitore (frame -> type, corpo) devono coincidere."""
    import payload as p
    from backup_link import BLE_COMPANY_ID, SimulatedBle
    from ble_receiver import frame_to_message
    from decoder import decode
    agg = p.summarize([{"type": "crossing", "cls": "pedestrian", "dir": "in"}] * 5, 1739011500, 1739012400, "n")
    for type_, body in ((p.TYPE_AGG, p.pack_agg(agg, 40)), (p.TYPE_HB, p.pack_hb(1739012400, backlog=40)),
                        (p.TYPE_TAMPER, p.pack_alarm(1739012123, 2))):
        ble = SimulatedBle()
        assert ble.send(body, type_)
        cmd = ble.commands[-1]
        assert cmd[:3] == ["btmgmt", "add-adv", "-d"]
        ad = bytes.fromhex(cmd[3])
        assert len(ad) == 31 and ad[1] == 0xFF and int.from_bytes(ad[2:4], "little") == BLE_COMPANY_ID
        rx_type, rx_body = frame_to_message(ad[4:])
        assert rx_type == type_ and decode(rx_type, rx_body) == decode(type_, body)
        ble.idle()
        assert ble.commands[-1] == ["btmgmt", "rm-adv", "1"]
    print("OK  BLE: frame 27 byte nodo -> ricevitore -> decoder coerente (AGG, HB, allarme)")


# ---------------------------------------------------------------- uplink: conferme
def test_online_follows_positive_pubacks_only():
    from paho.mqtt.packettypes import PacketTypes
    from paho.mqtt.reasoncodes import ReasonCode
    from outbox import Outbox
    from uplink_mqtt import MqttUplink
    work = tempfile.mkdtemp(prefix="mdgb-ack-")
    ob = Outbox(os.path.join(work, "o.db"))
    seqs = ob.put_many([{"v": 1, "ts": 1.0, "type": "crossing"}, {"v": 1, "ts": 2.0, "type": "crossing"}])
    up = MqttUplink(ob, "nodo-t", "mdgb", "127.0.0.1", free_port(), ack_window_s=30)   # nessun broker
    up.c.is_connected = lambda: True
    try:
        t = time.time()
        assert not up.online(t), "connesso ma senza PUBACK non è online"
        up._inflight[1] = (seqs, t)
        up._on_publish(up.c, None, 1, ReasonCode(PacketTypes.PUBACK, identifier=0x87), None)   # Not authorized
        assert ob.backlog() == 2 and up.nacks == 1 and not up.online(t)
        assert up.pump() == 0, "dopo un PUBACK negativo si aspetta prima di rispedire"
        up._inflight[2] = (seqs, t)
        up._on_publish(up.c, None, 2, ReasonCode(PacketTypes.PUBACK, identifier=0x10), None)   # no subscribers = OK
        assert ob.backlog() == 0 and up.online(time.time())
        assert up.stable_s(up.ok_since + 61) == 0, "più di 30 s senza PUBACK: non più online"
        up.last_ack = up.ok_since + 60
        assert 59 < up.stable_s(up.ok_since + 61) < 62
    finally:
        up.stop()
        shutil.rmtree(work, ignore_errors=True)
    print("OK  online = PUBACK positivo recente; PUBACK negativo non marca inviato e mette in attesa")


# ---------------------------------------------------------------- file C3/C5
def test_c3_files_exactly_once_across_restart():
    from comms.jsonl import JsonlWriter
    from event_source import C3FileSource
    from outbox import Outbox
    work = tempfile.mkdtemp(prefix="mdgb-c3-")
    c3dir, db = os.path.join(work, "c3"), os.path.join(work, "o.db")
    t = [1739012400.0]
    w = JsonlWriter(c3dir, "c3", rotate_s=60, clock=lambda: t[0])
    infos = []
    try:
        for i in range(5):
            w.write({"v": 1, "ts": t[0] + i, "type": "crossing", "track_id": i, "cls": "pedestrian", "dir": "in"})
        w.write({"v": 1, "ts": t[0], "type": "status", "state": "PRESENCE", "fps": 9.6})
        with open(w.path, "a") as f:                     # riga a metà: lo scrittore non ha ancora finito
            f.write('{"v":1,"ts":1739012406,"type":"crossing","track_id":5')
        ob = Outbox(db)
        src = C3FileSource(c3dir, ob)
        assert src.poll(infos.append) == 5 and [o["type"] for o in infos] == ["status"]
        assert src.poll() == 0
        ob = Outbox(db)                                  # "riavvio" del processo comms
        assert C3FileSource(c3dir, ob).poll() == 0, "dopo il riavvio nessun doppione"
        with open(w.path, "a") as f:
            f.write(',"cls":"pedestrian","dir":"out"}\n')
        assert C3FileSource(c3dir, ob).poll() == 1, "la riga completata si legge una volta sola"
        with open(w.path, "a") as f:                     # scrittore caduto a metà riga, poi rotazione
            f.write('{"v":1,"ts":17390124')
        t[0] += 61
        w.write({"v": 1, "ts": t[0], "type": "incident", "kind": "person_down", "track_id": 9})
        mcu = JsonlWriter(c3dir, "mcu", clock=lambda: t[0])
        mcu.write({"v": 1, "src": "mcu", "type": "env", "t_c": 14.2, "ts": t[0]})
        mcu.write({"v": 1, "src": "mcu", "type": "tamper", "code": 2, "ts": t[0]})
        assert C3FileSource(c3dir, ob).poll(infos.append) == 2
        assert ob.backlog() == 8
        assert sorted(json.loads(b)["type"] for _, b in ob.pending(50)) == ["crossing"] * 6 + ["incident", "tamper"]
        assert [o["type"] for o in infos] == ["status", "env"]
    finally:
        w.close()
        shutil.rmtree(work, ignore_errors=True)
    print("OK  file C3/C5: esattamente una volta, anche dopo riavvio, righe incomplete e rotazione")


# ---------------------------------------------------------------- end-to-end
def _start_central(port, work):
    import ingest
    ingest.MQTT_PORT, ingest.MQTT_HOST = port, "127.0.0.1"
    store = ingest.Store(os.path.join(work, "central.db"))
    return store, ingest.main_loop(store)


def test_offline_end_to_end():
    need_mosquitto()
    from aggregator import Aggregator
    from backup_link import McuLoraBackup, SimulatedMcu
    from event_source import SimulatedSource
    from outbox import Outbox
    from payload import TYPE_AGG
    from uplink_mqtt import MqttUplink

    work = tempfile.mkdtemp(prefix="mdgb-e2e-")
    os.chmod(work, 0o777)        # se mosquitto gira come root scende all'utente "mosquitto": deve poter scrivere
    port = free_port()
    broker = Broker(port, work)
    broker.start()
    store, ing_client = _start_central(port, work)

    ob = Outbox(os.path.join(work, "outbox.db"))
    mcu = SimulatedMcu()
    up = MqttUplink(ob, "nodo-test", "mdgb", "127.0.0.1", port, batch=50, ack_timeout_s=5)
    agg = Aggregator(ob, up, McuLoraBackup(mcu), period_s=2, node_id="nodo-test")
    assert wait_until(up.connected, 5), "il nodo non si connette al broker"

    stop = threading.Event()          # ferma la generazione di eventi
    stop_node = threading.Event()     # ferma il loop del nodo (solo a fine test)
    sim = SimulatedSource(seed=1)
    online_seen = []

    def generate():                                    # ~40 eventi/s
        while not stop.is_set():
            ob.put(sim.make_event())
            time.sleep(0.025)

    def node_loop():
        t_hb = 0
        while not stop_node.is_set():
            up.pump()
            agg.tick()
            if time.time() - t_hb >= 1:
                up.publish("hb", {"v": 1, "node_id": "nodo-test", "type": "hb", "online": True}, retain=True)
                t_hb = time.time()
            online_seen.append(up.online())
            time.sleep(0.05)

    threading.Thread(target=generate, daemon=True).start()
    threading.Thread(target=node_loop, daemon=True).start()

    time.sleep(4)
    assert up.online(), "con il broker acceso e i PUBACK il nodo deve essere online"
    print(f"... fase ONLINE: backlog={ob.backlog()}")
    broker.stop()
    print("... broker SPENTO (simulazione guasto di rete)")
    time.sleep(7)
    backlog_offline = ob.backlog()
    pkts = [(t, b) for t, b in mcu.sent if t == TYPE_AGG]
    print(f"... durante l'offline: backlog={backlog_offline}, AGG passati al backup (LoRa simulata)={len(pkts)}")
    assert not up.online(), "senza broker il nodo non è online"
    assert backlog_offline > 100, "gli eventi offline dovrebbero accumularsi nell'outbox"
    assert len(pkts) >= 2 and all(len(b) == 26 for _, b in pkts), "durante l'offline gli AGG devono uscire sul backup"

    broker.start()
    print("... broker RIACCESO: backfill")
    assert wait_until(up.online, 40), "il nodo non torna online"
    time.sleep(2)
    stop.set()
    assert wait_until(lambda: ob.backlog() == 0, 60), f"backlog non svuotato: {ob.backlog()}"

    total = ob._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def complete():
        r = store.report()
        return r and r[0]["events"] == total

    assert wait_until(complete, 30), f"centrale incompleta: {store.report()} vs {total}"
    rep = store.report()[0]
    print(f"OK  eventi generati={total}, ricevuti={rep['events']}, buchi={rep['gaps']}, "
          f"duplicati scartati={rep['duplicates_dropped']}")
    assert rep["gaps"] == 0
    hb = store.db.execute("SELECT data FROM hb WHERE node='nodo-test'").fetchone()
    assert hb and json.loads(hb[0])["online"] is True

    stop_node.set()
    up.stop()
    ing_client.loop_stop()
    broker.stop()
    shutil.rmtree(work, ignore_errors=True)


def test_negative_puback_end_to_end():
    need_mosquitto()
    from event_source import SimulatedSource
    from outbox import Outbox
    from uplink_mqtt import MqttUplink

    work = tempfile.mkdtemp(prefix="mdgb-nack-")
    os.chmod(work, 0o777)
    port = free_port()
    # il nodo può scrivere hb ma NON events -> Mosquitto risponde PUBACK 0x87 (Not authorized)
    broker = Broker(port, work, acl="topic readwrite mdgb/+/hb\ntopic read mdgb/#\n")
    broker.start()
    store, ing_client = _start_central(port, work)
    ob = Outbox(os.path.join(work, "outbox.db"))
    sim = SimulatedSource(seed=2)
    ob.put_many([sim.make_event() for _ in range(120)])
    up = MqttUplink(ob, "nodo-nack", "mdgb", "127.0.0.1", port, batch=50, ack_timeout_s=5, nack_backoff_max_s=2)
    stop_node = threading.Event()

    def node_loop():
        while not stop_node.is_set():
            up.pump()
            time.sleep(0.05)

    try:
        assert wait_until(up.connected, 5)
        threading.Thread(target=node_loop, daemon=True).start()
        up.publish("hb", {"v": 1, "node_id": "nodo-nack", "type": "hb", "online": True}, retain=True)
        assert wait_until(lambda: up.nacks >= 2, 10), "nessun PUBACK negativo ricevuto"
        assert ob.backlog() == 120, "un PUBACK negativo non deve marcare nulla come inviato"
        assert up.online(), "gli hb confermati tengono il canale online: il problema è l'autorizzazione, non la rete"
        assert up.stable_s() == 0, "dopo un PUBACK negativo il canale non è 'stabile'"
        nacks = up.nacks
        time.sleep(3)
        assert up.nacks - nacks <= 3, f"troppi tentativi ({up.nacks - nacks} in 3 s): manca l'attesa crescente"
        print(f"... PUBACK negativi={up.nacks}, backlog={ob.backlog()} (invariato)")
        broker.set_acl("topic readwrite mdgb/#\n")
        assert wait_until(lambda: ob.backlog() == 0, 20), f"backlog non svuotato dopo la correzione: {ob.backlog()}"
        assert wait_until(lambda: store.report() and store.report()[0]["events"] == 120, 10)
        rep = store.report()[0]
        assert rep["gaps"] == 0
        print(f"OK  PUBACK negativo: eventi in coda finché il broker li rifiuta, poi 120/120, buchi={rep['gaps']}")
    finally:
        stop_node.set()
        up.stop()
        ing_client.loop_stop()
        broker.stop()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    test_c4b_node_and_central_agree()
    test_ble_frame_roundtrip()
    test_online_follows_positive_pubacks_only()
    test_c3_files_exactly_once_across_restart()
    test_offline_end_to_end()
    test_negative_puback_end_to_end()
    print("TUTTI I TEST SUPERATI")
