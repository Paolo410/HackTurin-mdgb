# comms/ — la rete dei nodi (lato Arduino UNO Q)

**Owner:** Lorenzo Dragoni (communication engineer).
Contratti tra i moduli: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md). Decisioni e numeri: [DECISIONS.md](DECISIONS.md).
Il programma del PC (la centrale) è in [`app/`](../app/README.md). Cosa devono fare gli altri: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md).

## Cosa fa

Sull'Arduino UNO Q `comms/` fa due lavori, entrambi veri (nessuna simulazione sulla scheda):

```
                    ┌──────────── MCU (firmware di Salvatore): semaforo, LED, display, sensori
                    │  ▲ C1 comandi + C2 "sono vivo"        │ C5 batteria, ambiente, manomissione, fail-safe
                    │  │      (Bridge della UNO Q)          ▼
 2) actuators.py ───┘  ai/ (Paolo) ── usa actuators.py ──► logs/c3/mcu-*.jsonl
                       ai/ (Paolo) ── scrive gli eventi ──► logs/c3/c3-*.jsonl
                                                                 │
 1) node/main.py  ◄──────────────────── legge i due file ────────┘
       │ salva ogni evento su disco (SQLite), lo manda alla centrale via Wi-Fi (MQTT) e lo segna "inviato" solo alla
       │ conferma; se per 30 s non arrivano conferme accende il Bluetooth (BLE) e manda stato, conteggi e allarmi;
       │ dopo 60 s di rete stabile lo spegne
       ▼
 PC della centrale (app "MDGB Centrale")
```

1. **La rete** (`node/`): porta i dati alla centrale e non li perde mai. È il programma `node/main.py`.
2. **Il collegamento visione ↔ semaforo** (`actuators.py`): la visione di Paolo lo importa per mandare i comandi all'MCU
   tramite il Bridge della UNO Q e ricevere le righe dell'MCU. Non è la rete verso la centrale, ma la specifica lo
   assegna a comms (trasporti degli attuatori) e la visione sulla scheda non parte senza.

La sicurezza non passa dalla rete: se la rete si rompe, il semaforo funziona lo stesso.

### Demo in locale, produzione nel cloud

| | Demo (adesso) | Produzione (in futuro) |
|---|---|---|
| Broker MQTT | Mosquitto dentro l'app sul PC della centrale | un broker MQTT 5 in cloud |
| Rete | PC e Arduino sulla stessa rete Wi-Fi | Internet |
| Sicurezza | rete locale, senza cifratura | TLS e un certificato per nodo |
| Backup | BLE verso il PC (10–50 m) | LoRaWAN (chilometri) |

MQTT è vero in entrambi i casi: Mosquitto è un broker MQTT 5 completo, solo che gira sul PC invece che in cloud.
Il codice è lo stesso: cambiano solo le righe `MQTT_*` e `BACKUP_LINK` in `comms/.env`.

## Installazione sull'Arduino UNO Q

Dal PC dove gira l'app della centrale, nella cartella del repo:

```bash
./comms/deploy/push_to_arduino.sh arduino@<IP della scheda> --service
```

