"""Subscriber di backend: riceve tutto, deduplica, salva, rileva perdite.

Fonti:
  1. Broker principale (Mosquitto/HiveMQ...):  {prefix}/+/events | agg | alert | status | agg/backup
  2. (opzionale) broker MQTT di The Things Network: v3/{app}@ttn/devices/+/up   (aggregati via LoRaWAN)

Garanzie:
  - dedup: PRIMARY KEY(node, seq) + INSERT OR IGNORE  -> i reinvii dopo un blackout non creano doppioni
  - perdita dati visibile: per ogni nodo confronta max(seq) con il numero di seq ricevuti ("buchi")
  - aggregati LoRa marcati come provvisori: vengono superati da quelli calcolati sugli eventi reali

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
import ssl
import sqlite3
import threading
import time

import paho.mqtt.client as mqtt

from decoder import decode

logging.basicConfig(level=logging.INFO, format="%(asctime)s ingest %(levelname)-7s %(message)s")
log = logging.getLogger("ingest")

MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
PREFIX = os.environ.get("TOPIC_PREFIX", "torino/crosswalk")
DB_PATH = os.environ.get("INGEST_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend.db"))
MQTT_TLS = os.environ.get("MQTT_TLS", "0").lower() in ("1", "true", "yes")
MQTT_CA = os.environ.get("MQTT_CA", "")
MQTT_CERT = os.environ.get("MQTT_CERT", "")
MQTT_KEY = os.environ.get("MQTT_KEY", "")
CLIENT_ID = os.environ.get("INGEST_CLIENT_ID", "crosswalk-ingest")


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
                node TEXT, seq INTEGER, ts REAL, cat TEXT, dir INTEGER, conf REAL, rx_at REAL,
                PRIMARY KEY(node, seq));
            CREATE TABLE IF NOT EXISTS aggregates(
                node TEXT, window_start INTEGER, source TEXT, provisional INTEGER, data TEXT, rx_at REAL,
                PRIMARY KEY(node, window_start, source));
            CREATE TABLE IF NOT EXISTS status(node TEXT PRIMARY KEY, data TEXT, rx_at REAL);
            CREATE TABLE IF NOT EXISTS alerts(node TEXT, seq INTEGER, data TEXT, rx_at REAL,
                PRIMARY KEY(node, seq));
        """)
        self.dups = 0

    def add_events(self, node, events):
        now = time.time()
        with self.lock:
            self.db.execute("BEGIN")
            new = 0
            for e in events:
                cur = self.db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)",
                                      (node, e["seq"], e["ts"], e["cat"], e["dir"], e["conf"], now))
                new += cur.rowcount
            self.db.execute("COMMIT")
            self.dups += len(events) - new
        return new

    def add_aggregate(self, node, window_start, source, provisional, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO aggregates VALUES(?,?,?,?,?,?)",
                            (node, int(window_start), source, int(provisional), json.dumps(data), time.time()))

    def set_status(self, node, data):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO status VALUES(?,?,?)", (node, json.dumps(data), time.time()))

    def add_alert(self, node, data):
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO alerts VALUES(?,?,?,?)",
                            (node, data.get("seq", -1), json.dumps(data), time.time()))

    def report(self):
        with self.lock:
            rows = self.db.execute(
                "SELECT node, COUNT(*), MIN(seq), MAX(seq) FROM events GROUP BY node").fetchall()
            out = []
            for node, n, smin, smax in rows:
                gaps = (smax - smin + 1) - n
                by_cat = dict(self.db.execute(
                    "SELECT cat, COUNT(*) FROM events WHERE node=? GROUP BY cat", (node,)).fetchall())
                lora = self.db.execute(
                    "SELECT COUNT(*) FROM aggregates WHERE node=? AND provisional=1", (node,)).fetchone()[0]
                out.append({"node": node, "events": n, "seq_range": [smin, smax], "gaps": gaps,
                            "by_cat": by_cat, "lora_aggregates": lora, "duplicates_dropped": self.dups})
        return out


def main_loop(store):
    def on_connect(c, u, flags, rc, props):
        log.info("connesso al broker %s:%d (sessione esistente=%s)", MQTT_HOST, MQTT_PORT, flags.session_present)
        for t in ("events", "agg", "alert", "status", "agg/backup"):
            c.subscribe(f"{PREFIX}/+/{t}", qos=1)

    def on_message(c, u, msg):
        try:
            parts = msg.topic.split("/")
            node = parts[len(PREFIX.split("/"))]
            kind = "/".join(parts[len(PREFIX.split("/")) + 1:])
            body = json.loads(msg.payload) if msg.payload else {}
            if kind == "events":
                new = store.add_events(node, body["events"])
                log.info("%s: +%d eventi (batch %d, seq %d..%d)", node, new, len(body["events"]),
                         body["events"][0]["seq"], body["events"][-1]["seq"])
            elif kind == "agg":
                store.add_aggregate(node, body["window_start"], "mqtt", False, body)
            elif kind == "agg/backup":                       # dal ricevitore LoRa P2P / ESP-NOW
                port = body.get("port", 1)
                data = decode(bytes.fromhex(body["hex"]), port)
                if "alarm" in data:
                    log.warning("%s: ALLARME %s via %s", node, data["alarm"], body.get("via"))
                else:
                    store.add_aggregate(node, data["window_start"], body.get("via", "backup"), True, data)
                    log.info("%s: aggregato provvisorio via %s, backlog sul nodo=%d",
                             node, body.get("via"), data["backlog"])
            elif kind == "alert":
                store.add_alert(node, body)
                log.info("%s: ALERT utente lento (%s)", node, body.get("cat"))
            elif kind == "status":
                store.set_status(node, body)
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
    """Aggregati che arrivano via LoRaWAN attraverso The Things Network."""
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
            port = um.get("f_port", 1)
            data = um.get("decoded_payload") or decode(base64.b64decode(um["frm_payload"]), port)
            if port == 9:
                log.warning("%s: ALLARME watchdog via LoRaWAN", dev)
            else:
                store.add_aggregate(dev, data["window_start"], "lorawan", True, data)
                rssi = um.get("rx_metadata", [{}])[0].get("rssi")
                log.info("%s: aggregato provvisorio via LoRaWAN (RSSI %s dBm), backlog=%s", dev, rssi, data["backlog"])
        except Exception as e:
            log.error("uplink TTN non valido: %s", e)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"crosswalk-ingest-ttn")
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
                log.info("RIEPILOGO %s: %d eventi, buchi=%d, duplicati scartati=%d, aggregati LoRa=%d",
                         r["node"], r["events"], r["gaps"], r["duplicates_dropped"], r["lora_aggregates"])
    except KeyboardInterrupt:
        pass
