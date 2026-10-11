# Istruzioni per l'assistente AI: lancio della demo e miglioramento della visione

> **Per gli umani.** In una chat nuova (anche da un altro account) incollate:
>
> ```text
> Leggi PROMPT_GIT_TEAM.md, PROMPT_SMART_CROSSING.md e ai/docs/ISTRUZIONI_AI.md e seguili.
> Sono Paolo (data scientist). Task: <lancio della demo | miglioramento del modello | ...>.
> ```

Da qui in poi le istruzioni sono per te, assistente AI. Rispondi in italiano, commenti nel codice in inglese.
Scritto l'11/10/2026 mattina, dopo la PR #22. Se qualcosa qui non torna con il codice, vale il codice: verificalo.

## 0. Regole che valgono sempre

- `PROMPT_GIT_TEAM.md` ha la precedenza: branch nuovo da `origin/main`, commit piccoli, PR in squash, mai push su main.
- **Perimetro:** Paolo è il proprietario di `ai/`. `firmware/` è di Salvatore, `comms/`, `app/` e `docs/CONTRACTS.md`
  di Lorenzo, `hardware/` di Kuzey. Per le loro aree prepara la proposta e falla girare, non modificare.
- **Sulla scheda:** chiedi prima di fermare, avviare o ricaricare l'app di App Lab o lo sketch (sono di Salvatore) e
  il servizio di rete `mdgb-comms` (di Lorenzo). La visione (`mdgb-ai`) è di Paolo.
- **Credenziali:** quelle del tecnico stanno in `ai/.env` sulla scheda; non chiederle e non scriverle. Il codice del
  badge sta solo in `arduino_secrets.h` (fuori da git): non stamparlo mai. I comandi che chiedono la password di
  `sudo` li apri nel terminale di Paolo e la scrive lui. Una password vista in chiaro nel terminale non va ripetuta.
- **Privacy:** la visione non salva mai fotogrammi. Gli strumenti di sviluppo (`evaluate.py`, `benchmark.py`)
  scrivono immagini solo in `ai/samples/` (fuori da git).
- **Mai in git:** `.env`, pesi dei modelli (`ai/models/`), video, `samples/`.
- Comandi lunghi: in background. Con ssh non usare `pkill -f <qualcosa>`: chiude anche la tua sessione ssh.

## 1. Mappa del sistema

| Cosa | Dove | Come si controlla |
|---|---|---|
| Visione (`smartcrossing.app`): camera, conteggi, regola, comandi al semaforo | scheda, servizio `mdgb-ai` | `journalctl -u mdgb-ai -f` (una riga al secondo con FPS, ms per fase, stato, conteggi) |
| Pagina del tecnico della visione (badge, poi login) | scheda, porta 8090 | `http://MDGB.local:8090/` |
| App di App Lab `mdgb`: sketch (semaforo, LCD, buzzer, sensori, RFID) e pannello | scheda, App Lab, porta 7000 | `arduino-app-cli app list` (di Salvatore) |
| Rete verso la centrale (MQTT, backup Bluetooth) | scheda, servizio `mdgb-comms` | `journalctl -u mdgb-comms -f` (di Lorenzo) |
| Centrale: broker MQTT 1883 e dashboard 8080 | PC di Lorenzo | `http://<ip del PC>:8080/` (avviata con `WEB_HOST=0.0.0.0`) |

