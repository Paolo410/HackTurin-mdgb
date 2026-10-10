"""Backup BLE: failover con isteresi, ricevitore, diagnosi in centrale, e la prova "Wi-Fi spento / riacceso".

Tempi reali 30 s / 60 s / 5 min: nei test sono scalati (2 s / 3 s / 1 s), la logica è la stessa.
"""
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (ROOT, os.path.join(ROOT, "comms", "node"), os.path.join(ROOT, "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

from aggregator import Aggregator  # noqa: E402
from backup_link import SimulatedBle  # noqa: E402
from decoder import decode  # noqa: E402
from diagnosis import diagnose  # noqa: E402
from failover import Failover  # noqa: E402
from outbox import Outbox  # noqa: E402
from payload import TYPE_AGG, TYPE_HB, TYPE_INCIDENT  # noqa: E402


# ------------------------------------------------------------------ failover (unitari, orologio finto)
class FakeUplink:
    def __init__(self):
        self.last_ack, self.stable = 0.0, 0.0

    def stable_s(self, now=None):
        return self.stable

    def online(self, now=None):
        return False


@pytest.fixture
def rig(tmp_path):
    t = [1739012400.0]
    ob = Outbox(str(tmp_path / "o.db"))
    up = FakeUplink()
    ble = SimulatedBle()
    agg = Aggregator(ob, up, period_s=900, node_id="nodo01")
    fo = Failover(ob, up, ble, agg, on_after_s=30, off_after_s=60, hb_period_s=300, alarm_hold_s=2,
                  clock=lambda: t[0])
    up.last_ack = t[0]                        # MQTT confermato all'inizio
    return t, ob, up, ble, fo


def frames_by_type(ble):
    return {f[0]: f[1:] for f in ble.frames.values()}


def test_backup_turns_on_after_30s_without_confirmations(rig):
    t, ob, up, ble, fo = rig
    ob.put({"v": 1, "ts": t[0] - 1000, "type": "crossing", "cls": "pedestrian", "dir": "in"})
    t[0] += 29
    fo.tick()
    assert not fo.active and not ble.frames, "prima di 30 s il backup resta spento"
    t[0] += 1
    fo.tick()
    assert fo.active
    got = frames_by_type(ble)
    assert set(got) == {TYPE_HB, TYPE_AGG}, "all'accensione HB e AGG partono SUBITO"
    hb = decode(TYPE_HB, got[TYPE_HB])
    assert hb["backlog"] == 0 and hb["offline_min"] == 0 and hb["ts"] == int(t[0])


def test_hb_every_period_agg_every_window(rig):
    t, ob, up, ble, fo = rig
    t[0] += 30
    fo.tick()
    n_hb = lambda: sum(1 for c in ble.commands if c[:2] == ["btmgmt", "add-adv"] and c[-1] == "2")
    n_agg = lambda: sum(1 for c in ble.commands if c[:2] == ["btmgmt", "add-adv"] and c[-1] == "1")
    assert (n_hb(), n_agg()) == (1, 1)
    t[0] += 299
    fo.tick()
    assert n_hb() == 1
    t[0] += 1
    fo.tick()
    assert n_hb() == 2, "HB ogni 5 min"
    t[0] += 900
    fo.tick()
    assert n_agg() == 2, "un AGG a ogni finestra chiusa"
    assert decode(TYPE_HB, frames_by_type(ble)[TYPE_HB])["offline_min"] == 20


def test_alarms_go_out_immediately_and_do_not_overwrite_each_other(rig):
    t, ob, up, ble, fo = rig
    ob.put({"v": 1, "ts": t[0] + 5, "type": "tamper", "code": 2, "src": "mcu"})   # prima dell'accensione
    t[0] += 30
    fo.tick()
    assert decode(10, frames_by_type(ble)[10]) ["code"] == 2, "allarmi non confermati partono all'accensione"
    ob.put({"v": 1, "ts": t[0], "type": "incident", "kind": "person_down", "track_id": 3})
    ob.put({"v": 1, "ts": t[0], "type": "lamp_fault", "src": "mcu"})
    ob.put({"v": 1, "ts": t[0], "type": "near_miss", "a": 1, "b": 2})                 # non è un allarme
    t[0] += 2
    fo.tick()
    assert decode(TYPE_INCIDENT, frames_by_type(ble)[TYPE_INCIDENT])["detail"] == "person_down"
    t[0] += 1
    fo.tick()
    assert TYPE_INCIDENT in frames_by_type(ble), "ogni allarme resta in onda almeno alarm_hold_s"
    t[0] += 1
    fo.tick()
    assert decode(12, frames_by_type(ble)[12])["detail"] == "lamp_fault"
    assert set(frames_by_type(ble)) == {TYPE_HB, TYPE_AGG, 12}, "HB e AGG restano in onda insieme agli allarmi"


def test_backup_turns_off_only_after_60s_of_stable_mqtt(rig):
    t, ob, up, ble, fo = rig
    t[0] += 30
    fo.tick()
    up.last_ack, up.stable = t[0], 59          # MQTT tornato, ma stabile da 59 s
    fo.tick()
    assert fo.active and ble.frames
    up.stable = 0                              # un'interruzione azzera il conteggio (isteresi)
    fo.tick()
    up.stable = 60
    fo.tick()
    assert not fo.active and not ble.frames and not ble.active
    assert ble.commands[-2:] == [["btmgmt", "rm-adv", "1"], ["btmgmt", "rm-adv", "2"]]


def test_backup_turns_on_if_mqtt_never_comes_up(tmp_path):
    t = [1000.0]
    ob, up, ble = Outbox(str(tmp_path / "o.db")), FakeUplink(), SimulatedBle()
    fo = Failover(ob, up, ble, Aggregator(ob, up, 900, "n"), clock=lambda: t[0])
    t[0] += 29.9
    fo.tick()
    assert not fo.active
    t[0] += 0.1
    fo.tick()
    assert fo.active, "30 s dall'avvio senza MQTT -> backup acceso"


# ------------------------------------------------------------------ ricevitore BLE
def test_receiver_forwards_each_frame_once_and_retries_on_failure():
    from ble_receiver import Receiver
    sent, fail = [], [True]

    def pub(topic, payload):
        if fail[0]:
            raise OSError("broker irraggiungibile")
        sent.append((topic, json.loads(payload)))

    rx = Receiver("nodo01", pub)
    frame = bytes([2]) + bytes(26)
    assert rx.handle(frame, -70, "AA") is None and not sent
    fail[0] = False
    assert rx.handle(frame, -70, "AA")["type"] == 2
    assert rx.handle(frame, -71, "AA") is None, "beacon ripetuto: già inoltrato"
    assert rx.handle(b"\x01\x02", -70, "AA") is None, "non è un frame MDGB"
    assert sent[0][0] == "mdgb/nodo01/backup" and sent[0][1]["via"] == "ble"


# ------------------------------------------------------------------ diagnosi
def test_diagnosis_table():
    now = 10_000.0
    hb_ok = {"online": True, "mode": "normal", "batt": 80}
    bhb = lambda mode="normal", batt=None: {"kind": "hb", "mode": mode, "batt": batt}
    alarm = lambda name, code=0: {"kind": "alarm", "alarm": name, "code": code, "detail": "x"}
    assert diagnose(now)["code"] == "unknown"
    assert diagnose(now, hb_ok, now - 5)["code"] == "ok"
    assert diagnose(now, hb_ok, now - 100, [(now - 10, "ble", bhb())]) == \
        {"code": "network_down", "text": "rete giù, nodo sano", "via": "ble", "last_contact": now - 10}
    assert diagnose(now, hb_ok, now - 5, [(now - 1, "ble", bhb("failsafe"))])["code"] == "faulty"
    assert diagnose(now, {"online": False}, now - 1)["code"] == "destroyed", "Last Will senza preavviso"
    old = now - 2000
    assert diagnose(now, hb_ok, old, [(old, "lorawan", alarm("dead"))])["code"] == "linux_hung"
    assert diagnose(now, hb_ok, old, [(old - 60, "ble", alarm("tamper", 2))])["code"] == "tampered"
    assert diagnose(now, hb_ok, old, [(old - 300, "ble", alarm("tamper", 3)), (old - 60, "ble", alarm("tamper", 2))]
                    )["code"] == "destroyed", "sportello aperto dal tecnico col badge: niente allarme"
    assert diagnose(now, None, None, [(old, "ble", bhb(batt=12))])["code"] == "battery_low"


# ------------------------------------------------------------------ prova "Wi-Fi spento / riacceso"
class WifiProxy:
    """Proxy TCP tra nodo e broker. cut() simula il Wi-Fi che sparisce: i byte si perdono ma la connessione NON
    si chiude (il nodo se ne accorge solo dai PUBACK mancanti); restore() lo riporta, chiudendo le connessioni
    morte come succede dopo un vero blackout."""

    def __init__(self, target_port):
        self.target, self.up, self.conns, self.lock = target_port, True, [], threading.Lock()
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen()
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            if not self.up:
                c.close()
                continue
            try:
                u = socket.create_connection(("127.0.0.1", self.target))
            except OSError:
                c.close()
                continue
            with self.lock:
                self.conns.append((c, u))
            for a, b in ((c, u), (u, c)):
                threading.Thread(target=self._pipe, args=(a, b), daemon=True).start()

    def _pipe(self, a, b):
        try:
            while True:
                data = a.recv(65536)
                if not data:
                    break
                if self.up:
                    b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.close()
                except OSError:
                    pass

    def cut(self):
        self.up = False

    def restore(self):
        with self.lock:
            conns, self.conns = self.conns, []
        for pair in conns:
            for s in pair:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                    s.close()
                except OSError:
                    pass
        self.up = True

    def close(self):
        self.srv.close()
        self.restore()


def test_wifi_off_then_on_ble_backup_end_to_end():
    import paho.mqtt.client as mqtt
    from ble_receiver import Receiver
    from event_source import SimulatedSource
    from test_offline import Broker, _start_central, free_port, need_mosquitto, wait_until
    from uplink_mqtt import MqttUplink
    need_mosquitto()

    work = tempfile.mkdtemp(prefix="mdgb-wifi-")
    os.chmod(work, 0o777)
    port = free_port()
    broker = Broker(port, work)
    broker.start()
    store, ing_client = _start_central(port, work)
    wifi = WifiProxy(port)
    node = "nodo-wifi"
    win = {"mqtt_window_s": 2, "backup_window_s": 4}

    ob = Outbox(os.path.join(work, "outbox.db"))
    up = MqttUplink(ob, node, "mdgb", "127.0.0.1", wifi.port, batch=50, ack_timeout_s=3, ack_window_s=2)
    ble = SimulatedBle()
    agg = Aggregator(ob, up, period_s=2, node_id=node)
    fo = Failover(ob, up, ble, agg, on_after_s=2, off_after_s=3, hb_period_s=1, alarm_hold_s=0.3)

    gw = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="ble-gw-test", protocol=mqtt.MQTTv5)
    gw.connect("127.0.0.1", port)
    gw.loop_start()
    rx = Receiver(node, lambda topic, payload: gw.publish(topic, payload, qos=1))

    stop_gen, stop_all = threading.Event(), threading.Event()
    sim = SimulatedSource(seed=3)
    log = {}

    def generate():                                    # ~40 eventi/s
        while not stop_gen.is_set():
            ob.put(sim.make_event())
            time.sleep(0.025)

    def node_loop():
        t_hb = 0.0
        while not stop_all.is_set():
            now = time.time()
            up.pump()
            agg.tick(now)
            was = fo.active
            fo.tick(now)
            if fo.active != was:
                log["on" if fo.active else "off"] = now
            if now - t_hb >= 0.5:
                up.publish("hb", {"v": 1, "node_id": node, "type": "hb", "online": True, "mode": "normal"}, retain=True)
                t_hb = now
            if up.online(now) and "restore" in log and "back" not in log:
                log["back"] = now
            time.sleep(0.05)

    def air():                                         # la radio: il laptop vede i beacon in onda
        while not stop_all.is_set():
            for frame in list(ble.frames.values()):
                rx.handle(frame, -65, "uno-q")
            time.sleep(0.2)

    for f in (generate, node_loop, air):
        threading.Thread(target=f, daemon=True).start()
    try:
        assert wait_until(lambda: store.diagnose(node, **win)["code"] == "ok", 10), store.diagnose(node, **win)
        time.sleep(1)
        assert not fo.active and not ble.frames
        print(f"... Wi-Fi acceso: diagnosi '{store.diagnose(node, **win)['text']}', backlog={ob.backlog()}")

        wifi.cut()
        log["cut"] = time.time()
        assert wait_until(lambda: fo.active, 6), "il backup BLE non si accende"
        dt = log["on"] - log["cut"]
        assert 1.5 <= dt <= 4, f"acceso dopo {dt:.1f} s: atteso circa on_after_s=2 s (30 s nella realtà)"
        assert {f[0] for f in ble.frames.values()} >= {TYPE_HB, TYPE_AGG}, "HB e AGG subito all'accensione"
        assert wait_until(lambda: store.diagnose(node, **win)["code"] == "network_down", 8), store.diagnose(node, **win)
        print(f"... Wi-Fi SPENTO: BLE acceso dopo {dt:.1f} s, diagnosi '{store.diagnose(node, **win)['text']}' "
              f"via {store.diagnose(node, **win)['via']}")
        ob.put({"v": 1, "ts": time.time(), "type": "incident", "kind": "person_down", "track_id": 999})
        t_alarm = time.time()
        assert wait_until(lambda: store.db.execute(
            "SELECT COUNT(*) FROM backup WHERE node=? AND type=?", (node, TYPE_INCIDENT)).fetchone()[0], 3)
        print(f"... allarme 'persona a terra' arrivato in centrale via BLE in {time.time() - t_alarm:.1f} s")
        time.sleep(2)
        backlog_off = ob.backlog()
        assert backlog_off > 100, "durante il blackout gli eventi si accumulano su disco"
        assert store.report()[0]["backup_aggregates"] >= 1, "aggregati provvisori in centrale via BLE"

        log["restore"] = time.time()
        wifi.restore()
        assert wait_until(lambda: ob.backlog() == 0, 30), f"backfill incompleto: {ob.backlog()}"
        assert wait_until(lambda: not fo.active, 10), "il backup BLE non si spegne"
        stable = log["off"] - log["back"]
        assert stable >= 2.5, f"spento dopo {stable:.1f} s di MQTT stabile: atteso off_after_s=3 s (60 s nella realtà)"
        assert not ble.frames and not ble.active
        print(f"... Wi-Fi RIACCESO: backlog {backlog_off} -> 0, BLE spento dopo {stable:.1f} s di MQTT stabile")

        stop_gen.set()
        time.sleep(0.5)
        total = ob._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert wait_until(lambda: store.report()[0]["events"] == total, 20), (store.report(), total)
        rep = store.report()[0]
        assert rep["gaps"] == 0
        assert wait_until(lambda: store.diagnose(node, **win)["code"] == "ok", 5)
        print(f"OK  Wi-Fi spento/riacceso: inviati={total}, ricevuti={rep['events']}, buchi={rep['gaps']}, "
              f"duplicati scartati={rep['duplicates_dropped']}, diagnosi finale '{store.diagnose(node, **win)['text']}'")
    finally:
        stop_gen.set()
        stop_all.set()
        up.stop()
        gw.loop_stop()
        ing_client.loop_stop()
        wifi.close()
        broker.stop()
        shutil.rmtree(work, ignore_errors=True)
