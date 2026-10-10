# Portare `ai/` sulla Arduino UNO Q

**Non ancora provato sulla scheda.** Provato sul PC: il pacchetto che va sulla scheda, insieme al file di
Lorenzo che parla con lo sketch e alla libreria ufficiale del Bridge, contro un router finto (comandi, heartbeat,
righe del microcontrollore). Le voci "da verificare" vengono dalla documentazione o da fonti non ufficiali.

Ordine deciso dal team: **prima sketch + visione**, poi la rete verso la centrale (Lorenzo).

## Come è fatto il sistema sulla scheda

| Cosa | Dove gira | Di chi |
|---|---|---|
| Sketch: semaforo, buzzer, sensori, RFID, antifurto | microcontrollore | Salvatore |
| `main.py` dell'app di App Lab: riceve i dati dello sketch | container di App Lab | Salvatore |
| **Visione** (`smartcrossing.app`): camera, regole, comandi al semaforo, pagina del tecnico | Linux, fuori da App Lab | Paolo |
| Rete verso la centrale e backup | Linux | Lorenzo, dopo |

- **La visione sta fuori da App Lab**, in `~/venv`: stesso codice provato sul PC, dipendenze isolate da quelle di
  App Lab. Parla con lo sketch attraverso il servizio `arduino-router` della scheda (`--actuator bridge`).
- **La camera la apre solo la visione.** Il `main.py` dell'app di App Lab non deve aprirla: una camera non può
  essere letta da due programmi insieme.
- **Per parlare con lo sketch** la visione usa tre file già scritti da Lorenzo (`comms/actuators.py`, `jsonl.py`,
  `__init__.py`). Sono il collegamento visione–sketch, non la rete: li copia `--bridge`.

## 1. Accesso alla scheda

```bash
ssh arduino@<nome-della-scheda>.local      # utente arduino, password scelta al primo avvio con App Lab
```

Per non digitare la password a ogni copia: `ssh-copy-id arduino@<scheda>` (una volta).
Se ssh avvisa che la chiave dell'host è cambiata, non ignorarlo: capire prima perché (altro dispositivo che aveva
quell'indirizzo, scheda reinstallata), poi `ssh-keygen -R <indirizzo>` sul PC.

Controlli da fare subito sulla scheda:

```bash
cat /etc/os-release; python3 --version    # atteso: Debian 13, Python 3.13 (requirements.txt va bene da 3.11 a 3.13)
nproc; free -h; df -h ~                   # 4 core, 2 o 4 GB di RAM; l'ambiente Python pesa circa 500 MB
ls ~/ArduinoApps; arduino-app-cli app list   # l'app di Salvatore e se è avviata
ls -l /dev/video* /var/run/arduino-router.sock
```

## 2. Copiare la visione

**Dove si scrive:** sul PC (non sulla scheda), nel Terminale, dentro la cartella del repo.

```bash
cd ~/dev/HackTurin-mdgb
./ai/deploy/push_to_arduino.sh arduino@<scheda> --bridge
```

Cosa fa, nell'ordine:

