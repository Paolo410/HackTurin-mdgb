# app/ — la centrale (app per il PC)

**Owner:** Lorenzo Dragoni (communication engineer). Lato Arduino: [`comms/`](../comms/README.md).
Contratti: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md). Cosa devono fare gli altri: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md).

## Cosa fa

**MDGB Centrale** è l'app che gira sul PC di chi controlla gli attraversamenti. Doppio clic e si apre una finestra con:

- la **mappa delle camere**: verde OK, giallo "rete giù, nodo sano", rosso guasto/manomissione/spento, grigio camera senza dati;
- clic su una camera: stato, canale (Wi-Fi o Bluetooth con il segnale), coda di eventi in attesa, batteria, semaforo,
  traffico per finestra di tempo, sicurezza (precedenza data, near-miss, pedoni vulnerabili), allarmi, link
  "Apri in Google Maps" e "Apri in Mappe";
- **video dal vivo** della camera con i riconoscimenti, se la visione lo trasmette (campo `video` in `nodes.json`): si apre
  solo con un clic, si chiude cambiando camera e non viene mai registrato;
- **flusso atteso** per ogni camera: pedoni in/out, ciclisti e veicoli attesi adesso e nelle prossime 3 ore, stimati
  da un modello (calendario, luoghi vicini, ESA WorldCover, meteo) e corretti con i conteggi della camera. Funziona
  anche per una camera che non manda dati. Modello e limiti: [`ai/forecast/`](../ai/forecast/README.md) (owner Paolo);
- tutti gli allarmi e i numeri della rete: eventi ricevuti, **eventi persi (deve restare 0)**, doppioni scartati;
- in alto: MQTT connesso o no, Bluetooth in ascolto o no, e l'**indirizzo da dare all'Arduino** (`Arduino → 192.168.x.y:1883`).

Dietro la finestra l'app riceve i dati dei nodi in due modi e li salva nello stesso database:

```
 Arduino ──Wi-Fi──► broker MQTT (Mosquitto, avviato dall'app) ──► centrale ──► database + dashboard
 Arduino ──Bluetooth (solo se il suo Wi-Fi è giù)──────────────► centrale      (senza Internet)
```

**Demo e produzione.** Nella demo il broker MQTT gira sul PC, dentro l'app, e l'Arduino si collega al PC sulla stessa rete
Wi-Fi. In produzione al posto del PC ci sarà un broker MQTT 5 in cloud con TLS e un
certificato per nodo: è la stessa app, cambiano solo le righe `MQTT_*` del file di configurazione.

## Per il centralino: solo l'app (Mac o Windows)

Il centralino riceve **un solo file** e non installa nient'altro: dentro ci sono Python, le librerie, la dashboard e il
broker Mosquitto. L'app si può mettere dove si vuole (Applicazioni, Desktop, chiavetta): non serve il repo.

**Mac** — `MDGB-Centrale-mac.zip` (circa 18 MB):
1. doppio clic sullo zip, trascina **MDGB Centrale** in Applicazioni (o dove vuoi);
2. la prima volta: clic destro sull'app → **Apri** → Apri (non è firmata da uno sviluppatore Apple registrato;
   su macOS 15 se serve: Impostazioni di Sistema → Privacy e sicurezza → "Apri comunque");
