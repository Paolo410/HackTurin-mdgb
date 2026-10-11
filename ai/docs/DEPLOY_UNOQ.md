# Portare `ai/` sulla Arduino UNO Q

**Provato sulla scheda il 10/10/2026:** copia, ambiente Python, camera vera, 9,2 FPS, e con l'app `mdgb` avviata
il semaforo comandato attraverso il Bridge (rosso d'urgenza, fail-safe): vedi `DECISIONS.md`, punto 33.
**Non ancora provato:** una richiesta nata da una scena vera (serve la calibrazione), la pagina del tecnico dal
telefono, l'avvio automatico.

Per avviare l'una o l'altra app (ne gira una sola alla volta, perché caricano lo sketch sul microcontrollore):
`arduino-app-cli app start user:mdgb` oppure `arduino-app-cli app start user:test`, o da App Lab.

Ordine deciso dal team: **prima sketch + visione**, poi la rete verso la centrale (Lorenzo).

**Com'è la scheda dall'11/10 notte** (`DECISIONS.md`, punti 37–42):
- app `mdgb`, app predefinita di App Lab: sketch con il cicalino muto per il tecnico e `mdgb_link.py` di Lorenzo nel
  `main.py`. Lo sketch non manda `mcu_event`: urto, badge e fail-safe passano da `mdgb_link.py`;
- visione come servizio `mdgb-ai` e rete come servizio `mdgb-comms` (broker sul PC di Lorenzo): partono da soli;
- tutti gli eventi in una cartella sola, `~/ArduinoApps/mdgb/data/c3`, scelta da
  `push_to_arduino.sh --bridge --applab mdgb`:
  - `c3-*.jsonl`: la visione;
  - `applab-*.jsonl`: sensori, urto, badge e fail-safe, scritti da `mdgb_link.py`.
- Backup del vecchio sketch e del `main.py` in `~/HackTurin-mdgb/backups/`.

## Come è fatto il sistema sulla scheda

| Cosa | Dove gira | Di chi |
|---|---|---|
| Sketch: semaforo, buzzer, sensori, RFID, antifurto | microcontrollore | Salvatore |
| `main.py` dell'app di App Lab: riceve i dati dello sketch | container di App Lab | Salvatore |
| App `mdgb` in `~/ArduinoApps/` (10/10): copia di `test` con lo sketch che ascolta la visione e senza camera | come sopra | proposta di Paolo, da rivedere con Salvatore |
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
cat /etc/os-release; python3 --version    # trovato: Debian 13, Python 3.13.5
nproc; free -h; df -h ~                   # trovato: 4 core, 3,6 GB di RAM, 16 GB liberi
ls ~/ArduinoApps; arduino-app-cli app list   # l'app di Salvatore e se è avviata
cam -l; ls -l /var/run/arduino-router.sock   # la camera vista da libcamera; il router (scrivibile da tutti)
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
   sulla scheda e un paio di minuti. Sulla scheda manca `python3-venv` e `sudo` chiede la password: lo script
   crea l'ambiente senza pip e ci installa dentro con il pip di sistema, senza toccare nient'altro;
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

La camera della scheda è un sensore **IMX219 su CSI**, letto da libcamera: non è una webcam e OpenCV da solo non la
apre. Basta lanciare il programma con `libcamerify` davanti (pacchetto `libcamera-v4l2`, già sulla scheda): OpenCV
la vede come `/dev/video0`, 632x480.

- Se l'app di App Lab è avviata con il vecchio `main.py`, la camera è occupata e la scheda è molto più lenta
  (quel programma usa da solo il 140% di CPU): va usato il `main.py` senza camera.
- Una webcam USB, se mai servisse, si apre senza `libcamerify` con il suo indice.

## 6. Prova a mano, nell'ordine

Sulla scheda, in `~/HackTurin-mdgb/ai`:

```bash
libcamerify ~/venv/bin/python scripts/bench.py 0 --profile unoq     # 1. ms per fase con la camera vera
libcamerify ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator sim --operator-port 8090                             # 2. visione senza semaforo
libcamerify ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator bridge --operator-port 8090                          # 3. con il semaforo (serve lo sketch con mdgb_line)
```

Cosa guardare:

1. **FPS:** misurati 9,2 end-to-end con il profilo `unoq` (320 px, detector un frame su due). I numeri sono in
   `ai/README.md`, "Prestazioni misurate".
2. **Semaforo:** fermando la visione (`Ctrl+C`) torna al ciclo normale entro mezzo secondo. Con un bambino non
   accompagnato o un animale libero scatta il rosso dopo un giallo breve; con chi cammina piano il rosso dei
   veicoli dura di più. Servono la calibrazione e lo sketch nuovo.
3. **Tecnico:** dal telefono sulla stessa Wi-Fi, `http://<scheda>:8090/` dice "BLOCCATO". Passando il badge chiede
   utente e password, da dare entro 2 minuti; dopo il login mostra numeri e vista dal vivo fino a "Esci". Cinque
   password sbagliate: va ripassato il badge. Dal badge al logout il cicalino non suona (serve lo sketch con `tech`).
4. **Antifurto:** scuotendo la scheda, sulla pagina compare "ultimo urto N s fa". La visione continua a lavorare.

Se `--actuator bridge` scrive "no sketch provides mdgb_line", sulla scheda c'è ancora lo sketch senza `mdgb_line`:
la visione gira lo stesso, il semaforo fa il suo ciclo normale e badge e antifurto non arrivano alla visione.

## 7. Accendere e spegnere la visione

**Sulla scheda della demo la visione è un servizio dall'11/10** (`mdgb-ai`, parte da sola all'accensione):
`sudo systemctl restart mdgb-ai` (o `stop` / `start`), log con `journalctl -u mdgb-ai -f`. Dopo un aggiornamento
del codice: `push_to_arduino.sh ... --bridge --applab mdgb`, poi `sudo sh ~/mdgb-tools/installa_servizio_visione.sh`.
`run_vision.sh` serve solo dove il servizio non è installato: se il servizio è attivo, non parte.

