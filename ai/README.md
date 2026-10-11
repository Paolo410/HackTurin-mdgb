<img src="../docs/brand/mdgb-simbolo.svg" alt="MDGB" width="56" align="right">

# ai/ — visione e regole di MDGB

**Owner:** Paolo Malugani (data scientist).

## Scopo

Il package `smartcrossing` gira sul lato Linux della UNO Q (e identico su PC). Da una camera:

1. riconosce e segue pedoni, ciclisti, veicoli e animali (YOLOX-nano ONNX + ByteTrack);
2. conta gli attraversamenti per direzione, senza doppioni;
3. misura posizione e velocità a terra e ricava gli attributi del pedone (bambino, lento, ausili);
4. decide lo stato della segnalazione con una regola esplicita (`rules.py`) e lo invia al firmware (contratti C1 e C2);
5. scrive gli eventi anonimi per `comms/` e `app/` (contratto C3).

Non salva mai frame su disco. Tutto funziona senza internet.

Decisioni, numeri, interfacce e questioni aperte: [DECISIONS.md](DECISIONS.md).
Specifica completa: [`PROMPT_SMART_CROSSING.md`](../PROMPT_SMART_CROSSING.md), §5.1.

Accanto a `smartcrossing` c'è [`forecast/`](forecast/README.md): il modello del flusso atteso che la centrale mostra
per ogni camera (gradient boosting su calendario, luoghi vicini, ESA WorldCover e meteo, corretto con i conteggi del nodo).

## Stato

| Milestone | Contenuto | Stato |
|---|---|---|
| AI-M1 | sorgente video + detector + tracker + overlay, `bench.py` | fatto |
| AI-M2 | conteggio per direzione + ciclista/motociclista | fatto |
| AI-M3 | calibrazione, velocità, attributi, regole, `SimActuator` | fatto |
| AI-M4 | eventi, animali, logger, output C3 | fatto |
| AI-M5 | termocamera | fatto in simulazione, da provare con il sensore |
| AI-M6 | profilo `unoq`, prova sulla scheda, benchmark | la visione gira sulla scheda con la camera vera a 9 FPS e comanda il semaforo dell'app `mdgb`; manca la calibrazione sull'incrocio. Guida in [docs/DEPLOY_UNOQ.md](docs/DEPLOY_UNOQ.md) |

## Come si avvia

Prima volta:

```bash
cd ai
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
bash scripts/get_model.sh          # scarica yolox_nano.onnx (3,7 MB) in ai/models/ e ne crea la copia a input libero
```

Poi, con il virtualenv attivo e dentro `ai/`:

```bash
python -m smartcrossing.app --source 0                     # webcam, finestra con l'overlay (q o Esc per uscire)
python -m smartcrossing.app --source samples/video.mp4     # file video
python -m smartcrossing.app --source 0 --emulate-unoq      # limiti nominali della specifica: 10 FPS, 4 thread
python -m smartcrossing.app --source 0 --headless          # senza finestra, una riga di stato al secondo
python -m smartcrossing.app --source 0 --operator-port 8090  # in più la pagina del tecnico (badge + login)
python scripts/operator_login.py                           # imposta utente e password del tecnico
python scripts/calibrate.py --source samples/video.mp4     # calibra l'inquadratura e salva calib.json (vedi sotto)
python scripts/scenario.py                                 # elenco delle scene simulate (senza camera)
python scripts/scenario.py elderly_fast_car                # pedone lento + auto a 50 km/h: regole e attuatore
python scripts/animal_probe.py cartella_di_foto            # come il detector vede animali non previsti da COCO
python scripts/evaluate.py samples/video.mp4 --calib c.json  # numeri e fotogrammi annotati di un video di prova
python scripts/bench.py samples/video.mp4                  # ms medi e p95 per fase
pytest                                                     # test, senza hardware
```

- Senza `--source` si usa il primo video in `ai/samples/` (ignorata da git); se è vuota, la webcam.
- Su macOS la prima volta va autorizzato il terminale: Impostazioni di Sistema > Privacy e sicurezza > Fotocamera.
- `--actuator sim` (default) non richiede hardware. `--actuator serial --port ...` usa `comms/actuators.py`.
- `--site urbano|lungofiume|collina` sceglie quali animali contano (default `urbano`).
- Gli eventi C3 finiscono in `logs/c3/` nella root del repo (ignorata da git). `--c3-dir` cambia cartella,
  `--no-c3` li spegne.
