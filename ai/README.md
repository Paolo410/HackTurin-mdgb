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
| AI-M1 | sorgente video + detector + tracker + overlay, `bench.py` | da fare |
| AI-M2 | conteggio per direzione + ciclista/motociclista | da fare |
| AI-M3 | calibrazione, velocità, attributi, regole, `SimActuator` | da fare |
| AI-M4 | eventi, animali, logger, output C3 | da fare |
| AI-M5 | termocamera | da fare |
| AI-M6 | profilo `unoq`, prova sulla scheda, benchmark | da fare |

## Come si avvia

Non c'è ancora codice: i comandi qui sotto valgono da AI-M1 in poi.

```bash
cd ai
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
bash scripts/get_model.sh          # scarica yolox_nano.onnx in ai/models/ (ignorata da git)
python -m smartcrossing.app --source 0 --profile pc --site urbano
```

Opzioni previste: `--source 0|file.mp4|rtsp://…`, `--profile pc|unoq`, `--site urbano|lungofiume|collina`,
`--headless`, `--emulate-unoq` (10 FPS, input 320, 4 thread), `--actuator sim|serial|bridge`, `--thermal`.

Video di test: in `ai/samples/` (ignorata da git). Se è vuota si usa la webcam con `--source 0`.

Test: `pytest` dentro `ai/`, senza hardware.

## Dipendenze

A runtime: numpy, opencv-python (headless sulla UNO Q), onnxruntime, supervision, pyyaml, pyserial.
Niente torch né ultralytics. Le versioni sono fissate in `requirements.txt` (arriva con AI-M1); ogni pacchetto deve
avere la wheel per Linux aarch64.

Per lo sviluppo: pytest.

## Versione di Python

- Sviluppo: Python 3.12 su macOS Apple Silicon.
- UNO Q: il `python3` di Debian dentro un venv (il pip di sistema è bloccato). La versione va letta sulla scheda:
  è la questione aperta 9 in DECISIONS.md.

## Regole della cartella

- Tutte le soglie stanno in `config.yaml`, nessun numero nel codice.
- Commenti nel codice in inglese.
- Firmware, centralina e dashboard non sono in questa cartella: qui si usano i contratti e un `SimActuator` locale.