### Benchmark e prove su un video registrato, come se arrivasse dalla camera

I video di prova e le calibrazioni stanno in `~/HackTurin-mdgb/ai/samples/` sulla scheda (copiati a mano: non li porta
`push_to_arduino.sh`). Senza `sudo`, da `~/HackTurin-mdgb/ai`:

```bash
deploy/run_vision.sh video samples/Torino_1.mp4 --calib samples/calib/torino_1.json   # in loop, finché non torni alla camera
deploy/run_vision.sh video samples/Torino_night_1.mp4 --once                          # una passata, poi la tabella dei tempi
deploy/run_vision.sh camera                                                            # di nuovo la camera
journalctl -u mdgb-ai | grep -a -A8 "^pass "                                          # tempi per fase di ogni passata
```

- Tutto il resto funziona come con la camera: comandi al semaforo, pagina del tecnico (vista dal vivo con i riquadri),
  eventi in centrale. Per non muovere il semaforo vero: in fondo al comando `--actuator sim`.
- Gli eventi del video arrivano in centrale come `nodo01`: le statistiche del giorno li comprendono.
- Il video va a velocità reale: se la scheda è più lenta, salta i fotogrammi in ritardo come farebbe con la camera
  (`source.file_drop_late`).
- **Dalla pagina del tecnico** (dopo badge e login), solo quando la sorgente è un video: pulsanti *Video prima* /
  *Video dopo* (i video della stessa cartella, ognuno con la sua calibrazione da `samples/calib/` se c'è) e
  *Indietro* / *Avanti* di 10 s (`operator.video_seek_s`). Il cambio avviene dentro la visione: la sessione del
  tecnico resta aperta, tracce e conteggi ripartono per la scena nuova. Con la camera i pulsanti non ci sono.

A mano, senza `sudo`, in background (resta accesa anche chiudendo ssh):

```bash
ssh arduino@<scheda> '~/HackTurin-mdgb/ai/deploy/run_vision.sh start'    # stop | status | log
```

Il log è in `~/HackTurin-mdgb/logs/vision.log`. Dopo aver cambiato credenziali, calibrazione o codice: `stop`, poi `start`.

### Avvio automatico all'accensione

```bash
./ai/deploy/push_to_arduino.sh arduino@<scheda> --bridge --service    # chiede la password di sudo
ssh arduino@<scheda> 'journalctl -u mdgb-ai -f'
```

## 8. Pagina del tecnico

`--operator-port 8090`. Dal telefono, via Wi-Fi, sulla stessa rete della scheda.

- **Accesso in due passi:** badge sul lettore, poi utente e password entro 2 minuti (`operator.login_s`). La
  sessione resta aperta finché il tecnico non preme "Esci" (`operator.session_s: 0`). Login e logout consumano il
  badge: per rientrare va ripassato.
- **Cicalino muto mentre c'è il tecnico:** dal badge al logout, o ai 2 minuti se non entra, il comando C1 porta
  `"tech": true` e lo sketch non suona (solo il bip di conferma del badge). Lo sketch tiene da solo i 2 minuti dal
  badge, anche senza visione; senza heartbeat il campo non vale più e il cicalino torna attivo.
- **Cosa mostra**, dopo l'accesso, in tre schede:
  - **Stato:** una frase in cima ("Tutto funziona", "Una cosa da controllare"...), poi le parti da sistemare con il
    "cosa fare" e una riga per ogni parte che funziona (`smartcrossing/health.py`): camera, riconoscimento,
    collegamento con lo sketch, app di App Lab e sketch, temperatura e umidità, aria, luce, antifurto, lettore badge,
    salvataggio eventi. A lato il semaforo (stato della regola e motivo) e i dettagli della visione;
  - **Vista dal vivo:** la camera con i riquadri, i pulsanti dei video, i passaggi contati;
  - **Registro:** gli ultimi 100 eventi in memoria (parti del nodo, traffico, accessi e allarmi), scaricabili in testo.
  I sensori della scheda arrivano dalle righe `env` di `mdgb_link.py` ogni 10 s, che ripetono l'ultimo valore: da qui
  si vede l'app di App Lab o lo sketch che si fermano e i valori impossibili, non un singolo sensore che si stacca.
  Ogni cambio di stato di una parte va anche nel log del servizio (`journalctl -u mdgb-ai | grep diagnosi`).
- **Logo:** il segnaposto di `docs/brand/` (simbolo dentro la pagina, nessun file in più da copiare).
- **Interruttore delle immagini:** `operator.share_images: false` in `config.yaml` spegne la vista dal vivo e
  lascia solo le statistiche. È l'impostazione pensata per la produzione: nessuna immagine esce dal programma.
- **Le immagini non vengono mai salvate**: esistono in memoria solo mentre un tecnico connesso sta guardando.
- **Limite:** la pagina è HTTP in chiaro. Sulla rete locale la password viaggia non cifrata: per la strada serve
  HTTPS. Per la demo va bene, con una password usata solo qui.

## 9. Da verificare sull'hardware vero

- [x] `pip install` completo nel `~/venv`: due minuti, numpy 2.4.6, onnxruntime 1.30.0, opencv 4.14.0, supervision 0.30.5.
- [x] FPS e ms per fase: vedi `ai/README.md`.
- [x] Camera letta da OpenCV fuori da App Lab: sì, con `libcamerify`.
- [x] L'utente `arduino` può usare `/var/run/arduino-router.sock`: sì.
- [x] Sketch con `mdgb_line`: comandi e heartbeat ricevuti, rosso d'urgenza, fail-safe in circa mezzo secondo.
- [x] Antifurto e sensori nella cartella degli eventi, scritti da `mdgb_link.py`; la rete li porta alla centrale.
- [x] Rete verso la centrale: MQTT verso il PC di Lorenzo, heartbeat ogni 10 s con stato e FPS della visione.
- [x] Backup Bluetooth: la centrale lo riceve (−41 dBm) quando la rete cade, 0 eventi persi (`btmgmt` corretto in `comms/`).
- [x] Avvio automatico dopo un riavvio della scheda: visione, rete e app `mdgb`.
- [ ] Badge → pagina → login dal telefono, con il cicalino muto fino all'uscita.
- [ ] Pagina del tecnico dal telefono: login, costo della vista dal vivo sugli FPS, tempo del login.
- [ ] Temperatura e rallentamenti dopo 10 minuti di funzionamento.
- [ ] Visione e app di App Lab insieme: carico della CPU e memoria.
- [ ] Avvio automatico dopo un riavvio della scheda.
- [ ] Immagine della camera: di sera è scura e l'elaborazione di libcamera non è tarata per questo sensore.
