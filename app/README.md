# app/ — centrale di MDGB

**Owner:** Lorenzo Dragoni (communication engineer). Contratti: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md) (C4, C4-B).

## Scopo

Il codice che gira **sul tuo PC**. Riceve dai nodi via MQTT (AWS IoT Core) e via BLE (Bluetooth del PC, senza
Internet), deduplica, rileva i dati persi e fa la diagnosi di ogni nodo. Si lancia **un solo programma**:
`python app/central.py`. Guida completa: [comms/RILASCIO.md](../comms/RILASCIO.md).

| File | Cosa fa |
|---|---|
| `central.py` | **il programma della centrale**: MQTT + BLE nello stesso database, stato dei nodi ogni 10 s |
| `dashboard.py`, `dashboard.html` | dashboard su http://localhost:8080: mappa delle camere (OpenStreetMap, o schematica senza Internet), clic su una camera = stato, canale, coda, traffico, sicurezza e allarmi; riquadro con eventi persi e doppioni |
| `nodes.json` | camere della mappa: id, nome, lat, lon, profilo, `mock` per le camere di esempio |
| `diagnosis.py` | la regola della diagnosi (OK, rete giù, guasto, Linux bloccato, manomissione, batteria, distrutto) |
| `ingest.py` | subscriber con sessione persistente su `mdgb/+/events\|agg\|hb\|backup`; dedup su `(node, seq)`, buchi nei `seq`, aggregati provvisori dal backup; opzionale TTN |
| `decoder.py` | decoder unico dei messaggi C4-B (`AGG`, `HB`, allarmi) |
| `ble_receiver.py` | logica del ricevitore BLE (usata da `central.py`); da solo: `--dry-run` per la prima prova radio, oppure gateway remoto che inoltra su `mdgb/<node>/backup` |
| `lora_p2p_receiver.py` | mini-gateway LoRa P2P / ESP-NOW (piani B e C) |
| `ttn_formatter.js` | formatter da incollare su TTN (solo per leggere i messaggi nella console) |
| `mosquitto.conf` | broker locale per lo sviluppo |

## Come si avvia

```bash
pip install -r app/requirements.txt
cp app/.env.example app/.env            # endpoint AWS e certificato mdgb-ingest (oppure Mosquitto locale)
python app/central.py                   # MQTT + BLE + dashboard su http://localhost:8080
python app/central.py --host 0.0.0.0    # dashboard apribile anche da telefono/tablet sulla stessa rete
python app/central.py --report          # riepilogo dal DB (app/central.db, ignorato da git)
```

## Stato

| Milestone | Contenuto | Stato |
|---|---|---|
| CM-M2 | ingest v1 con dedup e buchi, decoder C4-B, ricevitori | fatto |
| CM-M3 | programma unico `central.py` (MQTT + BLE diretto), diagnosi dei nodi | fatto |
| CM-M3 | dashboard web con mappa delle camere | fatto |

## Dipendenze e Python

`paho-mqtt`, `pyserial`, `bleak`, `flask` (versioni fissate in `requirements.txt`). Python 3.9 o superiore.
La pagina carica Leaflet e le tile di OpenStreetMap da Internet solo per la mappa; senza Internet usa la mappa schematica.
