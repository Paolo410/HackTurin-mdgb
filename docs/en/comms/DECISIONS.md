# comms/ and app/ — decisions, numbers and interfaces

> English translation of [`comms/DECISIONS.md`](../../../comms/DECISIONS.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

Owner: Lorenzo Dragoni (communication engineer). Areas: `comms/` (network, on the Arduino), `app/` (central office, on
the PC), `docs/CONTRACTS.md` (message formats). Status as of 10/10/2026.

History in one line: the initial idea was AWS IoT Core as the broker; without AWS credits the demo uses a local broker
inside the central office app. The code is the same: in production it is enough to point to an MQTT 5 broker in the
cloud with TLS.

## 1. Decisions taken

| Topic | Decision |
|---|---|
| Safety | The node (Arduino UNO Q) decides locally and drives the traffic light through the MCU. The network only carries the data to the central office: if it falls, the traffic light works the same |
| Main channel | MQTT 5 over Wi-Fi, QoS 1, Last Will, persistent session. **Demo**: Mosquitto broker inside the app on the PC (port 1883, local network). **Production**: MQTT 5 broker in the cloud with TLS and one certificate per node |
| Store & Forward | Every event is written to disk (SQLite) **before** sending and marked sent only after a **positive** broker confirmation (PUBACK < 0x80). When the network returns the queue empties starting from the oldest |
| Event number | Persistent `seq`, never reused; `event_id` = `node_id` + `seq`. The central office deduplicates on `(node_id, seq)` and sees lost data from the gaps |
| "Online" | Only if confirmations arrive (positive PUBACK in the last 30 s), the TCP connection is not enough |
| Backup | **BLE** (UNO Q radio, `btmgmt` beacons) in the demo; **LoRaWAN** (Wio-E5 on the MCU) in the future. Only alarms, heartbeat and counts, never single events |
| Backup hysteresis | On after 30 s without confirmations (at once heartbeat + counts + pending alarms); off after 60 s of stable network. Meanwhile MQTT retries and recovers the queue |
| Central office | A PC app (**Mac and Windows**), **MDGB Centrale**: broker + MQTT reception + direct Bluetooth reception (without internet) + database + diagnosis + dashboard with map. Self-contained: a single file, can be moved anywhere. The Windows exe is built by GitHub Actions |
| Diagnosis | Crossing MQTT and backup: OK / network down, node healthy / node faulty / Linux stuck / tampering / battery low / node off or destroyed |
| Who has what | Developers: the whole repository. Arduino: only the 15 comms files that run there (`comms/deploy/push_to_arduino.sh`, the test tools only with `--tools`) next to Paolo's vision, in `~/HackTurin-mdgb`. Central operator: only the app zip (Mac or Windows) |
| No fakes on the board | The node reads only the real files of `ai/` and of the MCU; BLE only real (without BlueZ the node does not start); only real cameras on the map. Test events only with `tools/c3_sim.py` started by hand |
| App Lab | The Python of App Lab runs in a container without Bluetooth: the network stays a service on the Linux of the board. The App Lab app of the sketch passes it sensors and alarms with `comms/applab/mdgb_link.py` (files `applab-*.jsonl` in `~/ArduinoApps/<app>/data/c3`) |
| Bridge (vision ↔ MCU) | `BridgeActuator` with the official `arduino-router-bridge` library (the same as App Lab, works from a normal venv): `call("mdgb_line")` for C1/C2, `provide("mcu_event")` for C5 |
| Map | Vector map (MapLibre + OpenFreeMap, free, no key), light/dark/detailed style; schematic map without internet. Google Maps only with a key (optional) |
| Privacy | Only anonymous metadata towards the central office. Only exception (specification §5.3): the **live** video of the camera in the app, on the local network, if enabled and never recorded |
| Out of scope | 4G / second SIM (only in the pitch); LoRa (after the demo) |

## 2. Parameters and numbers

| Parameter | Value |
|---|---|
| Topics | `mdgb/<node_id>/events` (batches of up to 50 events), `agg` (counts), `hb` (status, every 10 s, retained + Last Will), `backup` |
| Demo broker | Mosquitto in the app, port 1883, open to the local network; the app shows the address to give to the Arduino |
| Confirmation timeout | 30 s, then the batch is sent again; after a negative PUBACK a growing wait up to 60 s |
| Reconnection | backoff from 1 to 30 s; keepalive 30 s; session 3600 s |
| Backup | on after 30 s without confirmations, off after 60 s stable; heartbeat every 30 s (demo) / 5 min (production) |
| Counts | windows of 60 s (demo) / 15 min (production) |
| Backup messages | binary: `AGG` 26 bytes, `HB` 12 bytes, alarms 5 bytes; BLE: 27-byte frames, up to 3 beacons together (AGG, HB, alarms) |
| MCU watchdog | 5 min without heartbeat from Linux → `DEAD` (only with LoRa) |
| Retention | at most 2,000,000 events on disk; only the oldest already-sent ones are deleted |

Full formats with examples: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md).

