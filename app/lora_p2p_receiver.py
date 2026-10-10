"""Mini-gateway per i Piani B e C: legge il ricevitore radio collegato al laptop via USB
e ripubblica i pacchetti sul broker in {prefix}/{node}/agg/backup.

  Piano B (LoRa P2P):  secondo Wio-E5 tramite adattatore USB-TTL   -> --mode wioe5   (9600 baud)
  Piano C (ESP-NOW):   ESP32 ricevitore via USB                     -> --mode espnow  (115200 baud)

Esempi:
  python lora_p2p_receiver.py --port /dev/tty.usbserial-0001 --mode wioe5
  python lora_p2p_receiver.py --port /dev/tty.usbserial-0002 --mode espnow
Richiede: pip install pyserial paho-mqtt
Con AWS IoT Core: stesse variabili del backend (MQTT_HOST/PORT/TLS/CA/CERT/KEY) e P2P_CLIENT_ID
= nome di un Thing dedicato (es. crosswalk-gw, creato con aws/ingest-policy.json).
"""
import argparse
import json
import os
import re
import time

import paho.mqtt.publish as publish
import serial

PREFIX = os.environ.get("TOPIC_PREFIX", "torino/crosswalk")
MQTT_PORT = int(os.environ.get("MQTT_PORT", 1883))
CLIENT_ID = os.environ.get("P2P_CLIENT_ID", "crosswalk-gw")
TLS = None
if os.environ.get("MQTT_TLS", "0").lower() in ("1", "true", "yes"):
    TLS = {"ca_certs": os.environ.get("MQTT_CA") or None,
           "certfile": os.environ.get("MQTT_CERT") or None,
           "keyfile": os.environ.get("MQTT_KEY") or None}
WIOE5_INIT = ["AT+MODE=TEST", "AT+TEST=RFCFG,868,SF7,125,12,15,14,ON,OFF,OFF", "AT+TEST=RXLRPKT"]
RX_WIOE5 = re.compile(r'RX "([0-9A-Fa-f]+)"')
RSSI_WIOE5 = re.compile(r"RSSI:?\s*(-?\d+)")
RX_ESPNOW = re.compile(r"^(\d+):([0-9A-Fa-f]+)$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--mode", choices=["wioe5", "espnow"], default="wioe5")
    ap.add_argument("--node", default=os.environ.get("NODE_ID", "xw-001"))
    ap.add_argument("--broker", default=os.environ.get("MQTT_HOST", "localhost"))
    a = ap.parse_args()

    s = serial.Serial(a.port, 9600 if a.mode == "wioe5" else 115200, timeout=1)
    if a.mode == "wioe5":
        for cmd in WIOE5_INIT:
            s.write((cmd + "\r\n").encode())
            time.sleep(0.5)
            print(cmd, "->", s.read_all().decode(errors="ignore").strip())

    print(f"in ascolto ({a.mode}) ... pubblico su {PREFIX}/{a.node}/agg/backup")
    last_rssi = None
    while True:
        line = s.readline().decode(errors="ignore").strip()
        if not line:
            continue
        m_rssi = RSSI_WIOE5.search(line)
        if m_rssi:
            last_rssi = int(m_rssi.group(1))
        if a.mode == "wioe5":
            m = RX_WIOE5.search(line)
            if not m:
                continue
            raw = m.group(1)
            port, hexdata = int(raw[:2], 16), raw[2:]            # il primo byte è la "porta" (vedi sketch)
        else:
            m = RX_ESPNOW.match(line)
            if not m:
                continue
            port, hexdata = int(m.group(1)), m.group(2)
        msg = {"port": port, "hex": hexdata, "via": "lora-p2p" if a.mode == "wioe5" else "esp-now",
               "rssi": last_rssi, "rx_at": time.time()}
        publish.single(f"{PREFIX}/{a.node}/agg/backup", json.dumps(msg), qos=1, hostname=a.broker,
                       port=MQTT_PORT, client_id=CLIENT_ID, tls=TLS)
        print("RX", msg)


if __name__ == "__main__":
    main()