Copia sulla scheda **solo** i file che girano lì (in `~/HackTurin-mdgb/comms`), crea `~/venv` con le dipendenze, scrive
`comms/.env` con il broker = questo PC, e con `--service` installa l'avvio automatico e fa partire il nodo (chiede la
password di sudo della scheda). Rilanciarlo aggiorna il codice; i dati restano. Altre opzioni:
`--tools` (aggiunge i 3 strumenti di collaudo, vedi sotto), `--broker IP` (broker su un altro PC),
`--applab CARTELLA` (legge anche l'app di App Lab dello sketch, vedi sotto),
`--pack` (crea `mdgb-nodo.tar.gz` da copiare a mano, senza ssh).

Nel log del nodo (`journalctl -u mdgb-comms -f`) deve comparire `backup BLE reale (btmgmt)`. Se manca BlueZ il nodo
**non parte** e lo dice (`sudo apt install bluez`): niente Bluetooth finto.

La visione di Paolo (`ai/`) gira sulla stessa scheda, in `~/HackTurin-mdgb/ai`: scrive gli eventi in
`~/HackTurin-mdgb/logs/c3/`, dove la rete li legge, e importa `comms/actuators.py`.
Procedura completa: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md#7-arduino-uno-q).

### Con l'app di App Lab dello sketch (Salvatore)

Il Python di App Lab gira in un container Docker che **non può usare il Bluetooth** della scheda (verificato nel codice di
[arduino-app-cli](https://github.com/arduino/arduino-app-cli): il container non usa la rete dell'host). Per questo la rete
resta un servizio sul Linux della scheda, e l'app di App Lab le passa i dati dello sketch tramite file:

1. nella cartella `python/` dell'app di App Lab vanno `applab/mdgb_link.py` e `applab/main.py` (il `main.py` di Salvatore
   con 5 righe in più: ogni callback inoltra il dato a `mdgb_link`);
2. `mdgb_link.py` scrive righe C5 in `/app/data/c3/applab-*.jsonl`, che sulla scheda è `~/ArduinoApps/<cartella>/data/c3/`;
3. `push_to_arduino.sh ... --applab <cartella>` fa leggere al nodo quella cartella (`MDGB_C3_DIR` in `comms/.env`).
   La visione di Paolo deve scrivere i suoi eventi nella stessa cartella (`MDGB_C3_DIR` o `--c3-dir`).

| Lo sketch manda | Alla centrale arriva |
|---|---|
| `sensor_env`, `sensor_light`, `sensor_air` (ogni 300 ms) | `env` ogni 10 s: `t_c`, `rh` (più `light` grezzo 0–1023, `eco2_ppm`, `tvoc_ppb`) |
| `alarm_status` (tentato furto) | `tamper` code 1, al massimo uno ogni 10 s |
| `rfid_status` "ACCESSO CONSENTITO" | `tamper` code 3 (badge del tecnico, informazione) |
| `led_status`, `sensor_movement`, `rfid_data`, accesso negato | niente (debug; il codice del badge non esce dalla scheda) |

## Configurazione (`comms/.env` sulla scheda)

| Chiave | Demo | Significato |
|---|---|---|
| `NODE_ID` | `nodo01` | nome del nodo, uguale a una camera di `nodes.json` nell'app |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS` | IP del PC, `1883`, `0` | dove sta il broker (lo imposta `push_to_arduino.sh`) |
| `BACKUP_LINK` | `ble` | canale di backup: `ble`, `lora` (futuro) o `none` |
| `BACKUP_HB_S` | `30` | ogni quanto il BLE manda lo stato (300 in produzione) |
| `AGG_PERIOD_S` | `60` | finestra dei conteggi (900 in produzione) |
| `MDGB_C3_DIR` | (vuoto) | cartella degli eventi; vuota = `~/HackTurin-mdgb/logs/c3`; con App Lab la imposta `--applab` |

Le altre (tempi del backup, batch, ritentativi) hanno già il valore giusto: sono in [`node/config.py`](node/config.py).

## File

Sulla scheda (copiati da `push_to_arduino.sh`):

| File | Cosa fa |
|---|---|
| `node/main.py` | il programma della rete: mette insieme i pezzi qui sotto |
| `node/event_source.py` | legge i file di `ai/` e dell'MCU in `logs/c3/`, senza perdere né duplicare righe |
| `node/outbox.py` | Store & Forward: ogni evento su disco prima dell'invio, segnato "inviato" solo dopo la conferma |
| `node/uplink_mqtt.py` | invio MQTT: conferme (PUBACK), ritentativi, "online" solo se arrivano conferme |
| `node/failover.py` | backup: quando accenderlo, cosa mandare, quando spegnerlo |
| `node/backup_link.py` | radio di backup: BLE (`btmgmt`) o LoRa tramite l'MCU |
| `node/aggregator.py` | conteggi per finestra di tempo |
| `node/payload.py` | formati dei messaggi (JSON e binari da 26/12/5 byte per il backup) |
| `node/config.py` | impostazioni (lette da `comms/.env`) |
| `actuators.py` | visione ↔ MCU: comandi C1/C2 e righe C5 via Bridge (sulla UNO Q), seriale (Arduino in USB) o simulato (PC) |
| `jsonl.py` | scrittura dei file `logs/c3/*.jsonl` con rotazione (la usa `actuators.py`) |
| `requirements.txt`, `.env.example`, `deploy/mdgb-comms.service` | dipendenze, configurazione d'esempio, avvio automatico |

Solo con `--tools`, per il collaudo (si lanciano a mano, il nodo non li usa mai):

| File | Cosa fa |
|---|---|
| `tools/ble_beacon_test.py` | prima prova della radio Bluetooth: beacon per 60 s, li vede l'app sul PC |
| `tools/c1_send.py` | prova del semaforo: stati C1 e heartbeat all'MCU via Bridge (`--port bridge`) o USB, fail-safe compreso |
| `tools/c3_sim.py` | eventi di prova nei file di `ai/`, per provare la rete sulla scheda prima che la visione sia pronta |

Nell'app di App Lab (trascinati da Salvatore nella cartella `python/`): `applab/mdgb_link.py`, `applab/main.py`.

Solo nel repo (sviluppatori): `deploy/push_to_arduino.sh`, `tests/` (test automatici della rete e della centrale),
`requirements-dev.txt`, questa documentazione.

## Test

```bash
pip install -r comms/requirements-dev.txt -r app/requirements.txt
brew install mosquitto                  # solo per i test che usano un broker vero
python -m pytest comms -q               # atteso: tutti verdi in ~1 minuto
```

Tra i test: il nodo vero (`node/main.py`) che legge file reali e consegna tutto alla centrale; la prova "Wi-Fi spento /
riacceso" con i tempi accorciati (BLE acceso, "rete giù, nodo sano", allarme via BLE, al ritorno 0 eventi persi); un
PUBACK negativo vero; `actuators.py` sul Bridge con la libreria ufficiale di Arduino contro un router finto.

## Python

Python 3.10 o superiore (sulla UNO Q il `python3` di Debian in un venv). Sulla scheda servono solo `requirements.txt`:
`paho-mqtt` (MQTT), `arduino-router-bridge` (il Bridge, libreria ufficiale di Arduino), `pyserial` (solo per un
Arduino in USB). Per i test `requirements-dev.txt` (aggiunge `pytest`). Versioni fissate.