- `--thermal mlx90621` usa la termocamera Grove 16x4 letta dal microcontrollore; `--thermal sim` ne simula una.
  `--night` forza la modalità notte per provare la fusione di giorno.
- **Non tenere il repo in una cartella sincronizzata** (Desktop o Documenti con iCloud, OneDrive, Dropbox): il
  virtualenv e `.git` vengono spostati nel cloud e l'avvio resta bloccato.

A schermo: un box per traccia con `#ID ruolo punteggio velocità attributi` (grigio finché la traccia non ha
5 frame), le zone e le linee di conteggio con la freccia del verso IN, i conteggi, FPS e millisecondi per fase. In
basso lo stato, la lampada, il motivo della decisione, i testi dei due display e le richieste alla centralina.
Ogni attraversamento e ogni cambio di stato vengono anche stampati sul terminale.

## Calibrazione

Si fa una volta per ogni posizione della camera, con `scripts/calibrate.py`:

1. si cliccano i quattro angoli delle strisce: prima i due sul cordolo vicino (1, 2), poi i due sul cordolo
   lontano girando intorno (3 di fronte a 2, 4 di fronte a 1);
2. si danno due misure in metri: `--along` è la distanza 1–2 (le strisce misurate lungo la strada), `--width` è la
   distanza 2–3 (la strada da cordolo a cordolo). Senza le opzioni lo script le chiede;
3. lo script mostra zone e linee ricavate: `s` salva `calib.json`, `r` ricomincia.

Da questi dati vengono ricavati: i metri e le velocità, le due zone d'attesa sui marciapiedi, le strisce, la
carreggiata e le due linee di conteggio. I margini stanno in `config.yaml` (`geometry`).
Con `--lines-only` si disegnano solo le due linee di conteggio, senza misure: basta per contare, non per le regole.
Senza una calibrazione in metri lo stato resta `IDLE`.

La calibrazione è manuale: la fa una persona all'installazione, e va rifatta se la camera viene spostata. Non c'è
una calibrazione automatica. Due aiuti:

- **misure senza metro:** in Italia le strisce pedonali sono larghe 50 cm con 50 cm di intervallo, e lunghe almeno
  2,50 m (regolamento del Codice della Strada, D.P.R. 495/1992, art. 145). Contando le strisce da cordolo a cordolo
  si ottiene la larghezza della strada: una striscia più un intervallo fanno un metro;
- **controllo di plausibilità:** dai quattro punti e dalle due misure lo script ricostruisce dove si trova la camera
  e stampa a che altezza da terra risulta. Se il numero è lontano dal vero, o se compare l'avviso che i punti non
  tornano con una camera reale, un angolo o una misura sono sbagliati. Vale per camere normali (webcam, telefono),
  non per immagini ritagliate da un lato.

L'altezza delle persone (attributo `child`) usa la posizione ricostruita della camera: da una camera in alto una
persona appare più corta di quanto è larga la strada accanto, e senza questa correzione gli adulti risultano bambini.
`child` si decide solo quando l'altezza è misurabile: calibrazione che torna con una camera reale e riquadro alto
almeno 30 pixel (`attributes.height_min_box_px`). Altrimenti resta non deciso, e vale la velocità di camminata misurata.

## Sulla scheda: microcontrollore e tecnico

Sulla UNO Q la visione gira come programma a parte accanto all'app di App Lab dello sketch. Come si copia e si
prova: [`docs/DEPLOY_UNOQ.md`](docs/DEPLOY_UNOQ.md) e `deploy/push_to_arduino.sh`.

- **Cosa arriva dal microcontrollore** (`smartcrossing/mcu.py`, righe C5 del contratto):
  - badge del tecnico: dà 2 minuti per entrare nella pagina del tecnico (`operator.login_s`);
  - urto: è l'antifurto del nodo. La visione continua a lavorare e lo mostra al tecnico; l'avviso alla centrale
    è compito della rete (`comms/`), da collegare quando le due parti si uniscono;
  - guasto lampada: `DEGRADED` finché il firmware lo segnala.
