"""Ricevitore del canale di backup BLE (gira sul laptop, o su qualsiasi PC con Bluetooth).

Ascolta i beacon del nodo (manufacturer data, company ID 0xFFFF, frame C4-B da 27 byte), elimina le
ripetizioni (un beacon viene ritrasmesso più volte al secondo) e ripubblica ogni messaggio NUOVO su
    {prefix}/{node}/backup     {"v": 1, "node_id", "via": "ble", "type", "hex", "rssi", "rx_at"}
Non decodifica: decodifica la centrale (un solo decoder, docs/CONTRACTS.md v1).

Uso:   python ble_receiver.py --node nodo01
       python ble_receiver.py --node nodo01 --dry-run         # prima prova: stampa e basta, niente broker
       python ble_receiver.py --node nodo01 --addr <indirizzo>   # filtra un solo nodo
Richiede: pip install bleak paho-mqtt     (+ le variabili MQTT_* se il broker non è sul PC locale)
"""
import argparse
import asyncio
import json
import os
import time

import paho.mqtt.publish as publish

COMPANY_ID = 0xFFFF
FRAME_SIZE = 27
PREFIX = os.environ.get("TOPIC_PREFIX", "mdgb")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
CLIENT_ID = os.environ.get("BLE_CLIENT_ID", "mdgb-ble-gw")
TLS = None
if os.environ.get("MQTT_TLS", "0").lower() in ("1", "true", "yes"):
    TLS = {"ca_certs": os.environ.get("MQTT_CA") or None,
           "certfile": os.environ.get("MQTT_CERT") or None,
           "keyfile": os.environ.get("MQTT_KEY") or None}


def frame_to_message(frame: bytes):
    """Frame BLE da 27 byte -> (type, corpo). Gli zeri in coda restano: il decoder legge solo i byte del tipo."""
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"frame di {len(frame)} byte, attesi {FRAME_SIZE}")
    return frame[0], frame[1:]


class Receiver:
    """Logica del ricevitore, separata dalla radio (testabile senza Bluetooth).
    handle() inoltra un frame solo la prima volta che lo vede; se l'inoltro fallisce (broker irraggiungibile)
    il frame non viene segnato come visto e si riprova al prossimo passaggio del beacon."""

    def __init__(self, node, publish_fn, prefix=PREFIX, max_seen=10000):
        self.node, self.publish_fn, self.prefix = node, publish_fn, prefix
        self.seen, self.max_seen = set(), max_seen

    def handle(self, frame: bytes, rssi=None, addr=None):
        frame = bytes(frame)
        if len(frame) != FRAME_SIZE or frame in self.seen:
            return None
        type_, body = frame_to_message(frame)
        msg = {"v": 1, "node_id": self.node, "via": "ble", "type": type_, "hex": body.hex().upper(),
               "rssi": rssi, "rx_at": time.time(), "ble_addr": addr}
        try:
            self.publish_fn(f"{self.prefix}/{self.node}/backup", json.dumps(msg))
        except Exception as e:
            print("inoltro fallito, riprovo al prossimo beacon:", e)
            return None
        if len(self.seen) >= self.max_seen:
            self.seen.clear()
        self.seen.add(frame)
        return msg


def mqtt_publish(topic, payload):
    publish.single(topic, payload, qos=1, hostname=MQTT_HOST, port=MQTT_PORT, client_id=CLIENT_ID, tls=TLS)


def main():
    from bleak import BleakScanner

    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default=os.environ.get("NODE_ID", "nodo01"))
    ap.add_argument("--addr", default=None,
                    help="indirizzo BLE del nodo (opzionale; su macOS è un UUID, non il MAC)")
    ap.add_argument("--dry-run", action="store_true", help="stampa i messaggi decodificati senza inoltrarli")
    a = ap.parse_args()
    if a.dry_run:
        from decoder import decode

        def show(topic, payload):
            m = json.loads(payload)
            print(topic, "type", m["type"], "rssi", m["rssi"], decode(m["type"], bytes.fromhex(m["hex"])))
        rx = Receiver(a.node, show)
    else:
        rx = Receiver(a.node, mqtt_publish)

    def on_adv(device, adv):
        if a.addr and device.address.upper() != a.addr.upper():
            return
        frame = adv.manufacturer_data.get(COMPANY_ID)
        if frame and rx.handle(frame, adv.rssi, device.address) and not a.dry_run:
            print("BLE RX inoltrato: type", frame[0], "da", device.address, "RSSI", adv.rssi)

    async def run():
        async with BleakScanner(detection_callback=on_adv):
            print(f"in ascolto dei beacon BLE (company 0x{COMPANY_ID:04X}) -> "
                  f"{'solo stampa' if a.dry_run else f'{PREFIX}/{a.node}/backup'}")
            await asyncio.Future()

    asyncio.run(run())


if __name__ == "__main__":
    main()
