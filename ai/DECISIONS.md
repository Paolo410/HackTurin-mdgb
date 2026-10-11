# ai/ — decisioni, numeri e interfacce

Owner: Paolo Malugani (data scientist). Estratto da `PROMPT_SMART_CROSSING.md` (i § rimandano a quel file).
Se questo file e la specifica divergono, vale la specifica; se la specifica e `docs/CONTRACTS.md` divergono, vale `CONTRACTS.md`.

## 1. Decisioni prese

| Tema | Decisione | Fonte |
|---|---|---|
| Detector | YOLOX-nano COCO in ONNX (Apache-2.0), eseguito con onnxruntime. Input 320, 416 opzionale | §2 |
| Tracking | `supervision.ByteTrack` | §2 |
| Conteggio per direzione | `supervision.LineZone` con `minimum_crossing_threshold` + età minima della traccia. Ogni ID conta al massimo una volta per verso | §2, §5.1.6 |
| Tipo di pedone | Cascata: detector COCO generico, poi attributi calcolati una volta per traccia | §2 |
| Bambino | Altezza in metri dall'omografia. Nessun modello | §2 |
| Anziano / lento | Velocità di camminata misurata. Non si stima l'età | §2 |
| Ausili (carrozzina, deambulatore, passeggino) | Classificatore ONNX opzionale sui ritagli 96x96, addestrato a parte. Se il file manca `aid = None` e il sistema funziona lo stesso | §2, §5.1.7 |
| Ciclista / motociclista | Derivati: persona sovrapposta a bicycle/motorcycle. Classe finale della traccia a maggioranza | §5.1.4 |
| Incidenti | Regole sulle traiettorie, nessun modello video | §2 |
| Sicurezza | Regola fisica (TTC, distanza d'arresto) in `rules.py` + fail-safe nel firmware via heartbeat. La sicurezza non dipende da Linux | §2 |
| Regole | `rules.py` è una macchina a stati esplicita in puro Python, senza OpenCV, testabile. Produce un dict conforme a C1 con `reason` leggibile | §5.1.11 |
| Privacy | Mai salvare frame su disco: solo metadati | §2, §5.1.12 |
| Dipendenze a runtime | numpy, opencv-python(-headless), onnxruntime, supervision, pyyaml, pyserial. Niente torch/ultralytics (peso, licenza AGPL) | §2 |
| Portabilità | Lo stesso codice Python gira su PC (macOS Apple Silicon, Linux) e su UNO Q (Debian aarch64) | §1 |
| Notte | Termocamera opzionale (`--thermal`). Hardware disponibile: Grove MLX90621 16x4 → striscia di calore lungo il cordolo, presenza per colonna. Niente blob 2D, niente classificazione | §6 |
| Animali | `animal` = dog, cat, horse, sheep, cow, bear; la classe COCO originale resta nei log. Nessun segnale acustico verso gli animali | §7 |
| Fine-tuning animali | Si decide con `scripts/animal_probe.py`: recall "almeno un animale" > 70% su cinghiale e capriolo → niente training | §7 |
| Test | pytest, devono passare su PC senza hardware | §8 |
| API esterne | Nessuna API inventata: documentazione ufficiale linkata nel commento, altrimenti stub + `TODO(verify)` | §0 |
| Lingua | Commenti nel codice in inglese | riga 16 |

Ordine di lavoro (§9): AI-M1 source + detector + tracker + overlay + `bench.py` → AI-M2 counting + derive →
AI-M3 calibrazione + velocità + attributes + rules + SimActuator (demo completa su PC con `--emulate-unoq`) →
AI-M4 events + animals + logger + output C3 → AI-M5 thermal → AI-M6 profilo `unoq`, test sulla scheda, benchmark nel README.

Vincoli di lavoro (dal brief di sessione di Paolo, non dalla specifica):
- ogni dipendenza deve avere la wheel aarch64;
- tutte le soglie in `config.yaml`, nessun numero nel codice;
- `requirements.txt` in `ai/` con versioni fissate;
- video di test in `ai/samples/` (ignorata da git), altrimenti webcam;
- ogni prova si ripete con `--emulate-unoq`, riportando FPS e ms per fase.

## 2. Parametri e numeri

Tutti finiscono in `config.yaml`. "n.s." = valore non specificato, vedi §6 di questo file.

### Prestazioni
| Parametro | Valore | Fonte |
|---|---|---|
| Obiettivo sulla UNO Q | ≥ 8 FPS end-to-end a 320 px | §1 |
| `--emulate-unoq` | 10 FPS, input 320, onnxruntime con 4 thread | §5.1.13 |
| Riferimenti noti sulla UNO Q | YOLOv8n 640 px con OpenCV DNN 1–2 FPS; yolox-nano di App Lab circa 10 FPS; YOLOv5-pico Edge Impulse 224 px circa 17 FPS | §1 |
| UNO Q | 4x Cortex-A53 a 2,0 GHz, nessuna NPU, 2/4 GB di RAM | §1 |

### Detector e tracking
| Parametro | Valore | Fonte |
|---|---|---|
| `input_size` | 320 (416 opzionale) | §5.1.2 |
| Preprocess | letterbox con padding 114, BGR, nessuna normalizzazione | §5.1.2 |
| Classi tenute | person, bicycle, car, motorcycle, bus, truck, dog, cat, horse, sheep, cow, bear, bird | §5.1.2 |
| `conf`, `nms`, `intra_op_num_threads`, `detect_every_n` | n.s. | §5.1.2 |
| `min_track_age` | 5 frame | §5.1.3 |
| Parametri ByteTrack | n.s. | §5.1.3 |
| Ciclista | IoU persona/bici > 0,3 e box della persona sopra quello della bici | §5.1.4 |

### Geometria e conteggio
| Parametro | Valore | Fonte |
|---|---|---|
| Calibrazione | 4 punti a terra (angoli delle strisce) + misure in metri → omografia in `calib.json` | §5.1.5 |
| Contenuto di `calib.json` | omografia, poligoni `waiting_zone_left/right`, `crosswalk`, `carriageway`, linee di conteggio, larghezza `W` | §5.1.5 |
| Punto di riferimento | bottom-center del box | §5.1.5 |
| Velocità | EMA su 5 campioni | §5.1.5 |
| Linee | `ped_line` lungo le strisce, `veh_line` trasversale alla corsia | §5.1.6 |
| `minimum_crossing_threshold` | n.s. | §5.1.6 |

### Attributi del pedone
| Attributo | Regola | Fonte |
|---|---|---|
| `child` | mediana dell'altezza su 5 frame < 1,30 m | §5.1.7 |
| `slow` | velocità media in zona d'attesa o sulle strisce < 0,9 m/s per almeno 2 s | §5.1.7 |
| `aid` | classi normal / wheelchair / walking_aid / stroller, ritagli 96x96, voto su 3–5 ritagli | §5.1.7 |

### Regole (`rules.py`)
| Grandezza | Formula o valore | Fonte |
|---|---|---|
| Distanza d'arresto | `d_stop = v*1.0 + v^2/(2*7.0)` (reazione 1,0 s, decelerazione 7,0 m/s²) | §5.1.11 |
| Tempo necessario al pedone | `T_need = W/v_ped + 1.0` | §5.1.11 |
| Tempo alla collisione | `TTC = d/v` | §5.1.11 |
| `v_ped` | 1,2 m/s di default; 0,8 se child, slow, aid o pedone visto solo in termico; se più bassa, la velocità misurata | §5.1.11 |
| Priorità degli stati | DEGRADED > WARN_PEDESTRIAN > ANIMAL_ALERT > WARN_DRIVER > ANIMAL_WARN > PRESENCE > IDLE | §5.1.11 |
| Intenzione del pedone | in zona d'attesa da più di 1 s, oppure in movimento verso la carreggiata | §5.1.11 |
| WARN_DRIVER | intenzione + `TTC < T_need` + `d > d_stop + 10` | §5.1.11 |
| WARN_PEDESTRIAN | `d ≤ d_stop + 10` e veicolo che non decelera (`a > −2 m/s²`) | §5.1.11 |
| Verde pedonale | `green_s = min(25, max(W/1.2, W/v_ped) + 2)` | §5.1.11 |
| DEGRADED | video assente da più di 1 s, oppure autodiagnosi fallita (varianza del Laplaciano sotto soglia, istogramma saturo) | §5.1.11 |
| Soglie dell'autodiagnosi | n.s. | §5.1.11 |

Valori di controllo dei test (§8): anziano 0,8 m/s, W = 7 m, auto a 13,9 m/s a 60 m → T_need 9,75 s, TTC 4,3 s,
d_stop 27,7 m → WARN_DRIVER; stessa auto a 25 m senza decelerazione → WARN_PEDESTRIAN; W = 12 m con v_ped 0,7 → 19,1 s;
con v_ped 0,3 → 25 s.

### Eventi (`events.py`)
| Evento | Regola | Fonte |
|---|---|---|
| Collisione | distanza a terra < 1 m tra due tracce, almeno una prima a > 3 m/s, poi entrambe < 0,3 m/s entro 1,5 s | §5.1.10 |
| Persona a terra | larghezza/altezza > 1,2 per più di 3 s in carreggiata | §5.1.10 |
| Frenata brusca | decelerazione > 6 m/s² | §5.1.10 |
| Near-miss | TTC < 1 s o PET < 1 s tra veicolo e pedone/animale | §5.1.10 |
| Veicolo fermo sulle strisce | più di 10 s | §5.1.10 |
| Yield rate | quota di veicoli che, con un pedone in zona d'attesa, rallentano sotto 2 m/s prima delle strisce | §5.1.10 |

### Animali
| Parametro | Valore | Fonte |
|---|---|---|
| `bird` | vale solo a terra in carreggiata, lunghezza ≥ 0,5 m, presente da più di 2 s | §7 |
| Cane al guinzaglio | persona entro 2,0 m a terra, direzione simile (< 45°) per almeno 1 s → stesso `group_id`, nessun allarme proprio | §7 |
| Taglia | `large` lunghezza ≥ 0,8 m o altezza ≥ 0,6 m; `medium` 0,3–0,8 m; `small` < 0,3 m (solo log) | §7 |
| Branco | animali entro 3 m → stesso `herd_id`; allerta attiva fino all'uscita dell'ultimo, +2 s | §7 |
| `large` libero in carreggiata | ANIMAL_ALERT (`AMBER_BLINK_4HZ`), anche senza veicoli | §7 |
| `medium` libero | ANIMAL_WARN solo con un veicolo a `d < d_stop + margine`; margine 30 m, 40 m nel profilo `collina` | §7 |
| Profili `--site` | `urbano` pedoni e cani, bird escluso; `lungofiume` + uccelli grandi a terra; `collina` + ungulati e branchi, soglie notturne più sensibili | §7 |

### Termocamera
| Parametro | Valore | Fonte |
|---|---|---|
| Sensore disponibile | Grove MLX90621, 16x4, FOV 60°x16° | §6 |
| Risoluzione a terra | a 4 m ogni colonna copre circa 29 cm; una persona occupa circa 2 colonne | §6 |
| Presenza per colonna | T > ambiente + 3 °C; la zona d'attesa è un insieme di colonne | §6 |
| Lettura | I2C dal MCU, inoltrata via Bridge come array di 64 temperature | §6 |
| Modalità notte | luminanza media del frame RGB sotto soglia per più di 5 s, oppure fotoresistenza via MCU. Soglia n.s. | §6 |
| Recupero | calore in zona d'attesa o sulle strisce senza detection RGB per almeno 0,5 s → "pedone non classificato" con v_ped 0,8 | §6 |
| Conferma | person RGB con calore sovrapposto → confidenza su; person senza calore in modalità notte → confidenza giù | §6 |
| Zone | disegnate sull'immagine termica in `calib_thermal.json`, senza omografia completa | §6 |

### Contratti (bozza §4)
| Parametro | Valore | Fonte |
|---|---|---|
| C1 | una riga JSON per messaggio: `v`, `seq`, `t_ms`, `state`, `led`, `green_s`, `req`, `lcd`, `oled`, `reason` | §4 |
| `req` | `ped_green_extend_s`, `veh_red_hold`, `flash`; in più `veh_red_now`, aggiunto l'11/10 (punto 31), da confermare con Lorenzo | §4 |
| `lcd` | massimo 2x16 caratteri | §4 |
| Seriale | 115200 baud | §4 |
| C2 heartbeat | ogni 100 ms; il firmware va in fail-safe dopo più di 500 ms senza | §4 |
| Limiti della centralina sulle `req` | estensione del verde pedonale ≤ 15 s, rosso veicolare trattenuto ≤ 20 s, verde veicolare minimo 8 s (costanti nel firmware) | §5.2 |
| C3 | eventi `crossing`, `near_miss`, `incident`, `status` in JSONL su file + endpoint HTTP locale | §4 |

## 3. Codice esistente

- In `ai/` non c'è ancora codice: la cartella nasce con questo file.
- Componenti riusati, non scritti da noi: pesi YOLOX-nano COCO in ONNX dalle release ufficiali
  Megvii-BaseDetection/YOLOX (URL da verificare, §5.1.2); `supervision` per ByteTrack e LineZone (§2).
- La specifica cita codice già testato solo per lo store & forward di `comms/` (806/806 eventi, §5.3): non è di `ai/`.

## 4. Cosa mi serve dagli altri

| Da chi | Cosa | Per quale milestone | Fonte |
|---|---|---|---|
| Lorenzo (comms) | Conferma dei contratti di §4 e `docs/CONTRACTS.md` v1 | AI-M3 (C1/C2), AI-M4 (C3) | §4, CM-M1 |
| Lorenzo (comms) | `comms/actuators.py` con l'interfaccia `Actuator` (sim, serial; bridge in CM-M4). Fino ad allora uso un `SimActuator` locale | AI-M3 in poi | §3, §4 |
| Salvatore (firmware) | Parser C1/C2 e fail-safe (FW-M1) per provare `rules.py` su LED e display veri | dopo AI-M3 | §5.2 |
| Salvatore (firmware) | Inoltro via Bridge dell'array di 64 temperature della MLX90621; lettura della luce; evento `tamper` | AI-M5 | §5.2, §6 |
| Salvatore (firmware) | Lavoro a quattro mani su `ai/docs/DEPLOY_UNOQ.md` e prova sulla scheda | AI-M6 | §10 |
| Kuzey (hardware) | Camera funzionante sulla UNO Q e hub USB-C alimentato se si usa la webcam | AI-M6 | §1, §5.4 |
| Kuzey (hardware) | Termocamera MLX90621 montata, con posizione e orientamento rispetto al cordolo | AI-M5 | §5.4, §6 |

## 5. Cosa fornisco agli altri

| A chi | Cosa | Fonte |
|---|---|---|
| Salvatore (firmware) | Comandi C1 generati da `rules.py` (`state`, `led`, `green_s`, `req`, `lcd`, `oled`, `reason`) e heartbeat C2 ogni 100 ms, inviati tramite `Actuator` | §4, §5.1.11 |
| Lorenzo (comms/app) | Eventi C3 (`crossing`, `near_miss`, `incident`, `status` con FPS, ms per fase e conteggi) in JSONL; modalità `--headless` per la dashboard | §4, §5.1.12–13 |
| Tutti | Entry point `python -m smartcrossing.app` con `--source`, `--profile`, `--site`, `--headless`, `--emulate-unoq`, `--actuator`, `--thermal` | §5.1.13 |
| Tutti | Script: `calibrate.py` (omografia e zone), `bench.py` (ms medi e p95 per fase), `animal_probe.py`, `get_model.sh` | §5.1 |
| Salvatore (firmware) | `ai/docs/DEPLOY_UNOQ.md`, scritto insieme | §10 |
| Pitch | Numeri a schermo: FPS, ms per fase, yield rate, near-miss; benchmark sulla scheda nel README | §9, §11 |
| Lorenzo (stretch) | Pipeline di previsione degli afflussi con dati simulati in `ai/forecast/` | §5.3 |

## 6. Questioni aperte

1. **Camera sulla UNO Q.** La specifica prevede webcam USB, file o RTSP (§5.1.1). `hardware/BOM.md` indica come
   camera principale la Sony IMX219 su Media Carrier (CSI), con la webcam USB come piano B. Va capito come si legge
   la IMX219 da Python sulla scheda. Per Kuzey e Salvatore. Non blocca AI-M1…M5 su PC.
   **Chiusa il 10/10 (punto 32):** la scheda monta la IMX219; si apre con `libcamerify`.
2. **Valore di `--thermal`.** L'opzione prevede `none|uvc|mlx90640` (§5.1.13) e AI-M5 parla di "MLX90640 simulata",
   ma il sensore disponibile è la MLX90621 16x4 (§6). Serve il valore `mlx90621` e un simulatore 16x4. Anche il test
   di §8 parla di "blob caldo", che con 4 righe diventa "colonne calde".
3. **Dati dal MCU verso Linux.** In §4 non c'è un contratto per: array termico, luce, `tamper`, `lamp_fault`
   (§5.2 dice "estendere C3"). Servono a `thermal.py` e allo stato DEGRADED. Per Lorenzo e Salvatore.
4. **Come si calcola `req`.** La specifica dà `green_s` ma non dice come ricavare `ped_green_extend_s` (manca la
   durata base del verde pedonale della centralina) né quando valgono `veh_red_hold` e `flash`. Per Salvatore e Lorenzo.
   **Deciso da Paolo il 10/10 (punto 31).**
5. **Testi di `lcd` e `oled`.** Ci sono solo due esempi (§1, §4). Manca il testo per ogni stato, e quale velocità
   compare in "PEDONE 47 km/h".
6. **Trasporto di C3.** "JSONL su file + endpoint HTTP locale" (§4): non è scritto chi espone l'endpoint. Flask è
   previsto solo per la dashboard (§2). Per Lorenzo.
7. **Pedone visto solo in termico.** Non è definito come compare in C3 (valore di `cls`). Per Lorenzo.
8. **Valori non specificati**, da scegliere e mettere in `config.yaml`: `conf`, `nms`, thread di onnxruntime su PC,
   `detect_every_n`, parametri ByteTrack, `minimum_crossing_threshold`, soglie dell'autodiagnosi, soglia di luminanza
   della modalità notte.
9. **Versione di Python sulla UNO Q.** La specifica non la indica; decide quali versioni fissare in `requirements.txt`.
   Da leggere sulla scheda. Per Salvatore.
10. **Misure dell'attraversamento.** La calibrazione chiede 4 punti con le misure in metri e la larghezza `W` (§5.1.5):
    non è scritto chi le fornisce per il plastico.
11. **Esempio di C1 in §4.** `green_s: 19` non corrisponde allo scenario della sua `reason` (W = 7 m e v_ped 0,8 danno
    10,75 s). È solo illustrativo: fanno fede i valori dei test di §8.
12. **`docs/CONTRACTS.md` non esiste ancora.** Finché Lorenzo non lo pubblica, `ai/` lavora contro la bozza di §4.
13. **Input a 320 px: risolto.** Il modello ufficiale dichiara un input fisso a 416 px, ma la rete non ha dimensioni
    fisse al suo interno. `scripts/make_dynamic_model.py` ne crea una copia a input libero (stessi pesi, output
    identico a 416 px). Il default è ora 320 px, come da specifica; il 416 resta disponibile da `config.yaml`.
14. **`sv.ByteTrack` è deprecato** in supervision e sparisce dalla 0.31. Con la versione fissata (0.30.5) funziona:
    il pin non va alzato senza cambiare tracker.
15. **Valori scelti in AI-M1** per i parametri non specificati (punto 8), tutti in `config.yaml` e da tarare su un
    video reale: `conf` 0,30, `nms` 0,45, `detect_every_n` 1, parametri ByteTrack ai default di supervision con
    soglia di attivazione 0,30. In più `nms_cross_class` 0,85: due box di classi diverse quasi coincidenti sono lo
    stesso oggetto, resta il punteggio migliore (persona e bici sovrapposte restano entrambe).
16. **Scelte di AI-M2**, tutte in `config.yaml`:
    - `minimum_crossing_threshold` 3 frame;
    - nomi dei ruoli allineati alla bozza di `docs/CONTRACTS.md` di Lorenzo (`pedestrian`, `cyclist`,
      `motorcyclist`, `car`, `bus`, `truck`, `animal`, `bird`);
    - linea `ped`: `pedestrian`, `cyclist`, `animal`; linea `veh`: `car`, `bus`, `truck`, `motorcyclist`, `cyclist`;
    - una bici o una moto senza persona riconosciuta sopra non viene contata;
    - le linee stanno in `calib.json` in coordinate normalizzate (0–1), così non dipendono dalla risoluzione.
17. **Scelte di AI-M3 da confermare con Salvatore e Lorenzo** (rispondono ai punti 4 e 5). Sono in `config.yaml`
    (`rules`) e in `rules.py`:
    - lampada per stato: IDLE `OFF`, PRESENCE `WHITE_ON`, WARN_DRIVER `AMBER_BLINK_2HZ`, WARN_PEDESTRIAN
      `RED_GROUND_BLINK`, ANIMAL_WARN `AMBER_BLINK_2HZ`, ANIMAL_ALERT `AMBER_BLINK_4HZ`, DEGRADED `YELLOW_FAILSAFE`;
    - `ped_green_extend_s` = `green_s` meno il verde standard `W/1,2 + 2`, arrotondato, al massimo 15 s
      (con W = 12 m e 0,7 m/s dà 19 s e +7 s, come l'esempio di §4);
    - `veh_red_hold` vero in WARN_DRIVER, in WARN_PEDESTRIAN e finché c'è qualcuno sulle strisce
      (**superato dal punto 31**: ora solo per chi ha bisogno di tempo, bambino solo o animale);
    - `flash` vero solo in ANIMAL_ALERT;
    - `lcd` su due righe da 16 caratteri ASCII: `PEDONE / IN ATTESA`, `PEDONE / SULLE STRISCE`,
      `PEDONE  47 km/h / RALLENTA`, `FRENA!  47 km/h / PEDONE`; la velocità è quella del veicolo in arrivo;
    - `oled`: `TEMPO VERDE 11 s` in PRESENCE, `ATTENDI auto 45km/h` in WARN_DRIVER, `FERMO! auto 45km/h` in
      WARN_PEDESTRIAN. Mai un invito ad attraversare.
18. **Altre scelte di AI-M3**:
    - in WARN_PEDESTRIAN un veicolo vicino che frena (a ≤ −2 m/s²) è considerato uno che dà la precedenza: lo stato
      resta PRESENCE;
    - lo stato scende solo dopo 1 s (`rules.hold_s`);
    - la velocità di camminata è la mediana delle velocità mentre il pedone cammina, non la media: così partenze e
      arresti non la abbassano. Chi sta fermo al cordolo non risulta lento;
    - altezza e lunghezza in metri vengono dalla scala locale dell'omografia nel punto d'appoggio: è
      un'approssimazione, da tarare con `geometry.height_scale` su una persona di altezza nota;
    - un veicolo conta per la regola solo se è in carreggiata e si sta avvicinando alle strisce a più di 1 m/s;
    - zone d'attesa profonde 1,5 m e larghe quanto le strisce più 1 m per lato;
    - soglie dell'autodiagnosi: varianza del Laplaciano sotto 15 = lente coperta, più del 50% di pixel saturi =
      abbagliamento. Da tarare sulla camera vera;
    - contratto del classificatore degli ausili (non ancora addestrato): ingresso 1x3x96x96, BGR, 0–255.
19. **Chiuse dalla bozza di `docs/CONTRACTS.md` di Lorenzo** (branch `lorenzo/ble-backup`): punto 3 (dati dal
    microcontrollore: contratto C5), punto 6 (C3 solo su file in `logs/c3/`), punto 7 (pedone solo termico:
    `attrs.thermal_only`).
20. **Scelte di AI-M4**, tutte in `config.yaml`:
    - quali classi COCO contano per sito: `urbano` dog e cat; `lungofiume` come urbano più gli uccelli grandi;
      `collina` anche horse, sheep, cow, bear (cinghiali e caprioli vengono visti come una di queste);
    - un branco è fatto da almeno 2 animali liberi entro 3 m: vale come allerta anche se sono di taglia media;
    - near-miss per TTC solo se il pedone è entro 1,5 m di lato dalla traiettoria del veicolo; per PET i due devono
      passare entro 1 m dallo stesso punto;
    - la frenata brusca vale solo per veicoli che andavano ad almeno 3 m/s;
    - una collisione richiede almeno un veicolo tra le due tracce;
    - `yield`: conta il veicolo che arriva mentre un pedone è in zona d'attesa; ha dato la precedenza se è sceso
      sotto 2 m/s prima delle strisce, anche se poi è ripartito;
    - i file C3 vanno in `logs/c3/` (o `$MDGB_C3_DIR`), un file nuovo ogni ora, come nella bozza di Lorenzo.
21. **Da proporre a Lorenzo**: un evento C3 `animal` (track_id, coco, size, free) per gli avvistamenti, compresi
    gli animali piccoli che la specifica vuole "solo nel log". Per ora escono solo sul terminale, perché la bozza
    del contratto non prevede quel tipo.
22. **Scelte di AI-M5**, tutte in `config.yaml` (`thermal`):
    - `--thermal` accetta `mlx90621` (il sensore del kit) e `sim`; `mlx90640` e `uvc` restano nell'elenco ma
      rispondono che il sensore non c'è (chiude il punto 2);
    - con 16x4 le zone sono insiemi di colonne, non poligoni: stanno in `calib_thermal.json`;
    - la temperatura ambiente è la mediana delle 64 letture;
    - il recupero del pedone vale solo in modalità notte: di giorno un cofano caldo darebbe falsi allarmi;
    - la persona vista dalla camera ma senza calore viene solo segnalata, non ignorata: in dubbio si protegge;
    - soglia di buio: luminosità media sotto 50 su 255. Da tarare sulla camera vera;
    - **da verificare:** al buio l'autodiagnosi "lente coperta" (immagine senza dettaglio) potrebbe scattare e
      mandare tutto in DEGRADED. Serve un video notturno vero per tarare le due soglie insieme;
    - **da verificare con Salvatore e Lorenzo:** formato della riga C5 `thermal` e `Actuator.set_listener`
      (bozza di `docs/CONTRACTS.md`), mai provati sul firmware.
23. **Stabilità dei comandi** (trovata provando AI-M5): il verde richiesto cresce soltanto finché c'è qualcuno, e un
    cambio della sola `reason` non fa partire un nuovo C1 prima della ripetizione di ogni secondo.
24. **Verso AI-M6**: `docs/DEPLOY_UNOQ.md` è una bozza non provata sulla scheda. Da fonti non ufficiali risulta che
    la UNO Q monta Debian 13 (quindi Python 3.13, compatibile con le versioni fissate: punto 9) e che per la camera
    CSI va abilitata un'opzione di App Lab (punto 1). Entrambe le cose vanno verificate sulla scheda.
25. **Modifiche nate dalla prova sui video reali** (branch `paolo/ai-video-tests`):
    - input a forma di immagine (`model.match_aspect`) e zona d'interesse (`roi` in `calib.json`): più pixel sugli
      oggetti a parità di costo;
    - velocità su una finestra di 0,5 s (`kinematics.window_s`), con l'EMA della specifica applicata sopra;
      accelerazione solo dopo una finestra piena di velocità;
    - nessuna velocità per box tagliati dal bordo, per salti impossibili (cambio di ID) e dove un pixel vale più di
      0,5 m a terra;
    - velocità di camminata = avanzamento netto negli ultimi 2 s, misurata solo se il pedone si è mosso per tutto
      quel tempo: chi aspetta fermo non risulta lento;
    - eventi: `yield` una sola volta per veicolo, quando arriva alle strisce; near-miss per TTC solo sopra 3 m/s;
      frenate e collisioni solo entro 30 m dalle strisce e solo per tracce con velocità nota;
    - autodiagnosi: soglia del Laplaciano da 15 a 4 (scene reali misurate: da 8 in su; lente coperta: sotto 2) e
      guasto confermato solo se si ripete al controllo successivo.
26. **Limiti emersi dai video**, non risolti:
    - nelle folle fitte (Shibuya, New York) il detector vede una parte dei pedoni e le tracce durano meno di un
      secondo: i conteggi in quelle scene non sono affidabili;
    - `child` dipende dall'altezza stimata, che con una camera molto dall'alto risultava troppo bassa: corretto al
      punto 27;
    - con una calibrazione stimata a occhio le velocità sono buone vicino alle strisce e inaffidabili lontano;
    - oggetti fermi scambiati per veicoli (un pannello stradale visto come `bus`) restano come tracce.
27. **Modifiche nate dai video di Torino** (branch `paolo/ai-video-tests`):
    - linea dei veicoli al centro delle strisce (`geometry.veh_line_offset_m: middle`). Con la linea 2 m prima delle
      strisce, i veicoli di una direzione entravano dal bordo dell'immagine già oltre la linea e non venivano contati;
    - la calibrazione accetta quattro punti che non sono gli angoli dell'attraversamento (`ground` in
      `build_metric_calib`), per quando un cordolo è coperto o fuori dall'immagine. A Torino i punti sono gli estremi
      di due strisce distanti 10 m, contate una per una: strisce e intervalli sono di 50 cm (regolamento del Codice
      della Strada, D.P.R. 495/1992, art. 145);
    - **altezza delle persone.** Prima l'altezza di un riquadro si convertiva in metri con la stessa scala della
      larghezza: da una camera in alto una persona appare accorciata e un adulto risultava alto 1,3–1,5 m. Ora dalla
      calibrazione si ricostruiscono lunghezza focale e posizione della camera (Zhang 2000, i due vincoli sulle prime
      due colonne dell'omografia) e l'altezza è quella esatta lungo la verticale sopra i piedi. Ipotesi: pixel
      quadrati e asse ottico al centro dell'immagine. Su quattro camere simulate, per una persona di 1,70 m:
      1,70 m senza errori di clic; con 3 px di errore sui quattro angoli il 90% delle stime sta fra 1,51 e 1,88 m
      (prima fra 1,23 e 1,86 m, con mediana 1,41 m dalla camera più alta);
    - **controllo della calibrazione** (`geometry.camera_tolerance: 0.2`). Se i quattro punti e le due misure non
      tornano con una camera reale, la posizione non viene ricostruita e `calibrate.py` lo dice. Con 0,2 passano
      almeno l'86% delle calibrazioni corrette cliccate con 4 px di errore (simulazione, 4 posizioni di camera);
      angoli scambiati o misure sbagliate non passano. Vale per obiettivi normali, non per immagini ritagliate da un lato;
    - `child` si decide solo se la calibrazione passa il controllo e il riquadro è alto almeno 30 px
      (`attributes.height_min_box_px`) e non tocca il bordo alto. Altrimenti resta non deciso: non è un bambino, e
      vale la velocità di camminata misurata. Le taglie degli animali usano comunque l'altezza approssimata;
    - `scripts/evaluate.py`: `--stabilize` compensa il tremolio di un video girato a mano (solo per le prove: il
      prodotto presume una camera fissa), `--save-video` scrive il video annotato, e il resoconto riporta le altezze
      stimate e la camera ricostruita.
    - **a 10 FPS una traccia vale dopo 2 fotogrammi, non 5** (`tracking.min_track_age` nei profili `unoq` e
      `--emulate-unoq`; su PC resta 5 come da specifica). Cinque fotogrammi a 10 FPS sono mezzo secondo: un'auto a
      30 km/h passa la linea prima che la sua traccia conti. Veicoli contati su Torino_1 (in un verso + nell'altro):

      | | 512 px | 320 px |
      |---|---|---|
      | 30 FPS, valida dopo 5 | 22 + 13 | 21 + 9 |
      | 10 FPS, valida dopo 5 | 11 + 5 | 11 + 0 |
      | 10 FPS, valida dopo 2 | 20 + 8 | 18 + 2 |

      È una deroga al default della specifica (§5.1.3), limitata ai profili a 10 FPS: da confermare.
28. **Limiti emersi dai video di Torino**, non risolti:
    - i pedoni vengono visti in parte: circa 4 per fotogramma quando ce ne sono fra 6 e 10 (budget 512), 2,4 con il
      budget di 320 previsto per la scheda. I file sono 478x850 e molto compressi, un pedone è alto 30–50 px;
    - con i limiti della scheda (10 FPS, 320 px) il verso lontano dei veicoli quasi non viene contato (2 invece di 13);
    - ciclisti, monopattini e rider non vengono riconosciuti: la bici, piccola, non viene rilevata;
    - `child`: su Torino_1 restano 4 falsi su 24 pedoni. I riquadri dei pedoni sono più corti di quanto la
      calibrazione prevede per un adulto (47 px contro 56–71): o il modello taglia le figure piccole, o la
      calibrazione a occhio ha un errore del 15%. Serve una persona di altezza nota in un video;
    - la calibrazione di Torino_2 non passa il controllo e non sono riuscito a correggerla a occhio: le velocità e
      le altezze di quel video non valgono;
    - un incrocio con veicoli in svolta (Torino_3) non si conta con una sola linea diritta;
    - pedoni lontani letti come `bird`, un'auto scura letta come `motorcycle`.
29. **Integrazione sulla UNO Q** (branch `paolo/ai-unoq`, decisa con Paolo e il team il 10/10 sera):
    - **ordine:** prima sketch (Salvatore) + visione, provati sulla scheda; la rete verso la centrale e il backup
      (Lorenzo) dopo;
    - **la visione gira su Linux fuori da App Lab**. Scartata l'alternativa "dentro `main.py` dell'app":
      onnxruntime e supervision andrebbero installati nel container di App Lab, mai provato, con il rischio di
      conflitti con le sue librerie;
    - **la camera la apre solo la visione**: il `main.py` dell'app di App Lab oggi la apre per mostrarla su una
      pagina web, e va tolta da lì (proposta consegnata a Salvatore);
    - **per parlare con lo sketch si usa `comms/actuators.py` di Lorenzo così com'è** (`BridgeActuator`): è il
      collegamento visione–sketch, non la rete. Finché non è su main, `push_to_arduino.sh --bridge` lo prende dal
      suo ramo. Dipendenza sulla scheda: `arduino-router-bridge==0.5.1`, come in `comms/requirements.txt`;
    - **l'urto è l'antifurto del nodo e non cambia lo stato della visione.** (La prima versione metteva la visione
      in `DEGRADED`, come dice §5.2 della specifica: Paolo ha chiarito che non è quello lo scopo.) La visione lo
      mostra al tecnico e basta;
    - **pagina del tecnico:** badge, poi login con utente e password, via Wi-Fi. Mostra numeri e vista dal vivo.
      `operator.share_images: false` lascia solo le statistiche: è l'interruttore per la produzione. Le immagini non
      si salvano mai (specifica: "mai salvare frame su disco") e si producono solo mentre un tecnico connesso guarda.
      Via Bluetooth un video non passerebbe: il BLE non ha la banda;
    - **credenziali:** nome utente e impronta PBKDF2 della password in `ai/.env`, mai nel repo. Limite noto: HTTP in
      chiaro;
    - **proposta di sketch per Salvatore** (fuori dal repo): `mdgb_line` per C1/C2, centralina simulata sui tre
      LED, fail-safe a 500 ms, blocco RFID e bip senza `delay()`, badge e antifurto anche verso la visione
      (`mcu_event`). Logica provata su PC con un finto Arduino, non compilata per la scheda. Aperto: lo stato della
      visione usato come chiamata pedonale (verde dei veicoli da 20 a 8 s) non è scritto nel contratto.
30. **Da fare quando si unisce la rete di Lorenzo:**
    - **antifurto verso la centrale:** l'allarme dell'accelerometro deve arrivare alla sua applicazione. Le righe
      `mcu_event` dello sketch passano già da `comms/actuators.py`, che le scrive in `mcu-*.jsonl` per il nodo; va
      verificato sulla scheda e va evitato che l'allarme arrivi due volte (anche `mdgb_link.py` lo inoltra);
    - cartella unica degli eventi (`--applab`, `MDGB_C3_DIR`) e permessi di scrittura in `~/ArduinoApps/<app>/data`;
    - stato del nodo "manomesso" in centrale: come si presenta e chi lo azzera (il badge del tecnico?).
31. **Cosa si chiede al semaforo, deciso da Paolo il 10/10 sera** (cambia quanto scritto al punto 17):
    - **rosso subito** per un bambino non accompagnato o un animale libero in strada, con un giallo breve prima;
    - **verde pedonale più lungo solo per chi ne ha bisogno**: `slow` (cammina sotto 0,9 m/s) o `aid`. Non più per
      ogni pedone più lento di 1,2 m/s, né per i bambini in quanto tali;
    - **il rosso non si trattiene più** per chiunque sia sulle strisce né negli stati di avviso: solo per chi ha
      bisogno di tempo e per bambino solo o animale;
    - "non accompagnato" = nessuno che non sia un bambino entro 2 m a terra (`rules.supervision_distance_m`, lo
      stesso criterio del cane al guinzaglio). Un pedone di cui non si conosce l'altezza conta come adulto;
    - animali: liberi, in carreggiata, di taglia media o grande (`rules.red_now_animal_sizes`);
    - **campo nuovo `req.veh_red_now` nel comando C1**: è una modifica al contratto, da far confermare a Lorenzo.
      È solo un'aggiunta: chi non lo conosce lo ignora;
    - `T_need` e gli avvisi a conducenti e pedoni non cambiano: per quelli il bambino resta a 0,8 m/s.
32. **Prima prova sulla scheda (10/10 sera)**, numeri in `README.md`:
    - a 320 px con il detector a ogni frame la scheda fa 5,8 FPS, sotto l'obiettivo di 8. Profilo `unoq`: detector
      un frame su due, 3 thread, tetto a 12 FPS. Con la camera vera: 9,2 FPS;
    - la camera è un IMX219 su CSI: si apre con `libcamerify` (chiude la questione aperta 1);
    - sulla scheda manca `python3-venv`: l'ambiente si crea senza pip e si installa con il pip di sistema;
    - gli FPS mostrati erano una media di tempi tra frame consecutivi: con il detector un frame su due dava numeri
      assurdi (220). Ora è la frequenza sugli ultimi 30 frame.
33. **App `mdgb` sulla scheda e prima prova del semaforo comandato (10/10, 23:30)**. Su richiesta di Paolo lo sketch
    proposto non sostituisce quello di Salvatore: è in una app nuova, `~/ArduinoApps/mdgb`, copia della sua `test`
    (versione sulla scheda, con buzzer su A5 e luce su A0) più `mdgb_line`. `test` è intatta. Misure dai log dell'app:
    - lo sketch compila per la scheda (129 kB, 16%) e parte;
    - ciclo normale: verde 20,0 s, giallo 3,0 s, rosso 10,0 s; badge, allarme e sensori come prima;
    - rosso d'urgenza chiesto attraverso il Bridge con `comms/actuators.py` quando il verde era acceso da 5 s: lo
      sketch ha aspettato il verde minimo (giallo a 8,0 s), giallo breve di 1,5 s, rosso tenuto 24,5 s finché la
      richiesta è rimasta, poi verde;
    - heartbeat fermati: fail-safe e ciclo normale dopo circa mezzo secondo (i log hanno la precisione del
      secondo sul lato visione, non permettono di dire di più);
    - visione vera con la camera collegata allo sketch: "visione collegata", nessuna riga rifiutata; fermandola,
      fail-safe. In quella prova 7,4 FPS: sulla scheda girava anche un `apt`.
    Non ancora provati sull'hardware: una richiesta nata da una scena vera (serve la calibrazione), badge → pagina
    del tecnico → login dal telefono, antifurto mostrato sulla pagina.
34. **Rosso dei veicoli a 20 s** (era 10): chiesto da Paolo perché tutti i pedoni abbiano il tempo di attraversare.
    È una costante dello sketch dell'app `mdgb` (`VEH_RED_MS`); i limiti diventano 20 + 15 s di estensione e
    20 + 20 s di rosso trattenuto. Misurato sulla scheda: 20,0 s. `deploy/run_vision.sh` accende e spegne la
    visione sulla scheda senza `sudo`.
35. **Stato a fine serata dell'11/10 (per chi riprende il lavoro):**
    - sulla scheda gira l'app `mdgb` (cicalino spento per ora: `BUZZER_ENABLED 0` nello sketch) e la visione,
      accesa con `deploy/run_vision.sh`. La sorgente dello sketch non è nel repo: è in `~/ArduinoApps/mdgb` sulla
      scheda e in `mdgb-app-proposta.zip` consegnato a Salvatore, che deciderà se e come metterlo in `firmware/`;
    - manca la calibrazione sull'incrocio vero: senza, la visione conta ma non chiede niente al semaforo;
    - non ancora provati: badge → pagina del tecnico → login dal telefono; una richiesta nata da una scena vera;
    - PR #9 e #11 aperte (la #11 sopra la #9); la PR #10 di Lorenzo non è su main;
    - da fare con Lorenzo: punto 30 e il campo `req.veh_red_now` nel contratto.
36. **Tecnico: 2 minuti per il login e cicalino muto mentre lavora** (chiesto da Paolo l'11/10, notte):
    - dal badge ci sono 2 minuti per entrare (`operator.login_s`); la sessione resta aperta fino a "Esci"
      (`operator.session_s: 0`, scelta di Paolo; con un limite, un badge con la pagina aperta lo fa ripartire).
      Login e logout consumano il badge: un secondo login, o rientrare dopo l'uscita, chiede un altro badge;
    - dal badge al logout (o ai 2 minuti senza login) il comando C1 porta il campo nuovo `"tech": true`. Lo sketch
      tiene muto il cicalino; resta il bip di conferma del badge (scelta di Paolo). Il campo parte al cambio, non
      aspetta la ripetizione di 1 s;
    - nello sketch: 2 minuti di silenzio dal badge anche senza visione, poi silenzio finché arriva `tech: true`.
      Quando `tech` passa da true a false (logout) il cicalino torna subito. Senza heartbeat il campo non vale:
      se la visione si ferma, l'antifurto torna a suonare. L'urto viene comunque segnalato (`mcu_event`, centrale);
    - Salvatore ha riacceso il cicalino l'11/10 (`BUZZER_ENABLED 1`) e tolto solo il bip del sensore di luce coperto,
      che di sera suonava di continuo;
    - `tech` è un campo nuovo del contratto C1, come `req.veh_red_now` (punto 31): da far scrivere a Lorenzo in
      `docs/CONTRACTS.md`. Chi non lo conosce lo ignora.
37. **Visione, sketch e rete insieme sulla scheda (11/10, 01:00)**, dopo il merge delle PR #9, #11 e #10:
    - **cartella unica degli eventi** (punto 30): `~/ArduinoApps/mdgb/data/c3`, che il container di App Lab vede
      come `/app/data/c3`. La visione ci arriva con `push_to_arduino.sh --applab mdgb` (file `ai/.c3_dir`, letto da
      `run_vision.sh`), la rete con lo stesso `--applab` del suo script;
    - **urto e badge una volta sola** (punto 30): li scrive solo `mdgb_link.py`, da `alarm_status` e
      `rfid_status`. Lo sketch non li manda più come `mcu_event` (resta solo il fail-safe). Così arrivano anche a
      visione spenta, e la visione li legge dagli stessi file (`C5FileTail`, ogni 0,5 s);
    - **app `mdgb` aggiornata** con l'ok di Paolo:
      - sketch del punto 36, sopra la versione di Salvatore delle 00:23 (soglia dell'urto 1,15 g);
      - `main.py` di adesso, senza camera, con le 5 righe di `mdgb_link`;
      - pacchetto e prova su PC in `mdgb-app-tecnico.zip`, consegnato a Salvatore;
    - **`~/venv` con il suo `pip`** (`python3 -m pip --python ~/venv/bin/python install pip`, senza sudo): lo
      script di Lorenzo usa `~/venv/bin/pip`, che mancava;
    - **rete:** servizio `mdgb-comms`, broker sul PC di Lorenzo (192.168.169.12:1883). Al broker arrivano
      `hb` ogni 10 s (stato IDLE, 8,7 FPS) e `agg` ogni 60 s (temperatura, umidità);
    - **Bluetooth di backup non attivo:** con BlueZ 5.82 `btmgmt` resta fermo se l'input è `/dev/null`, come
      sotto systemd: "power on" va in timeout dopo 5 s. Provato sulla scheda: con `input="\n"` in
      `subprocess.run` (`comms/node/backup_link.py`) risponde subito. Correzione per Lorenzo;
    - **vista dal vivo nell'app di Lorenzo:** non funziona per scelta. Lo stream della visione è solo per il
      tecnico con badge e login (punto 29).
38. **Comandi C1 troppo lunghi per il Bridge (11/10, 01:30)**, trovato provando tutto sulla scheda:
    - `arduino-router` rifiuta le chiamate `mdgb_line` oltre **238 byte** ("message size exceeds the limit").
      Misurato sulla scheda con righe di prova che lo sketch scarta. Il contratto C1 dice 512, e
      `comms/actuators.py` accorcia solo sopra 512;
    - nelle scene di prova i comandi arrivavano a 361 byte: PRESENCE, avvisi, rosso subito per animale o
      bambino, DEGRADED. **Nessuno arrivava allo sketch**; passavano solo IDLE e gli heartbeat. La prova del
      punto 33 usava righe corte;
    - ora `Commander` manda una riga che sta nel limite (`actuator.max_line_bytes: 238`). Prima accorcia `reason`,
      poi toglie `oled`, `lcd`, `led`, `green_s`, `t_ms`. Restano sempre `v`, `seq`, `state`, `req` e `tech`, cioè
      quello che lo sketch usa. Il comando completo resta per log, overlay e pagina del tecnico;
    - per Lorenzo: in CONTRACTS il limite del Bridge è 238, non 512.
39. **Camera ferma alle 01:11 dell'11/10.** Il flusso si è fermato senza errori del software; allo stop il kernel ha
    scritto `imx219 ... disabling streaming failed (-6)`: il sensore non risponde più sull'I2C (cavo CSI
    mosso o staccato durante il montaggio). Da lì il driver `qcom_camss` resta in "sta già registrando" e
    nessun programma apre la camera (`Failed to start streaming: Operation already in progress`), nemmeno
    `cam`. Si sblocca solo controllando il cavo e riavviando la scheda. La visione intanto era in DEGRADED
    ("video assente").
40. **Prova di tutto sulla scheda (11/10, 01:30-01:40)**, dopo il riavvio che ha sbloccato la camera (punto 39):
    - **avvio automatico:** visione come servizio `mdgb-ai` (si ferma con SIGINT come Ctrl+C, righe di stato in
      `journalctl`), rete `mdgb-comms`, app `mdgb` come app predefinita di App Lab. Provato con un riavvio: tutto
      riparte da solo. Al primo avvio la camera non è ancora pronta: systemd riavvia la visione dopo 2 s;
    - **comandi accorciati** (punto 38) provati sul Bridge: la riga completa da 366 byte viene rifiutata, quella
      accorciata da 234 byte arriva e lo sketch la accetta;
    - **visione interrotta:** fail-safe del semaforo dopo 485 ms; systemd la riavvia in 3,8 s; la camera si
      riapre; lo sketch torna "visione collegata" dopo 7,5 s;
    - **rete tagliata 100 s:** la centrale passa a "rete giù, nodo sano" via Bluetooth (−41 dBm). Alla
      riapertura torna su Wi-Fi in 18 s, con coda 0, 0 eventi persi e 0 doppioni;
    - **da sistemare in centrale (Lorenzo):**
      - all'inizio del taglio, per circa 5 s, compare "nodo distrutto": il Last Will MQTT arriva prima del
        primo beacon;
      - il fail-safe dello sketch non arriva in centrale quando la visione è spenta: `mcu_event` non ha più
        chi lo riceve;
    - **non ancora provati:** badge, login e cicalino muto dal telefono (serve qualcuno con il badge);
      calibrazione e richieste nate da una scena vera.
41. **Correzioni in centrale concordate con Lorenzo (11/10, 01:50)**, in PR #13 (area sua):
    - **"Nodo distrutto" per 5 s:** per 20 s da quando MQTT è perso la centrale mostra "Wi-Fi perso, attendo il
      Bluetooth" (giallo), poi decide. Lorenzo trovava troppi 40 s. Vale dopo la ricostruzione dell'app sul
      suo PC;
    - **fail-safe in centrale anche a visione spenta:** lo scrive `mdgb_link.py` dal messaggio `led_status`
      "FAIL-SAFE" dello sketch. Lo sketch dell'app `mdgb` non manda più nessun `mcu_event`: urto, badge e
      fail-safe passano tutti da `mdgb_link.py`, una volta sola. App aggiornata sulla scheda (backup in
      `~/HackTurin-mdgb/backups/`) e zip per Salvatore aggiornato;
    - **provato:** visione interrotta → riga di fail-safe dopo circa 0,7 s → la centrale mostra "nodo guasto
      (semaforo in fail-safe)" → con la visione ripartita da sola torna "nodo OK" dopo 12 s.
42. **Tracce che non si spezzano (11/10, notte)**, misurato su 13 video di prova, compreso il nuovo
    `Torino_night_1.mp4` (notte, 4 min 48 s, ripreso dall'alto, non calibrato):
    - **problema:** con i limiti della scheda le tracce duravano meno di 1 s in mediana, di notte (0,8 s) come di
      giorno (Torino_1 0,9 s, Shibuya 0,8 s). Un pedone che attraversa diventava più "persone": conteggi doppi,
      attributi mai decisi. Non è un effetto del buio;
    - **causa:** il detector passava al tracker solo i riquadri sopra 0,30, quindi il secondo aggancio di
      ByteTrack (riquadri tra 0,1 e la soglia) non lavorava mai. Con 5–6 rilevamenti al secondo lo spostamento
      tra due rilevamenti superava anche la tolleranza dell'aggancio;
    - **scelta:** `model.conf` 0,10 e `tracking.minimum_matching_threshold` 0,9 (era 0,8), scelte su 4 varianti.
      Le tracce nuove nascono comunque solo da riquadri sopra 0,4 (regola di ByteTrack). Altezza e voto di
      classe solo dai riquadri sopra 0,30 (`tracking.measure_min_conf`): quelli deboli sono spesso tagliati e
      facevano salire i falsi "bambini";
    - **risultati** (`--emulate-unoq`, prima → dopo):
      - durata mediana delle tracce: notte 0,8 → 1,7 s; Torino_1 0,9 → 1,5 s; Torino_3 1,2 → 2,0 s; Shibuya 0,8 → 1,4 s;
      - tracce sotto 1 s su Torino_1: 54 → 28;
      - veicoli contati su Torino_1: 20+5 → **23+10** (riferimento a 30 FPS e 512 px: 22+13);
      - con il detector un fotogramma su due (come sulla scheda): notte, tracce sotto 1 s 12 → 3; veicoli su
        Torino_1 12+0 → 18+0;
    - **sulla scheda:** 8,8 FPS come prima, detector 125 ms;
    - **non risolto:** i "bambini" su Torino_1 salgono da 9 a 11 con `--emulate-unoq` (restano 5 con il
      detector un fotogramma su due). La calibrazione di quel video è a occhio (punto 28): va verificato con una
      persona di altezza nota sulla camera vera. Sempre 0 veicoli nel verso lontano con il detector un
      fotogramma su due: dipende da linea di conteggio e frequenza, è da guardare a parte.
43. **Benchmark sulla scheda con i video di prova (11/10, 03:40)**, chiesto da Paolo per vedere dal vivo, su MQTT
    e sulla pagina del tecnico, come vengono analizzati:
    - **video al posto della camera, senza `sudo`:** `run_vision.sh video <file> [--calib ...] [--once]` e
      `run_vision.sh camera`. Il servizio esegue `deploy/vision_service.sh`, che legge la sorgente da
      `ai/.vision_args`. Serve una sola password, per installare il servizio in questa forma;
    - **il video si comporta come una camera:** in tempo reale salta i fotogrammi in ritardo
      (`source.file_drop_late`). Prima una scheda più lenta del video lo vedeva al rallentatore, con numeri non
      confrontabili con la camera;
    - **`--loop`:** ricomincia dall'inizio senza fermarsi, e a ogni passata stampa la tabella dei tempi per fase;
    - **prima prova:** Torino_1 sulla scheda a 8,4–8,6 FPS, auto contate e arrivate in centrale, 0 eventi persi,
      nessun comando rifiutato dal Bridge;
    - 21 video e le calibrazioni copiati in `~/HackTurin-mdgb/ai/samples/` sulla scheda (246 MB, fuori da git).

