# app/ — the central office (PC app)

> English translation of [`app/README.md`](../../../app/README.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

**Owner:** Lorenzo Dragoni (communication engineer). Arduino side: [`comms/`](../comms/README.md).
Contracts: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md). What the others have to do: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md).

## What it does

**MDGB Centrale** is the app that runs on the PC of whoever supervises the crossings. Double-click and a window opens
with:

- the **map of the cameras**: green OK, yellow "network down, node healthy", red fault/tampering/off, grey camera
  without data;
- click on a camera: status, channel (Wi-Fi or Bluetooth with the signal), queue of pending events, battery, traffic
  light, traffic per time window, safety (give way, near misses, vulnerable pedestrians), alarms, links "Open in
  Google Maps" and "Open in Maps";
- **live video** of the camera with the detections, if the vision streams it (field `video` in `nodes.json`): it opens
  only with a click, closes when changing camera and is never recorded;
- **expected flow** for every camera: pedestrians in/out, cyclists and vehicles expected per hour, now and over the next
  24 hours, estimated by a model (calendar, nearby places, ESA WorldCover, weather) and corrected with the counts of the
  camera. On the map a **halo** around every camera tells how many pedestrians are expected, and the slider above the
  map chooses the hour; in the detail there are the numbers of that hour and the 24-hour chart. It also works for a
  camera that sends no data. Model and limits: [`ai/forecast/`](../ai/forecast/README.md) (owner Paolo);
- **data for customers**: from the card at the bottom of the page an API key is created for a customer, tied to a zone
  around a camera; with it the customer downloads counts, estimates and forecasts of the cameras in their zone
  (`/api/v1/...`). The same estimates and the metrics of every camera also go out on MQTT (`mdgb/<node>/forecast` and
  `/analytics`). Addresses, formats and examples: [`docs/DATA_API.md`](../docs/DATA_API.md);
- every alarm and the network numbers: events received, **events lost (must stay 0)**, duplicates discarded;
- on top: MQTT connected or not, Bluetooth listening or not, and the **address to give to the Arduino**
  (`Arduino → 192.168.x.y:1883`).

Behind the window the app receives the data of the nodes in two ways and stores it in the same database:

```
 Arduino ──Wi-Fi──► MQTT broker (Mosquitto, started by the app) ──► central ──► database + dashboard
 Arduino ──Bluetooth (only if its Wi-Fi is down)────────────────► central      (without internet)
```

**Demo and production.** In the demo the MQTT broker runs on the PC, inside the app, and the Arduino connects to the PC
on the same Wi-Fi network. In production, instead of the PC there will be an MQTT 5 broker in the cloud with TLS and one
certificate per node: it is the same app, only the `MQTT_*` lines of the configuration file change.

## For the operator: only the app (Mac or Windows)

The operator receives **a single file** and installs nothing else: inside there are Python, the libraries, the dashboard
and the Mosquitto broker. The app can be put anywhere (Applications, Desktop, USB stick): the repository is not needed.

**Mac** — `MDGB-Centrale-mac.zip` (about 18 MB):
1. double-click the zip, drag **MDGB Centrale** into Applications (or wherever you want);
2. the first time: right-click on the app → **Open** → Open (it is not signed by a registered Apple developer; on
   macOS 15 if needed: System Settings → Privacy & Security → "Open Anyway");
3. allow **Bluetooth** (backup of the nodes) and **incoming connections** (needed by the Arduino to connect).

**Windows 10/11** — `MDGB-Centrale-windows.zip`:
1. extract the zip: there is a single file, **MDGB Centrale.exe**; put it wherever you want (e.g. on the Desktop);
2. the first time Windows may show "Windows protected your PC": **More info** → **Run anyway** (the exe is not signed
   by a registered publisher);
3. when the Firewall asks to allow `mosquitto` on **private networks**, allow it (needed by the Arduino).
   Bluetooth must be on in the Windows settings.

From then on: double-click to open it, close the window to stop it (the central office and the broker stop too).

## For the developer: build the app

**Mac** — from the repository folder (about 1 minute; installs Mosquitto with Homebrew if missing, to put it in the app):

```bash
./app/desktop/build_mac.sh
```

It creates in `app/desktop/dist/` `MDGB Centrale.app` and `MDGB-Centrale-mac.zip`. The app is built and signed (ad-hoc
signature) in a temporary folder, because iCloud (synced Desktop and Documents) would prevent the signature; at the end
a **self-test** runs (`--selftest`: broker, central office and dashboard without window).

**Windows** — two ways, same result (`MDGB Centrale.exe` and `MDGB-Centrale-windows.zip`, with self-test):
- **without a Windows PC**: GitHub → **Actions** → "App centrale per Windows" → latest run → **Artifacts** →
  `MDGB-Centrale-windows`. It starts by itself at every push that touches `app/`, or by hand with "Run workflow"
  ([`.github/workflows/centrale-windows.yml`](../../../.github/workflows/centrale-windows.yml));
