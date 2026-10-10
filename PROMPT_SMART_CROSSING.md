# MDGB (Mobility Data & Guardian Beacon) — sfida GOMA Smart Crossing — specifica di implementazione

> MDGB è un modulo che **si installa sul semaforo esistente**: vede chi sta arrivando, chiede alla centralina
> semaforica di allungare il verde o di trattenere il rosso, avvisa conducenti e pedoni con due display e manda alla
> centrale solo dati anonimi. Se si guasta, il semaforo torna esattamente com'era.

> **Per gli umani.** Questo file è il piano tecnico condiviso. Si usa insieme a `PROMPT_GIT_TEAM.md`
> (regole git e divisione delle cartelle). Comando da dare all'assistente AI:
>
> ```text
> Leggi PROMPT_GIT_TEAM.md e PROMPT_SMART_CROSSING.md e seguili. Sono <nome> (<ruolo>). Task: <milestone>.
> ```

---

Da qui in poi le istruzioni sono per te, assistente AI. Rispondi in italiano, commenti nel codice in inglese.

## 0. Regole d'ingaggio

1. `PROMPT_GIT_TEAM.md` ha la precedenza: branch, commit, perimetro delle cartelle, contratti.
2. Implementa SOLO i moduli dell'area dell'utente (vedi §3). Se ti serve un modulo di un'altra area non ancora
   pronto, crea un mock o un simulatore dentro le cartelle dell'utente, scritto contro i contratti di §4.
3. Le decisioni di §2 sono già prese: non rimetterle in discussione senza chiedere all'utente.
4. Nessuna API inventata. Per Arduino App Lab, il Bridge della UNO Q, supervision, onnxruntime e i sensori,
   verifica la documentazione ufficiale e metti il link nel commento. Se non riesci a verificarla: stub + `TODO(verify)`.
5. Ogni milestone finisce con: il comando esatto per provarla, l'output atteso e il messaggio per il team
   previsto da PROMPT_GIT_TEAM.md. Poi fermati e aspetta l'ok.
6. Hackathon: demo funzionante prima di codice perfetto. Codice semplice, poche dipendenze.

## 1. Contesto

- Brief GOMA: dispositivo embedded con computer vision e AI **interamente locali** che riconosce pedoni, ciclisti,
  veicoli, persone con disabilità e animali vicino a un attraversamento. Deve attivare una segnalazione luminosa
  in tempo reale secondo una **regola esplicita**, contare gli attraversamenti distinguendone la **direzione**
  (senza doppioni) e funzionare **senza internet**.
- **Concept MDGB**:
  - **Semaforo esistente**: MDGB non sostituisce la centralina semaforica. Le invia **richieste**: allungare il verde
    pedonale, trattenere il rosso veicolare, attivare il lampeggiante. La centralina le esegue rispettando i propri
    tempi minimi. **Fail-safe = la centralina torna al suo ciclo normale** (nessun rischio in più rispetto a oggi).
  - **Attraversamenti senza semaforo**: MDGB pilota un proprio lampeggiante; lì il fail-safe è il giallo lampeggiante.
  - **Nel prototipo** la centralina è **simulata nel firmware** (ciclo veicoli verde/giallo/rosso + omino pedonale,
    con tempi minimi) e il semaforo è fatto con le strip/il ring WS2813.
  - **Display**: Grove LCD 16x2 verso i conducenti ("PEDONE 47 km/h"), OLED verso i pedoni (conto alla rovescia,
    "ATTENDI: auto a 45 km/h"); avviso vocale opzionale (Grove MP3) per gli ipovedenti.
  - **Dati**: metadati anonimi + sensori ambientali (temperatura, umidità, luce, IMU) verso una centrale
    (MQTT/AWS IoT Core, backup BLE nel prototipo e LoRa in produzione). Le previsioni di afflusso si calcolano sul
    server: open data per il Comune + servizio a pagamento per le attività commerciali.
- Hardware finale: **Arduino UNO Q**.
  - MPU Qualcomm QRB2210: 4x Cortex-A53 a 2,0 GHz, GPU Adreno 702, nessuna NPU, Debian Linux aarch64, 2/4 GB di RAM.
  - MCU STM32U585 (Zephyr, sketch Arduino). Le due parti comunicano con il **Bridge** RPC di Arduino.
  - Una sola porta USB-C: la webcam USB passa da un hub USB-C alimentato.
