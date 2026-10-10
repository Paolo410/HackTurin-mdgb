# comms/ e app/ — decisioni, numeri e interfacce

Owner: Lorenzo Dragoni (communication engineer). Aree: `comms/`, `app/`, `docs/CONTRACTS.md`.

Fonti:
- **[L]** architettura di rete decisa da Lorenzo (sessione del 10/10/2026);
- **[CT]** codice già testato in `~/Desktop/HACKATHLON` (fuori dal repo, da integrare in CM-M2/CM-M3);
- **[S]** `PROMPT_SMART_CROSSING.md` (§4, §5.3, §9).

Regola: nell'area comms valgono [L] e [CT]. Dove la specifica dice altro, la differenza è in §6 di questo file.
Il riassunto dell'altra chat non è ancora stato incollato: quando arriva, si integra qui.

## 1. Decisioni prese

### Architettura

| Tema | Decisione | Fonte |
|---|---|---|
| Sicurezza | Il nodo UNO Q decide in locale e comanda direttamente l'attuatore (semaforo/LED) tramite l'MCU e il Bridge RPC. La sicurezza non dipende mai dalla rete | [L], [S] §2 |
| Canale primario | MQTT 5 su Wi-Fi verso AWS IoT Core. TLS mutuo con un certificato X.509 per nodo, client ID = nome del Thing. QoS 1, Last Will | [L], [CT] |
| Store & Forward | Ogni evento si scrive su disco (SQLite in WAL) **prima** dell'invio. Si marca inviato solo dopo un PUBACK **positivo**. Al ritorno della rete la coda si svuota dal più vecchio | [L], [CT] |
| ID evento | `event_id` = `node_id` + `seq`. `seq` è persistente e non si riusa mai (SQLite AUTOINCREMENT) | [L], [CT] |
| Deduplica | In centrale su `(node_id, seq)`; dai buchi nei `seq` si vedono i dati persi | [L], [CT] |
| Backup | LoRaWAN (Wio-E5 sull'MCU) in produzione, BLE (radio integrata della UNO Q, lato Linux) nella demo. Si sceglie con `BACKUP_LINK=lora\|ble` | [L], [CT] |
| Contenuto del backup | Solo allarmi, heartbeat e aggregati (C4), in formato binario compatto. Mai i singoli eventi: quelli restano nello Store & Forward | [L], [S] §4 |
| Failover | Backup attivo dopo 30 s senza conferme MQTT, con il primo pacchetto subito. Backup spento dopo 60 s di MQTT stabile | [L], [S] §5.3 |
| MQTT durante il backup | Il client MQTT si riconnette da solo e fa il backfill appena la rete torna | [CT] |
| Aggregati via backup | Sono provvisori: la centrale li sostituisce con quelli esatti, calcolati sugli eventi dopo il backfill | [CT] |
| Centrale (`app/`) | Subscriber sempre acceso con sessione persistente e deduplica. Diagnosi incrociando MQTT e backup (rete giù / nodo guasto / batteria scarica / manomissione). Dashboard | [L], [S] §5.3 |
| Fuori scope | Niente 4G e niente seconda SIM: se ne parla solo nel pitch | [L] |
| Credenziali | Certificati e chiavi solo in locale (`.env`, `certs/`), mai committati | [L] |

### Librerie e strumenti

| Dove | Cosa | Fonte |
|---|---|---|
| Nodo, lato Linux | `paho-mqtt` 2.x (MQTT v5, `CallbackAPIVersion.VERSION2`), `sqlite3` della stdlib, BLE con `btmgmt` (BlueZ) via subprocess | [CT] |
| Centrale | `paho-mqtt`, `bleak` (ricevitore BLE), `pyserial` (ricevitore LoRa P2P) | [CT] |
| MCU | `Arduino_RouterBridge` (RPC MessagePack su UART interna); Wio-E5 con comandi AT su UART | [CT] |
| Cloud | AWS IoT Core, una policy per ruolo, provisioning con AWS CLI | [CT] |
| Sviluppo | Mosquitto locale con `persistence true` | [CT] |

### Hardware della comunicazione

| Componente | Uso | Fonte |
|---|---|---|
| Arduino UNO Q | Linux (QRB2210, Python: uplink, Store & Forward, BLE) + MCU STM32U585 (attuatori, LoRa) | [L], [S] §1 |
| Wi-Fi 2,4 GHz integrato | canale primario | [S] §5.3 |
| Bluetooth integrato | backup nella demo; il ricevitore è il laptop, che fa da centrale | [L], [S] §5.3 |
| Grove Wio-E5 | backup LoRaWAN in produzione (EU868), su UART D0/D1 dell'MCU. Non è nella BOM della demo | [L], [CT] |

## 2. Parametri e numeri

### MQTT e AWS IoT Core

| Parametro | Valore | Fonte |
|---|---|---|
| Endpoint | AWS IoT Core ATS (`xxxx-ats.iot.<region>.amazonaws.com`) | [CT] |
| Porta | 8883 (TLS mutuo); 443 con ALPN `x-amzn-mqtt-ca` se la rete blocca la 8883; 1883 senza TLS solo con Mosquitto locale | [CT] |
| QoS | 1 ovunque (AWS IoT Core non supporta QoS 2) | [L], [CT] |
| Sessione | `clean_start=False`, Session Expiry 3600 s (default AWS 1 h, estendibile fino a 7 giorni) | [CT] |
| Keepalive | nodo 30 s, ingest 15 s | [CT] |
| Riconnessione | backoff esponenziale da 1 a 30 s | [CT] |
| Batch | massimo 50 eventi per messaggio, un batch in volo alla volta | [CT] |
| Timeout ACK | 30 s, poi il batch si rispedisce | [CT] |
| Dimensione massima | payload < 128 KB (limite AWS) | [CT] |
| Ciclo del nodo | ogni 0,2 s: invio della coda, aggregatore, heartbeat | [CT] |
| Stato | ogni 10 s su `status`, retained, con il backlog | [CT] |
| Last Will | `{"online": false}` su `status`, retained, QoS 1 | [CT] |
| Retention | massimo 2.000.000 righe; ogni 600 s si cancellano le più vecchie **già inviate**, mai quelle in coda | [CT] |

Topic del codice testato (prefisso `torino/crosswalk`, configurabile con `TOPIC_PREFIX`):

| Topic | Contenuto | QoS |
|---|---|---|
| `torino/crosswalk/{node}/events` | batch di eventi | 1 |
| `torino/crosswalk/{node}/agg` | aggregato esatto per finestra | 1 |
| `torino/crosswalk/{node}/alert` | utente lento rilevato (non passa dallo Store & Forward) | 1 |
| `torino/crosswalk/{node}/status` | online e backlog (retained, + Last Will) | 1 |
| `torino/crosswalk/{node}/agg/backup` | messaggi arrivati via BLE / LoRa e ripubblicati dal ricevitore | 1 |

La specifica usa `mdgb/<node_id>/events|agg|hb`: vedi §6.

Formato dei messaggi del codice testato:

```json
{"node":"xw-001","events":[{"seq":1842,"ts":1760000123.456,"cat":"wheelchair","dir":1,"conf":0.91}]}
{"window_start":1760000100,"period_s":900,"source":"mqtt","dir0":{"person":120,"wheelchair":3,"bicycle":15,"stroller":4,"other":1},"dir1":{"person":98,"wheelchair":2,"bicycle":11,"stroller":6,"other":0},"backlog":0}
{"online":true,"ts":1760000130.0,"backlog":0}
{"port":1,"hex":"146478E768…","via":"ble","rssi":-67,"rx_at":1760000140.2,"ble_addr":"AA:BB:CC:DD:EE:FF"}
```

### Failover e backup

| Parametro | Valore | Fonte |
|---|---|---|
| Attivazione del backup | 30 s senza conferme MQTT; il primo pacchetto parte subito | [L] |
| Spegnimento del backup | dopo 60 s di MQTT stabile | [L] |
| Scelta del canale | `BACKUP_LINK=lora\|ble` (il codice accetta anche `none`; default `ble`) | [L], [CT] |
| Aggregati | finestre fisse: 900 s (15 min) in produzione, 60 s nella demo (`AGG_PERIOD_S`) | [CT], [S] §4 |
| Heartbeat sul backup | ogni 5 min | [S] §4 |
| Allarmi sul backup | subito | [S] §4 |
| Recupero aggregati | al ritorno di MQTT al massimo 96 finestre per ciclo (1 giorno a 15 min) | [CT] |
| Heartbeat Linux → MCU | ogni 30 s (`HEARTBEAT_S`) | [CT] |
| Watchdog dell'MCU | 5 min senza heartbeat → uplink LoRa `DEAD` su fPort 9 | [CT] |
| LoRa duty cycle | 1% a 868 MHz → solo allarmi, heartbeat, aggregati | [S] §5.3 |

### Payload di backup (codice testato)

**LoRaWAN, 28 byte, little-endian** (`struct` `<BI10HHB`; stesso layout in `payload.py`, `decoder.py`, `ttn_formatter.js`):

| Byte | Campo | Tipo |
|---|---|---|
| 0 | `ver` (4 bit) \| `net_state` (2 bit: 0 online, 1 offline) \| `ts_quality` (2 bit: 0 NTP, 1 RTC) | uint8 |
| 1–4 | `window_start` (epoch, s) | uint32 |
| 5–14 | direzione 0: person, wheelchair, bicycle, stroller, other | 5 × uint16 |
| 15–24 | direzione 1: stesse categorie | 5 × uint16 |
| 25–26 | backlog / 10 | uint16 |
| 27 | spazio disco libero % | uint8 |

Esempio (finestra 1760000100, backlog 1234, disco 87%, offline):
`146478E768780003000F0004000100620002000B00060000007B0057`

| fPort | Messaggio | Corpo |
|---|---|---|
| 1 | aggregato | i 28 byte sopra |
| 9 | `DEAD` (watchdog dell'MCU) | `0xDE 0xAD` |
| 10 | manomissione | `ts` uint32 \| `code` uint8 |
| 11 | incidente sospetto | `ts` uint32 \| `code` uint8 |

Radio: EU868, OTAA, classe A, ADR attivo, `AT+MSGHEX`, UART a 9600 baud.

**BLE, 27 byte** (advertising non connettibile, Manufacturer Specific Data, company ID `0xFFFF`):
- aggregato: `type`(1) = 1 \| `window_start` uint32 \| 10 × uint16 \| backlog/10 uint16 (i 28 byte meno flag e disco);
- allarmi: `type`(1) = fPort \| primi 26 byte del corpo, con zeri in coda;
- struttura AD: `len` \| `0xFF` \| company ID LE \| frame = 31 byte (il massimo del legacy advertising);
- beacon `btmgmt add-adv`, istanza 1, aggiornato a ogni messaggio e spento con `rm-adv` quando MQTT torna sano;
- il ricevitore scarta i frame ripetuti e ricostruisce i 28 byte (flag = versione 1, offline; disco = 0).

### AWS IoT Core: policy

| Thing | Permessi | Fonte |
|---|---|---|
| nodo (es. `xw-001`) | `iot:Connect` solo come se stesso; `iot:Publish` e `iot:RetainPublish` solo su `torino/crosswalk/${ThingName}/*` | [CT] `aws/node-policy.json` |
| `crosswalk-ingest` | `iot:Subscribe`/`iot:Receive` su `torino/crosswalk/*`; `iot:Publish` su `torino/crosswalk/*/agg/backup` (per i ricevitori BLE/LoRa) | [CT] `aws/ingest-policy.json` |

### Test

| Test | Risultato | Fonte |
|---|---|---|
| End-to-end offline: broker spento e riacceso, circa 40 eventi/s | 806/806 eventi, 0 buchi, duplicati scartati | [L], [CT] |
| Payload 28 byte: nodo e backend decodificano allo stesso modo | OK, rieseguito il 10/10/2026 | [CT] |
| BLE: aggregato e allarme, nodo → frame 27 byte → ricevitore → decoder | OK, rieseguito il 10/10/2026 | [CT] |

## 3. Codice già scritto o testato

Tutto in `~/Desktop/HACKATHLON`, non ancora nel repo. Si integra in CM-M2/CM-M3 **senza riscriverlo**.

| File | Cosa fa | Destinazione |
|---|---|---|
| `crosswalk-node/python/outbox.py` | Store & Forward: SQLite WAL, `synchronous=FULL`, `put`/`pending`/`ack`/`backlog`, retention che non tocca la coda | `comms/` |
| `crosswalk-node/python/uplink_mqtt.py` | MQTT 5 + TLS (AWS), Last Will, sessione persistente, batch, ACK, backfill | `comms/` |
| `crosswalk-node/python/aggregator.py` | finestre fisse; online → JSON `agg` su MQTT, offline → 28 byte al backup | `comms/` |
| `crosswalk-node/python/backup_link.py` | Bridge verso l'MCU (o MCU simulato), backup LoRa e BLE intercambiabili | `comms/` |
| `crosswalk-node/python/payload.py` | evento JSON, aggregato da 28 byte | `comms/` |
| `crosswalk-node/python/config.py`, `main.py`, `event_source.py` | configurazione via variabili d'ambiente, orchestrazione, simulatore di eventi | `comms/` |
| `crosswalk-node/sketch/sketch.ino` | MCU: LoRaWAN/P2P/ESP-NOW, LED, watchdog `DEAD` | **non è area comms**: riferimento per Salvatore (`firmware/`) |
| `backend/ingest.py` | subscriber: dedup `PRIMARY KEY(node, seq)`, buchi, aggregati provvisori, anche da TTN | `app/` |
| `backend/decoder.py`, `ttn_formatter.js` | decoder dei 28 byte (Python e TTN) | `app/` |
| `backend/ble_receiver.py` | ricevitore BLE (bleak) → ripubblica su `…/agg/backup` | `app/` |
| `backend/lora_p2p_receiver.py`, `mosquitto.conf` | mini-gateway LoRa P2P / ESP-NOW; broker locale | `app/` |
| `aws/node-policy.json`, `ingest-policy.json`, `setup_thing.sh` | policy e creazione dei Thing con certificati in `certs/` | `comms/` |
| `tests/test_offline.py` | payload, BLE, end-to-end offline | `comms/` |

Come si prova (sul laptop, senza scheda):

```bash
brew install mosquitto
pip install -r backend/requirements.txt
python tests/test_offline.py          # deve stampare "TUTTI I TEST SUPERATI"
```

Cosa manca rispetto alle decisioni di §1:
1. un PUBACK **negativo** (reason code ≥ 0x80) oggi marca l'evento come inviato: `_on_publish` non guarda il reason code;
2. "online" oggi è `is_connected()`: deve basarsi sulle conferme (PUBACK);
3. manca l'isteresi 30 s / 60 s: il backup si accende e si spegne seguendo `is_connected()`;
4. manca "primo pacchetto subito": offline l'aggregatore manda solo quando si chiude una finestra (fino a 15 min);
5. manca l'heartbeat sul backup e non c'è ancora chi produce gli allarmi (le porte 10/11 hanno solo il decoder);
6. manca la diagnosi in centrale e manca la dashboard.

## 4. Cosa mi serve dagli altri

| Da chi | Cosa | Per quale milestone |
|---|---|---|
| Salvatore (firmware) | Nomi e firme delle funzioni Bridge lato MCU per C1/C2 (proposta in CONTRACTS v1) | CM-M4 (`BridgeActuator`) |
| Salvatore (firmware) | Formato e nomi con cui l'MCU manda a Linux: dati ambientali (ogni 10 s), `tamper`, `lamp_fault`, ingresso in fail-safe | CM-M3 (aggregati, allarmi, diagnosi) |
| Salvatore (firmware) | Solo produzione: `lora_send` + watchdog `DEAD` sul Wio-E5 (riferimento: il vecchio `sketch.ino`) | dopo la demo |
| Paolo (vision) | Valori ammessi di C3: `cls`, `dir`, `line`, `attrs.aid`, `type`, `kind`; frequenza delle righe `status` | CM-M1 (contratto), CM-M2 |
| Paolo (vision) | Quali eventi C3 sono allarmi da mandare subito sul backup | CM-M3 |
| Paolo (vision) | Accordo sul trasporto di C3 (file JSONL e/o HTTP) e su dove scrive il file | CM-M1 |
| Kuzey (electronics) | Se si vuole la diagnosi "batteria scarica": come si legge la carica della LiPo (pin e partitore) | CM-M3 |
| Kuzey (electronics) | Pin dell'interruttore magnetico del case (manomissione) nella sezione Pinout | CM-M3 |

## 5. Cosa fornisco io agli altri

| A chi | Cosa |
|---|---|
| Tutti | `docs/CONTRACTS.md` v1 (C1–C4, Bridge, payload di backup), di cui sono l'owner |
| Paolo | `comms/actuators.py`: interfaccia `Actuator` con `SimActuator` e `SerialActuator` (CM-M1), `BridgeActuator` (CM-M4) |
| Salvatore | Trasporto di C1/C2 verso l'MCU (seriale 115200 e Bridge) e uno strumento da PC per inviare comandi e heartbeat al firmware |
| Salvatore | Il vecchio `sketch.ino` (LoRaWAN, watchdog) come riferimento per il backup LoRa in produzione |
| Tutti | Uplink MQTT/AWS con Store & Forward e backup (`comms/`), ingest e dashboard della centrale (`app/`) |
| Tutti | Script di provisioning AWS (un certificato per nodo, solo in locale) e prova "Wi-Fi spento / riacceso" per la demo |

## 6. Questioni aperte

Differenze tra le decisioni di §1–2 e la specifica (§4, §5.3, §9):

1. **Prefisso dei topic**: [CT] `torino/crosswalk/{node}/…`, [S] `mdgb/<node_id>/…`. Cambiare il prefisso tocca anche le policy AWS.
2. **Topic**: [S] ha `events`, `agg`, `hb`. [CT] ha `status` (con Last Will) al posto di `hb`, più `alert` e `agg/backup`.
3. **Formato degli eventi**: [S] un evento per messaggio con `event_id` stringa (`"nodo07-000805"`); [CT] batch fino a 50 con `seq` intero e nodo nella busta.
4. **Dopo il PUBACK**: [S] l'evento "si cancella"; [L]/[CT] si marca inviato e si tiene (serve agli aggregati esatti; la retention cancella solo i già inviati).
5. **Failover**: [S] parla di "passaggio al backup" e "ritorno al Wi-Fi dopo 60 s"; in [L]/[CT] MQTT non si ferma mai: il backfill riparte subito e i 60 s valgono solo per spegnere il backup. [L] aggiunge "primo pacchetto subito".
6. **`agg` con `event_id`**: in [S] l'aggregato prende un `event_id` dallo stesso contatore degli eventi; in [CT] l'aggregato è identificato da `(nodo, window_start)` e si ricalcola.
7. **Categorie**: [CT] usa person, wheelchair, bicycle, stroller, other e `dir` 0/1; C3 usa `cls` + `attrs` e `dir` in/out, con veicoli e animali. Il payload da 28 byte e la tabella dell'outbox vanno adattati.
8. **Heartbeat e batteria**: l'`hb` di [S] ha `mode`, `link`, `batt`, `queue`; [CT] manda solo `online`, `ts`, `backlog`. Il payload di backup non ha batteria né stato del nodo, che servono alla diagnosi.
9. **Nome dell'impostazione**: [S] `backup: ble|lora`, [L] `BACKUP_LINK=lora|ble`.
10. **LoRa**: [S] "gateway della centrale"; [CT] TTN o AWS IoT Core for LoRaWAN, più Piano B (P2P) e Piano C (ESP-NOW), che [L] non prevede.
11. **`alert`**: in [CT] l'alert per utente lento esce su MQTT senza Store & Forward e accende il LED da Linux (`pedestrian_alert`); con C1 la decisione passa a `rules.py` e il LED al firmware.

Altri punti:

12. **`seq` dopo la perdita del DB**: se il file SQLite si perde (container, scheda reinstallata) `seq` riparte da 1 e la centrale scarterebbe i nuovi eventi come duplicati.
13. **Versioni**: le regole del team chiedono versioni fissate in `requirements.txt`; [CT] usa intervalli (`paho-mqtt>=2.0,<3`).
14. **`.gitignore`**: copre `.env`, `*.pem`, `*.key`, `*.crt` ma non la cartella `certs/` (`setup_thing.sh` ci scrive anche `.public.key` e la CA).
15. **`ttn_formatter.js`** gestisce solo le fPort 1 e 9: con 10/11 restituisce un errore.
16. **Aggregato online "inviato" troppo presto**: in `aggregator.py` la finestra conta come pubblicata quando paho accetta il messaggio, non al PUBACK.
17. **Trasporto di C3** (questione 6 di Paolo) e **pedone visto solo in termico** (questione 7 di Paolo): da chiudere in CONTRACTS v1.
18. **Dati MCU → Linux** (questione 3 di Paolo): nessun contratto in [S]; da chiudere in CONTRACTS v1 con Salvatore.