- **Pagina del tecnico** (`--operator-port`, `smartcrossing/status_page.py`), dal telefono via Wi-Fi:
  - accesso in due passi: badge sul lettore, poi utente e password entro 2 minuti. La sessione resta aperta
    finché il tecnico non preme "Esci" (`operator.session_s: 0`; con un limite, un badge lo fa ripartire).
    Cinque password sbagliate chiudono la pagina fino al badge successivo;
  - **cicalino muto mentre c'è il tecnico:** dal badge al logout (o ai 2 minuti senza login) il comando C1 porta
    `"tech": true` e lo sketch non suona (resta solo il bip di conferma del badge). Fermandosi la visione, lo sketch
    torna a suonare: senza heartbeat il campo non vale più. Campo nuovo del contratto C1, da confermare con Lorenzo;
  - mostra stato, motivo, FPS, tempi, conteggi, sensori e la vista dal vivo con i riquadri della visione;
  - `operator.share_images: false` spegne le immagini e lascia solo le statistiche (per la produzione);
  - le immagini non vengono mai salvate: esistono in memoria solo mentre un tecnico connesso guarda;
  - credenziali: `python scripts/operator_login.py` salva in `ai/.env` (ignorato da git) il nome utente e la sola
    impronta della password. Limite: HTTP in chiaro, per la strada serve HTTPS.

## Regola

`rules.py` è una macchina a stati in puro Python. Ogni decisione riporta in `reason` i numeri che l'hanno prodotta.

| Stato | Quando | Lampada |
|---|---|---|
| `IDLE` | nessun pedone in attesa o sulle strisce | `OFF` |
| `PRESENCE` | pedone in attesa o sulle strisce, nessun veicolo pericoloso | `WHITE_ON` |
| `WARN_DRIVER` | pedone che vuole attraversare, `TTC < T_need` e veicolo oltre `d_stop + 10 m` | `AMBER_BLINK_2HZ` |
| `WARN_PEDESTRIAN` | veicolo entro `d_stop + 10 m` che non frena (`a > −2 m/s²`) | `RED_GROUND_BLINK` |
| `DEGRADED` | video assente da più di 1 s, lente coperta, camera abbagliata | `YELLOW_FAILSAFE` |

- `d_stop = v·1,0 + v²/(2·7,0)`, `T_need = W/v_ped + 1,0`, `TTC = d/v`, `green_s = min(25, max(W/1,2, W/v_ped) + 2)`.
- `v_ped`: 1,2 m/s; 0,8 per bambino, pedone lento o con ausilio; la velocità misurata se è più bassa.
- Le velocità si misurano su una finestra di mezzo secondo, non tra un frame e l'altro: il box di un oggetto fermo
  trema di qualche pixel e da un frame all'altro sembrerebbe muoversi. Non si misura la velocità quando il box è
  tagliato dal bordo dell'immagine, né dove la calibrazione è troppo grossolana (un pixel vale più di mezzo metro).
- Il pedone "vuole attraversare" se è sulle strisce, oppure in zona d'attesa da più di 1 s o in cammino verso la strada.
- Lo stato sale subito e scende solo dopo 1 s, per non far tremolare le lampade.
- Il verde richiesto può solo crescere finché c'è qualcuno: una stima di velocità che oscilla non fa cambiare la
  richiesta a ogni frame, e un tempo già promesso non viene ritirato.
- Il comando C1 parte a ogni cambio e viene ripetuto almeno ogni secondo. L'heartbeat C2 parte ogni 100 ms da un
  thread separato, ma solo se il ciclo della visione è vivo: se la visione si blocca l'heartbeat si ferma e il
  firmware va in fail-safe da solo.
- Sul display dei pedoni l'AI non scrive mai di attraversare: non conosce la fase del semaforo.

Cosa chiede al semaforo (campo `req` del comando), in due soli casi:

| Chi c'è | Richiesta | Campo |
|---|---|---|
| chi ha bisogno di più tempo: cammina sotto 0,9 m/s (`slow`) o ha un ausilio (`aid`: carrozzina, deambulatore, passeggino) | verde pedonale più lungo, fino a 15 s; rosso dei veicoli trattenuto finché è sulle strisce | `ped_green_extend_s`, `veh_red_hold` |
| un bambino non accompagnato alle strisce o in strada, oppure un animale libero in carreggiata (non i piccoli, non il cane al guinzaglio) | rosso ai veicoli subito, trattenuto finché sono lì | `veh_red_now`, `veh_red_hold` |