- Scheda: `ssh arduino@MDGB.local` (l'11/10 era `192.168.169.105`; il PC di Lorenzo `192.168.169.12`). Su un'altra
  rete gli indirizzi cambiano: usa `MDGB.local` o chiedi.
- Codice della visione sulla scheda: `~/HackTurin-mdgb/ai` (copiato, **non** è un repo git), Python in `~/venv`.
- Sorgente della visione: `~/HackTurin-mdgb/ai/.vision_args`. Se esiste, la visione legge un video (prove e
  benchmark); se non c'è, la camera. Sopravvive ai riavvii.
- Tutto parte da solo all'accensione: visione, rete e app `mdgb`.

## 2. Lancio della demo, passo per passo

Fai un passo alla volta, controlla l'esito e riferiscilo prima di passare al successivo.

1. **Codice aggiornato sulla scheda.** Sul PC, dal repo aggiornato (`git switch main && git pull`):
   ```bash
   ./ai/deploy/push_to_arduino.sh arduino@MDGB.local --bridge --applab mdgb
   ```
   Copia solo la visione (e i 3 file di `comms/` che parlano con lo sketch). Con il codice arriva anche la pagina del
   tecnico nuova di Salvatore (PR #21), se non l'ha già installata lui: avvisalo.
2. **Camera al posto del video.** L'11/10 mattina la visione era lasciata sul video notturno in loop:
   ```bash
   ssh arduino@MDGB.local '~/HackTurin-mdgb/ai/deploy/run_vision.sh camera'
   ```
   Riavvia la visione senza `sudo` (systemd la fa ripartire con la nuova sorgente in pochi secondi).
3. **Controllo della visione:**
   ```bash
   ssh arduino@MDGB.local 'journalctl -u mdgb-ai -n 5 --no-pager'
   ```
   Atteso: `fps=` intorno a 6 (detector su ogni fotogramma dall'11/10), `detect=` 110–135 ms, stato `IDLE` o
   `PRESENCE`. Con il video si misurava 5,9; con la camera non è ancora stato misurato.
   - **FPS sotto 5:** qualcos'altro usa la CPU (`top`). Un'app di App Lab che apre la camera porta la visione a 3 FPS:
     la camera la deve aprire solo la visione.
   - **Ripiego** se serve più fluidità a schermo: `detect_every_n: 2` in `profiles.unoq` di `config.yaml` sulla
     scheda, poi `run_vision.sh restart`: 8,4 FPS, ma solo 4,2 analizzati e meno passaggi contati
     (`docs/BENCHMARK.md`). Dillo a Paolo prima di farlo.
   - **Camera ferma senza errori** (successo la notte dell'11/10, punto 39 di `DECISIONS.md`): si sblocca riavviando
     la scheda.
4. **Semaforo e sketch:** `arduino-app-cli app list` deve mostrare `mdgb` avviata. Se va riavviata: `stop` e poi
   `start` (`restart` risponde "Is Running"), ma **chiedi prima a Salvatore**.
5. **Centrale:** la dashboard deve mostrare il nodo collegato, con stato e conteggi che cambiano.
   - Da qualunque PC del team: `python avvia_centrale.py` dalla cartella del repo (vedi il README principale). Apre
     la centrale di `app/` e annuncia in rete il nome `mdgb-centrale.local`.
   - La scheda deve avere `MQTT_HOST=mdgb-centrale.local` in `~/HackTurin-mdgb/comms/.env` (una volta sola, poi
     `sudo systemctl restart mdgb-comms`): controlla con `grep MQTT_HOST` prima di cambiare qualcosa. Se c'è un
     indirizzo IP, qualcuno ha rilanciato `comms/deploy/push_to_arduino.sh` senza `--broker mdgb-centrale.local`:
     **mettiti d'accordo con Lorenzo prima di riscriverlo** (l'11/10 alle 11:15 due PC lo hanno cambiato insieme).
   - `journalctl -u mdgb-comms -n 3` deve dire `rete=ONLINE`. La rete è di Lorenzo: per problemi leggi
     `comms/README.md` e chiedi a lui.
6. **Calibrazione della camera montata.** Senza `ai/calib.json` la visione usa le linee d'esempio: conta, ma non
   misura velocità e non applica la regola. Appena la camera è fissata: prendi un fotogramma o un breve video dalla
   camera (con `run_vision.sh video ...` o salvandone uno a mano, solo per la calibrazione), poi sul PC
   `python scripts/calibrate.py --source <file>` (finestra: 4 angoli delle strisce, poi `--along` e `--width` in
   metri) oppure, senza finestra, `--corners "x,y x,y x,y x,y" --along A --width W --roi "x0,y0,x1,y1"`.
   Ricopia con `push_to_arduino.sh` e riavvia la visione. La zona d'interesse (`roi`) stretta su strisce, attesa e
   strada prima delle strisce fa vedere le persone più grandi allo stesso costo.
7. **Prove della demo** (checklist in `PROMPT_SMART_CROSSING.md` §11, scaletta in `docs/MDGB_DOCUMENTAZIONE.md` §13):
   - *Kill test della visione:* `ssh arduino@MDGB.local 'kill -INT $(systemctl show mdgb-ai -p MainPID --value)'`.
     Atteso: il semaforo torna al ciclo normale entro mezzo secondo (misurato 485 ms) e systemd riavvia la visione in
     circa 4 s;
   - *Kill test della rete:* procedura di Lorenzo (`comms/README.md`): backup Bluetooth, 0 eventi persi;
   - *Tecnico:* badge sul lettore, login entro 2 minuti, cicalino muto fino al logout;
   - *Benchmark dal vivo:* `run_vision.sh video samples/Torino_1.mp4 --calib samples/calib/torino_1.json` e i
     pulsanti video prima/dopo nella pagina del tecnico. **Alla fine torna alla camera** (passo 2).
8. **Numeri per il pitch:** `docs/BENCHMARK.md`, sezione "In breve" (pedoni 13 su 23, veicoli 47 su 77, verso giusto
   100%, nessun doppione; 17 su 17 dove la camera vede bene la linea). Pagina da mostrare:
   https://claude.ai/artifact/4tZEMS17r6mBMoujJidXiD (privata: Paolo la deve condividere).

## 3. Cosa è stato fatto la notte del 10–11/10 sulla visione

Dettagli e numeri: `docs/BENCHMARK.md` e i punti 42–48 di `DECISIONS.md`. In sintesi:

- **Tracking** (`smartcrossing/tracking.py`, `counting.py`):
  - `_ByteTrack` restituisce ogni traccia con il box con cui è stata associata: `sv.ByteTrack` scartava le auto
    veloci, che erano seguite ma mai contate;
  - box allargati del 50% per l'associazione (`tracking.box_buffer`, buffered IoU del tracker C-BIoU);
  - lato della linea ricordato per 30 rilevamenti (`counting.side_memory`; supervision lo dimenticava dopo 4);
  - detector su ogni fotogramma sulla scheda (`profiles.unoq`);
  - ricucitura delle tracce attraverso la linea (`counting.stitch_s`), nel codice ma spenta.
- **Benchmark** (`scripts/benchmark.py`, `benchmarks/`):
  - riferimento YOLOX-l a 960 px rivisto a vista;
  - emulazione agli FPS misurati sulla scheda;
  - confronto nel punto in cui si supera la linea;
  - solo video a camera ferma.
- **Provati e scartati:** INT8 (più lento sul Cortex-A53), PP-PicoDet-S (2,2 volte più lento), 416 px (3,8 FPS),
  tracce nuove da 0,30, conferma dopo 2 rilevamenti, correzione gamma.
- **Risultato** (8 video a camera ferma): pedoni da 9 a 13 su 23, ciclisti da 0 a 2 su 4, veicoli da 24 a 47 su 77;
  verso giusto 100% e nessun conteggio in più, prima e dopo.

## 4. Come continuare a migliorare il modello

### Metodo (non saltarlo)

1. **Un cambio alla volta**, come variante in `benchmarks/variants.json` (gli `args` sono opzioni di
   `scripts/evaluate.py`, per esempio `--set tracking.box_buffer=0.5`). Si giudica su `score` contro `scheda_nuova`.
2. **FPS veri della scheda.** Ogni variante va emulata agli FPS che la scheda fa davvero con quell'impostazione. Se
   cambi il costo del detector (dimensione, modello), misuralo sulla scheda prima: una configurazione in un file
   `/tmp/config_x.yaml` sulla scheda, `run_vision.sh video samples/Torino_1.mp4 --calib samples/calib/torino_1.json
   --config /tmp/config_x.yaml`, 45 s, poi `journalctl -u mdgb-ai --since "-25s" | grep fps`. Poi rimetti la sorgente
   com'era (`.vision_args`) e riavvia.
3. **Solo camere ferme** per il conteggio (`"fixed": true` in `benchmarks/videos.json`).
4. **Riferimento controllato a vista:** dopo ogni variante promettente, `review` sui disaccordi e `judge` per
   annotare dove aveva ragione la scheda. Un solo `judge` per video con tutte le decisioni, poi di nuovo `review`:
   gli indici `r…`/`g…` cambiano dopo ogni `judge`.
5. **Numeri onesti:** pochi passaggi (27 persone, 77 veicoli), quindi non scegliere per +1. Riporta sempre prima e
   dopo, anche i conteggi in più e il verso.
6. **Test:** `cd ai && python -m pytest -q tests` deve restare verde; ogni comportamento nuovo con il suo test.

```bash
cd ai
python scripts/benchmark.py run <variante>            # ~1 min per variante sul Mac
python scripts/benchmark.py score scheda_nuova <variante>
python scripts/benchmark.py review <variante> torino_1 [--kind pedestrian]
python scripts/benchmark.py judge <variante> torino_1 --add g3 --remove r5 --note "cosa si vede"
python scripts/benchmark.py run riferimento --only <video> --force   # riferimento, ~10 min per 5 minuti di video (CoreML)
python scripts/benchmark.py reference                 # dopo un nuovo riferimento (conserva le revisioni)
```

### Trappole note

- **Video di Torino illeggibili sul Mac** ("Operation not permitted", attributo `com.apple.macl` di macOS dall'11/10
  mattina). Le copie sulla scheda sono intatte: `scp arduino@MDGB.local:HackTurin-mdgb/ai/samples/Torino_1.mp4 <cartella>/`
  e poi `MDGB_VIDEOS=<cartella>` davanti ai comandi di `benchmark.py`. Non provare a togliere l'attributo: è una
  protezione di sistema, se serve la sblocca Paolo.
- Due processi che decodificano lo stesso video HEVC insieme sul Mac a volte falliscono: lancia i `run` uno alla
  volta.
- `--emulate-unoq` limita thread e FPS ma il Mac resta più veloce: i tempi si misurano solo sulla scheda.
- Il riferimento usa CoreML (`models/yolox_l_960.onnx`, da `scripts/make_dynamic_model.py --fixed 960` sul modello
  YOLOX-l): gira solo su Mac.

### Prossimi passi, in ordine

1. **Più dati veri (alto valore, 1–2 ore).**
   - Calibrare Torino_4 (220 s, molte persone sulle strisce) e Torino_7. Le loro inquadrature sono diverse da
     Torino_3 e Torino_1: servono calibrazioni nuove in `samples/calib/` e le righe in `benchmarks/videos.json`.
   - Poi riferimento, `review` e `judge`.
   - Raddoppia il campione dei pedoni.
2. **Benchmark con la camera della scheda (alto valore).**
   - Appena la camera è montata, registrare 2–3 minuti di passaggi veri, solo per il benchmark e fuori da git.
   - Poi calibrazione, riferimento e confronto.
   - Sono i numeri che contano davvero per la demo.
3. **Zona d'interesse stretta (`roi`) per la camera montata (basso costo).**
   - Solo strisce, attesa e strada prima: le persone appaiono più grandi a parità di calcolo.
   - Misurarlo con una variante che cambia solo la `roi`.
4. **Rivalutare le opzioni spente quando il campione è più grande:** `tracking.track_activation_threshold` 0,2 e
   `counting.stitch_s` 1,5. Insieme davano veicoli 49/77 invece di 47 ma un conteggio in più.
5. **Persone sotto i 20 px (il limite vero di YOLOX-nano a 320 px).**
   - La strada è adattare il detector alla nostra inquadratura: distillazione da YOLOX-l (pseudo-etichette sui video,
     addestramento di YOLOX-nano con il codice ufficiale Megvii, Apache-2.0, in un ambiente a parte con torch: mai a
     runtime).
   - Dividere per video tra addestramento e prova, altrimenti i numeri non valgono.
   - È lavoro di più ore: proponilo a Paolo, non avviarlo da solo durante la demo.
6. **Da non riprovare sulla UNO Q:**
   - INT8: la CPU non ha le istruzioni a 8 bit;
   - PicoDet: troppo lento;
   - 416 px su ogni fotogramma: troppo lento per gli oggetti veloci.
   - Si possono riprovare su una scheda con Cortex-A55/A76 o con NPU.

## 5. Fine di ogni task

Come in `PROMPT_GIT_TEAM.md`:
- comando per provarlo e risultato atteso;
- commit e PR;
- 3–5 righe da incollare nella chat del team.

Aggiorna `DECISIONS.md` (punto nuovo, numerato dopo l'ultimo) e, se cambiano i numeri, `docs/BENCHMARK.md`, la
sezione 7.9 di `docs/MDGB_DOCUMENTAZIONE.md` e le traduzioni in `docs/en/`.
