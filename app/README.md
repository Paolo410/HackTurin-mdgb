# app/ — centrale di MDGB

**Owner:** Lorenzo Dragoni (communication engineer). Contratti: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md) (C4, C4-B).

## Scopo

Riceve dai nodi via MQTT (AWS IoT Core) e dai canali di backup (BLE nella demo, LoRaWAN in produzione), deduplica,
rileva i dati persi e, da CM-M3, fa la diagnosi dei nodi e mostra la dashboard.

| File | Cosa fa |
|---|---|
| `ingest.py` | subscriber con sessione persistente su `mdgb/+/events\|agg\|hb\|backup`; dedup su `(node, seq)`, buchi nei `seq`, aggregati provvisori dal backup; opzionale TTN |
| `decoder.py` | decoder unico dei messaggi C4-B (`AGG`, `HB`, allarmi) |
| `ble_receiver.py` | ricevitore BLE (laptop): inoltra i beacon del nodo su `mdgb/<node>/backup` |
| `lora_p2p_receiver.py` | mini-gateway LoRa P2P / ESP-NOW (piani B e C) |
| `ttn_formatter.js` | formatter da incollare su TTN (solo per leggere i messaggi nella console) |
| `mosquitto.conf` | broker locale per lo sviluppo |

## Come si avvia

```bash
pip install -r app/requirements.txt
python app/ingest.py                    # ascolta; ogni 10 s stampa il riepilogo
python app/ingest.py --report           # riepilogo dal DB (app/central.db, ignorato da git)
python app/ble_receiver.py --node nodo01
```

Con AWS IoT Core: stesse variabili `MQTT_*` del nodo, con il certificato del Thing `mdgb-ingest`
(`INGEST_CLIENT_ID=mdgb-ingest`); il ricevitore BLE usa un Thing suo (`mdgb-ble-gw`, policy `ingest-policy.json`).

## Stato

| Milestone | Contenuto | Stato |
|---|---|---|
| CM-M2 | ingest v1 con dedup e buchi, decoder C4-B, ricevitori | fatto |
| CM-M3 | diagnosi dei nodi, dashboard flask | da fare |

## Dipendenze e Python

`paho-mqtt`, `pyserial`, `bleak` (versioni fissate in `requirements.txt`). Python 3.9 o superiore.
