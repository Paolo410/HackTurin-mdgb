# comms/ e app/ — decisioni, numeri e interfacce

Owner: Lorenzo Dragoni (communication engineer). Aree: `comms/`, `app/`, `docs/CONTRACTS.md`.

Fonti:
- **[L]** architettura di rete decisa da Lorenzo (sessione del 10/10/2026);
- **[R]** riassunto della chat precedente di Lorenzo (decisioni prese prima della specifica del team);
- **[CT]** codice già testato in `~/Desktop/HACKATHLON` (fuori dal repo, da integrare in CM-M2/CM-M3);
- **[S]** `PROMPT_SMART_CROSSING.md` (§4, §5.3, §9);
- **[C1]** `docs/CONTRACTS.md` v1, approvata da Lorenzo il 10/10/2026.

Regola: nell'area comms valgono [L], [R] e [CT]; dove questi e i contratti divergono, vale `docs/CONTRACTS.md` v1.
Le voci superate dai contratti sono segnate "superato da v1" (§6).

## 1. Decisioni prese

### Architettura

| Tema | Decisione | Fonte |
|---|---|---|
| Ruolo del nodo | "Consigliere": l'UNO Q decide in locale e comanda l'attuatore (semaforo/LED) tramite l'MCU e il Bridge RPC. In un impianto reale il controller certificato del semaforo resta. La sicurezza non dipende mai dalla rete | [L], [R], [S] §1 |
| Fail-safe | Visione giù → profilo lento + pulsante; Linux bloccato → l'MCU fa il ciclo fisso e manda `DEAD`; rete giù → nessun effetto sul semaforo | [R] |
| Canale primario | MQTT 5 su Wi-Fi verso AWS IoT Core (sponsor). TLS mutuo con un certificato X.509 per nodo, client ID = nome del Thing. QoS 1, Last Will, stato retained, sessione persistente | [L], [R], [CT] |
| Store & Forward | SQLite in WAL sull'eMMC (la UNO Q non ha slot SD). Ogni evento si scrive **prima** dell'invio e si marca inviato solo dopo un PUBACK **positivo**. Al ritorno della rete la coda si svuota dal più vecchio | [L], [R], [CT] |
| ID evento | `event_id` = `node_id` + `seq`. `seq` è persistente e non si riusa mai (SQLite AUTOINCREMENT) | [L], [R], [CT] |
| Deduplica | In centrale su `(node_id, seq)`; dai buchi nei `seq` si vedono i dati persi | [L], [R], [CT] |
| Backup | LoRaWAN (Grove Wio-E5 868 MHz sull'MCU) in produzione, BLE (radio integrata della UNO Q, beacon `btmgmt`) nella demo. Si sceglie con `BACKUP_LINK=lora\|ble`. Piani B/C: LoRa P2P, ESP-NOW | [L], [R], [CT] |
| Contenuto del backup | Solo allarmi, heartbeat e aggregati, in binario compatto. Mai i singoli eventi: quelli restano nello Store & Forward | [L], [R], [S] §4 |
| Failover | Backup attivo dopo 30 s senza conferme MQTT, con il primo pacchetto subito. Backup spento dopo 60 s di MQTT stabile. MQTT intanto si riconnette e fa il backfill appena può | [L], [R], [CT] |
| Aggregati via backup | Sono provvisori: la centrale li sostituisce con quelli esatti, calcolati sugli eventi dopo il backfill | [CT] |
| Centrale (`app/`) | Subscriber sempre acceso con sessione persistente e deduplica. Diagnosi incrociando MQTT e backup: rete giù / nodo guasto / Linux bloccato / batteria scarica / manomissione / nodo distrutto. Dashboard | [L], [R], [S] §5.3 |
| Privacy | Nessuna immagine esce dal nodo; niente targhe né multe, solo statistiche anonime | [R], [S] §2 |
| Fuori scope | Niente 4G e niente seconda SIM: se ne parla solo nel pitch | [L], [R] |
| Credenziali | Certificati e chiavi solo in locale (`.env`, `certs/`), mai committati. Un certificato revocabile per nodo | [L], [R] |
| Contratti | Topic `mdgb/<node_id>/events\|agg\|hb\|backup`, batch di eventi C3 con `seq` + `event_id`, aggregati con chiave `(node_id, t0)`, backup binario `AGG` 26 byte / `HB` 12 byte / allarmi, C3 su file JSONL, Bridge `mdgb_line` / `mcu_event` | [C1] |

### Librerie e strumenti

| Dove | Cosa | Fonte |
|---|---|---|
| Nodo, lato Linux | `paho-mqtt` 2.x (MQTT v5, `CallbackAPIVersion.VERSION2`), `sqlite3` della stdlib, `pyserial` (attuatore da PC), BLE con `btmgmt` (BlueZ) via subprocess | [CT] |
| Centrale | `paho-mqtt`, `bleak` (ricevitore BLE), `pyserial` (ricevitore LoRa P2P); `flask` per la dashboard | [CT], [S] §2 |
| MCU | `Arduino_RouterBridge` (RPC MessagePack su UART interna); Wio-E5 con comandi AT su UART | [CT] |
| Cloud | AWS IoT Core, una policy per ruolo, provisioning con AWS CLI. Da fare: IoT Rule → DynamoDB, Device Shadow | [CT], [R] |
| Sviluppo | Mosquitto locale con `persistence true` | [CT] |

### Hardware

| Componente | Uso | Fonte |
|---|---|---|
| Arduino UNO Q 4 GB | Linux (QRB2210, Python: uplink, Store & Forward, BLE) + MCU STM32U585 (attuatori, LoRa) | [L], [R], [S] §1 |
| Wi-Fi 2,4 GHz integrato | canale primario | [S] §5.3 |
| Bluetooth integrato | backup nella demo; il ricevitore è il laptop, che fa da centrale | [L], [S] §5.3 |
| Grove Wio-E5 | backup LoRaWAN in produzione (EU868), su UART D0/D1 dell'MCU. Non è nella lista dell'hackathon: va chiesto a Seeed | [L], [R], [CT] |
| LTC2941 | contatore di carica della batteria → `batt` | [R] |
| AHT20, sensore di luce | dati ambientali degli aggregati | [R], [S] §5.2 |
| Modulino Movement, micro switch, NFC | manomissione: urto/inclinazione, sportello aperto, badge del tecnico | [R] |
| Grove Base Shield V2 su 3,3 V | collegamento dei moduli Grove | [R] |

Produzione (solo pitch): secure element (ATECC608 o SE050); pannello solare 150 Wp, LiFePO4 12,8 V 40 Ah con
protezione sotto 0 °C, MPPT Victron 75/10, modalità energetiche in base alla carica [R].

## 2. Parametri e numeri

### MQTT e AWS IoT Core

| Parametro | Valore | Fonte |
|---|---|---|
| Endpoint | AWS IoT Core ATS (`xxxx-ats.iot.<region>.amazonaws.com`) | [CT] |
| Porta | 8883 (TLS mutuo); 443 con ALPN `x-amzn-mqtt-ca` se la rete blocca la 8883; 1883 senza TLS solo con Mosquitto locale | [CT], [R] |
| QoS | 1 ovunque (AWS IoT Core non supporta QoS 2) | [L], [CT] |
| Sessione | `clean_start=False`, Session Expiry 3600 s (default AWS 1 h, estendibile fino a 7 giorni) | [CT], [R] |
| Keepalive | nodo 30 s, ingest 15 s | [CT], [R] |
| Riconnessione | backoff esponenziale da 1 a 30 s | [CT], [R] |
| Batch | massimo 50 eventi per messaggio, un batch in volo alla volta | [CT], [R] |
| Timeout ACK | 30 s, poi il batch si rispedisce | [CT], [R] |
| Dimensione massima | payload < 128 KB (limite AWS) | [CT] |
| Ciclo del nodo | ogni 0,2 s: invio della coda, aggregatore, heartbeat | [CT] |
| Heartbeat MQTT | ogni 10 s, retained, con il backlog (`status` in [CT], `hb` in [C1]) | [CT], [C1] |
| Last Will | `online: false` retained, QoS 1 | [CT], [C1] |
| Retention | massimo 2.000.000 righe; ogni 600 s si cancellano le più vecchie **già inviate**, mai quelle in coda | [CT] |

Topic e formati: `docs/CONTRACTS.md` v1 (prefisso `mdgb`). Il codice testato usa ancora i topic `torino/crosswalk/{node}/…`
e il formato evento `{"node":"xw-001","events":[{"seq":1842,"ts":…,"cat":"person","dir":0,"conf":0.91}]}`:
si adegua in CM-M2.

### Failover e backup

| Parametro | Valore | Fonte |
|---|---|---|
| Attivazione del backup | 30 s senza conferme MQTT; il primo pacchetto parte subito | [L], [R] |
| Spegnimento del backup | dopo 60 s di MQTT stabile | [L], [R] |
| Scelta del canale | `BACKUP_LINK=lora\|ble` (il codice accetta anche `none`; default `ble`) | [L], [CT] |
| Aggregati | finestre fisse: 900 s (15 min) in produzione, 60 s nella demo (`AGG_PERIOD_S`) | [CT], [R], [S] §4 |
| Heartbeat sul backup | ogni 5 min | [S] §4, [C1] |
| Allarmi sul backup | subito | [S] §4, [C1] |
| Test del canale LoRa | ogni 6 h anche con MQTT sano (solo produzione) | [R] |
| Recupero aggregati | al ritorno di MQTT al massimo 96 finestre per ciclo (1 giorno a 15 min) | [CT] |
| Watchdog dell'MCU | 5 min senza heartbeat da Linux → uplink LoRa `DEAD` su fPort 9; nuovo tentativo di join ogni 60 s | [CT], [R] |

### Radio

| Parametro | Valore | Fonte |
|---|---|---|
| LoRaWAN | EU868, OTAA, classe A, ADR attivo, `AT+MSGHEX`, UART 9600 baud su D0/D1 (`Serial1`, da verificare) | [CT], [R] |
| Airtime | a SF7 un payload di 28 B occupa circa 90 ms; duty cycle 1% a 868 MHz; fair use TTN 30 s di airtime al giorno | [R], [S] §5.3 |
| LoRa P2P (Piano B) | `AT+TEST=RFCFG,868,SF7,125,12,15,14,ON,OFF,OFF` | [CT], [R] |
| ESP-NOW (Piano C) | UART 115200 baud, canale 1 | [CT], [R] |
| BLE | advertising non connettibile, Manufacturer Specific Data, company ID `0xFFFF`, 31 byte, `btmgmt add-adv` | [CT], [R] |

Formato binario del backup: `docs/CONTRACTS.md` v1 (C4-B). Quello del codice testato (aggregato LoRa da 28 byte con
le 5 categorie person, wheelchair, bicycle, stroller, other e frame BLE da 27 byte; porte 1 aggregato, 9 `DEAD`,
10 manomissione, 11 incidente) è superato da v1.

### AWS IoT Core: policy del codice testato

| Thing | Permessi | Fonte |
|---|---|---|
| nodo (es. `xw-001`) | `iot:Connect` solo come se stesso; `iot:Publish` e `iot:RetainPublish` solo sui propri topic | [CT] `aws/node-policy.json` |
| `crosswalk-ingest` | `iot:Subscribe`/`iot:Receive` su tutti i nodi; `iot:Publish` solo sui topic di backup (per i ricevitori BLE/LoRa) | [CT] `aws/ingest-policy.json` |

### Energia (stima di produzione)

5 W → 120 Wh al giorno. A dicembre circa 1,5 kWh/kWp al giorno → 120 Wp e circa 42 Ah con 4 giorni di autonomia [R].

### Test

| Test | Risultato | Fonte |
|---|---|---|
| End-to-end offline: broker spento e riacceso, circa 40 eventi/s | 806/806 eventi, 0 buchi, 2 duplicati scartati | [R], [CT] |
| Payload 28 byte: nodo e backend decodificano allo stesso modo | OK, rieseguito il 10/10/2026 | [R], [CT] |
| BLE: aggregato e allarme, nodo → frame 27 byte → ricevitore → decoder | OK, rieseguito il 10/10/2026 | [R], [CT] |
| TLS mutuo contro un broker locale | OK | [R] |
| `sketch.ino` compilato con intestazioni simulate | OK nelle 3 varianti | [R] |
| UNO Q vera, AWS reale | **mai provati** | [R] |

## 3. Codice già scritto o testato

Tutto in `~/Desktop/HACKATHLON`, non ancora nel repo. Si integra in CM-M2/CM-M3 **senza riscriverlo**.

| File | Cosa fa | Destinazione |
|---|---|---|
| `crosswalk-node/python/outbox.py` | Store & Forward: SQLite WAL, `synchronous=FULL`, `put`/`pending`/`ack`/`backlog`, retention che non tocca la coda | `comms/` |
| `crosswalk-node/python/uplink_mqtt.py` | MQTT 5 + TLS (AWS), Last Will, sessione persistente, batch, ACK, backfill | `comms/` |
| `crosswalk-node/python/aggregator.py` | finestre fisse; online → JSON `agg` su MQTT, offline → backup | `comms/` |
| `crosswalk-node/python/backup_link.py` | Bridge verso l'MCU (o MCU simulato), backup LoRa e BLE intercambiabili | `comms/` |
| `crosswalk-node/python/payload.py` | evento JSON, aggregato binario | `comms/` |
| `crosswalk-node/python/config.py`, `main.py`, `event_source.py` | configurazione via variabili d'ambiente, orchestrazione, simulatore di eventi | `comms/` |
| `crosswalk-node/sketch/sketch.ino` | MCU: LoRaWAN/P2P/ESP-NOW, LED, watchdog `DEAD` | **non è area comms**: riferimento per Salvatore (`firmware/`) |
| `esp32-pianoC/` | sketch ESP-NOW (Piano C) | riferimento, non si integra per la demo |
| `backend/ingest.py` | subscriber: dedup `PRIMARY KEY(node, seq)`, buchi, allarmi, aggregati provvisori, anche da TTN | `app/` |
| `backend/decoder.py`, `ttn_formatter.js` | decoder del backup (Python e TTN) | `app/` |
| `backend/ble_receiver.py` | ricevitore BLE (bleak) → ripubblica sul topic di backup | `app/` |
| `backend/lora_p2p_receiver.py`, `mosquitto.conf` | mini-gateway LoRa P2P / ESP-NOW; broker locale | `app/` |
| `aws/node-policy.json`, `ingest-policy.json`, `setup_thing.sh` | policy e creazione dei Thing con certificati in `certs/` | `comms/` |
| `tests/test_offline.py` | payload, BLE, end-to-end offline | `comms/` |
| `docs/BOM_crosswalk_node.xlsx` | BOM del prototipo e del nodo sul campo, dimensionamento solare | resta fuori: la BOM del team è `hardware/BOM.md` |

Come si prova (sul laptop, senza scheda):

```bash
brew install mosquitto
pip install -r backend/requirements.txt
python tests/test_offline.py          # deve stampare "TUTTI I TEST SUPERATI"
```

Codice nel repo:

| File | Cosa fa | Milestone |
|---|---|---|
| `comms/actuators.py` | interfaccia `Actuator` (C1/C2) con `SimActuator`, `SerialActuator`; righe C5 dall'MCU | CM-M1 |
| `comms/jsonl.py` | scrittura dei file JSONL con rotazione (regole di C3) | CM-M1 |
| `comms/tools/c1_send.py` | manda C1 e C2 al firmware da PC, anche togliendo l'heartbeat per provare il fail-safe | CM-M1 |

Cosa manca rispetto alle decisioni di §1:
1. un PUBACK **negativo** (reason code ≥ 0x80) oggi marca l'evento come inviato: `_on_publish` non guarda il reason code;
2. "online" oggi è `is_connected()`: deve basarsi sulle conferme (PUBACK);
3. manca l'isteresi 30 s / 60 s: il backup si accende e si spegne seguendo `is_connected()`;
4. manca "primo pacchetto subito": offline l'aggregatore manda solo quando si chiude una finestra (fino a 15 min);
5. manca l'heartbeat sul backup, manca il test LoRa ogni 6 h e non c'è ancora chi produce gli allarmi;
6. manca la diagnosi in centrale e manca la dashboard.

## 4. Cosa mi serve dagli altri

| Da chi | Cosa | Per quale milestone |
|---|---|---|
| Salvatore (firmware) | Conferma di `mdgb_line` (C1/C2) e `mcu_event` (C5) via Bridge, e delle righe C5 | CM-M3, CM-M4 |
| Salvatore (firmware) | Righe C5: `env` (con `batt` dal LTC2941), `tamper`, `lamp_fault`, `failsafe` | CM-M3 (aggregati, allarmi, diagnosi) |
| Salvatore (firmware) | Verifica che D0/D1 siano `Serial1`; solo produzione: `lora_send` + watchdog `DEAD` (riferimento: il vecchio `sketch.ino`) | dopo la demo |
| Paolo (vision) | Conferma dei valori ammessi di C3 (`cls`, `type`, `kind`, `attrs`), della riga `yield` e del trasporto su file JSONL | CM-M2 |
| Kuzey (electronics) | Pin di LTC2941, AHT20, micro switch e NFC nella sezione Pinout; consumo reale della UNO Q; alimentatore USB-C PD | CM-M3 |
| Organizzazione | Wi-Fi della venue: porta 8883 aperta? client isolation? Chi possiede l'account AWS? Wio-E5 da Seeed | CM-M2 |

## 5. Cosa fornisco io agli altri

| A chi | Cosa |
|---|---|
| Tutti | `docs/CONTRACTS.md` v1 (C1–C5, Bridge, backup binario, diagnosi), di cui sono l'owner |
| Paolo | `comms/actuators.py`: interfaccia `Actuator` con `SimActuator` e `SerialActuator` (CM-M1), `BridgeActuator` (CM-M4) |
| Salvatore | Trasporto di C1/C2 verso l'MCU (seriale 115200 e Bridge) e `comms/tools/c1_send.py` per provare il firmware da PC |
| Salvatore | Il vecchio `sketch.ino` (LoRaWAN, watchdog) come riferimento per il backup LoRa in produzione |
| Tutti | Uplink MQTT/AWS con Store & Forward e backup (`comms/`), ingest con deduplica, diagnosi e dashboard (`app/`) |
| Tutti | Provisioning AWS (policy + script, un certificato per nodo, solo in locale), decoder TTN, prova "Wi-Fi spento / riacceso" |

## 6. Questioni aperte

Superate da `docs/CONTRACTS.md` v1:
- prefisso `torino/crosswalk` e topic `status`, `alert`, `agg/backup` → `mdgb/<node_id>/events|agg|hb|backup`;
- topic proposti in [R] `phases`, `incident`, `conflict`, `vehicles`, `env` → tipi di evento dentro `events` (C3) e campi di `agg`/`hb`;
- funzioni Bridge di [R] `ped_request`, `ped_extend`, `phase_done`, `heartbeat`, `pedestrian_alert` → C1/C2 su `mdgb_line`
  (la centralina simulata e i limiti dei tempi sono del firmware, la regola del verde è di `rules.py`);
- categorie person, wheelchair, bicycle, stroller, other → `cls` + `attrs` di C3;
- byte della batteria nel payload LoRa (28 → 29 byte) → `batt` in `AGG` e `HB` (C4-B);
- evento di fase di [R] (`profile`, `green_s`, `extended_s`, `waiting`, `on_crossing_at_red`) → C1 (`green_s`, `req`) e C3;
- in [S] l'evento "si cancella" dopo il PUBACK → resta marcato inviato (serve agli aggregati esatti).

Ancora aperte:
1. **`seq` dopo la perdita del DB**: se il file SQLite si perde (container, scheda reinstallata) `seq` riparte da 1 e la centrale scarterebbe i nuovi eventi come duplicati.
2. **Da verificare sulla UNO Q**: `btmgmt` e i permessi nel container di App Lab; persistenza del DB nel container; supporto BLE Coded PHY; `Monitor.begin()`; stabilità dell'indirizzo BLE; se più processi Linux possono usare il Bridge insieme.
3. **Esterni**: disponibilità del Wio-E5, copertura TTN nella venue, Wi-Fi della venue (porta 8883, client isolation), account AWS.
4. **`.gitignore`**: copre `.env`, `*.pem`, `*.key`, `*.crt` ma non la cartella `certs/` (si aggiunge in CM-M2, commit separato).
5. **Versioni**: [CT] usa intervalli (`paho-mqtt>=2.0,<3`); nel repo si fissano.
6. **`ttn_formatter.js`** gestisce solo le fPort 1 e 9; si rifà sul formato C4-B in CM-M3.
7. **Aggregato online "inviato" troppo presto**: in `aggregator.py` la finestra conta come pubblicata quando paho accetta il messaggio, non al PUBACK.
8. **Contesto di altre aree** ([R], non comms): profili del semaforo (velocità 3,0 / 1,2 / 0,8 m/s, verde = 2 s + L/v, minimo 7 s, massimo 25 s),
   modello YOLO26n/NCNN. La specifica del team decide diversamente (YOLOX-nano ONNX, `green_s` in `rules.py`): valgono le aree di Paolo e Salvatore.
9. **Pitch** (file condivisi): numeri da verificare (Torino circa 500 pedoni investiti l'anno, "uno su due sulle strisce" nel 2025);
   "funziona di notte" richiede IR o termocamera; seconda camera per le auto in arrivo; licenze (Ultralytics AGPL, MIO-TCD non commerciale).