- Un pedone qualunque, o un bambino con un adulto entro 2 m (`rules.supervision_distance_m`), non cambia il ciclo.
- `veh_red_now` è un campo nuovo rispetto alla bozza del contratto C1: va confermato da Lorenzo.
- Servono la calibrazione in metri (altezza, velocità di camminata, distanze) e, per gli ausili, il classificatore
  opzionale, che oggi non c'è: carrozzine e deambulatori si riconoscono solo se chi li usa cammina piano.

Attributi del pedone, decisi una volta per traccia: `child` (altezza mediana su 5 frame sotto 1,30 m), `slow`
(velocità di camminata sotto 0,9 m/s, misurata per almeno 2 s mentre cammina), `aid` (classificatore opzionale
`models/aid_cls.onnx`: se manca resta sconosciuto).

Scene simulate (`scripts/scenario.py`): fanno girare tracker, geometria, regole e attuatore senza camera. Con
`--realtime --actuator serial --port ...` muovono lampade e display veri.

| Scena | Cosa mostra |
|---|---|
| `elderly_fast_car` | pedone lento in attesa, auto a 50 km/h: WARN_DRIVER, poi WARN_PEDESTRIAN |
| `pedestrian_crossing` | un pedone attraversa: un conteggio, nessuna richiesta al semaforo |
| `loose_dog_and_leashed_dog` | cane al guinzaglio (nessun allarme), poi cane grande libero (ANIMAL_ALERT) |
| `car_yields` | un'auto rallenta per il pedone in attesa: yield rate 100% |
| `night_pedestrian_seen_by_heat` | di notte la camera non vede il pedone, la termocamera sì: scatta l'avviso |

## Animali

- `animal` = dog, cat, horse, sheep, cow, bear; la classe COCO originale resta negli eventi (`coco`).
- Taglia dalla calibrazione: `large` (lunghezza ≥ 0,8 m o altezza ≥ 0,6 m), `medium` (0,3–0,8 m), `small` (solo log).
- `large` libero in carreggiata → `ANIMAL_ALERT` (`AMBER_BLINK_4HZ`), anche senza veicoli. `medium` libero →
  `ANIMAL_WARN` solo con un veicolo entro `d_stop` + 30 m (40 m sul sito `collina`).
- Al guinzaglio (persona entro 2 m, stessa direzione, da almeno 1 s): nessun allarme proprio.
- Branco (animali entro 3 m): allerta finché l'ultimo è in carreggiata, più 2 s.
- `bird` conta solo sul sito `lungofiume`, a terra in carreggiata, lungo almeno 0,5 m e presente da più di 2 s.
- Nessun segnale acustico verso gli animali.

## Notte: termocamera

Opzionale, con `--thermal`. Il sensore del kit è la Grove MLX90621: 16 colonne per 4 righe. Con 4 righe non si
cercano sagome: il sensore guarda lungo il cordolo e ogni colonna è una fetta di marciapiede.

