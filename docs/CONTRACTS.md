# Contratti tra i moduli MDGB — v1

Owner: **Lorenzo Dragoni** (communication engineer). Sezione Pinout: **Kuzey Bicher** (electronics).
Base: `PROMPT_SMART_CROSSING.md` §4, corretta con le decisioni di `comms/DECISIONS.md`.

Regole:
- ogni messaggio JSON ha `"v"` (versione del suo contratto); questo file è la v1;
- campi nuovi **opzionali** si possono aggiungere senza cambiare versione: chi legge ignora i campi che non conosce;
- rinominare, togliere o cambiare il significato di un campo = nuova versione, proposta dall'owner e comunicata al team;
- tempi in secondi epoch UTC (`ts`, float) salvo dove indicato `t_ms`; testi in UTF-8; JSON su una riga sola.

Le voci marcate **[da confermare: X]** sono proposte mie su punti che la specifica lascia aperti: X deve dire ok.

## Mappa

| ID | Da → A | Trasporto | Produce | Consuma |
|---|---|---|---|---|
| C1 | AI → firmware: comando | seriale 115200 o Bridge, via `Actuator` | Paolo (`rules.py`) | Salvatore |
| C2 | AI → firmware: heartbeat | come C1 | Paolo (`app.py`) | Salvatore |
| C3 | AI → comms/app: eventi | file JSONL | Paolo (`logger.py`) | Lorenzo |
| C4 | nodo → centrale | MQTT 5 / AWS IoT Core | Lorenzo (`comms/`) | Lorenzo (`app/`) |
| C4-B | nodo → centrale, backup | BLE (demo) / LoRaWAN (produzione), binario | Lorenzo (`comms/`), Salvatore per la radio LoRa | Lorenzo (`app/`) |
| C5 | firmware → Linux: dati dell'MCU | seriale o Bridge, righe JSON | Salvatore | Paolo, Lorenzo |
| Bridge | funzioni RPC Linux ↔ MCU sulla UNO Q | Arduino_RouterBridge | Salvatore (MCU), Lorenzo (Linux) | — |

Processi sulla UNO Q **[da confermare: Paolo]**: `ai` (visione, regole, `Actuator`) e `comms` (uplink, Store & Forward,
backup) girano separati e si parlano solo tramite i file di C3. Se `comms` cade la sicurezza non cambia; se `ai` cade
il firmware va in fail-safe e `comms` continua a svuotare la coda.

---

## C1 — Comando AI → firmware (invariato rispetto a §4)

```json
{"v":1,"seq":1842,"t_ms":1739012345678,"state":"WARN_DRIVER","led":"AMBER_BLINK_2HZ","green_s":19,"req":{"ped_green_extend_s":7,"veh_red_hold":true,"flash":false},"lcd":"PEDONE  47 km/h","oled":"ATTENDI auto 45km/h","reason":"anziano 0.8 m/s; auto 50 km/h a 60 m; TTC 4.3 s < T_need 9.8 s"}
```

- `state` ∈ `IDLE | PRESENCE | WARN_DRIVER | WARN_PEDESTRIAN | ANIMAL_WARN | ANIMAL_ALERT | DEGRADED`
- `led` ∈ `OFF | WHITE_ON | AMBER_BLINK_2HZ | AMBER_BLINK_4HZ | RED_GROUND_BLINK | YELLOW_FAILSAFE`
- `req` = richieste alla centralina (reale o simulata). Il firmware le applica solo entro i suoi limiti fissi
  (verde pedonale +15 s al massimo, rosso veicolare trattenuto 20 s al massimo, verde veicolare minimo 8 s).
- `lcd` (conducenti) e `oled` (pedoni): testi da mostrare.

