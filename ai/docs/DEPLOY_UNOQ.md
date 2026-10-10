# Portare `ai/` sulla Arduino UNO Q

**Non ancora provato sulla scheda.** Provato sul PC: il pacchetto che va sulla scheda, insieme a
`comms/actuators.py` di Lorenzo e alla libreria ufficiale del Bridge, contro un router finto (comandi, heartbeat,
righe del microcontrollore). Le voci "da verificare" vengono dalla documentazione o da fonti non ufficiali.

## Come è fatto il sistema sulla scheda

| Cosa | Dove gira | Di chi |
|---|---|---|
| Sketch: semaforo, buzzer, sensori, RFID | microcontrollore | Salvatore |
| `main.py` dell'app di App Lab: riceve i dati dello sketch e li scrive su file | container di App Lab | Salvatore, Lorenzo |
| **Visione** (`smartcrossing.app`): camera, regole, comandi al semaforo, pagina del tecnico | Linux, servizio `mdgb-ai` | Paolo |
| Rete (`comms/node/main.py`): porta gli eventi alla centrale | Linux, servizio `mdgb-comms` | Lorenzo |

- **La visione sta fuori da App Lab**, in `~/venv`: stesso codice provato sul PC, dipendenze isolate da quelle di
  App Lab. Parla con lo sketch attraverso il servizio `arduino-router` della scheda (`--actuator bridge`).
- **La camera la apre solo la visione.** Il `main.py` dell'app di App Lab non deve aprirla: una camera non può
  essere letta da due programmi insieme.
- **Gli eventi stanno in una sola cartella**, `~/ArduinoApps/<app>/data/c3/`: lì scrivono la visione (`c3-*.jsonl`),
  l'app di App Lab (`applab-*.jsonl`) e `comms/actuators.py` (`mcu-*.jsonl`); lì legge la rete. La visione legge
  dagli `applab-*.jsonl` l'urto, il badge del tecnico e i sensori.

## 1. Accesso alla scheda

```bash
ssh arduino@<nome-della-scheda>.local      # utente arduino, password scelta al primo avvio con App Lab
```

Per non digitare la password a ogni copia: `ssh-copy-id arduino@<nome-della-scheda>.local` (una volta).
Se ssh avvisa che la chiave dell'host è cambiata, non ignorarlo: controlla sulla scheda (terminale di App Lab) con
`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` che l'impronta sia quella mostrata, poi
`ssh-keygen -R <indirizzo>` sul PC.

Controlli da fare subito sulla scheda:

```bash
cat /etc/os-release; python3 --version    # atteso: Debian 13, Python 3.13 (requirements.txt va bene da 3.11 a 3.13)
nproc; free -h; df -h ~                   # 4 core, 2 o 4 GB di RAM; l'ambiente Python pesa circa 500 MB
ls ~/ArduinoApps; arduino-app-cli app list   # nome della cartella dell'app di Salvatore e se è avviata
ls -l /dev/video* /var/run/arduino-router.sock
```

## 2. Copiare la visione

Dal PC, nella root del repo. Si copia solo quello che gira sulla scheda (3,5 MB), non si fa `git clone`: il repo è
privato e servirebbe un token sulla scheda.

```bash
./ai/deploy/push_to_arduino.sh arduino@<scheda> --applab <cartella-dell'app>
```

