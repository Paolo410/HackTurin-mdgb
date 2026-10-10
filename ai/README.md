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

## Stato

| Milestone | Contenuto | Stato |
|---|---|---|
| AI-M1 | sorgente video + detector + tracker + overlay, `bench.py` | fatto |
| AI-M2 | conteggio per direzione + ciclista/motociclista | fatto |
| AI-M3 | calibrazione, velocità, attributi, regole, `SimActuator` | da fare |
| AI-M4 | eventi, animali, logger, output C3 | da fare |
| AI-M5 | termocamera | da fare |
| AI-M6 | profilo `unoq`, prova sulla scheda, benchmark | da fare |

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
python -m smartcrossing.app --source 0 --emulate-unoq      # limiti della UNO Q: 10 FPS, 4 thread
python -m smartcrossing.app --source 0 --headless          # senza finestra, una riga di stato al secondo
python scripts/calibrate.py --source samples/video.mp4     # disegna le due linee di conteggio e salva calib.json
python scripts/bench.py samples/video.mp4                  # ms medi e p95 per fase
pytest                                                     # test, senza hardware
```

- Senza `--source` si usa il primo video in `ai/samples/` (ignorata da git); se è vuota, la webcam.
- Su macOS la prima volta va autorizzato il terminale: Impostazioni di Sistema > Privacy e sicurezza > Fotocamera.
- `--site`, `--actuator` e `--thermal` sono già accettati ma non hanno effetto fino alle rispettive milestone.
- **Non tenere il repo in una cartella sincronizzata** (Desktop o Documenti con iCloud, OneDrive, Dropbox): il
  virtualenv e `.git` vengono spostati nel cloud e l'avvio resta bloccato.

A schermo: un box per traccia con `#ID ruolo punteggio` (grigio finché la traccia non ha 5 frame), le linee di
conteggio con la freccia del verso IN, i conteggi, FPS e millisecondi per fase. `rules` e `act` mostrano `-` fino
ad AI-M3. Ogni attraversamento contato viene anche stampato sul terminale.

## Conteggio

- **Ruoli:** `pedestrian`, `cyclist`, `motorcyclist`, `car`, `bus`, `truck`, `animal`, `bird`. Un ciclista è una
  persona sovrapposta a una bici (IoU > 0,3, persona più in alto); la bici con il suo ciclista diventa `ridden` e
  non si conta. Il ruolo di una traccia è quello della maggioranza dei suoi frame.
- **Linee** (in `calib.json`, coordinate normalizzate 0–1):
  - `ped`, lungo le strisce a metà carreggiata: conta `pedestrian`, `cyclist`, `animal`;
  - `veh`, trasversale alla corsia: conta `car`, `bus`, `truck`, `motorcyclist`, `cyclist`.
- **Niente doppioni:** conta il punto in basso al centro del box, servono 3 frame oltre la linea, e ogni traccia
  conta al massimo una volta per verso su ciascuna linea.
- **Una linea conta solo tra i suoi due estremi:** chi passa oltre la fine del segmento non viene contato.
  Conviene disegnarla più lunga del necessario. Le coordinate possono uscire dall'immagine (meno di 0, più di 1).
- **Verso:** la freccia a schermo indica IN. Per scambiare IN e OUT si invertono i due punti della linea (tasto `i`
  in `calibrate.py`).
- Senza `calib.json` si usa `calib.example.json`: una linea `ped` verticale al centro, che continua oltre i bordi
  dell'immagine. Serve per provare con la webcam spostandosi da un lato all'altro.

## Prestazioni misurate

Su PC (Apple M1, onnxruntime solo CPU). `--emulate-unoq` limita FPS e thread ma non rallenta i core: questi numeri
**non** prevedono la velocità sulla UNO Q. I numeri veri arrivano con AI-M6, sulla scheda.

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