Trasporto (aggiunte mie, valgono per seriale e Bridge):
- una riga = un oggetto JSON, terminata da `\n` sulla seriale (senza `\n` come argomento Bridge);
- **massimo 512 byte per riga** (dimensione del buffer di ricezione dell'MCU);
- seriale: 115200 baud, 8N1;
- `lcd` **[da confermare: Salvatore]**: solo ASCII, massimo 32 caratteri; i primi 16 vanno sulla riga 1, i successivi sulla riga 2;
- **[da confermare: Paolo]** l'AI ripete l'ultimo C1 almeno ogni 1 s anche se non cambia, così una riga persa sulla
  seriale non lascia il firmware in uno stato vecchio. Il firmware tratta i C1 come idempotenti.

## C2 — Heartbeat AI → firmware (invariato rispetto a §4)

```json
{"v":1,"hb":1843}
```

- Ogni 100 ms, stesso trasporto di C1.
- Più di 500 ms senza heartbeat: in modalità `signalized` il firmware annulla tutte le richieste e la centralina torna
  al ciclo normale; in modalità `uncontrolled` passa a `YELLOW_FAILSAFE`.

## Interfaccia Python `Actuator` (`comms/actuators.py`)

```python
class Actuator:
    def send(self, cmd: dict) -> None: ...      # C1
    def heartbeat(self, seq: int) -> None: ...  # C2
    def close(self) -> None: ...
# implementazioni: SimActuator, SerialActuator(port, baud=115200), BridgeActuator (UNO Q)
# factory: make_actuator(kind: "sim" | "serial" | "bridge", **kwargs) -> Actuator
```

- `send` e `heartbeat` non bloccano e non sollevano eccezioni se il collegamento cade: `SerialActuator` si riconnette da solo
  (la sicurezza è comunque garantita dal timeout di 500 ms del firmware). Se il collegamento è lento si manda solo
  l'ultimo C1 e l'ultimo C2 (i comandi sono stati, non code).
- Se una riga supera 512 byte, `Actuator` accorcia `reason`; se non basta solleva `ValueError` (errore di programmazione,
  non di rete).
- Le righe C5 ricevute dall'MCU vengono scritte da `Actuator` in `$MDGB_C3_DIR/mcu-*.jsonl` (stesse regole di C3).
  **[da confermare: Paolo]** In più: `set_listener(cb: Callable[[dict], None])` opzionale, per avere le righe C5 anche
  dentro `ai/` (per esempio `lamp_fault` o `tamper` → `DEGRADED`, array termico).

## Bridge — funzioni RPC sulla UNO Q

Libreria [Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge) (MessagePack-RPC).
Lato MCU: `Bridge.begin()`, `Bridge.provide(...)`, `Bridge.provide_safe(...)`, `Bridge.call(...)`, `Bridge.notify(...)`.
Lato Python: `from arduino.app_utils import Bridge` (usato nel codice testato: `Bridge.call(name, *args)`).
`TODO(verify)`: `Bridge.notify` e `Bridge.provide` lato Python, e se più processi Linux possono usare il Bridge insieme.

**[da confermare: Salvatore]**

| Funzione | Chi la espone | Argomenti | Ritorno | Uso |
|---|---|---|---|---|
| `mdgb_line` | MCU, con `Bridge.provide_safe` (gira nel `loop()`, niente race con LED e centralina) | `String`: una riga C1 o C2 | `bool` (true = riga valida) | C1, C2. Stesso parser della seriale |
| `mcu_event` | Linux, con `Bridge.provide` | `String`: una riga C5 | — (l'MCU usa `Bridge.notify`) | C5 |
| `lora_send` | MCU | `int fport`, `String hex` (corpo C4-B) | `bool` (true = in coda) | solo produzione |
| `lora_joined` | MCU | — | `bool` | solo produzione |

Avvertenza della libreria: non chiamare `Bridge.call` dentro una funzione registrata con `provide` (rischio di deadlock).
Watchdog di produzione: se l'MCU non riceve C2 per 5 min, manda via LoRa `DEAD` (C4-B tipo 9).

## C5 — Dati dell'MCU → Linux [da confermare: Salvatore, Paolo]

Stesso trasporto di C1, in senso opposto. Sulla seriale le righe che iniziano con `{` sono C5; le altre sono log di debug
e si ignorano.

```json
{"v":1,"src":"mcu","type":"env","t_c":14.2,"rh":81,"lux":120,"batt":87}
{"v":1,"src":"mcu","type":"tamper","code":1}
{"v":1,"src":"mcu","type":"lamp_fault","pattern":"AMBER_BLINK_2HZ","i_ma":120,"exp_ma":480}
{"v":1,"src":"mcu","type":"failsafe","reason":"hb_timeout"}
{"v":1,"src":"mcu","type":"thermal","t":[21.4,21.6,"… 64 valori, 16x4 per righe"]}
```

- `env` ogni 10 s; `thermal` 4 volte al secondo (per `thermal.py`); gli altri appena succedono.
- `env.batt`: carica della batteria in % dal LTC2941, opzionale (assente se non misurata). Ogni campo di `env` è opzionale.
- `tamper.code`: 1 = urto o inclinazione (IMU), 2 = sportello del case aperto (micro switch), 3 = apertura autorizzata
  (badge NFC del tecnico: la centrale non dà allarme per lo sportello nei 10 min successivi).
- `failsafe.reason`: `hb_timeout` | `lamp_fault` | `boot`.
- L'MCU non ha l'ora: `ts` lo aggiunge Linux quando riceve la riga.
- `Actuator` scrive su file tutte le righe C5 tranne `thermal` (troppo frequente: arriva solo al listener).

## C3 — Eventi AI → comms/app

Formato invariato rispetto a §4:

```json
{"v":1,"ts":1739012345.67,"type":"crossing","track_id":12,"cls":"pedestrian","attrs":{"child":false,"slow":true,"aid":null},"dir":"in","line":"ped"}
{"v":1,"ts":1739012350.10,"type":"near_miss","a":12,"b":31,"ttc_s":0.8,"pet_s":null}
{"v":1,"ts":1739012399.00,"type":"incident","kind":"person_down","track_id":12,"zone":"carriageway"}
{"v":1,"ts":1739012400.00,"type":"status","state":"PRESENCE","fps":9.6,"lat_ms":{"detect":71,"track":3,"rules":1,"act":2},"counts":{"ped_in":14,"ped_out":11,"car_in":52}}
```

Valori ammessi **[da confermare: Paolo]**:
- `type` ∈ `crossing | near_miss | incident | yield | status`;
- `cls` ∈ `pedestrian | cyclist | motorcyclist | car | bus | truck | animal | bird`; per `animal` e `bird` c'è anche
  `"coco":"dog"` (classe COCO originale, §7);
- pedone visto solo in termico (questione 7 di Paolo): `"cls":"pedestrian"` con `"attrs":{"thermal_only":true}`;
- `attrs.aid` ∈ `null` (modello assente) `| "normal" | "wheelchair" | "walking_aid" | "stroller"`;
- `dir` ∈ `in | out`; `line` ∈ `ped | veh`;
- `incident.kind` ∈ `person_down | collision | hard_brake | vehicle_on_crosswalk`;
- `yield` (nuovo, serve allo yield rate degli aggregati): una riga per veicolo arrivato con un pedone in zona d'attesa,
  `{"v":1,"ts":…,"type":"yield","track_id":31,"yielded":true}`;
- `status` ogni 5 s.

Trasporto **[da confermare: Paolo]** (chiude la questione 6 di Paolo; l'endpoint HTTP non serve in v1):
- cartella `$MDGB_C3_DIR` (default `logs/c3/` nella root del repo, ignorata da git);
- file `c3-YYYYMMDD-HHMMSS.jsonl` (ora UTC di apertura): l'ordine alfabetico è l'ordine temporale;
- solo append: una riga completa per scrittura, terminata da `\n`, con flush. Rotazione = si chiude il file e se ne apre
  uno nuovo. Mai riscrivere o troncare un file;
- un file si può cancellare solo dopo 7 giorni (a `comms` servono finché non li ha letti);
- `comms` legge i file in ordine e salva (file, offset) nello stesso commit SQLite dell'outbox: niente perdite e niente
  doppioni anche se `comms` si riavvia. Una riga senza `\n` finale si legge solo quando è completa.

---

## C4 — Nodo → centrale (MQTT 5, AWS IoT Core)

**Demo (senza crediti AWS):** broker Mosquitto dentro l'app della centrale sul PC, porta 1883 sulla rete locale, senza
TLS né certificati. Topic e messaggi sono identici; in produzione si torna alla connessione qui sotto.

Connessione: TLS mutuo sulla porta 8883 (443 con ALPN `x-amzn-mqtt-ca` se la rete blocca la 8883), un certificato X.509
per nodo, client ID = `node_id` = nome del Thing (`^[a-z0-9-]{1,32}$`, es. `nodo07`). MQTT 5, QoS 1 ovunque,
`clean_start=false`, Session Expiry 3600 s.

### Topic

Prefisso `mdgb` (configurabile con `TOPIC_PREFIX`). Al posto di `torino/crosswalk` del codice testato: cambiano anche le policy AWS.

| Topic | Da → A | Contenuto | QoS | Retained |
|---|---|---|---|---|
| `mdgb/<node_id>/events` | nodo → centrale | batch di eventi dallo Store & Forward | 1 | no |
| `mdgb/<node_id>/agg` | nodo → centrale | aggregato esatto per finestra | 1 | no |
| `mdgb/<node_id>/hb` | nodo → centrale | heartbeat ogni 10 s; Last Will sullo stesso topic | 1 | sì |
| `mdgb/<node_id>/backup` | ricevitore BLE/LoRa → centrale | messaggi C4-B ripubblicati | 1 | no |

Non c'è più `alert`: gli allarmi sono eventi e passano dallo Store & Forward come tutti gli altri.

### `events`

```json
{"v":1,"node_id":"nodo07","events":[
  {"seq":805,"event_id":"nodo07-000805","ts":1739012345.67,"type":"crossing","track_id":12,"cls":"pedestrian","attrs":{"child":false,"slow":true,"aid":null},"dir":"in","line":"ped"},
  {"seq":806,"event_id":"nodo07-000806","ts":1739012350.10,"type":"near_miss","a":12,"b":31,"ttc_s":0.8,"pet_s":null}
]}
```

- Ogni evento = la riga C3 (o C5 non periodica: `tamper`, `lamp_fault`, `failsafe`) **invariata**, più `seq` ed `event_id`
  aggiunti da `comms`.
- `seq`: intero assegnato da `comms` quando scrive l'evento su disco, persistente, mai riusato.
  `event_id` = `<node_id>-<seq>` con `seq` di almeno 6 cifre (`nodo07-000805`).
- Da 1 a 50 eventi per messaggio, in ordine di `seq`. Online di solito ne parte uno alla volta; nel backfill si riempie il batch.
- La centrale deduplica su `(node_id, seq)`; i buchi nei `seq` sono dati persi.
- Le righe C3 `status` e C5 `env`/`thermal` non diventano eventi: finiscono in `hb` e `agg`.

### `agg`

```json
{"v":1,"node_id":"nodo07","type":"agg","t0":1739011500,"t1":1739012400,"counts":{"pedestrian":{"in":14,"out":11},"cyclist":{"in":4,"out":2},"car":{"in":52,"out":0}},"vulnerable":3,"near_miss":1,"incident":0,"yield_rate":0.42,"env":{"t_c":14.2,"rh":81,"lux":120},"queue":0}
```

- Finestre fisse di 900 s (60 s nella demo), calcolate dagli eventi su disco: sono esatte, anche quelle maturate durante
  un blackout (si mandano al ritorno della rete).
- Chiave `(node_id, t0)`, senza `event_id`: se arriva due volte si sovrascrive. Sostituisce l'aggregato provvisorio
  arrivato dal backup.
- `vulnerable` = pedoni con `child`, `slow` o `aid` diverso da `null`/`normal`. `yield_rate` = `null` se nessun veicolo.

### `hb`

```json
{"v":1,"node_id":"nodo07","type":"hb","ts":1739012400.0,"online":true,"mode":"normal","state":"PRESENCE","backup":"off","batt":null,"queue":0,"disk_free_pct":87,"fps":9.6}
```

Last Will (retained, QoS 1), pubblicato dal broker se il nodo sparisce:
```json
{"v":1,"node_id":"nodo07","type":"hb","online":false}
```

- `mode` ∈ `normal | degraded | failsafe` (`degraded` = ultimo `status` C3 in `DEGRADED`; `failsafe` = C5 `failsafe`).
- `backup` ∈ `off | ble | lora`: canale di backup acceso in questo momento.
- `batt` = % o `null` se non misurata; `queue` = eventi in coda non ancora confermati.

### Semantica del failover (nodo)

- Conferma = PUBACK con reason code < 0x80 (0x00 Success e 0x10 No matching subscribers sono conferme).
  PUBACK con reason code ≥ 0x80: l'evento **non** è inviato e resta in coda.
- Siccome `hb` parte ogni 10 s con QoS 1, ci sono conferme anche quando non ci sono eventi.
- Nessuna conferma per 30 s → backup acceso, e subito parte il primo pacchetto (`HB` e ultimo `AGG` chiuso).
- MQTT continua a riconnettersi e fa il backfill appena può.
- 60 s di MQTT stabile (connesso, conferme regolari, nessun PUBACK negativo) → backup spento.

---

## C4-B — Backup compatto (BLE nella demo, LoRaWAN in produzione)

Solo allarmi (subito), heartbeat (ogni 5 min) e aggregati (ogni 15 min). Mai i singoli eventi. Binario, little-endian.
Solo mentre il backup è acceso (vedi failover).

Busta comune:
- **LoRaWAN**: fPort = `type`, FRMPayload = corpo. Wio-E5 su UART dell'MCU, EU868, OTAA, classe A, ADR (comandi AT del codice testato).
- **BLE**: advertising non connettibile, Manufacturer Specific Data con company ID `0xFFFF` (riservato ai test).
  Frame di 27 byte = `type` (1 byte) + corpo, con zeri in coda. Struttura AD: `len | 0xFF | 0xFFFF LE | frame` = 31 byte.
- `ver` = 1 (il vecchio aggregato da 28 byte del prototipo non si usa più).

| type / fPort | Messaggio | Quando | Corpo |
|---|---|---|---|
| 1 | `AGG` aggregato | ogni 15 min e all'accensione del backup | 26 byte |
| 2 | `HB` heartbeat | ogni 5 min e all'accensione del backup | 12 byte |
| 9 | `DEAD` | watchdog dell'MCU, solo LoRa | `0xDE 0xAD` |
| 10 | `TAMPER` manomissione | subito | `ts` uint32 \| `code` uint8 (come C5) |
| 11 | `INCIDENT` | subito | `ts` uint32 \| `code` uint8: 1 person_down, 2 collision, 3 hard_brake, 4 vehicle_on_crosswalk |
| 12 | `FAULT` nodo guasto | subito | `ts` uint32 \| `code` uint8: 1 lamp_fault, 2 video assente, 3 lente coperta, 4 abbagliamento, 5 fail-safe del firmware |

Solo produzione: un `HB` via LoRa ogni 6 h anche con MQTT sano, per verificare che il canale di backup funzioni.

### `AGG`, 26 byte (`struct` `<BIBHHHHBBBBBbBHHB`)

| Byte | Campo | Tipo | Note |
|---|---|---|---|
| 0 | `ver` (4 bit) \| `ts_quality` (2 bit: 0 NTP, 1 RTC) \| `degraded` (1 bit) \| riservato (1 bit) | uint8 | |
| 1–4 | `t0` | uint32 | inizio finestra, epoch s |
| 5 | durata della finestra | uint8 | minuti |
| 6–7 | pedoni `in` | uint16 | |
| 8–9 | pedoni `out` | uint16 | |
| 10–11 | ciclisti (in + out) | uint16 | |
| 12–13 | veicoli (car, motorcyclist, bus, truck; in + out) | uint16 | |
| 14 | animali | uint8 | saturato a 255 |
| 15 | pedoni vulnerabili | uint8 | saturato a 255 |
| 16 | near-miss | uint8 | |
| 17 | incidenti | uint8 | |
| 18 | yield rate | uint8 | 0–100 %, 255 = n.d. |
| 19 | temperatura | int8 | °C arrotondati, −128 = n.d. |
| 20 | umidità | uint8 | %, 255 = n.d. |
| 21–22 | luce | uint16 | lux, 65535 = n.d. |
| 23–24 | backlog / 10 | uint16 | eventi in coda |
| 25 | batteria | uint8 | %, 255 = n.d. |

Esempio (t0 1739011500, 15 min, 14/11 pedoni, 6 ciclisti, 52 veicoli, 1 animale, 3 vulnerabili, 1 near-miss,
yield 42%, 14 °C, 81%, 120 lux, backlog 1234, batteria n.d.):
`10AC35A7670F0E000B0006003400010301002A0E5178007B00FF`

### `HB`, 12 byte (`struct` `<BIBHBBH`)

| Byte | Campo | Tipo | Note |
|---|---|---|---|
| 0 | `ver` (4 bit) \| `mode` (2 bit: 0 normal, 1 degraded, 2 failsafe) \| `ts_quality` (2 bit) | uint8 | |
| 1–4 | `ts` | uint32 | epoch s |
| 5 | `state` | uint8 | indice in C1: 0 IDLE, 1 PRESENCE, 2 WARN_DRIVER, 3 WARN_PEDESTRIAN, 4 ANIMAL_WARN, 5 ANIMAL_ALERT, 6 DEGRADED |
| 6–7 | backlog / 10 | uint16 | |
| 8 | batteria | uint8 | %, 255 = n.d. |
| 9 | disco libero | uint8 | % |
| 10–11 | minuti senza conferme MQTT | uint16 | |

Esempio: `103039A767017B00FF570200`

Vincoli: 26 byte è il massimo che entra in un advertising BLE legacy, e sta sotto i 51 byte di LoRaWAN EU868 anche a SF12.
Con l'1% di duty cycle un `AGG` ogni 15 min e un `HB` ogni 5 min stanno largamente nei limiti. Su TTN vale anche il
fair use di 30 s di airtime al giorno: rispettato solo con SF bassi (ADR); con un gateway proprio della centrale no.

### Ricevitore → centrale (`mdgb/<node_id>/backup`)

```json
{"v":1,"node_id":"nodo07","via":"ble","type":1,"hex":"10AC35A7670F0E000B0006003400010301002A0E5178007B00FF","rssi":-67,"rx_at":1739012401.2}
```

- `via` ∈ `ble | lorawan`. Il ricevitore non decodifica: inoltra `type` e corpo, decodifica la centrale (un solo decoder).
- `node_id`: per il BLE dal MAC del nodo (tabella nella configurazione del ricevitore, `TODO(verify)` che l'indirizzo BLE
  della UNO Q sia stabile); per LoRaWAN dal `device_id` di TTN (= `node_id`).
- Il ricevitore BLE inoltra un frame solo la prima volta che lo vede (il beacon si ripete più volte al secondo).
- Nella demo il ricevitore BLE è dentro la centrale (`app/central.py`) e scrive direttamente nel suo database: il
  backup non passa da Internet. Il topic `backup` serve ai ricevitori remoti (gateway LoRaWAN, ricevitori BLE lontani).
- BLE: il nodo tiene in onda fino a tre beacon insieme (istanza 1 `AGG`, 2 `HB`, 3 allarmi), a rotazione.

---

## Diagnosi in centrale

| MQTT (`hb` negli ultimi 30 s) | Backup (C4-B negli ultimi 11 min) | Ultima informazione | Diagnosi |
|---|---|---|---|
| sì | — | `mode` normal | nodo OK |
| sì o no | sì o no | `mode` degraded/failsafe, oppure `FAULT` | nodo guasto (con il codice) |
| no | sì | `mode` normal | rete giù, nodo sano |
| no | no | `DEAD` ricevuto | Linux bloccato, MCU vivo |
| no | no | `TAMPER` (code 1 o 2) negli ultimi 10 min | manomissione (probabile) |
| no | no | batteria < 20% o in calo | batteria scarica (probabile) |
| no | no | nessun preavviso | nodo distrutto o senza alimentazione |

`TAMPER` code 3 (badge NFC del tecnico) non è un allarme: per 10 min lo sportello aperto (code 2) non conta.

---

## Pinout (owner: Kuzey Bicher)

Da compilare. Pin che servono alla comunicazione:

| Pin | Componente | Direzione | Note |
|---|---|---|---|
| D0/D1 (UART) | Grove Wio-E5 | MCU ↔ modulo | solo produzione, 9600 baud |
| _?_ | micro switch dello sportello | ingresso MCU | C5 `tamper` code 2 |
| _?_ | lettore NFC | MCU | C5 `tamper` code 3 (badge del tecnico) |
| _?_ (I2C) | LTC2941 | MCU | C5 `env.batt` |
| _?_ (I2C) | AHT20, sensore di luce | MCU | C5 `env` |

## Changelog

- v1 (10/10/2026): prima versione da §4 di `PROMPT_SMART_CROSSING.md` con le decisioni di `comms/DECISIONS.md`.
