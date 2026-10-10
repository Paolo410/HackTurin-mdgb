"""Subscriber della centrale: riceve tutto, deduplica, salva, rileva perdite (docs/CONTRACTS.md v1, C4 e C4-B).

Fonti:
  1. Broker principale (AWS IoT Core / Mosquitto):  {prefix}/+/events | agg | hb | backup
  2. (opzionale) broker MQTT di The Things Network: v3/{app}@ttn/devices/+/up   (backup via LoRaWAN)

Garanzie:
  - dedup: PRIMARY KEY(node, seq) + INSERT OR IGNORE  -> i reinvii dopo un blackout non creano doppioni
  - perdita dati visibile: per ogni nodo confronta max(seq) con il numero di seq ricevuti ("buchi")
  - aggregati del backup marcati come provvisori: vengono superati da quelli calcolati sugli eventi reali
  - messaggi di backup deduplicati su (node, type, ts): lo stesso beacon visto da più ricevitori conta una volta

Uso:
  python ingest.py                 # ascolta e stampa statistiche ogni 10 s
  python ingest.py --report        # stampa il riepilogo dal DB ed esce
Variabili: MQTT_HOST, MQTT_PORT, TOPIC_PREFIX, INGEST_DB, TTN_APP_ID, TTN_API_KEY, TTN_HOST
           AWS IoT Core: MQTT_TLS=1, MQTT_CA, MQTT_CERT, MQTT_KEY, INGEST_CLIENT_ID (= nome del Thing "ingest")
"""
import argparse
import base64
import json
import logging
import os
import re
import ssl
import sqlite3
import threading
import time

import paho.mqtt.client as mqtt

from decoder import decode
from diagnosis import diagnose