3. consenti **Bluetooth** (backup dei nodi) e **connessioni in entrata** (servono all'Arduino per collegarsi).

**Windows 10/11** — `MDGB-Centrale-windows.zip`:
1. estrai lo zip: c'è un solo file, **MDGB Centrale.exe**; mettilo dove vuoi (es. sul Desktop);
2. la prima volta Windows può mostrare "Windows ha protetto il PC": **Ulteriori informazioni** → **Esegui comunque**
   (l'exe non è firmato da un editore registrato);
3. quando il Firewall chiede di consentire `mosquitto` sulle **reti private**, consenti (serve all'Arduino).
   Il Bluetooth deve essere acceso nelle impostazioni di Windows.

Da lì in poi: doppio clic per aprirla, chiudi la finestra per fermarla (si fermano anche la centrale e il broker).

## Per lo sviluppatore: costruire l'app

**Mac** — dalla cartella del repo (circa 1 minuto; installa Mosquitto con Homebrew se manca, per metterlo nell'app):

```bash
./app/desktop/build_mac.sh
```

Crea in `app/desktop/dist/` `MDGB Centrale.app` e `MDGB-Centrale-mac.zip`. L'app viene costruita e firmata (firma
ad-hoc) in una cartella temporanea, perché iCloud (Desktop e Documenti sincronizzati) impedirebbe la firma; alla fine
parte un **autotest** (`--selftest`: broker, centrale e dashboard senza finestra).

**Windows** — due strade, stesso risultato (`MDGB Centrale.exe` e `MDGB-Centrale-windows.zip`, con autotest):
- **senza un PC Windows**: GitHub → **Actions** → "App centrale per Windows" → ultima esecuzione → **Artifacts** →
  `MDGB-Centrale-windows`. Parte da sola a ogni push che tocca `app/`, oppure a mano con "Run workflow"
  ([`.github/workflows/centrale-windows.yml`](../.github/workflows/centrale-windows.yml));
- **su un PC Windows** con Python 3.12 e Mosquitto installato: dalla cartella del repo, in PowerShell,
  `powershell -ExecutionPolicy Bypass -File app\desktop\build_windows.ps1`.

## Impostazioni

Pulsanti **Configurazione** e **Cartella** in alto nella finestra. La cartella è
`~/Library/Application Support/MDGB Centrale/` sul Mac e `%APPDATA%\MDGB Centrale\` su Windows, e contiene:

| File | Cosa |
|---|---|
| `config.env` | broker (locale o cloud), Bluetooth, porta della dashboard, chiave di Google Maps. Dopo una modifica, riapri l'app |
| `nodes.json` | camere sulla mappa, una per Arduino: `id` (= `NODE_ID` dell'Arduino), nome, `lat`, `lon`, profilo, `video` (facoltativo: indirizzo dello stream dal vivo, es. `http://192.168.1.50:8090/stream.mjpg`). Si modifica anche ad app aperta. Un nodo che si collega senza essere qui compare lo stesso nella lista, senza posizione |
| `certs/` | solo con un broker in cloud: certificati TLS della centrale |
| `central.db`, `centrale.log` | database e log della centrale |

**Mappa.** Mappa vettoriale moderna (MapLibre + OpenFreeMap, gratis e senza chiave): stile automatico chiaro/scuro
come il Mac, oppure "Dettagliata" dal menu sopra la mappa (la scelta resta memorizzata). Le camere con un problema
pulsano. Senza Internet si passa da soli a una mappa schematica con le stesse camere. Facoltativo: con una chiave di
Google Maps (`GOOGLE_MAPS_API_KEY`, API "Maps JavaScript", serve un account con fatturazione) si usa Google Maps.

**Dashboard da telefono/tablet.** In `config.env` metti `WEB_HOST=0.0.0.0` e apri `http://<IP del PC>:8080` dal telefono
sulla stessa rete.

## Da sorgente (sviluppo, test)

```bash
pip install -r app/desktop/requirements.txt
python app/desktop/centrale_app.py        # come l'app, con la finestra
python app/central.py --no-ble            # senza finestra: dashboard su http://localhost:8080 (broker già avviato a parte)
python app/central.py --report            # riepilogo del database ed esce
```

## Prova sul PC senza scheda (solo sviluppatori)

L'app mostra solo nodi veri. Per provarla senza Arduino si fa girare sul PC lo stesso programma della scheda, con eventi
di prova scritti nei file come farebbe la visione. Con l'app aperta (broker dentro l'app, porta 1883), dalla cartella del repo:

```bash
python -m comms.tools.c3_sim --rate 2 --duration 600 --dir /tmp/c3 &
MQTT_HOST=127.0.0.1 NODE_ID=nodo01 BACKUP_LINK=none MDGB_C3_DIR=/tmp/c3 DB_PATH=/tmp/nodo01.db python comms/node/main.py
```

`BACKUP_LINK=none` perché sul PC non c'è la radio della UNO Q. Sulla scheda vera: vedi
[`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md#7-arduino-uno-q).

## File

| File | Cosa fa |
|---|---|
| `desktop/centrale_app.py` | l'app: cartella delle impostazioni, avvio di Mosquitto, centrale, finestra; chiusura pulita |
| `desktop/build_mac.sh`, `desktop/build_windows.ps1`, `desktop/centrale.spec`, `desktop/make_icon.py` | costruzione dell'app per Mac e Windows (PyInstaller) e delle icone |
| `central.py` | la centrale: MQTT + Bluetooth + dashboard (`Central.start()` / `stop()`) |
| `ingest.py` | ricezione MQTT, database, deduplica su (nodo, numero evento), conteggio degli eventi persi |
| `dashboard.py`, `dashboard.html` | la pagina e i suoi dati (`/api/state`, `/api/info`, `/api/forecast/<nodo>`) |
| `diagnosis.py` | la regola che decide lo stato di ogni nodo (OK, rete giù, guasto, Linux bloccato, manomissione, batteria, spento) |
| `decoder.py` | lettura dei messaggi binari del backup (BLE oggi, LoRa in futuro) |
| `ble_receiver.py` | ricezione dei beacon Bluetooth; da solo con `--dry-run` serve alla prima prova radio |
| `nodes.json` | la camera del nodo vero (`nodo01`), copiata nelle impostazioni al primo avvio |

I test sono in `comms/tests/` (`python -m pytest comms -q`).

## Dipendenze

`paho-mqtt`, `bleak`, `flask`, `certifi` (`requirements.txt`); per l'app anche `pywebview` e `pyinstaller` (`desktop/requirements.txt`).
Per costruire l'app serve Mosquitto installato (Homebrew sul Mac, `C:\Program Files\mosquitto` su Windows): finisce
dentro l'app. Python 3.9 o superiore (3.12 per la build Windows). Provata su macOS (Apple Silicon); Windows tramite la
build automatica su GitHub.