Copia `smartcrossing/`, `config.yaml`, il modello, la calibrazione (se c'è `ai/calib.json`), crea `~/venv` e
installa `requirements.txt` (serve Internet la prima volta). Alla fine stampa versioni e avvisi: camera assente,
router non raggiungibile, cartella degli eventi non scrivibile. Rilanciarlo aggiorna il codice.
Senza ssh: `--pack` crea `mdgb-ai.tar.gz` da copiare a mano.

Per comandare il semaforo serve anche `comms/` sulla scheda: lo porta Lorenzo con
`./comms/deploy/push_to_arduino.sh arduino@<scheda> --applab <cartella>` (stesso `~/venv`).

## 3. Calibrazione

Sulla scheda non c'è finestra. Si calibra sul PC su un video o un fotogramma ripreso dalla camera montata
(`scripts/calibrate.py --source ...`), si salva `ai/calib.json` e si rilancia `push_to_arduino.sh`.
Senza `calib.json` la visione conta i passaggi ma non misura velocità e non applica le regole.

## 4. Camera

- **Webcam USB** con hub USB-C alimentato: `--source 0` apre `/dev/video0` (da verificare l'indice).
- Se l'app di App Lab è avviata con il vecchio `main.py`, la camera è occupata: va usato il `main.py` senza camera.

## 5. Prova a mano, nell'ordine

Sulla scheda, in `~/HackTurin-mdgb/ai`:

```bash
~/venv/bin/python scripts/bench.py 0 --profile unoq                 # 1. ms per fase: quanti FPS abbiamo davvero
MDGB_C3_DIR=$(cat .c3_dir) ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator sim --operator-port 8090                             # 2. visione senza semaforo
MDGB_C3_DIR=$(cat .c3_dir) ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator bridge --operator-port 8090                          # 3. con il semaforo (serve lo sketch con mdgb_line)
```

Cosa guardare:

1. **FPS:** obiettivo almeno 8 end-to-end a 320 px. Se non ci si arriva, in ordine: `model.detect_every_n: 2`,
   `model.input_size: 256`, `source.resize_width` più basso nel profilo `unoq`.
2. **Badge:** passando il badge compare una riga `tamper` code 3 negli `applab-*.jsonl` e la pagina
   `http://<scheda>:8090/` si apre dal telefono (stessa rete Wi-Fi). Prima del badge dice "BLOCCATO".
3. **Urto:** muovendo la scheda lo stato diventa `DEGRADED` ("nodo urtato") per 30 s o fino al badge.
4. **Semaforo:** con una persona davanti alla camera il verde dei veicoli si accorcia; fermando la visione
   (`Ctrl+C`) il semaforo torna al ciclo normale entro mezzo secondo.

Se `--actuator bridge` scrive "no sketch provides mdgb_line", sulla scheda c'è ancora lo sketch senza `mdgb_line`:
la visione continua a girare, il semaforo fa il suo ciclo normale.

## 6. Avvio automatico

```bash
./ai/deploy/push_to_arduino.sh arduino@<scheda> --applab <cartella> --service    # chiede la password di sudo
ssh arduino@<scheda> 'journalctl -u mdgb-ai -f'
```

## 7. Pagina del tecnico

`--operator-port 8090` apre una pagina con stato, motivo, FPS, tempi, conteggi, sensori e manomissione.
**Solo numeri, nessuna immagine.** Risponde per 10 minuti dopo il badge del tecnico (`operator.unlock_s`), poi si
richiude. Il badge serve anche a riarmare il nodo dopo un urto. Via Bluetooth non passerebbe un video; i numeri
alla centrale ci arrivano già con il backup BLE di Lorenzo.
Limite: la pagina è in chiaro sulla rete locale e la sola protezione è il badge. Va bene per la demo, non per la strada.

## 8. Da verificare sull'hardware vero

- [ ] `pip install` completo nel `~/venv`: tempo, spazio, versioni stampate dallo script.
- [ ] FPS e ms per fase con `bench.py`, a 320 px e 4 thread. Temperatura e rallentamenti dopo 10 minuti.
- [ ] Camera letta da OpenCV fuori da App Lab (`/dev/video0`).
- [ ] L'utente `arduino` può usare `/var/run/arduino-router.sock`.
- [ ] La visione può scrivere in `~/ArduinoApps/<app>/data/c3/` (cartella creata dal container di App Lab).
- [ ] Sketch con `mdgb_line`: comandi e heartbeat ricevuti, fail-safe entro 0,5 s.
- [ ] `ai`, `comms` e l'app di App Lab insieme: carico della CPU e memoria.
- [ ] Avvio automatico dopo un riavvio della scheda.
