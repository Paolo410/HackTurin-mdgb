# app/ — la centrale (app per il PC)

**Owner:** Lorenzo Dragoni (communication engineer). Lato Arduino: [`comms/`](../comms/README.md).
Contratti: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md). Cosa devono fare gli altri: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md).

## Cosa fa

**MDGB Centrale** è l'app che gira sul PC di chi controlla gli attraversamenti. Doppio clic e si apre una finestra con:

- la **mappa delle camere**: verde OK, giallo "rete giù, nodo sano", rosso guasto/manomissione/spento, grigio camera senza dati;
- clic su una camera: stato, canale (Wi-Fi o Bluetooth con il segnale), coda di eventi in attesa, batteria, semaforo,
  traffico per finestra di tempo, sicurezza (precedenza data, near-miss, pedoni vulnerabili), allarmi, link
  "Apri in Google Maps" e "Apri in Mappe";
- tutti gli allarmi e i numeri della rete: eventi ricevuti, **eventi persi (deve restare 0)**, doppioni scartati;
- in alto: MQTT connesso o no, Bluetooth in ascolto o no, e l'**indirizzo da dare all'Arduino** (`Arduino → 192.168.x.y:1883`).

Dietro la finestra l'app riceve i dati dei nodi in due modi e li salva nello stesso database:

```
 Arduino ──Wi-Fi──► broker MQTT (Mosquitto, avviato dall'app) ──► centrale ──► database + dashboard
 Arduino ──Bluetooth (solo se il suo Wi-Fi è giù)──────────────► centrale      (senza Internet)
```

**Demo e produzione.** Nella demo il broker MQTT gira sul PC, dentro l'app, e l'Arduino si collega al PC sulla stessa rete
Wi-Fi. In produzione al posto del PC ci sarà un broker in cloud (AWS IoT Core o un altro broker MQTT 5) con TLS e un
certificato per nodo: è la stessa app, cambiano solo le righe `MQTT_*` del file di configurazione.

## Per il centralino: solo l'app

Il centralino riceve **un solo file**, `MDGB-Centrale-mac.zip` (circa 18 MB, broker Mosquitto incluso), e non installa
nient'altro:
1. doppio clic sullo zip, trascina **MDGB Centrale** in Applicazioni;
2. la prima volta: clic destro sull'app → **Apri** → Apri (l'app non è firmata da uno sviluppatore Apple registrato;
   su macOS 15 se serve: Impostazioni di Sistema → Privacy e sicurezza → "Apri comunque");
3. consenti **Bluetooth** (backup dei nodi) e **connessioni in entrata** (servono all'Arduino per collegarsi).

Da lì in poi: doppio clic per aprirla, chiudi la finestra per fermarla.

## Per lo sviluppatore: costruire l'app

Dalla cartella del repo, su un Mac (circa 1 minuto; installa Mosquitto con Homebrew se manca, per metterlo nell'app):

```bash
./app/desktop/build_mac.sh
```

Crea in `app/desktop/dist/` sia `MDGB Centrale.app` sia `MDGB-Centrale-mac.zip` da dare al centralino. L'app viene
costruita e firmata (firma ad-hoc) in una cartella temporanea: se il repo è su Desktop o Documenti sincronizzati con
iCloud, iCloud aggiunge attributi che impedirebbero la firma.

Per chiuderla basta chiudere la finestra: si fermano anche la centrale e il broker.

## Impostazioni

Pulsanti **Configurazione** e **Cartella** in alto nella finestra. La cartella è
`~/Library/Application Support/MDGB Centrale/` e contiene:

| File | Cosa |
|---|---|
| `config.env` | broker (locale o cloud), Bluetooth, porta della dashboard, chiave di Google Maps. Dopo una modifica, riapri l'app |
| `nodes.json` | camere sulla mappa: `id` (= `NODE_ID` dell'Arduino), nome, `lat`, `lon`, profilo, `mock: true` per le camere di esempio. Si modifica anche ad app aperta |
| `certs/` | solo per il cloud: certificati del broker (vedi `comms/aws/`) |
| `central.db`, `centrale.log` | database e log della centrale |

**Mappa.** Con una chiave di Google Maps (`GOOGLE_MAPS_API_KEY`, API "Maps JavaScript") la mappa è Google Maps; senza
chiave è una mappa web senza chiave; senza Internet una mappa schematica con le stesse camere.

**Dashboard da telefono/tablet.** In `config.env` metti `WEB_HOST=0.0.0.0` e apri `http://<IP del PC>:8080` dal telefono
sulla stessa rete.

## Da sorgente (sviluppo, test)

```bash
pip install -r app/desktop/requirements.txt
python app/desktop/centrale_app.py        # come l'app, con la finestra
python app/central.py --no-ble            # senza finestra: dashboard su http://localhost:8080 (broker già avviato a parte)
python app/central.py --report            # riepilogo del database ed esce
```

## File

| File | Cosa fa |
|---|---|
| `desktop/centrale_app.py` | l'app: cartella delle impostazioni, avvio di Mosquitto, centrale, finestra; chiusura pulita |
| `desktop/build_mac.sh`, `desktop/centrale.spec`, `desktop/make_icon.py` | costruzione di `MDGB Centrale.app` (PyInstaller) e della sua icona |
| `central.py` | la centrale: MQTT + Bluetooth + dashboard (`Central.start()` / `stop()`) |
| `ingest.py` | ricezione MQTT, database, deduplica su (nodo, numero evento), conteggio degli eventi persi |
| `dashboard.py`, `dashboard.html` | la pagina e i suoi dati (`/api/state`, `/api/info`) |
| `diagnosis.py` | la regola che decide lo stato di ogni nodo (OK, rete giù, guasto, Linux bloccato, manomissione, batteria, spento) |
| `decoder.py` | lettura dei messaggi binari del backup (BLE oggi, LoRa in futuro) |
| `ble_receiver.py` | ricezione dei beacon Bluetooth; da solo con `--dry-run` serve alla prima prova radio |
| `nodes.json` | camere di esempio, copiate nelle impostazioni al primo avvio |

I test sono in `comms/tests/` (`python -m pytest comms -q`).

## Dipendenze

`paho-mqtt`, `bleak`, `flask` (`requirements.txt`); per l'app anche `pywebview` e `pyinstaller` (`desktop/requirements.txt`).
Mosquitto (broker MQTT) da Homebrew. Python 3.9 o superiore. Testata su macOS (Apple Silicon).
