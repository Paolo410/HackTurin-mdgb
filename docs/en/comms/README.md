# comms/ — the network of the nodes (Arduino UNO Q side)

> English translation of [`comms/README.md`](../../../comms/README.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

**Owner:** Lorenzo Dragoni (communication engineer).
Contracts between the modules: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md). Decisions and numbers: [DECISIONS.md](DECISIONS.md).
The PC program (the central office) is in [`app/`](../app/README.md). What the others have to do: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md).

## What it does

On the Arduino UNO Q `comms/` does two jobs, both real (no simulation on the board):

```
                    ┌──────────── MCU (Salvatore's firmware): traffic light, LEDs, displays, sensors
                    │  ▲ C1 commands + C2 "I am alive"       │ C5 battery, environment, tampering, fail-safe
                    │  │      (UNO Q Bridge)                 ▼
 2) actuators.py ───┘  ai/ (Paolo) ── uses actuators.py ──► logs/c3/mcu-*.jsonl
                       ai/ (Paolo) ── writes the events ──► logs/c3/c3-*.jsonl
                                                                 │
 1) node/main.py  ◄──────────────────── reads both files ────────┘
       │ stores every event on disk (SQLite), sends it to the central office over Wi-Fi (MQTT) and marks it "sent" only
       │ on confirmation; if no confirmation arrives for 30 s it turns on Bluetooth (BLE) and sends status, counts and
       │ alarms; after 60 s of stable network it turns it off
       ▼
 Central office PC (app "MDGB Centrale")
```

1. **The network** (`node/`): brings the data to the central office and never loses it. It is the program `node/main.py`.
2. **The vision ↔ traffic-light link** (`actuators.py`): Paolo's vision imports it to send commands to the MCU through
   the UNO Q Bridge and receive the MCU lines. It is not the network towards the central office, but the specification
   assigns it to comms (actuator transports) and the vision on the board does not start without it.

Safety does not go through the network: if the network breaks, the traffic light works the same.

### Local demo, production in the cloud

| | Demo (now) | Production (future) |
|---|---|---|
| MQTT broker | Mosquitto inside the app on the central office PC | an MQTT 5 broker in the cloud |
| Network | PC and Arduino on the same Wi-Fi network | Internet |
| Security | local network, no encryption | TLS and one certificate per node |
| Backup | BLE to the PC (10–50 m) | LoRaWAN (kilometres) |

MQTT is real in both cases: Mosquitto is a complete MQTT 5 broker, it just runs on the PC instead of the cloud. The
code is the same: only the `MQTT_*` and `BACKUP_LINK` lines in `comms/.env` change.

## Installation on the Arduino UNO Q

From the PC where the central office app runs, in the repository folder:

```bash
./comms/deploy/push_to_arduino.sh arduino@<board IP> --service
```

It copies to the board **only** the files that run there (in `~/HackTurin-mdgb/comms`), creates `~/venv` with the
dependencies, writes `comms/.env` with broker = this PC, and with `--service` installs the automatic start and starts
the node (it asks the sudo password of the board). Running it again updates the code; the data stays. Other options:
`--tools` (adds the 3 test tools, see below), `--broker IP` (broker on another PC), `--applab FOLDER` (also reads the
App Lab app of the sketch, see below), `--pack` (creates `mdgb-nodo.tar.gz` to copy by hand, without ssh).

The node log (`journalctl -u mdgb-comms -f`) must show `backup BLE reale (btmgmt)`. If BlueZ is missing the node
**does not start** and says so (`sudo apt install bluez`): no fake Bluetooth.