- **Colonna calda:** almeno un punto sopra la temperatura ambiente (mediana dell'immagine) di 3 °C.
- **Zone:** `calib_thermal.json` dice quali colonne guardano quale zona (`waiting_zone_left`, `crosswalk`,
  `waiting_zone_right`). Senza quel file si usa `calib_thermal.example.json`.
- **Modalità notte:** l'immagine della camera è buia (luminosità media sotto 50) da più di 5 s. Si esce con la
  stessa attesa.
- **Recupero:** di notte, calore in una zona senza nessuna persona vista lì dalla camera per almeno 0,5 s diventa
  un "pedone non classificato", trattato come vulnerabile (`v_ped` 0,8 m/s).
- **Conferma:** una persona vista dalla camera senza calore nella sua zona, di notte, viene segnata come non
  confermata. Resta comunque protetta: per ignorarla va attivato `thermal.drop_unconfirmed`.
- I dati arrivano dal microcontrollore con le righe C5 `thermal` (64 temperature). Questo percorso non è ancora
  provato sul sensore vero.

## Eventi (contratto C3)

Dalle traiettorie, senza modelli video. Ogni evento esce una volta sola, sul terminale e nei file C3.

| Evento | Regola |
|---|---|
| `crossing` | attraversamento di una linea di conteggio, con `attrs` per i pedoni e `coco` per gli animali |
| `near_miss` | veicolo diretto verso un pedone o un animale con TTC < 1 s, oppure passaggio sullo stesso punto a meno di 1 s di distanza (PET) |
| `incident` `collision` | due tracce a meno di 1 m, entrambe ferme, una delle due era sopra 3 m/s meno di 1,5 s prima |
| `incident` `person_down` | box più largo che alto (rapporto > 1,2) per più di 3 s in carreggiata |
| `incident` `hard_brake` | decelerazione oltre 6 m/s² |
| `incident` `vehicle_on_crosswalk` | veicolo fermo sulle strisce per più di 10 s |
| `yield` | per ogni veicolo arrivato con un pedone in attesa: ha rallentato sotto 2 m/s prima delle strisce? |
| `status` | ogni 5 s: stato, FPS, ms per fase, conteggi |

A schermo e a fine corsa: yield rate, near-miss e incidenti.

## Conteggio

- **Ruoli:** `pedestrian`, `cyclist`, `motorcyclist`, `car`, `bus`, `truck`, `animal`, `bird`. Un ciclista è una
  persona sovrapposta a una bici (IoU > 0,3, persona più in alto); la bici con il suo ciclista diventa `ridden` e
  non si conta. Il ruolo di una traccia è quello della maggioranza dei suoi frame.
- **Linee** (in `calib.json`, coordinate normalizzate 0–1):
  - `ped`, lungo le strisce a metà carreggiata: conta `pedestrian`, `cyclist`, `animal`;
  - `veh`, trasversale alla corsia: conta `car`, `bus`, `truck`, `motorcyclist`, `cyclist`.
- **Niente doppioni:** conta il punto in basso al centro del box, servono 3 frame oltre la linea, e ogni traccia
  conta al massimo una volta per verso su ciascuna linea.
- **Tracce valide:** una traccia conta dopo 5 frame (specifica). Nei profili della scheda (`unoq`, `--emulate-unoq`)
  ne bastano 2: cinque frame sarebbero mezzo secondo, e un'auto passerebbe la linea prima di contare.
- **Una linea conta solo tra i suoi due estremi:** chi passa oltre la fine del segmento non viene contato.
  Conviene disegnarla più lunga del necessario. Le coordinate possono uscire dall'immagine (meno di 0, più di 1).
- **Verso:** la freccia a schermo indica IN. Per scambiare IN e OUT si invertono i due punti della linea (tasto `i`
  in `calibrate.py`).
- Senza `calib.json` si usa `calib.example.json`: una linea `ped` verticale al centro, che continua oltre i bordi
  dell'immagine. Serve per provare con la webcam spostandosi da un lato all'altro.

## Prestazioni misurate

### Sulla Arduino UNO Q (10/10/2026)

Debian 13, Python 3.13, onnxruntime 1.30 solo CPU, input 416x256 (budget 320 px). Scheda senza altri programmi.

Catena completa su un video di prova 720p con molta gente (`scripts/bench.py`):

| Impostazione | detect | track | totale per frame | FPS |
|---|---|---|---|---|
| 320 px, 4 thread, detector a ogni frame | 148 ms | 24 ms | 172 ms | 5,8 |
| 320 px, 3 thread | 143 ms | 24 ms | 166 ms | 6,0 |
| 256 px, 3 thread | 95 ms | 19 ms | 114 ms | 8,8 |
| **320 px, 3 thread, detector un frame su due (profilo `unoq`)** | 139 ms | 24 ms | 82 ms in media | **12,3** |

Con la camera vera della scheda (IMX219 su CSI, scena vuota), profilo `unoq`: **9,2 FPS end-to-end**, detect 129 ms,
track 1 ms. Obiettivo della specifica: almeno 8.

- **Perché un frame su due e non 256 px:** sul video di Torino, a parità di carico, 256 px conta 8 veicoli,
  320 px con il detector un frame su due ne conta 16 (riferimento a 30 FPS e 512 px: 35).
- **Tre thread e non quattro:** il quarto core serve a camera, tracker e al resto; con quattro va uguale o peggio.
- **La camera costa** circa il 20% di un core a 10 letture al secondo.
- **Con l'app di App Lab che tiene aperta la camera** (140% di CPU) il detector a ogni frame scendeva a 3,1 FPS.

### Su PC

Su PC (Apple M1, onnxruntime solo CPU). `--emulate-unoq` limita FPS e thread ma non rallenta i core: questi numeri
**non** prevedono la velocità sulla UNO Q.

Detector, 4 thread, stessi 300 frame alternati tra le due dimensioni:

| Input | detect (mediana / p95) |
|---|---|
| 320 px (default) | 11,5 / 15,3 ms |
| 416 px | 17,6 / 24,3 ms |

Il 320 costa il 65% del 416. Il tracker pesa 0,5–0,7 ms.

Webcam, input 416 px (prima del passaggio a 320):

| Modalità | detect (media / p95) | FPS end-to-end |
|---|---|---|
| profilo `pc` | 12,7 / 17,4 ms | 26,6 (la webcam ne dà circa 30) |
| `--emulate-unoq` | 16,9 / 24,0 ms | 9,8 (limite imposto: 10) |

## Risoluzione: forma dell'immagine e zona d'interesse

Provando su video reali il limite principale è risultato la dimensione dei pedoni: in un'inquadratura larga, a
320 px, una persona lontana occupa una decina di pixel e non viene vista. Due rimedi, senza costo in più:

- **Input a forma di immagine** (`model.match_aspect`, attivo): lo stesso numero di pixel di 320x320, ma con le
  proporzioni dell'immagine (416x256 per un 16:9). Niente pixel sprecati in bordi vuoti: sui video di prova le
  persone trovate sono circa il doppio, con lo stesso tempo di calcolo.
- **Zona d'interesse** (`"roi": [x0, y0, x1, y1]` in `calib.json`, oppure `calibrate.py --roi`): il detector guarda
  solo la parte dell'immagine che serve, cioè le strisce e la strada prima. Gli oggetti diventano più grandi a
  parità di costo. Sul video di New York, pedoni trovati sulle strisce per frame: 3,4 sull'immagine intera,
  5,1 sulla fascia delle strisce, 8,8 portando il budget a 416.

La regola pratica per chi monta la camera: le strisce e le zone d'attesa devono riempire l'inquadratura.

## Modello

`scripts/get_model.sh` scarica il file ufficiale `yolox_nano.onnx`, che dichiara un input fisso a 416 px, e crea
`yolox_nano_dynamic.onnx` con `scripts/make_dynamic_model.py`. La copia ha gli stessi pesi e la dimensione d'ingresso
libera: a 416 px dà un output identico all'originale, e accetta anche 320 px (`model.input_size` in `config.yaml`,
multiplo di 32). Sulla UNO Q si copia la cartella `models/` già pronta dal PC.