- **on a Windows PC** with Python 3.12 and Mosquitto installed: from the repository folder, in PowerShell,
  `powershell -ExecutionPolicy Bypass -File app\desktop\build_windows.ps1`.

## Settings

**Configurazione** and **Cartella** buttons at the top of the window. The folder is
`~/Library/Application Support/MDGB Centrale/` on the Mac and `%APPDATA%\MDGB Centrale\` on Windows, and contains:

| File | What |
|---|---|
| `config.env` | broker (local or cloud), Bluetooth, dashboard port, Google Maps key, how often to publish estimates and metrics on MQTT. After a change, reopen the app |
| `nodes.json` | cameras on the map, one per Arduino: `id` (= `NODE_ID` of the Arduino), name, `lat`, `lon`, profile, `video` (optional: address of the live stream, e.g. `http://192.168.1.50:8090/stream.mjpg`). It can be edited with the app open. A node that connects without being here appears in the list anyway, without position |
| `certs/` | only with a cloud broker: TLS certificates of the central office |
| `central.db`, `centrale.log` | database and log of the central office |

**Map.** Modern vector map (MapLibre + OpenFreeMap, free and without a key): automatic light/dark style like the Mac,
or "Dettagliata" (detailed) from the menu above the map (the choice is remembered). Cameras with a problem pulse.
Without internet it switches by itself to a schematic map with the same cameras. Optional: with a Google Maps key
(`GOOGLE_MAPS_API_KEY`, "Maps JavaScript" API, needs an account with billing) Google Maps is used.

**Dashboard from a phone/tablet.** In `config.env` set `WEB_HOST=0.0.0.0` and open `http://<PC IP>:8080` from the phone
on the same network.

## From source (development, tests)

```bash
pip install -r app/desktop/requirements.txt
python app/desktop/centrale_app.py        # like the app, with the window
python app/central.py --no-ble            # without window: dashboard on http://localhost:8080 (broker started separately)
python app/central.py --report            # summary of the database, then exits
```

## Test on the PC without a board (developers only)

The app shows only real nodes. To test it without an Arduino, run on the PC the same program as on the board, with
test events written in the files as the vision would do. With the app open (broker inside the app, port 1883), from the
repository folder:

```bash
python -m comms.tools.c3_sim --rate 2 --duration 600 --dir /tmp/c3 &
MQTT_HOST=127.0.0.1 NODE_ID=nodo01 BACKUP_LINK=none MDGB_C3_DIR=/tmp/c3 DB_PATH=/tmp/nodo01.db python comms/node/main.py
```

`BACKUP_LINK=none` because the PC does not have the radio of the UNO Q. On the real board: see
[`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md#7-arduino-uno-q).

## Files

| File | What it does |
|---|---|
| `desktop/centrale_app.py` | the app: settings folder, Mosquitto start, central office, window; clean shutdown |
| `desktop/build_mac.sh`, `desktop/build_windows.ps1`, `desktop/centrale.spec`, `desktop/make_icon.py` | build of the app for Mac and Windows (PyInstaller) and of the icons |
| `central.py` | the central office: MQTT + Bluetooth + dashboard (`Central.start()` / `stop()`) |
| `ingest.py` | MQTT reception, database, deduplication on (node, event number), count of lost events |
| `dashboard.py`, `dashboard.html` | the page and its data (`/api/state`, `/api/info`, `/api/flow`, `/api/forecast/<node>`) |
| `customers.py` | customer API keys (zone, expiry, usage) and the `/api/v1/...` API; from the terminal: `python app/customers.py create\|list\|revoke` |
| `publisher.py` | estimates and metrics of every camera on MQTT, every `ANALYTICS_PERIOD_S` seconds |
| `diagnosis.py` | the rule that decides the status of every node (OK, network down, fault, Linux stuck, tampering, battery, off) |
| `decoder.py` | reading of the binary backup messages (BLE today, LoRa in the future) |
| `ble_receiver.py` | reception of the Bluetooth beacons; on its own with `--dry-run` it serves the first radio test |
| `nodes.json` | the camera of the real node (`nodo01`), copied into the settings at the first start |

The tests are in `comms/tests/` (`python -m pytest comms -q`).

## Dependencies

`paho-mqtt`, `bleak`, `flask`, `certifi` (`requirements.txt`); for the app also `pywebview` and `pyinstaller`
(`desktop/requirements.txt`). Building the app needs Mosquitto installed (Homebrew on the Mac,
`C:\Program Files\mosquitto` on Windows): it ends up inside the app. Python 3.9 or later (3.12 for the Windows build).
Tested on macOS (Apple Silicon); Windows through the automatic build on GitHub.