Paolo's vision (`ai/`) runs on the same board, in `~/HackTurin-mdgb/ai`: it writes the events in
`~/HackTurin-mdgb/logs/c3/`, where the network reads them, and imports `comms/actuators.py`.
Full procedure: [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../docs/INSTRUCTIONS_FOR_OTHERS.md#7-arduino-uno-q).

### With the App Lab app of the sketch (Salvatore)

The Python of App Lab runs in a Docker container that **cannot use the Bluetooth** of the board (verified in the code
of [arduino-app-cli](https://github.com/arduino/arduino-app-cli): the container does not use the host network). That is
why the network stays a service on the Linux of the board, and the App Lab app passes it the data of the sketch through
files:

1. `applab/mdgb_link.py` and `applab/main.py` go in the `python/` folder of the App Lab app (Salvatore's `main.py` with
   5 more lines: every callback forwards the value to `mdgb_link`);
2. `mdgb_link.py` writes C5 lines in `/app/data/c3/applab-*.jsonl`, which on the board is `~/ArduinoApps/<folder>/data/c3/`;
3. `push_to_arduino.sh ... --applab <folder>` makes the node read that folder (`MDGB_C3_DIR` in `comms/.env`).
   Paolo's vision must write its events in the same folder (`MDGB_C3_DIR` or `--c3-dir`).

| The sketch sends | The central office gets |
|---|---|
| `sensor_env`, `sensor_light`, `sensor_air` (every 300 ms) | `env` every 10 s: `t_c`, `rh` (plus raw `light` 0–1023, `eco2_ppm`, `tvoc_ppb`) |
| `alarm_status` (theft attempt) | `tamper` code 1, at most one every 10 s |
| `rfid_status` "ACCESSO CONSENTITO" | `tamper` code 3 (technician badge, information) |
| `led_status` "FAIL-SAFE: ..." | `failsafe` (the vision does not answer: it arrives also when the vision is off), at most one every 10 s |
| `led_status`, `sensor_movement`, `rfid_data`, access denied | nothing (debug; the badge code never leaves the board) |

## Configuration (`comms/.env` on the board)

| Key | Demo | Meaning |
|---|---|---|
| `NODE_ID` | `nodo01` | name of the node, equal to a camera in `nodes.json` of the app |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_TLS` | PC IP, `1883`, `0` | where the broker is (set by `push_to_arduino.sh`) |
| `BACKUP_LINK` | `ble` | backup channel: `ble`, `lora` (future) or `none` |
| `BACKUP_HB_S` | `30` | how often BLE sends the status (300 in production) |
| `AGG_PERIOD_S` | `60` | count window (900 in production) |
| `MDGB_C3_DIR` | (empty) | events folder; empty = `~/HackTurin-mdgb/logs/c3`; with App Lab set by `--applab` |

The others (backup timings, batches, retries) already have the right value: they are in [`node/config.py`](../../../comms/node/config.py).

## Files

On the board (copied by `push_to_arduino.sh`):

| File | What it does |
|---|---|
| `node/main.py` | the network program: puts together the pieces below |
| `node/event_source.py` | reads the files of `ai/` and of the MCU in `logs/c3/`, without losing or duplicating lines |
| `node/outbox.py` | Store & Forward: every event on disk before sending, marked "sent" only after the confirmation |
| `node/uplink_mqtt.py` | MQTT sending: confirmations (PUBACK), retries, "online" only if confirmations arrive |
| `node/failover.py` | backup: when to turn it on, what to send, when to turn it off |
| `node/backup_link.py` | backup radio: BLE (`btmgmt`) or LoRa through the MCU |
| `node/aggregator.py` | counts per time window |
| `node/payload.py` | message formats (JSON and 26/12/5-byte binaries for the backup) |
| `node/config.py` | settings (read from `comms/.env`) |
| `actuators.py` | vision ↔ MCU: C1/C2 commands and C5 lines over the Bridge (on the UNO Q), serial (Arduino over USB) or simulated (PC) |
| `jsonl.py` | writing of the `logs/c3/*.jsonl` files with rotation (used by `actuators.py`) |
| `requirements.txt`, `.env.example`, `deploy/mdgb-comms.service` | dependencies, example configuration, automatic start |

Only with `--tools`, for testing (started by hand, the node never uses them):

| File | What it does |
|---|---|
| `tools/ble_beacon_test.py` | first test of the Bluetooth radio: beacons for 60 s, seen by the app on the PC |
| `tools/c1_send.py` | traffic-light test: C1 states and heartbeat to the MCU over the Bridge (`--port bridge`) or USB, fail-safe included |
| `tools/c3_sim.py` | test events in the files of `ai/`, to test the network on the board before the vision is ready |

In the App Lab app (dragged by Salvatore into the `python/` folder): `applab/mdgb_link.py`, `applab/main.py`.

Only in the repository (developers): `deploy/push_to_arduino.sh`, `tests/` (automatic tests of the network and the
central office), `requirements-dev.txt`, this documentation.

## Tests

```bash
pip install -r comms/requirements-dev.txt -r app/requirements.txt
brew install mosquitto                  # only for the tests that use a real broker
python -m pytest comms -q               # expected: all green in about 1 minute
```

Among the tests: the real node (`node/main.py`) reading real files and delivering everything to the central office; the
"Wi-Fi off / on again" test with shortened timings (BLE on, "network down, node healthy", alarm over BLE, 0 events lost
on return); a real negative PUBACK; `actuators.py` on the Bridge with the official Arduino library against a fake router.

## Python

Python 3.10 or later (on the UNO Q Debian's `python3` in a venv). On the board only `requirements.txt` is needed:
`paho-mqtt` (MQTT), `arduino-router-bridge` (the Bridge, official Arduino library), `pyserial` (only for an Arduino over
USB). For the tests `requirements-dev.txt` (adds `pytest`). Pinned versions.
