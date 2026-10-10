# comms/ — la rete dei nodi (lato Arduino UNO Q)

**Owner:** Lorenzo Dragoni (communication engineer).
Contratti tra i moduli: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md). Decisioni e numeri: [DECISIONS.md](DECISIONS.md).
Il programma del PC (la centrale) è in [`app/`](../app/README.md). Cosa devono fare gli altri: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md).

## Cosa fa

Sull'Arduino UNO Q gira un programma, `comms/node/main.py`, che porta i dati del nodo alla centrale e non li perde mai:

```
 ai/ (Paolo) ── scrive gli eventi ──► logs/c3/c3-*.jsonl
 firmware (Salvatore) ── righe MCU ──► logs/c3/mcu-*.jsonl          (le scrive comms/actuators.py)
                                            │
                              comms/node/main.py
                                            │ 1. salva ogni evento su disco (SQLite)
                                            │ 2. lo manda alla centrale via Wi-Fi (MQTT), lo segna "inviato" solo alla conferma
                                            │ 3. se per 30 s non arrivano conferme: accende il Bluetooth (BLE) e manda
                                            │    stato, conteggi e allarmi; dopo 60 s di rete stabile lo spegne
                                            ▼
                         PC della centrale (app "MDGB Centrale")
```

Il semaforo **non** passa da qui: lo comandano `ai/` e il firmware. Se questa rete si rompe, il semaforo funziona lo stesso.

### Demo in locale, produzione nel cloud

| | Demo (adesso) | Produzione (in futuro) |
|---|---|---|
| Broker MQTT | dentro l'app sul PC della centrale (Mosquitto) | un broker MQTT 5 in cloud |
| Rete | PC e Arduino sulla stessa rete Wi-Fi | Internet |
| Sicurezza | rete locale, senza cifratura | TLS e un certificato per nodo |
| Backup | BLE verso il PC (10–50 m) | LoRaWAN (chilometri) |

Il codice è lo stesso: cambiano solo le righe `MQTT_*` e `BACKUP_LINK` in `comms/.env`.

## Installazione sull'Arduino UNO Q

Sulla scheda va **solo** il codice che gira lì. Dal PC dello sviluppatore, un comando copia via ssh la rete
(`comms/node`, gli strumenti per la scheda, la configurazione d'esempio e il servizio di avvio) in `~/HackTurin-mdgb` e prepara
Python. Niente app del PC, test o documentazione:

```bash
./comms/deploy/push_to_arduino.sh arduino@<IP della scheda>     # oppure --pack: crea mdgb-nodo.tar.gz per la chiavetta
```

Poi sulla scheda: `nano ~/HackTurin-mdgb/comms/.env` (in `MQTT_HOST` l'indirizzo che l'app sul PC mostra in alto) e
`sudo ~/venv/bin/python ~/HackTurin-mdgb/comms/node/main.py` (`sudo` serve per il Bluetooth). Avvio automatico all'accensione:
[`deploy/mdgb-comms.service`](deploy/mdgb-comms.service). Rilanciare lo script aggiorna il codice: `.env` e dati restano.

La visione di Paolo (`ai/`) gira sulla stessa scheda, in `~/HackTurin-mdgb/ai`: così scrive gli eventi in `~/HackTurin-mdgb/logs/c3/`, dove
questo programma li legge, e importa `comms/actuators.py`. Come portarla sulla scheda lo decide Paolo.
Procedura completa: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md#7-arduino-uno-q).

## Configurazione (`comms/.env`)

| Chiave | Demo | Significato |
|---|---|---|
| `NODE_ID` | `nodo01` | nome del nodo, uguale a una camera di `app/nodes.json` |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS` | IP del PC, `1883`, `0` | dove sta il broker (l'app sul PC mostra l'indirizzo giusto) |
| `BACKUP_LINK` | `ble` | canale di backup: `ble`, `lora` (futuro) o `none` |
| `BACKUP_HB_S` | `30` | ogni quanto il BLE manda lo stato (300 in produzione) |
| `EVENT_SOURCE` | `c3` | `c3` = eventi dai file di `ai/`; `sim` = eventi finti generati qui |
| `AGG_PERIOD_S` | `60` | finestra dei conteggi (900 in produzione) |

Le altre (tempi del backup, batch, ritentativi) hanno già il valore giusto: sono in [`node/config.py`](node/config.py).

## File

| File | Cosa fa |
|---|---|
| `node/main.py` | il programma del nodo: mette insieme i pezzi qui sotto |
| `node/outbox.py` | Store & Forward: ogni evento su disco prima dell'invio, segnato "inviato" solo dopo la conferma |
| `node/uplink_mqtt.py` | invio MQTT: conferme (PUBACK), ritentativi, "online" solo se arrivano conferme |
| `node/failover.py` | backup BLE: quando accenderlo, cosa mandare, quando spegnerlo |
| `node/backup_link.py` | radio di backup: BLE (`btmgmt`) o LoRa tramite l'MCU |
| `node/aggregator.py` | conteggi per finestra di tempo |
| `node/event_source.py` | lettura dei file di `ai/` e dell'MCU (senza perdere né duplicare righe) e simulatore |
| `node/payload.py` | formati dei messaggi (JSON e binari da 26/12 byte per il backup) |
| `node/config.py` | impostazioni (lette da `comms/.env`) |
| `actuators.py` | **per Paolo**: come `ai/` manda i comandi al semaforo (C1/C2), via seriale o simulato |
| `jsonl.py` | **per Paolo**: scrittura dei file di eventi `logs/c3/c3-*.jsonl` con rotazione |
| `tools/c3_sim.py` | eventi finti come quelli di `ai/`: per provare la rete prima che la visione sia pronta |
| `tools/ble_beacon_test.py` | prima prova del Bluetooth vero sulla UNO Q |
| `tools/c1_send.py` | **per Salvatore**: manda comandi e heartbeat al firmware dal PC, per provare il fail-safe |
| `deploy/push_to_arduino.sh` | copia sulla scheda solo questi file e prepara Python (o crea il pacchetto `--pack`) |
| `deploy/mdgb-comms.service` | avvio automatico sulla UNO Q |
| `tests/` | test automatici della rete e della centrale |

## Test

```bash
pip install -r comms/requirements-dev.txt -r app/requirements.txt
brew install mosquitto                  # solo per i test che usano un broker vero
python -m pytest comms -q               # atteso: tutti verdi in ~45 s
```

Tra i test c'è la prova completa "Wi-Fi spento / riacceso" con i tempi accorciati: il BLE si accende, la centrale
dice "rete giù, nodo sano", un allarme arriva via BLE, al ritorno della rete gli eventi arrivano tutti e il BLE si spegne.

## Python

Python 3.9 o superiore (sulla UNO Q il `python3` di Debian in un venv). Sulla scheda servono solo `requirements.txt`
(`paho-mqtt`, `pyserial`); per i test `requirements-dev.txt` (aggiunge `pytest`). Versioni fissate.
