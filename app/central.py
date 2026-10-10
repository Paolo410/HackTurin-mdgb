"""Programma della centrale (docs/CONTRACTS.md v1). Sul PC si usa l'app "MDGB Centrale" (app/desktop/), che avvia
questa stessa classe Central; da terminale: python app/central.py.

    canale principale:  nodo ──Wi-Fi/MQTT──► AWS IoT Core (o Mosquitto) ──► qui   (ingest.py)
    canale di backup:   nodo ──BLE──────────────────────────────────────► qui   (Bluetooth del PC, SENZA Internet)
Tutto finisce nello stesso database (app/central.db): eventi deduplicati, aggregati, heartbeat, messaggi di
backup, e ogni 10 s la diagnosi di ogni nodo (OK / rete giù / guasto / Linux bloccato / manomissione / ...).
La dashboard per chi guarda i dati è su http://localhost:8080 (dashboard.py).

Uso:
    python app/central.py                       # MQTT + BLE + dashboard (nodo nodo01)
    python app/central.py --host 0.0.0.0        # dashboard visibile anche da telefono/tablet sulla stessa rete
    python app/central.py --node nodo07         # nome del nodo da associare ai beacon BLE
    python app/central.py --no-ble              # solo MQTT (PC senza Bluetooth)
    python app/central.py --report              # riepilogo dal database ed esce
Variabili MQTT come ingest.py (MQTT_HOST, MQTT_PORT, MQTT_TLS, MQTT_CA, MQTT_CERT, MQTT_KEY, INGEST_CLIENT_ID).
"""
import argparse
import asyncio
import json
import logging
import os
import socket
import threading
import time

import dashboard
import ingest
from ble_receiver import COMPANY_ID, Receiver

log = logging.getLogger("ingest")


def ble_to_store(store, node):
    """Ricevitore BLE che scrive direttamente nel database della centrale (niente broker, niente Internet)."""
    def deliver(topic, payload):
        m = json.loads(payload)
        ingest.handle_backup(store, m["node_id"], m["type"], bytes.fromhex(m["hex"]), "ble", m.get("rssi"))
    return Receiver(node, deliver)


def log_status(store):
    for r in store.report():
        log.info("RIEPILOGO %s: %d eventi, buchi=%d, duplicati scartati=%d, aggregati di backup=%d",
                 r["node"], r["events"], r["gaps"], r["duplicates_dropped"], r["backup_aggregates"])
    for node in store.nodes():
        d = store.diagnose(node)
        log.info("STATO %s: %s%s", node, d["text"], f" via {d['via']}" if d["via"] else "")


def lan_ip():
    """Indirizzo di questo PC sulla rete locale: è quello da dare ai nodi (MQTT_HOST) in modalità locale."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))        # nessun pacchetto parte: serve solo a scegliere l'interfaccia
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class Central:
    """Tutti i servizi della centrale: MQTT (+ TTN), Bluetooth, dashboard. start() non blocca; stop() ferma tutto."""

    def __init__(self, db_path=None, node="nodo01", use_ble=True, addr=None, web=True, host="127.0.0.1", port=8080):
        self.db_path = db_path or ingest.DB_PATH
        self.node, self.use_ble, self.addr = node, use_ble, addr
        self.web, self.host, self.port = web, host, port
        self.ble_status = "spento" if not use_ble else "in avvio"
        self.store = self.mqtt = self.ttn = self.server = None
        self._stop = threading.Event()
        self._thread = None

    @property
    def url(self):
        return f"http://localhost:{self.server.server_port}" if self.server else None

    def start(self):
        self.store = ingest.Store(self.db_path)
        self.mqtt = ingest.main_loop(self.store)
        self.ttn = ingest.ttn_loop(self.store)
        if self.web:
            try:
                self.server = dashboard.serve(self.store, self.host, self.port, info=self.info)
            except OSError:                       # porta occupata: ne sceglie una libera
                self.server = dashboard.serve(self.store, self.host, 0, info=self.info)
            log.info("dashboard: %s", self.url)
        self._thread = threading.Thread(target=lambda: asyncio.run(self._run()), name="central", daemon=True)
        self._thread.start()
        return self

    def info(self):
        """Stato della centrale stessa, mostrato in alto nella dashboard."""
        local = ingest.MQTT_HOST in ("localhost", "127.0.0.1")
        return {"mqtt": {"host": ingest.MQTT_HOST, "port": ingest.MQTT_PORT, "tls": ingest.MQTT_TLS,
                         "connected": bool(self.mqtt and self.mqtt.is_connected()), "local": local,
                         "nodes_connect_to": f"{lan_ip()}:{ingest.MQTT_PORT}" if local else None},
                "ble": self.ble_status, "config_dir": os.environ.get("MDGB_HOME"), "db": self.db_path,
                "maps_key": os.environ.get("GOOGLE_MAPS_API_KEY", "")}

    async def _run(self):
        scanner = None
        if self.use_ble:
            try:
                from bleak import BleakScanner
                rx = ble_to_store(self.store, self.node)

                def on_adv(device, adv):
                    if self.addr and device.address.upper() != self.addr.upper():
                        return
                    frame = adv.manufacturer_data.get(COMPANY_ID)
                    if frame and rx.handle(frame, adv.rssi, device.address):
                        log.info("BLE: beacon type %d da %s (RSSI %s)", frame[0], device.address, adv.rssi)

                # TODO(verify): scansione BLE da un thread non principale su macOS (CoreBluetooth via bleak)
                scanner = BleakScanner(detection_callback=on_adv)
                await scanner.start()
                self.ble_status = "in ascolto"
                log.info("BLE in ascolto (company 0x%04X) per il nodo %s", COMPANY_ID, self.node)
            except Exception as e:                  # niente Bluetooth o permesso negato: si continua solo MQTT
                self.ble_status = f"non disponibile ({e})"
                log.error("BLE non disponibile (%s): la centrale continua solo con MQTT", e)
                scanner = None
        t_log = time.time()
        try:
            while not self._stop.is_set():
                await asyncio.sleep(0.5)
                if time.time() - t_log >= 10:
                    log_status(self.store)
                    t_log = time.time()
        finally:
            if scanner is not None:
                await scanner.stop()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        for c in (self.mqtt, self.ttn):
            if c is not None:
                c.loop_stop()
                c.disconnect()
        if self.server:
            self.server.shutdown()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--node", default="nodo01", help="nodo a cui appartengono i beacon BLE ricevuti")
    ap.add_argument("--addr", default=None, help="accetta solo i beacon di questo indirizzo BLE (su macOS è un UUID)")
    ap.add_argument("--no-ble", action="store_true")
    ap.add_argument("--no-web", action="store_true", help="senza dashboard")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 = dashboard visibile dalla rete locale")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.report:
        print(json.dumps(ingest.Store(ingest.DB_PATH).report(), indent=2, ensure_ascii=False))
        return
    central = Central(node=a.node, use_ble=not a.no_ble, addr=a.addr, web=not a.no_web, host=a.host,
                      port=a.port).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        central.stop()


if __name__ == "__main__":
    main()
