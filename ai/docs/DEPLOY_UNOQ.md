# Portare `ai/` sulla Arduino UNO Q

Bozza scritta sul PC, **non ancora provata sulla scheda**. Da completare con Salvatore (firmware e Bridge).
Le voci segnate "da verificare" vengono da fonti non ufficiali o dalla specifica, non da una prova nostra.

## 1. Accesso alla scheda

- Primo avvio con Arduino App Lab via USB: si sceglie nome della scheda, password e Wi-Fi.
- Poi da PC, sulla stessa rete:
  ```bash
  ssh arduino@<nome-o-ip-della-scheda>
  ```
  Utente `arduino`, password scelta al primo avvio (da verificare). Se la connessione è rifiutata, il server SSH
  va avviato sulla scheda (da verificare). In alternativa: terminale di App Lab oppure ADB via USB-C.
- Controlli da fare subito:
  ```bash
  cat /etc/os-release      # atteso: Debian 13 "trixie", arm64 (da verificare)
  python3 --version        # atteso: 3.13. Le versioni in requirements.txt vanno bene da 3.11 a 3.13
  nproc; free -h; df -h ~  # 4 core, 2 o 4 GB di RAM, spazio libero (l'ambiente Python pesa circa 500 MB)
  ```

## 2. Codice e ambiente

```bash
git clone https://github.com/Paolo410/HackTurin-mdgb.git ~/HackTurin-mdgb
python3 -m venv ~/venv          # il pip di sistema è bloccato; se manca venv: sudo apt install python3-venv
~/venv/bin/pip install -r ~/HackTurin-mdgb/ai/requirements.txt
```

- Su Linux aarch64 `requirements.txt` installa da solo la variante headless di OpenCV.
- `requirements-dev.txt` (pytest, onnx) sulla scheda non serve.
- Senza internet sulla scheda: scaricare le wheel sul PC con
  `pip download -r requirements.txt --platform manylinux2014_aarch64 --python-version 3.13 --only-binary=:all: -d wheels`
  e copiarle (da verificare).

## 3. Modello e calibrazione

Si preparano sul PC e si copiano, perché la preparazione del modello richiede `onnx`:

```bash
# sul PC, dalla root del repo
scp -r ai/models arduino@<scheda>:~/HackTurin-mdgb/ai/
scp ai/calib.json arduino@<scheda>:~/HackTurin-mdgb/ai/        # dopo aver calibrato l'inquadratura definitiva
```

La calibrazione vale per una posizione della camera: se la camera si sposta va rifatta. Sulla scheda non c'è
finestra: si calibra sul PC con un fotogramma o un video ripreso dalla camera montata, poi si copia `calib.json`.

## 4. Camera

- **Webcam USB:** la scheda ha una sola porta USB-C, quindi serve un hub USB-C alimentato. Linux la vede come
  dispositivo video standard (da verificare):
  ```bash
  ls /dev/video*
  ```
  `--source 0` apre `/dev/video0`. Se la webcam è su un altro indice, usare quello.
- **Camera IMX219 sulla Media Carrier** (quella prevista in `hardware/BOM.md`): l'immagine di serie della scheda
  non attiva il sottosistema delle camere; nelle impostazioni di App Lab c'è un'opzione per abilitare le carrier
  esterne (da verificare). Va capito come si legge da Python: se compare come `/dev/video*` funziona con
  `--source <indice>`, altrimenti serve una sorgente dedicata in `sources.py`. È la questione aperta 1.

## 5. Prova

```bash
cd ~/HackTurin-mdgb/ai
~/venv/bin/python scripts/bench.py 0 --profile unoq                                   # ms per fase
~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless --no-c3   # una riga al secondo
```

Obiettivo della specifica: almeno 8 FPS end-to-end a 320 px. Il profilo `unoq` usa input 320, 4 thread, 10 FPS.
Se non si arriva a 8 FPS, in ordine:

1. `model.detect_every_n: 2` in `config.yaml`: il detector gira un frame sì e uno no;
2. `model.input_size: 256` (il modello accetta ogni multiplo di 32): meno pixel, pedoni lontani meno visibili;
3. `source.resize_width` più basso nel profilo `unoq`.

I numeri misurati vanno riportati in `ai/README.md`, sezione "Prestazioni misurate".

## 6. Firmware e Bridge

- Caricare lo sketch di `firmware/unoq_mcu/` sul microcontrollore (Salvatore).
- `--actuator bridge` usa `BridgeActuator` di `comms/actuators.py` (milestone CM-M4 di Lorenzo, non ancora fatta).
  Fino ad allora: `--actuator sim`, oppure `--actuator serial --port ...` verso un Arduino collegato via USB.
- Prova del fail-safe: con il sistema in funzione, fermare il processo (`Ctrl+C` o `systemctl stop mdgb-ai`).
  Entro mezzo secondo il semaforo deve tornare al ciclo normale.

## 7. Avvio automatico

```bash
sudo cp ~/HackTurin-mdgb/ai/deploy/mdgb-ai.service /etc/systemd/system/
sudo systemctl enable --now mdgb-ai
journalctl -u mdgb-ai -f          # righe di stato, cambi di stato, attraversamenti
```

Gli eventi C3 finiscono in `~/HackTurin-mdgb/logs/c3/`, dove li legge `comms/`.

## 8. Da verificare sull'hardware vero

- [ ] Accesso SSH, versione di Debian e di Python.
- [ ] `pip install` completo: tempo e spazio occupato.
- [ ] FPS e ms per fase con `bench.py`, a 320 px e 4 thread. Temperatura e rallentamenti dopo 10 minuti.
- [ ] Camera: IMX219 sulla Media Carrier oppure webcam USB con hub alimentato.
- [ ] `BridgeActuator`: comandi C1 e heartbeat C2 ricevuti dal microcontrollore.
- [ ] Righe C5 dal microcontrollore: termocamera (`thermal`), urto (`tamper`), lampada (`lamp_fault`).
- [ ] Prova del fail-safe: processo fermato, semaforo al ciclo normale entro 0,5 s.
- [ ] Avvio automatico dopo un riavvio della scheda.
- [ ] `ai` e `comms` in funzione insieme: carico della CPU e memoria.

Alternativa da valutare se App Lab risulta più semplice: impacchettare tutto come app di App Lab (da verificare
sulla documentazione ufficiale).
