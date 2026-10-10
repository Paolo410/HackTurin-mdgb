"""Programma della centrale: È L'UNICO DA LANCIARE SUL PC (docs/CONTRACTS.md v1).

    canale principale:  nodo ──Wi-Fi/MQTT──► AWS IoT Core (o Mosquitto) ──► qui   (ingest.py)
    canale di backup:   nodo ──BLE──────────────────────────────────────► qui   (Bluetooth del PC, SENZA Internet)
Tutto finisce nello stesso database (app/central.db): eventi deduplicati, aggregati, heartbeat, messaggi di
backup, e ogni 10 s la diagnosi di ogni nodo (OK / rete giù / guasto / Linux bloccato / manomissione / ...).

Uso:
    python app/central.py                       # MQTT + BLE (nodo nodo01)
    python app/central.py --node nodo07         # nome del nodo da associare ai beacon BLE
    python app/central.py --no-ble              # solo MQTT (PC senza Bluetooth)
    python app/central.py --report              # riepilogo dal database ed esce
Variabili MQTT come ingest.py (MQTT_HOST, MQTT_PORT, MQTT_TLS, MQTT_CA, MQTT_CERT, MQTT_KEY, INGEST_CLIENT_ID).
"""
import argparse
import asyncio
import json
import logging
import time

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


async def run(store, node, use_ble, addr=None):
    scanner = None
    if use_ble:
        try:
            from bleak import BleakScanner
            rx = ble_to_store(store, node)

            def on_adv(device, adv):
                if addr and device.address.upper() != addr.upper():
                    return
                frame = adv.manufacturer_data.get(COMPANY_ID)
                if frame and rx.handle(frame, adv.rssi, device.address):
                    log.info("BLE: beacon type %d da %s (RSSI %s)", frame[0], device.address, adv.rssi)

            scanner = BleakScanner(detection_callback=on_adv)
            await scanner.start()
            log.info("BLE in ascolto (company 0x%04X) per il nodo %s", COMPANY_ID, node)
        except Exception as e:                      # niente Bluetooth o permesso negato: si continua solo MQTT
            log.error("BLE non disponibile (%s): la centrale continua solo con MQTT", e)
            scanner = None
    try:
        while True:
            await asyncio.sleep(10)
            log_status(store)
    finally:
        if scanner is not None:
            await scanner.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--node", default="nodo01", help="nodo a cui appartengono i beacon BLE ricevuti")
    ap.add_argument("--addr", default=None, help="accetta solo i beacon di questo indirizzo BLE (su macOS è un UUID)")
    ap.add_argument("--no-ble", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    store = ingest.Store(ingest.DB_PATH)
    if a.report:
        print(json.dumps(store.report(), indent=2, ensure_ascii=False))
        return
    ingest.main_loop(store)
    ingest.ttn_loop(store)
    try:
        asyncio.run(run(store, a.node, not a.no_ble, a.addr))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