## 3. Code

| Where | What |
|---|---|
| `comms/node/` | the network program on the Arduino: Store & Forward, MQTT, BLE backup with hysteresis, reading of the events of `ai/` |
| `comms/actuators.py`, `comms/jsonl.py` | for `ai/`: commands to the traffic light and MCU lines (Bridge on the UNO Q, serial, simulated on the PC) and writing of the event files |
| `comms/tools/` | testing, by hand only: `ble_beacon_test` (radio), `c1_send` (traffic light over the Bridge or USB), `c3_sim` (test events) |
| `comms/deploy/` | `push_to_arduino.sh` (brings the network to the board, sets the broker, `--service` for the automatic start), systemd service |
| `app/` | the central office: `central.py`, `ingest.py`, `diagnosis.py`, `dashboard.py`/`.html`, `decoder.py`, `ble_receiver.py` |
| `app/desktop/` | the PC app and its build (`build_mac.sh`) |
| `comms/applab/` | for Salvatore's App Lab app: `mdgb_link.py` (sensors and alarms of the sketch → C5 lines) and its `main.py` with the forwarding |
| `comms/tests/` | 41 tests, including the real node reading real files, the "Wi-Fi off / on again" test, a real negative PUBACK and the Bridge with the official library against a fake router |

Tested: the whole chain on the PC (real broker, real node with test events in the files, network loss: 0 events lost);
the Bridge with the official Arduino library; the app built, signed and started from the zip; `push_to_arduino.sh` on a
"fake board" (clean folder, simulated ssh) with the node started from there.
**Never tested**: real UNO Q, real Bluetooth, sketch with `mdgb_line`, Wi-Fi of the venue.

## 4. What I need from the others

| From | What |
|---|---|
| Paolo | C3 events in `logs/c3/` (done with his `logger.py`); the vision on the board in `~/HackTurin-mdgb/ai` |
| Salvatore | C1/C2 parser and fail-safe; in the sketch `Bridge.provide_safe("mdgb_line", ...)` and `Bridge.notify("mcu_event", line)` for the C5 lines (environment, battery, tampering, lamp fault, fail-safe) |
| Kuzey | pinout in `docs/CONTRACTS.md` (case door, NFC, LTC2941, AHT20, light) |

## 5. What I provide to the others

Contracts (`docs/CONTRACTS.md`), the network on the board, `comms/actuators.py` and `comms/jsonl.py` for `ai/`, the test
tools, the central office app and the instructions (`docs/INSTRUCTIONS_FOR_OTHERS.md`).

## 6. Open questions

1. **Bridge, sketch side**: `mdgb_line` and `mcu_event` from Salvatore; the Linux side is done. Test: `c1_send --port bridge`.
2. **Hardware tests**: Bluetooth of the UNO Q (`btmgmt` as root, several beacons together, range), permissions of the
   `arduino-router` socket for the vision user, network of the venue (devices isolated? → hotspot or your own router),
   Mac firewall for incoming connections.
3. **`seq` after losing the database**: if the node file is lost, `seq` restarts from 1 and the central office would
   discard the new events as duplicates. The database must stay on the board (`comms/node/data/`).
4. **Counts over MQTT marked "sent" too early**: the window counts as published when it leaves, not on confirmation; the
   central office can recompute it from the events anyway.
5. **LoRa (later)**: MCU side (`lora_send`, `DEAD` watchdog), decoder already in `app/decoder.py`.
6. **Repository on iCloud**: the repository on the synced Desktop creates "… 2" copies of files when git rewrites them;
   better to move it out of Desktop/Documents (e.g. `~/Developer/`).