- Sviluppo e test su macOS (Apple Silicon) e Linux. **Lo stesso codice Python deve girare su PC e su UNO Q.**
- Prestazioni note sulla UNO Q:
  - YOLOv8n 640 px con OpenCV DNN: 1–2 FPS;
  - yolox-nano di App Lab: circa 10 FPS;
  - YOLOv5-pico di Edge Impulse a 224 px: circa 17 FPS.
  Obiettivo: **≥ 8 FPS end-to-end a 320 px**.
- Ambiente dell'hackathon: si lavora in sede sab 10–20 e dom 9–16. La consegna è domenica alle 16.

## 2. Decisioni già prese

| Tema | Decisione | Perché |
|---|---|---|
| Detector | **YOLOX-nano COCO in ONNX** (Apache-2.0) eseguito con **onnxruntime**, input 320 (416 opzionale) | Gira su x86/arm64/aarch64, niente torch a runtime, licenza libera |
| Tracking | `supervision.ByteTrack` | MIT, leggero |
| Conteggio direzionale | `supervision.LineZone` con `minimum_crossing_threshold` + età minima della traccia | Evita doppioni e oscillazioni sulla linea |
| Tipo di pedone | **Cascata**: detector COCO generico, poi attributi calcolati **una volta per traccia** | Niente conflitti di etichette tra dataset, costo minimo |
| Bambino | Altezza in metri (omografia), < 1,30 m | Nessun ML, robusto |
| Anziano / lento | **Velocità di camminata misurata** < 0,9 m/s | Si misura il tempo che serve davvero, non si indovina l'età |
| Ausili (carrozzina, deambulatore, passeggino) | Classificatore ONNX **opzionale** sui ritagli 96x96 (lo addestra il data scientist a parte) | Se il modello manca il sistema funziona lo stesso |
| Incidenti | **Regole sulle traiettorie**, nessun modello video | Troppo pesante per la UNO Q |
| Sicurezza | Regola fisica (TTC, distanza d'arresto) + **fail-safe nel firmware** (heartbeat) | Linguaggio "safety" di GOMA: la sicurezza non dipende da Linux |
| Privacy | **Mai salvare frame su disco**: solo metadati | GDPR / AI Act, argomento da pitch |
| Runtime Python | numpy, opencv-python(-headless), onnxruntime, supervision, pyyaml, pyserial; flask solo per la dashboard | Niente torch/ultralytics a runtime (peso, licenza AGPL) |

## 3. Moduli → cartelle → owner

| Area (cartella) | Owner | Moduli |
|---|---|---|
| `ai/` | Data scientist | package `ai/smartcrossing/`: sources, detector, tracking, derive, geometry, counting, attributes, animals, thermal, events, rules, logger, `app.py` (entry point), scripts di calibrazione/benchmark/probe, test |
| `firmware/` | Embedded engineer | `firmware/unoq_mcu/` (STM32 della UNO Q via Bridge), `firmware/serial_mcu/` (Arduino R4/qualsiasi, per i test da PC), fail-safe, parsing comandi, LED |
| `comms/`, `app/`, `docs/CONTRACTS.md` | Communication engineer | trasporti degli attuatori (sim, serial, bridge) in `comms/`, dashboard web headless in `app/`, log offline e sync, broadcast V2X opzionale, contratti |
| `hardware/` | Electronics engineer | schema LED, driver MOSFET, alimentazione, hub USB-C, termocamera, pinout, BOM |

Integrazione: `ai/smartcrossing/app.py` importa gli attuatori da `comms/` tramite l'interfaccia `Actuator`
definita in §4. Finché `comms/` non è pronto, `ai/` usa il proprio `SimActuator` locale.

## 4. Contratti v1 (bozza da far confermare al communication engineer e poi copiare in `docs/CONTRACTS.md`)

**C1 — Comando AI → firmware** (righe JSON, una per messaggio. Seriale a 115200 baud o argomento della chiamata Bridge):
```json
{"v":1,"seq":1842,"t_ms":1739012345678,"state":"WARN_DRIVER","led":"AMBER_BLINK_2HZ","green_s":19,"req":{"ped_green_extend_s":7,"veh_red_hold":true,"flash":false},"lcd":"PEDONE  47 km/h","oled":"ATTENDI auto 45km/h","reason":"anziano 0.8 m/s; auto 50 km/h a 60 m; TTC 4.3 s < T_need 9.8 s"}
```
- `req` = richieste alla centralina (reale o simulata): la centralina le applica solo se rispettano i suoi tempi minimi.
- `lcd` (max 2x16 caratteri) e `oled` = testi per i display verso conducenti e pedoni.
- `state` ∈ IDLE | PRESENCE | WARN_DRIVER | WARN_PEDESTRIAN | ANIMAL_WARN | ANIMAL_ALERT | DEGRADED
- `led` ∈ OFF | WHITE_ON | AMBER_BLINK_2HZ | AMBER_BLINK_4HZ | RED_GROUND_BLINK | YELLOW_FAILSAFE

**C2 — Heartbeat AI → firmware**, ogni 100 ms: `{"v":1,"hb":1843}`.
Se il firmware non riceve heartbeat per **più di 500 ms**:
- modalità `signalized` (semaforo esistente) → **annulla tutte le richieste e lascia la centralina nel ciclo normale**;
- modalità `uncontrolled` (strisce senza semaforo) → `YELLOW_FAILSAFE`.

**C3 — Eventi AI → comms/app** (JSONL su file + endpoint HTTP locale):
```json
{"v":1,"ts":1739012345.67,"type":"crossing","track_id":12,"cls":"pedestrian","attrs":{"child":false,"slow":true,"aid":null},"dir":"in","line":"ped"}
{"v":1,"ts":1739012350.10,"type":"near_miss","a":12,"b":31,"ttc_s":0.8,"pet_s":null}
{"v":1,"ts":1739012399.00,"type":"incident","kind":"person_down","track_id":12,"zone":"carriageway"}
{"v":1,"ts":1739012400.00,"type":"status","state":"PRESENCE","fps":9.6,"lat_ms":{"detect":71,"track":3,"rules":1,"act":2},"counts":{"ped_in":14,"ped_out":11,"car_in":52}}
```

**C4 — Nodo → centrale** (MQTT 5 su TLS verso AWS IoT Core, un certificato X.509 per nodo; topic `mdgb/<node_id>/events`,
`mdgb/<node_id>/agg`, `mdgb/<node_id>/hb`):
```json
{"v":1,"event_id":"nodo07-000805","node_id":"nodo07","ts":1739012345.67,"type":"crossing", "...": "campi di C3"}
{"v":1,"event_id":"nodo07-000806","node_id":"nodo07","type":"agg","t0":1739011500,"t1":1739012400,"ped":{"in":14,"out":11},"veh":{"car":52,"bike":6},"env":{"t_c":14.2,"rh":81,"lux":120},"yield_rate":0.42}
{"v":1,"node_id":"nodo07","type":"hb","ts":1739012400,"mode":"normal","link":"wifi","batt":null,"queue":0}
```
- `event_id` univoco = `node_id` + contatore **persistente** (sopravvive ai riavvii). Il server scarta gli ID già visti
  (QoS 1 = "almeno una volta" → possono arrivare doppi).
- Sul canale di backup (BLE/LoRa) passano **solo**: allarmi subito, `hb` ogni 5 min, `agg` ogni 15 min, in formato
  compatto. Gli eventi completi restano nello store & forward.

**Interfaccia Python** (in `comms/actuators.py`, con mock in `ai/`):
```python
class Actuator:
    def send(self, cmd: dict) -> None: ...      # C1
    def heartbeat(self, seq: int) -> None: ...  # C2
    def close(self) -> None: ...
# implementazioni: SimActuator (overlay), SerialActuator(port, baud), BridgeActuator (UNO Q)
```

## 5. Specifica per area

### 5.1 `ai/` — package `smartcrossing`

1. **`sources.py`**: webcam (indice), file video, RTSP. Ridimensionamento e `--max-fps`. Restituisce `(frame, t_monotonic)`.
2. **`detector.py`**:
   - YOLOX-nano ONNX. `scripts/get_model.sh` scarica `yolox_nano.onnx` dalle release ufficiali
     Megvii-BaseDetection/YOLOX (verifica l'URL) in `ai/models/` (ignorata da git).
   - Preprocess YOLOX corretto: letterbox con padding 114, BGR, **nessuna** normalizzazione.
   - Decodifica di griglie e stride in numpy, NMS.
   - Parametri: `input_size` 320/416, `conf`, `nms`, `intra_op_num_threads`, `detect_every_n` (nei frame intermedi lavora solo il tracker).
   - Classi tenute: person, bicycle, car, motorcycle, bus, truck, dog, cat, horse, sheep, cow, bear, bird.
3. **`tracking.py`**: `sv.ByteTrack` con parametri da config. Una traccia è valida dopo `min_track_age` frame (default 5).
   Storia per traccia: posizioni a terra, velocità, voti di classe.
4. **`derive.py`**:
   - ciclista = person sovrapposta a bicycle (IoU > 0,3 e box della persona sopra quello della bici);
   - motociclista analogo;
   - classe finale della traccia a maggioranza.
5. **`geometry.py`** + **`scripts/calibrate.py`**:
   - si cliccano 4 punti a terra (angoli delle strisce), si inseriscono le misure in metri e si salva l'omografia in `calib.json`;
   - nello stesso file: poligoni `waiting_zone_left/right`, `crosswalk`, `carriageway`, linee di conteggio, larghezza `W`;
   - API: pixel → metri (punto bottom-center), velocità (EMA su 5 campioni), accelerazione, altezza stimata in metri,
     lunghezza a terra in metri.
6. **`counting.py`**:
   - `ped_line` lungo le strisce (anchor BOTTOM_CENTER) e `veh_line` trasversale alla corsia;
   - `minimum_crossing_threshold` da config;
   - conteggi IN/OUT per classe;
   - ogni tracker_id contato al massimo una volta per verso.
7. **`attributes.py`** (calcolati una volta per traccia, poi memorizzati):
   - `child`: mediana dell'altezza su 5 frame < 1,30 m;
   - `slow`: velocità media nella zona d'attesa o sulle strisce < 0,9 m/s per almeno 2 s;
   - `aid`: classificatore ONNX opzionale `ai/models/aid_cls.onnx` sui ritagli person 96x96
     (normal / wheelchair / walking_aid / stroller), voto su 3–5 ritagli. Se il file manca → `None`, senza errori.
8. **`animals.py`** (§7).
9. **`thermal.py`** (§6).
10. **`events.py`** (soglie in config):
    - collisione: distanza a terra < 1 m tra due tracce, almeno una prima a > 3 m/s, poi entrambe < 0,3 m/s entro 1,5 s;
    - persona a terra: rapporto larghezza/altezza > 1,2 per più di 3 s in carreggiata;
    - frenata brusca: decelerazione > 6 m/s²;
    - near-miss: TTC < 1 s o PET < 1 s tra veicolo e pedone/animale;
    - veicolo fermo sulle strisce per più di 10 s;
    - **yield rate**: su quanti veicoli in arrivo con un pedone in zona d'attesa hanno rallentato sotto 2 m/s prima delle strisce.
11. **`rules.py`** — MACCHINA A STATI ESPLICITA, pura Python, senza OpenCV, completamente testabile:
    - `d_stop = v*1.0 + v^2/(2*7.0)`, `T_need = W/v_ped + 1.0`, `TTC = d/v`;
    - `v_ped` = 1,2 m/s di default; 0,8 se child, slow, aid oppure pedone non classificato visto solo in termico;
      se più bassa si usa la velocità misurata;
    - priorità: DEGRADED > WARN_PEDESTRIAN > ANIMAL_ALERT > WARN_DRIVER > ANIMAL_WARN > PRESENCE > IDLE;
    - WARN_DRIVER: pedone con intenzione (in zona d'attesa da più di 1 s, oppure in movimento verso la carreggiata),
      TTC < T_need e d > d_stop + 10;
    - WARN_PEDESTRIAN: d ≤ d_stop + 10 e il veicolo non decelera (a > −2 m/s²);
    - estensione del verde: `green_s = min(25, max(W/1.2, W/v_ped) + 2)`;
    - DEGRADED: la sorgente video non arriva da più di 1 s, oppure l'autodiagnosi fallisce
      (varianza del Laplaciano sotto soglia = lente coperta; istogramma saturo = abbagliamento);
    - output: un dict conforme a C1, con `reason` leggibile.
12. **`logger.py`**: eventi C3 in JSONL con rotazione, funziona offline. Mai frame.
13. **`app.py`**: `python -m smartcrossing.app --source 0|file.mp4|rtsp://… --profile pc|unoq --site urbano|lungofiume|collina [--headless] [--emulate-unoq] [--actuator sim|serial|bridge] [--thermal none|uvc|mlx90640]`.
    - Overlay: box, ID, classe, attributi, velocità in km/h, zone, linee e conteggi, stato con `reason`,
      FPS e ms per fase (detect/track/rules/act).
    - `--emulate-unoq`: 10 FPS, input 320, onnxruntime con 4 thread.
    - `--headless`: nessuna finestra; pubblica C3 per la dashboard di `app/`.
14. **Script**:
    - `scripts/bench.py`: ms medi e p95 per fase su un video, stampa una tabella;
    - `scripts/animal_probe.py <cartella>`: classe COCO e confidenza migliori per immagine, più il recall "almeno un animale".

### 5.2 `firmware/`

- `serial_mcu/serial_mcu.ino` (UNO R4 o qualsiasi Arduino) e `unoq_mcu/` (STM32 della UNO Q via Bridge: verifica le API
  ufficiali di App Lab, cioè la libreria Bridge lato sketch e lato Python).
- Parsing di C1 e C2. Mappa `led` → pin, con i pin in `pins.h` presi dalla sezione Pinout di CONTRACTS.md.
- **Centralina simulata** (`signal_controller`): ciclo veicoli verde 20 s → giallo 3 s → rosso, omino pedonale
  verde/rosso, chiamata pedonale (Grove Touch). Applica le `req` di C1 **solo** entro limiti fissi:
  estensione del verde pedonale ≤ 15 s, rosso veicolare trattenuto ≤ 20 s, verde veicolare minimo 8 s.
  I limiti sono costanti nel firmware, non configurabili da Linux.
- **Fail-safe locale**: niente heartbeat per più di 500 ms → in `signalized` si annullano le richieste e la centralina
  torna al ciclo normale; in `uncontrolled` → `YELLOW_FAILSAFE` (giallo a 1 Hz). Watchdog hardware.
  Al boot: ciclo normale (o giallo) finché non arriva il primo heartbeat.
- Display: LCD 16x2 (conducenti) e OLED (pedoni) mostrano i testi `lcd`/`oled` di C1; senza heartbeat mostrano
  solo il ciclo normale / il conto alla rovescia.
- Sensori ambientali (AHT20 temperatura/umidità, sensore di luce, Modulino Movement): letti dal MCU ogni 10 s e
  inoltrati a Linux via Bridge per gli aggregati C4.
- **Secondo percorso di sicurezza (indipendente dalla visione)**: Grove PIR + Modulino Distance (ToF, circa 1,3 m)
  letti direttamente dal MCU. Se rilevano un pedone in zona d'attesa mentre la visione è in DEGRADED o non ci sono
  heartbeat → `AMBER_BLINK_2HZ` invece del semplice giallo.
- **Monitoraggio della lampada**: Grove ACS70331 sulla linea 5 V delle strip WS2813. Per ogni pattern c'è una corrente
  attesa; se si scosta di oltre ±30% → si invia all'AI/comms un evento `lamp_fault` (estendere C3) e si passa in fail-safe.
- Modulino Movement: un urto o un'inclinazione oltre soglia → evento `tamper` (la calibrazione non vale più → DEGRADED).
- LED: Grove WS2813 strip ×2 (veicoli / a terra) + RGB LED Ring 16 (lanterna pedonale), luminosità limitata via software.
- Pannello verso i veicoli: Grove LCD 16x2 (testo breve + velocità).

### 5.3 `comms/` e `app/`

Principio: **la sicurezza è locale, i dati non si perdono mai, il nodo resta visibile anche quando la rete cade.**

- `comms/actuators.py`: `SimActuator`, `SerialActuator` (pyserial, riconnessione automatica), `BridgeActuator`.
- **Canale principale**: MQTT 5 su TLS verso AWS IoT Core via Wi-Fi 2,4 GHz, un certificato per nodo
  (revocabile singolarmente). QoS 1. Solo metadati anonimi (C4), mai immagini.
- **Store & forward**: ogni evento si scrive su disco (es. SQLite) **prima** dell'invio e si cancella solo dopo il
  PUBACK di AWS. Al ritorno della rete la coda si svuota da sola; il server deduplica per `event_id`.
  Se esiste già codice testato (test 806/806 eventi), va integrato qui senza riscriverlo.
- **Failover**: nessun PUBACK per 30 s → passaggio al backup. **Ritorno al Wi-Fi solo dopo 60 s di conferme
  regolari** (isteresi: niente salti continui tra i canali).
- **Backup**: BLE nel prototipo (il laptop della demo = centrale), LoRa verso un gateway della centrale in produzione
  (nessuna dipendenza da internet; regola dell'1% di duty cycle a 868 MHz → solo allarmi, hb, agg).
  Si cambia con un'impostazione (`backup: ble|lora`).
- **Diagnosi in centrale**: MQTT ❌ + backup ✅ → rete giù, nodo sano; autodiagnosi fallita → nodo guasto;
  entrambi ❌ dopo batteria in calo → batteria scarica; entrambi ❌ dopo un evento IMU/apertura del case → manomissione.
- `app/`: dashboard della centrale: mappa/stato dei nodi, canale attivo, coda dello store & forward, conteggi per
  classe e direzione, yield rate, near-miss, allarmi, dati ambientali. Stream MJPEG **solo** live, solo in locale e
  solo se abilitato.
- **Server (stretch, dopo la demo base)**: storico degli aggregati + modello di previsione degli afflussi
  (es. gradient boosting su ora, giorno, meteo, eventi) in `ai/forecast/`. All'hackathon non c'è storico: si mostra
  la pipeline con dati simulati, dichiarandolo. API esterne (meteo, Google Maps Platform, Copernicus) opzionali,
  dietro una chiave in `.env`, mai indispensabili.
- Stretch V2X: broadcast UDP o ESP-NOW di un messaggio "VAM-like" (posizione, classe, direzione del pedone) verso un
  secondo device che fa da "cruscotto auto" e mostra "PEDONE NASCOSTO A X m". Misura la latenza end-to-end.

### 5.4 `hardware/`

- Semaforo del plastico: lanterne veicoli (rosso/giallo/verde) e pedonale (omino rosso/verde) con strip/ring WS2813;
  lampeggiante ambra; driver MOSFET; alimentazione 5 V separata per i LED.
- Display: LCD 16x2 (verso i conducenti) e OLED (verso i pedoni); pulsante di chiamata (Grove Touch).
- Sensori ambientali: AHT20, sensore di luce, Modulino Movement.
- Hub USB-C alimentato per la webcam (e per la termocamera UVC).
- Termocamera (§6): Grove MLX90621 16x4 (disponibile). Componenti e priorità: `hardware/BOM.md`.
- Pinout in `docs/CONTRACTS.md`, BOM, export PNG/PDF dello schema.

## 6. Notte: termocamera (opzionale, attivabile con `--thermal`)

Motivazione: dopo il ritorno all'ora solare (25/10) il buio arriva in ora di punta. Con poca luce la camera RGB
perde i pedoni scuri. La termocamera vede il calore e, in più, **non permette di riconoscere nessuno** (privacy).

Due opzioni hardware, stessa interfaccia `ThermalSource.read() -> (temp_or_gray_frame, t)`:

| Opzione | Risoluzione | Cosa ci si fa | Note |
|---|---|---|---|
| **A0. Grove MLX90621 (16x4, FOV 60°x16°) — QUELLA DISPONIBILE** | A 4 m ogni colonna copre circa 29 cm: una persona occupa circa 2 colonne | **Striscia di calore lungo il cordolo**: per ogni colonna, presenza se T > ambiente + 3 °C; la zona d'attesa = un insieme di colonne | Niente blob 2D né classificazione. Lettura I2C dal MCU, inoltrata via Bridge come array di 64 temperature |
| **A. MLX90640** (I2C, 32x24, FOV 55°x35° o 110°x75°) — non disponibile | Una persona a 8 m occupa circa 8 px di altezza; un cinghiale circa 4 px | **Solo presenza per zona**: blob sopra la soglia di temperatura (es. > ambiente + 4 °C), area minima, tracking dei centroidi | Economica. Niente YOLO. Lettura da Linux via I2C oppure dal MCU e poi Bridge (verifica cosa è più semplice sulla UNO Q) |
| **B. Termocamera UVC** (es. 256x192) | Persona a 8 m: decine di px | Detector su immagine termica: pesi YOLO-Thermal / dataset TD4PWMR, oppure fine-tuning su FLIR ADAS (verifica licenze) | Si vede come una webcam con OpenCV: verifica che il modello scelto sia UVC |

Logica di fusione (`thermal.py`):
- **Modalità notte**: luminanza media del frame RGB < soglia per più di 5 s (oppure fotoresistenza via MCU).
- **Recupero**: blob termico in zona d'attesa o sulle strisce **senza** detection RGB per almeno 0,5 s
  → traccia "pedone non classificato" con `v_ped` = 0,8 (in dubbio si protegge di più).
- **Conferma**: una detection RGB "person" con blob termico sovrapposto aumenta la confidenza;
  una "person" senza calore in modalità notte (riflesso, manifesto) la diminuisce.
- **Zone del termico**: poligoni disegnati direttamente sull'immagine termica in `calib_thermal.json` (niente omografia completa).
- Test con frame sintetici (array numpy con blob caldi).

## 7. Animali

- Classe `animal` = dog, cat, horse, sheep, cow, bear. Conserva la classe COCO originale nei log.
  `bird` vale **solo** se a terra in carreggiata, lunghezza ≥ 0,5 m (oca o cigno, non piccione) e presente da più di 2 s.
- **Cane al guinzaglio**: animale con una persona entro 2,0 m a terra e direzione di moto simile (< 45°) per almeno 1 s
  → stesso `group_id`, nessun allarme proprio (valgono le regole del pedone).
- **Taglia** dall'omografia:
  - `large` = lunghezza ≥ 0,8 m o altezza ≥ 0,6 m;
  - `medium` = 0,3–0,8 m;
  - `small` < 0,3 m (solo log: ricci, scoiattoli e gatti lontani sono fuori portata della camera).
- **Branco**: animali entro 3 m → stesso `herd_id`. L'allerta resta attiva finché l'ultimo membro è in carreggiata, +2 s.
- Stati:
  - `large` libero in carreggiata → ANIMAL_ALERT (`AMBER_BLINK_4HZ`), anche senza veicoli;
  - `medium` libero → ANIMAL_WARN solo se c'è un veicolo con d < d_stop + margine (30 m, 40 m nel profilo `collina`).
  - **Nessun segnale acustico** verso gli animali.
- Profili `--site`:
  - `urbano`: pedoni e cani, bird escluso;
  - `lungofiume`: + uccelli grandi a terra;
  - `collina`: + ungulati e branchi, soglie notturne più sensibili, termico consigliato.
- `scripts/animal_probe.py` serve a decidere se fare fine-tuning: se il recall "almeno un animale" sulle foto di
  cinghiale e capriolo supera il 70%, niente training.

## 8. Test (pytest, devono passare su PC senza hardware)

- rules: anziano (0,8 m/s), W = 7 m, auto a 50 km/h (13,9 m/s) a 60 m → WARN_DRIVER (T_need 9,75 s, TTC 4,3 s, d_stop 27,7 m);
  stessa auto a 25 m senza decelerazione → WARN_PEDESTRIAN; nessun veicolo → PRESENCE; video assente per 1,5 s → DEGRADED.
- green: W = 12 m, v_ped = 0,7 → 19,1 s; v_ped = 0,3 → 25 s (tetto massimo).
- counting: una traccia che oscilla sulla linea non genera doppi conteggi; un attraversamento reale conta 1 nel verso giusto.
- geometry: con un'omografia nota, la conversione pixel→metri rientra nella tolleranza.
- events: tracce sintetiche di collisione, persona a terra e frenata brusca generano l'evento giusto.
- animals: cinghiale di 1,2 m in carreggiata → ANIMAL_ALERT; gatto di 0,25 m → solo log; cane a 1,5 m da una persona
  → nessun allarme; branco di 3 → l'allerta resta attiva finché esce l'ultimo.
- thermal: blob caldo in zona d'attesa senza detection RGB per 0,6 s in modalità notte → pedone non classificato con v_ped = 0,8.
- firmware (se possibile, test su host): parser C1/C2 e timeout dell'heartbeat.

## 9. Milestone (per area; ognuna chiude con commit, PR e messaggio al team)

**ai/**
- AI-M1: source + detector + tracker + overlay su un video → box e ID stabili; `bench.py`.
- AI-M2: counting + derive (ciclista) → conteggi IN/OUT corretti, senza doppioni.
- AI-M3: calibrazione + velocità + attributes + rules + SimActuator → la demo completa gira sul PC (`--emulate-unoq`).
- AI-M4: events + animals + logger + output C3.
- AI-M5: thermal (prima MLX90640 simulata, poi l'hardware reale se disponibile).
- AI-M6: profilo `unoq`, test sulla scheda, numeri del benchmark nel README.

**firmware/**
- FW-M1: `serial_mcu` con centralina simulata, parser C1/C2, LED, display e fail-safe, testato da PC con `SerialActuator`.
- FW-M2: `unoq_mcu` via Bridge, stesso comportamento.
- FW-M3: sensori (PIR, ToF, AHT20, luce, IMU, ACS70331) + secondo percorso di sicurezza + monitoraggio della lampada.

**comms/ + app/**
- CM-M1: CONTRACTS.md v1 (da §4) + `actuators.py` (sim/serial).
- CM-M2: MQTT/AWS IoT Core + store & forward (integrando il codice già testato) + dedup lato server.
- CM-M3: failover BLE con isteresi + diagnosi + dashboard della centrale.
- CM-M4: BridgeActuator.
- CM-M5 (stretch): V2X "pedone nascosto" verso uno smartphone; pipeline di previsione con dati simulati.

**hardware/**
- HW-M1: pinout + schema dei LED + BOM.
- HW-M2: termocamera + hub + case (stampa 3D).

## 10. Deploy sulla UNO Q (`ai/docs/DEPLOY_UNOQ.md`, lo scrive il data scientist con l'embedded)

ssh sulla scheda; `python3 -m venv ~/venv` (il pip di sistema è bloccato); `pip install -r ai/requirements.txt`
(versione headless di OpenCV); copia di `models/` e `calib.json`; webcam tramite hub USB-C alimentato;
servizio systemd per l'avvio automatico; caricamento del firmware sull'STM32; verifica del Bridge.
Alla fine: la lista di cosa resta da verificare sull'hardware reale.
In alternativa, se App Lab risulta più semplice: packaging come app App Lab (verifica la documentazione).

## 11. Checklist della demo (domenica entro le 14)

- [ ] Video notturno e diurno di un attraversamento: conteggi corretti mostrati a schermo.
- [ ] Scenario anziano + auto veloce: WARN_DRIVER con la `reason` visibile, poi WARN_PEDESTRIAN.
- [ ] **Kill test visione**: si chiude il processo AI → entro 0,5 s il semaforo torna al ciclo normale (o al giallo
      lampeggiante senza semaforo), e PIR/ToF continuano a vedere il pedone.
- [ ] **Kill test rete**: si spegne il Wi-Fi → dopo 30 s il nodo passa al BLE e la dashboard mostra "rete giù, nodo sano";
      si riaccende → la coda si svuota, eventi inviati = ricevuti.
- [ ] Verde pedonale esteso e rosso veicolare trattenuto visibili sul semaforo del plastico, con i testi su LCD/OLED.
- [ ] Verde esteso per un pedone lento, con il calcolo mostrato.
- [ ] Animale libero vs cane al guinzaglio.
- [ ] Numeri a schermo: FPS, ms per fase, yield rate, near-miss.
- [ ] Nessun frame salvato su disco (da dire nel pitch).
