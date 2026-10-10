"""Ricevitore del canale di backup BLE (gira sul laptop, o su qualsiasi PC con Bluetooth).

Ascolta i beacon del nodo (manufacturer data, company ID 0xFFFF, frame da 27 byte), elimina le
ripetizioni (un beacon viene ritrasmesso più volte al secondo) e ripubblica ogni messaggio NUOVO su
    {prefix}/{node}/agg/backup     {"port", "hex", "via": "ble", "rssi", "rx_at"}
convertendo l'aggregato nel formato standard da 28 byte: ingest.py e la dashboard non cambiano.

Uso:   python ble_receiver.py --node xw-001
       python ble_receiver.py --node xw-001 --addr AA:BB:CC:DD:EE:FF     # filtra un solo nodo
Richiede: pip install bleak paho-mqtt     (+ le variabili MQTT_* se il broker è AWS IoT Core)
"""
import argparse
import asyncio
import json
import os
import time

import paho.mqtt.publish as publish

COMPANY_ID = 0xFFFF
FRAME_SIZE = 27
PREFIX = os.environ.get("TOPIC_PREFIX", "torino/crosswalk")
MQTT_HOST = os.environ.get("MQTT_HOST", "localhost")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
CLIENT_ID = os.environ.get("BLE_CLIENT_ID", "crosswalk-ble-gw")
TLS = None
if os.environ.get("MQTT_TLS", "0").lower() in ("1", "true", "yes"):
    TLS = {"ca_certs": os.environ.get("MQTT_CA") or None,
           "certfile": os.environ.get("MQTT_CERT") or None,
           "keyfile": os.environ.get("MQTT_KEY") or None}


def frame_to_message(frame: bytes):
    """Frame BLE da 27 byte -> (port, payload) nel formato del backend.
    Aggregato: ricostruisce i 28 byte standard (flag = versione 1, offline; disco = 0 non trasmesso)."""
    if len(frame) != FRAME_SIZE:
        raise ValueError(f"frame di {len(frame)} byte, attesi {FRAME_SIZE}")
    port = frame[0]
    if port == 1:
        flags = (1 << 4) | (1 << 2)
        return port, bytes([flags]) + frame[1:27] + b"\x00"
    return port, frame[1:]


def main():
    from bleak import BleakScanner

    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default=os.environ.get("NODE_ID", "xw-001"))
    ap.add_argument("--addr", default=None, help="indirizzo BLE del nodo (opzionale)")
    a = ap.parse_args()
    seen = set()

    def on_adv(device, adv):
        if a.addr and device.address.upper() != a.addr.upper():
            return
        frame = adv.manufacturer_data.get(COMPANY_ID)
        if not frame or len(frame) != FRAME_SIZE:
            return
        key = bytes(frame)
        if key in seen:                     # stesso beacon ripetuto: già inoltrato
            return
        seen.add(key)
        port, payload = frame_to_message(bytes(frame))
        msg = {"port": port, "hex": payload.hex().upper(), "via": "ble",
               "rssi": adv.rssi, "rx_at": time.time(), "ble_addr": device.address}
        publish.single(f"{PREFIX}/{a.node}/agg/backup", json.dumps(msg), qos=1,
                       hostname=MQTT_HOST, port=MQTT_PORT, client_id=CLIENT_ID, tls=TLS)
        print("BLE RX", msg)

    async def run():
        async with BleakScanner(detection_callback=on_adv):
            print(f"in ascolto dei beacon BLE (company 0x{COMPANY_ID:04X}) -> {PREFIX}/{a.node}/agg/backup")
            await asyncio.Future()

    asyncio.run(run())


if __name__ == "__main__":
    main()
