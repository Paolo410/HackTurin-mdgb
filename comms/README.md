# comms/ — comunicazione di MDGB

**Owner:** Lorenzo Dragoni (communication engineer). Contratti: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md).
Decisioni, numeri e questioni aperte: [DECISIONS.md](DECISIONS.md).

## Scopo

- Trasporto dei comandi verso l'MCU: interfaccia `Actuator` per C1 (comando) e C2 (heartbeat), righe C5 dall'MCU.
- Uplink verso la centrale: MQTT 5 su AWS IoT Core con Store & Forward (CM-M2).
- Backup BLE (demo) / LoRaWAN (produzione) con isteresi 30 s / 60 s (CM-M3).

La centrale (ingest, diagnosi, dashboard) sta in `app/`.

## Stato

| Milestone | Contenuto | Stato |
|---|---|---|
| CM-M1 | `docs/CONTRACTS.md` v1, `actuators.py` (sim, serial), `tools/c1_send.py` | fatto |
| CM-M2 | MQTT/AWS IoT Core + Store & Forward (codice già testato) + dedup in centrale | da fare |
| CM-M3 | backup BLE con isteresi, diagnosi, dashboard | da fare |
| CM-M4 | `BridgeActuator` | da fare |

## Uso da `ai/`

```python
from comms.actuators import make_actuator

act = make_actuator("serial", port="/dev/cu.usbmodem1101")   # "sim" senza hardware; "bridge" in CM-M4
act.set_listener(lambda c5: ...)   # opzionale: righe C5 dall'MCU (env, tamper, lamp_fault, failsafe, thermal)
act.send(c1)                       # dict conforme a C1: non blocca, non solleva se il cavo cade
act.heartbeat(seq)                 # ogni 100 ms
act.close()
```

- La root del repo deve essere nel path: da `ai/` si lancia con `PYTHONPATH=..` (oppure `ai/` aggiunge la root a `sys.path`).
- `send` solleva `ValueError` solo se il comando non sta in 512 byte nemmeno accorciando `reason`.
- Se il collegamento è lento si mandano solo l'ultimo C1 e l'ultimo C2. Dopo una riconnessione un comando più vecchio
  di 1 s non si manda: il contratto chiede all'AI di ripetere C1 almeno ogni secondo.
- Le righe C5 (tranne `thermal`) finiscono in `$MDGB_C3_DIR/mcu-*.jsonl` (default `logs/c3/`, ignorata da git).
- `SimActuator.failsafe` dice se il firmware vero sarebbe in fail-safe (nessun C2 da più di 500 ms): utile per l'overlay.

## Provare il firmware da PC (per Salvatore)

```bash
python -m comms.tools.c1_send --port /dev/cu.usbmodem1101 --duration 30 --stop-hb-at 20
```

Cicla IDLE → PRESENCE → WARN_DRIVER → WARN_PEDESTRIAN → ANIMAL_ALERT (3 s ciascuno, C1 ripetuto ogni secondo), C2 a 10 Hz,
stampa le righe C5 che arrivano. A 20 s toglie l'heartbeat: entro 500 ms il firmware deve andare in fail-safe.
Senza hardware: `--port sim`.

## Come si avvia e si prova

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r comms/requirements.txt
python -m pytest comms -q          # dalla root del repo: 12 test, nessun hardware
```

## Dipendenze

`pyserial` (versione fissata in `requirements.txt`); `pytest` per i test. Da CM-M2: `paho-mqtt`.

## Versione di Python

Import provato con 3.9, test completi con 3.14: niente sintassi oltre la 3.8. Sulla UNO Q: il `python3` di Debian in un venv.