## Dipendenze

A runtime (`requirements.txt`, versioni fissate): numpy 2.4.6, onnxruntime 1.30.0, opencv-python 4.14.0.94
(variante headless su Linux aarch64, scelta in automatico), supervision 0.30.5, pyyaml 6.0.3.
Niente torch né ultralytics. Ogni pacchetto ha la wheel per Linux aarch64.

- supervision installa anche scipy, matplotlib, pillow, av, requests e tqdm: l'ambiente pesa circa 490 MB.
- supervision va tenuto sotto la 0.31: lì `sv.ByteTrack` viene rimosso.
- pyserial arriva quando serve (attuatore seriale).

Per lo sviluppo (`requirements-dev.txt`): pytest 9.1.1 e onnx 1.23.0 (serve solo a preparare il modello, non va sulla scheda).

## Versione di Python

- Sviluppo: Python 3.12 su macOS Apple Silicon.
- Le versioni fissate funzionano con Python 3.11, 3.12 e 3.13.
- UNO Q: il `python3` di Debian dentro un venv (il pip di sistema è bloccato). La versione va letta sulla scheda:
  è la questione aperta 9 in DECISIONS.md.

## Regole della cartella

- Tutte le soglie stanno in `config.yaml`, nessun numero nel codice.
- Commenti nel codice in inglese.
- Firmware, centralina e dashboard non sono in questa cartella: qui si usano i contratti e un `SimActuator` locale.