logging.basicConfig(level=logging.INFO, format="%(asctime)s ingest %(levelname)-7s %(message)s")
log = logging.getLogger("ingest")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_dotenv(path):
    """Legge KEY=VALUE da app/.env (ignorato da git) senza sovrascrivere le variabili già impostate."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), re.split(r"\s+#", v, maxsplit=1)[0].strip())
    except FileNotFoundError:
        pass


def _path(v):
    return v if not v or os.path.isabs(v) else os.path.join(REPO_ROOT, v)


_load_dotenv(os.path.join(REPO_ROOT, "app", ".env"))
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
PREFIX = os.environ.get("TOPIC_PREFIX", "mdgb")
DB_PATH = os.environ.get("INGEST_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "central.db"))
MQTT_TLS = os.environ.get("MQTT_TLS", "0").lower() in ("1", "true", "yes")
MQTT_CA = _path(os.environ.get("MQTT_CA", ""))
MQTT_CERT = _path(os.environ.get("MQTT_CERT", ""))
MQTT_KEY = _path(os.environ.get("MQTT_KEY", ""))
CLIENT_ID = os.environ.get("INGEST_CLIENT_ID", "mdgb-ingest")


def tls_context():
    ctx = ssl.create_default_context(cafile=MQTT_CA or None)
    if MQTT_CERT and MQTT_KEY:
        ctx.load_cert_chain(MQTT_CERT, MQTT_KEY)
    if MQTT_PORT == 443:
        ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])
    return ctx


class Store:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS events(
                node TEXT, seq INTEGER, ts REAL, type TEXT, body TEXT, rx_at REAL,
                PRIMARY KEY(node, seq));
            CREATE TABLE IF NOT EXISTS aggregates(
                node TEXT, window_start INTEGER, source TEXT, provisional INTEGER, data TEXT, rx_at REAL,
                PRIMARY KEY(node, window_start, source));
            CREATE TABLE IF NOT EXISTS hb(node TEXT PRIMARY KEY, data TEXT, rx_at REAL);
            CREATE TABLE IF NOT EXISTS backup(
                node TEXT, type INTEGER, ts INTEGER, via TEXT, data TEXT, rx_at REAL,
                PRIMARY KEY(node, type, ts));
        """)
        self.dups = 0

    def add_events(self, node, events):
        now = time.time()
        with self.lock:
            self.db.execute("BEGIN")
            new = 0
            for e in events:
                cur = self.db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?)",
                                      (node, e["seq"], e.get("ts"), e.get("type"), json.dumps(e), now))
                new += cur.rowcount
            self.db.execute("COMMIT")
            self.dups += len(events) - new
        return new

    def add_aggregate(self, node, window_start, source, provisional, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO aggregates VALUES(?,?,?,?,?,?)",
                            (node, int(window_start), source, int(provisional), json.dumps(data), time.time()))

    def set_hb(self, node, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO hb VALUES(?,?,?)", (node, json.dumps(data), time.time()))

    def add_backup(self, node, type_, data, via):
        """Ritorna True se il messaggio è nuovo (non già visto da un altro ricevitore)."""
        now = time.time()
        ts = data.get("t0") or data.get("ts") or int(now // 60) * 60     # DEAD non ha ts: chiave al minuto
        with self.lock:
            new = self.db.execute("INSERT OR IGNORE INTO backup VALUES(?,?,?,?,?,?)",
                                  (node, type_, int(ts), via, json.dumps(data), now)).rowcount
        if new and data.get("kind") == "agg":
            self.add_aggregate(node, data["t0"], via, True, data)
        return bool(new)

    def nodes(self):
        with self.lock:
            return [r[0] for r in self.db.execute(
                "SELECT node FROM hb UNION SELECT node FROM backup UNION SELECT DISTINCT node FROM events")]

    def diagnose(self, node, now=None, **windows):
        """Diagnosi del nodo incrociando l'ultimo `hb` MQTT e i messaggi di backup dell'ultima ora."""
        now = time.time() if now is None else now
        with self.lock:
            row = self.db.execute("SELECT data, rx_at FROM hb WHERE node=?", (node,)).fetchone()
            rows = self.db.execute("SELECT rx_at, via, data FROM backup WHERE node=? AND rx_at>=?",
                                   (node, now - 3600)).fetchall()
        hb, hb_rx = (json.loads(row[0]), row[1]) if row else (None, None)
        return diagnose(now, hb, hb_rx, [(t, v, json.loads(d)) for t, v, d in rows], **windows)

    def report(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT node, COUNT(*), MIN(seq), MAX(seq) FROM events GROUP BY node").fetchall()
            out = []
            for node, n, smin, smax in rows:
                gaps = (smax - smin + 1) - n
                by_type = dict(self.db.execute(
                    "SELECT type, COUNT(*) FROM events WHERE node=? GROUP BY type", (node,)).fetchall())
                prov = self.db.execute(
                    "SELECT COUNT(*) FROM aggregates WHERE node=? AND provisional=1", (node,)).fetchone()[0]
                out.append({"node": node, "events": n, "seq_range": [smin, smax], "gaps": gaps,
                            "by_type": by_type, "backup_aggregates": prov, "duplicates_dropped": self.dups})
        for r in out:
            r["diagnosis"] = self.diagnose(r["node"])["text"]
        return out


def handle_backup(store, node, type_, raw: bytes, via, rssi=None):
    data = decode(type_, raw)
    if not store.add_backup(node, type_, data, via):
        return
    if data["kind"] == "alarm":
        log.warning("%s: ALLARME %s %s via %s (RSSI %s)", node, data["alarm"], data.get("detail", ""), via, rssi)
    elif data["kind"] == "agg":
        log.info("%s: aggregato provvisorio via %s, backlog sul nodo=%d", node, via, data["backlog"])
    else:
        log.info("%s: hb via %s, mode=%s, backlog=%d, %d min senza conferme MQTT",
                 node, via, data["mode"], data["backlog"], data["offline_min"])


def main_loop(store):
    def on_connect(c, u, flags, rc, props):
        log.info("connesso al broker %s:%d (sessione esistente=%s)", MQTT_HOST, MQTT_PORT, flags.session_present)
        for t in ("events", "agg", "hb", "backup"):
            c.subscribe(f"{PREFIX}/+/{t}", qos=1)

    def on_message(c, u, msg):
        try:
            parts = msg.topic.split("/")
            node = parts[len(PREFIX.split("/"))]
            kind = "/".join(parts[len(PREFIX.split("/")) + 1:])
            body = json.loads(msg.payload) if msg.payload else {}
            if body.get("node_id", node) != node:
                log.warning("node_id %s diverso dal topic %s: vale il topic", body.get("node_id"), msg.topic)
            if kind == "events":
                evs = body["events"]
                new = store.add_events(node, evs)
                log.info("%s: +%d eventi (batch %d, seq %d..%d)", node, new, len(evs), evs[0]["seq"], evs[-1]["seq"])
            elif kind == "agg":
                store.add_aggregate(node, body["t0"], "mqtt", False, body)
            elif kind == "backup":                       # dai ricevitori BLE / LoRa P2P / ESP-NOW
                handle_backup(store, node, int(body["type"]), bytes.fromhex(body["hex"]), body.get("via", "backup"),
                              body.get("rssi"))
            elif kind == "hb":
                store.set_hb(node, body)
        except Exception as e:
            log.error("messaggio non valido su %s: %s", msg.topic, e)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, protocol=mqtt.MQTTv5)
    if MQTT_TLS:
        c.tls_set_context(tls_context())
    c.on_connect, c.on_message = on_connect, on_message
    # sessione persistente: se l'ingest si disconnette, il broker gli conserva i messaggi QoS 1
    props = mqtt.Properties(mqtt.PacketTypes.CONNECT)
    props.SessionExpiryInterval = int(os.environ.get("MQTT_SESSION_EXPIRY_S", 3600))  # AWS: default max 1 h
    c.reconnect_delay_set(1, 30)
    c.connect_async(MQTT_HOST, MQTT_PORT, keepalive=15, clean_start=False, properties=props)
    c.loop_start()
    return c


def ttn_loop(store):
    """Backup C4-B che arriva via LoRaWAN attraverso The Things Network (device_id = node_id, fPort = type)."""
    app, key = os.environ.get("TTN_APP_ID"), os.environ.get("TTN_API_KEY")
    if not (app and key):
        log.info("TTN non configurato (TTN_APP_ID/TTN_API_KEY): salto")
        return None
    host = os.environ.get("TTN_HOST", "eu1.cloud.thethings.network")

    def on_message(c, u, msg):
        try:
            up = json.loads(msg.payload)
            dev = up["end_device_ids"]["device_id"]
            um = up["uplink_message"]
            rssi = um.get("rx_metadata", [{}])[0].get("rssi")
            handle_backup(store, dev, um.get("f_port", 1), base64.b64decode(um.get("frm_payload", "")), "lorawan", rssi)
        except Exception as e:
            log.error("uplink TTN non valido: %s", e)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{CLIENT_ID}-ttn")
    c.username_pw_set(f"{app}@ttn", key)
    c.tls_set()
    c.on_connect = lambda cl, u, f, rc, p: cl.subscribe(f"v3/{app}@ttn/devices/+/up", qos=1)
    c.on_message = on_message
    c.connect_async(host, 8883, keepalive=30)
    c.loop_start()
    return c


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    store = Store(DB_PATH)
    if args.report:
        print(json.dumps(store.report(), indent=2))
        raise SystemExit
    main_loop(store)
    ttn_loop(store)
    try:
        while True:
            time.sleep(10)
            for r in store.report():
                log.info("RIEPILOGO %s: %d eventi, buchi=%d, duplicati scartati=%d, aggregati di backup=%d",
                         r["node"], r["events"], r["gaps"], r["duplicates_dropped"], r["backup_aggregates"])
            for node in store.nodes():
                d = store.diagnose(node)
                log.info("STATO %s: %s%s", node, d["text"], f" via {d['via']}" if d["via"] else "")
    except KeyboardInterrupt:
        pass
