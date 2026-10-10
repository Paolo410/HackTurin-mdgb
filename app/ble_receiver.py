"""Ricevitore del canale di backup BLE (gira sul laptop, o su qualsiasi PC con Bluetooth).

Ascolta i beacon del nodo (manufacturer data, company ID 0xFFFF, frame C4-B da 27 byte), elimina le
ripetizioni (un beacon viene ritrasmesso più volte al secondo) e ripubblica ogni messaggio NUOVO su
    {prefix}/{node}/backup     {"v": 1, "node_id", "via": "ble", "type", "hex", "rssi", "rx_at"}
Non decodifica: decodifica la centrale (un solo decoder, docs/CONTRACTS.md v1).

Uso:   python ble_receiver.py --node nodo01
       python ble_receiver.py --node nodo01 --addr AA:BB:CC:DD:EE:FF     # filtra un solo nodo
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


def main():
    from bleak import BleakScanner

    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default=os.environ.get("NODE_ID", "nodo01"))
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
        type_, body = frame_to_message(bytes(frame))
        msg = {"v": 1, "node_id": a.node, "via": "ble", "type": type_, "hex": body.hex().upper(),
               "rssi": adv.rssi, "rx_at": time.time(), "ble_addr": device.address}
        publish.single(f"{PREFIX}/{a.node}/backup", json.dumps(msg), qos=1,
                       hostname=MQTT_HOST, port=MQTT_PORT, client_id=CLIENT_ID, tls=TLS)
        print("BLE RX", msg)

    async def run():
        async with BleakScanner(detection_callback=on_adv):
            print(f"in ascolto dei beacon BLE (company 0x{COMPANY_ID:04X}) -> {PREFIX}/{a.node}/backup")
            await asyncio.Future()

    asyncio.run(run())


if __name__ == "__main__":
    main()