1. impacchetta solo quello che gira sulla scheda (codice della visione, `config.yaml`, modello, calibrazione se
   c'è `ai/calib.json`: 3,5 MB) e lo copia via ssh in `~/HackTurin-mdgb/ai` sulla scheda. Niente test, video o
   documenti. Non si usa `git pull` sulla scheda: il repo è privato e servirebbe un token lì sopra;
2. con `--bridge` copia anche i tre file di Lorenzo in `~/HackTurin-mdgb/comms`;
3. sulla scheda crea l'ambiente Python `~/venv` (solo la prima volta) e installa le dipendenze. Serve Internet
   sulla scheda e qualche minuto;
4. controlla e stampa: versioni installate, camera, router, cartella degli eventi, credenziali del tecnico.

Rilanciarlo aggiorna il codice. Senza ssh: `--pack` crea `mdgb-ai.tar.gz` da copiare a mano.

## 3. Credenziali del tecnico

Sulla scheda, una volta (le scrive chi le deve conoscere; nel repo non ci sono):

```bash
cd ~/HackTurin-mdgb/ai && ~/venv/bin/python scripts/operator_login.py
```

Chiede utente e password e salva in `ai/.env` il nome e la sola impronta della password. Senza questo passo
nessuno può entrare nella pagina del tecnico.

## 4. Calibrazione

Sulla scheda non c'è finestra. Si calibra sul PC su un video o un fotogramma ripreso dalla camera montata
(`scripts/calibrate.py --source ...`), si salva `ai/calib.json` e si rilancia `push_to_arduino.sh`.
Senza `calib.json` la visione conta i passaggi ma non misura velocità e non applica le regole.

## 5. Camera

- **Webcam USB** con hub USB-C alimentato: `--source 0` apre `/dev/video0` (da verificare l'indice).
- Se l'app di App Lab è avviata con il vecchio `main.py`, la camera è occupata: va usato il `main.py` senza camera.

## 6. Prova a mano, nell'ordine

Sulla scheda, in `~/HackTurin-mdgb/ai`:

```bash
~/venv/bin/python scripts/bench.py 0 --profile unoq                 # 1. ms per fase: quanti FPS abbiamo davvero
~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator sim --operator-port 8090                             # 2. visione senza semaforo
~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator bridge --operator-port 8090                          # 3. con il semaforo (serve lo sketch con mdgb_line)
```

Cosa guardare:

1. **FPS:** obiettivo almeno 8 end-to-end a 320 px. Se non ci si arriva, in ordine: `model.detect_every_n: 2`,
   `model.input_size: 256`, `source.resize_width` più basso nel profilo `unoq`.
2. **Semaforo:** con una persona davanti alla camera il verde dei veicoli si accorcia; fermando la visione
   (`Ctrl+C`) il semaforo torna al ciclo normale entro mezzo secondo.
3. **Tecnico:** dal telefono sulla stessa Wi-Fi, `http://<scheda>:8090/` dice "BLOCCATO". Passando il badge chiede
   utente e password; dopo il login mostra numeri e vista dal vivo. Cinque password sbagliate: va ripassato il badge.
4. **Antifurto:** scuotendo la scheda, sulla pagina compare "ultimo urto N s fa". La visione continua a lavorare.

Se `--actuator bridge` scrive "no sketch provides mdgb_line", sulla scheda c'è ancora lo sketch senza `mdgb_line`:
la visione gira lo stesso, il semaforo fa il suo ciclo normale e badge e antifurto non arrivano alla visione.

## 7. Avvio automatico

```bash
./ai/deploy/push_to_arduino.sh arduino@<scheda> --bridge --service    # chiede la password di sudo
ssh arduino@<scheda> 'journalctl -u mdgb-ai -f'
```

## 8. Pagina del tecnico

`--operator-port 8090`. Dal telefono, via Wi-Fi, sulla stessa rete della scheda.

- **Accesso in due passi:** badge sul lettore, poi utente e password. La sessione dura 10 minuti dal badge
  (`operator.unlock_s`); un altro badge aggiunge tempo.
- **Cosa mostra:** stato, motivo, FPS, tempi, conteggi, sensori, ultimo urto; e la vista dal vivo della camera con
  i riquadri della visione.
- **Interruttore delle immagini:** `operator.share_images: false` in `config.yaml` spegne la vista dal vivo e
  lascia solo le statistiche. È l'impostazione pensata per la produzione: nessuna immagine esce dal programma.
- **Le immagini non vengono mai salvate**: esistono in memoria solo mentre un tecnico connesso sta guardando.
- **Limite:** la pagina è HTTP in chiaro. Sulla rete locale la password viaggia non cifrata: per la strada serve
  HTTPS. Per la demo va bene, con una password usata solo qui.

## 9. Da verificare sull'hardware vero

- [ ] `pip install` completo nel `~/venv`: tempo, spazio, versioni stampate dallo script.
- [ ] FPS e ms per fase con `bench.py`, a 320 px e 4 thread. Temperatura e rallentamenti dopo 10 minuti.
- [ ] Camera letta da OpenCV fuori da App Lab (`/dev/video0`).
- [ ] L'utente `arduino` può usare `/var/run/arduino-router.sock`.
- [ ] Sketch con `mdgb_line`: comandi e heartbeat ricevuti, fail-safe entro 0,5 s, badge e antifurto alla visione.
- [ ] Costo della vista dal vivo sugli FPS mentre un tecnico guarda (5 immagini al secondo, 480 px).
- [ ] Tempo del login sulla scheda (il controllo della password è volutamente lento: sul Mac 50 ms).
- [ ] Visione e app di App Lab insieme: carico della CPU e memoria.
- [ ] Avvio automatico dopo un riavvio della scheda.
