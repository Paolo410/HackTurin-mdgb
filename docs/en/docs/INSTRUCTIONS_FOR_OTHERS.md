# Instructions for the others — network and central office (Lorenzo)

> English translation of [`docs/INSTRUCTIONS_FOR_OTHERS.md`](../../INSTRUCTIONS_FOR_OTHERS.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

What I did, what you have to do to connect, and how to prepare everything on the PC and on the Arduino UNO Q.
Details: [`comms/README.md`](../comms/README.md) (Arduino), [`app/README.md`](../app/README.md) (PC),
[`docs/CONTRACTS.md`](CONTRACTS.md) (message formats, **the reference for everybody**).

## 1. The system in one picture

```
 ARDUINO UNO Q (on the traffic light)                                      CENTRAL OFFICE PC
 ┌─────────────────────────────────────────────────────────┐              ┌──────────────────────────┐
 │ MCU: firmware (Salvatore) ── traffic light, LEDs, displays│             │ app "MDGB Centrale"      │
 │   ▲ C1 commands, C2 heartbeat  │ C5 MCU lines            │              │  - MQTT broker (demo)    │
 │   │        (Bridge)            ▼                         │   Wi-Fi      │  - database              │
 │ Linux: ai/ (Paolo) ── uses comms/actuators.py            │   MQTT       │  - dashboard with map    │
 │         └─ writes the C3 events in logs/c3/*.jsonl       │ ───────────► │  - diagnosis of the nodes│
 │ Linux: comms/node/main.py (Lorenzo) reads logs/c3,       │   Bluetooth  │                          │
 │         stores on disk, sends; if Wi-Fi is down → BLE    │ ───────────► │                          │
 └─────────────────────────────────────────────────────────┘ (backup only) └──────────────────────────┘
```

- **Safety stays on the board**: `ai/` decides, the firmware drives the traffic light. The network only carries the data
  to the central office: if it falls, the traffic light works the same.
- **Local demo**: the MQTT broker (Mosquitto, real MQTT) is inside the app on the PC; PC and Arduino are on the same Wi-Fi
  network. **In production** instead of the PC there will be an MQTT 5 broker in the cloud with TLS and one certificate
  per node: same code, only the configuration changes. The BLE backup will become LoRaWAN.
- **No simulations on the board**: the node reads only the real events of the vision and of the MCU, the Bluetooth is the
  one of the UNO Q (if it is missing, the node does not start and says so), the Bridge uses the official Arduino library.

## 2. After the merge (everybody)

```bash
git switch main && git pull
```

Then everybody continues on their own branch as in `PROMPT_GIT_TEAM.md`. No new dependency in your folders.
In `comms/requirements.txt` there is `arduino-router-bridge` (the Bridge, official Arduino library): on the board it is
installed by `push_to_arduino.sh` in the same `~/venv` as the vision.
I added to `.gitignore`: `certs/`, `*.db-wal`, `*.db-shm`, `mosquitto-data/`.

## 3. Paolo (`ai/`)

**Events towards the central office (contract C3).** One JSON line per event, in files `logs/c3/c3-*.jsonl` (folder
`logs/` in the root of the repo, already ignored by git). Your `logger.py` already does it. The network
(`comms/node/main.py`) reads the files by itself: if one of the two programs restarts nothing is lost or duplicated.

- Contract values: `cls` = `pedestrian`, `cyclist`, `motorcyclist`, `car`, `bus`, `truck`, `animal`, `bird`;
  `dir` = `in`/`out`; `line` = `ped`/`veh`; `attrs` (`child`, `slow`, `aid`).
- Other line types: `near_miss`, `incident` (`kind` = `person_down`, `collision`, `hard_brake`, `vehicle_on_crosswalk`),
  `yield` (`yielded` true/false), `status` every ~5 s (state and FPS). The `incident` lines reach the central office
  **at once**, also over BLE.

**Commands to the traffic light (contracts C1 and C2).** Your `--actuator bridge` now works: it uses `BridgeActuator` of
`comms/actuators.py`, which talks to the MCU through the `arduino-router` service of the board.

```python
from comms.actuators import make_actuator

act = make_actuator("bridge")    # on the UNO Q; "serial" (port=...) for an Arduino over USB, "sim" without hardware
act.set_listener(on_mcu_line)    # C5 lines from the MCU (env, tamper, lamp_fault, failsafe, thermal)
act.send(c1)                     # on a state change and anyway at least every second
act.heartbeat(seq)               # every 100 ms: without it, after 500 ms the firmware goes into fail-safe
```

`send` and `heartbeat` never block and never raise exceptions: if the router or the sketch do not answer, they write it
in the log and retry; meanwhile the firmware stays in the normal cycle (fail-safe). Your `ai/deploy/mdgb-ai.service`
(`--actuator bridge`) is fine as it is.

**On the board only the code that runs there.** Your guide (`ai/docs/DEPLOY_UNOQ.md`) does a `git clone` of the whole
repo: this way the PC app and the documentation would also end up on the board (and the repo is private: a token would
be needed on the board). Proposal: copy only `ai/` from the PC, as I do with `comms/`, for example
`rsync -a --exclude __pycache__ ai arduino@<IP>:~/HackTurin-mdgb/` (model and `calib.json` included). Your call.

**If Salvatore's App Lab app also runs on the board**, the events go in its folder, where the network reads them:
in your service `Environment=MDGB_C3_DIR=/home/arduino/ArduinoApps/<folder>/data/c3` (or `--c3-dir`).

**Live video in the app (optional, specification §5.3: live only, local only, only if enabled).** If the vision
exposes an **MJPEG** stream with the overlay, for example `http://<board IP>:8090/stream.mjpg`
(`Content-Type: multipart/x-mixed-replace`), in the app it is enough to put that address in the `video` field of the
camera in `nodes.json`: "Guarda dal vivo" (watch live) appears. The stream must never be saved to disk.

## 4. Salvatore (`firmware/`)

**With your App Lab app (sketch + `main.py`)**, to send sensors and alarms to the central office:

1. drag `comms/applab/mdgb_link.py` and `comms/applab/main.py` into the `python/` folder of your app in App Lab
   (the `main.py` is yours, identical, with 5 more lines that forward the data to `mdgb_link`); the sketch does not change;
2. start the app; on the board `ls ~/ArduinoApps` tells the name of its folder;
3. Lorenzo: `./comms/deploy/push_to_arduino.sh arduino@<IP> --service --applab <folder>`.

The backup Bluetooth cannot run inside App Lab (container without Bluetooth): that is why the network is a separate
service on the same board, which reads what `mdgb_link.py` writes. What reaches the central office: environment every
10 s, "manomissione: urto" (tampering: shock) for the theft attempt, "badge del tecnico" (technician badge) for the
granted access (`comms/README.md`).
Careful: your `main.py` opens the camera, which is also needed by Paolo's vision: for the final demo you have to decide
who uses it.

**For the traffic light driven by the vision** two more things are needed in the sketch (library
[Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge), names in `docs/CONTRACTS.md`):

```cpp
#include <Arduino_RouterBridge.h>

// C1 or C2, one JSON line without '\n': same parser as the serial. true = valid line.
bool mdgb_line(String line) {
  return parse_c1_c2(line);
}

void setup() {
  Bridge.begin();
  Bridge.provide_safe("mdgb_line", mdgb_line);   // provide_safe: runs inside loop(), no race with LEDs and controller
}

// C5 towards Linux, when something happens (and "env" every 10 s):
//   Bridge.notify("mcu_event", "{\"v\":1,\"src\":\"mcu\",\"type\":\"failsafe\",\"reason\":\"hb_timeout\"}");
```

- **C1/C2** as in `docs/CONTRACTS.md`: at most 512 bytes. No heartbeat for more than 500 ms → fail-safe.
- **C5**: `env` (`t_c`, `rh`, `lux`, `batt`) every 10 s; `tamper` (`code` 1 shock, 2 door, 3 NFC badge);
  `lamp_fault`; `failsafe` (`reason`). `actuators.py` writes them to file and the network brings them to the central
  office (alarms at once, also over BLE). In the loop do not call `Bridge.call` inside `mdgb_line` (risk of deadlock,
  the library says so).
- **Test on the board** (with the vision stopped: `sudo systemctl stop mdgb-ai`), after `push_to_arduino.sh ... --tools`:
  `cd ~/HackTurin-mdgb && ~/venv/bin/python -m comms.tools.c1_send --port bridge --duration 30 --stop-hb-at 20`.
  It cycles the traffic-light states, heartbeat at 10 Hz, removes it at 20 s (fail-safe within 500 ms), prints the C5
  lines and at the end says whether the MCU answered (`-> OK`). With an Arduino over USB from the PC:
  `--port /dev/cu.usbmodemXXXX`.
- The backup Bluetooth is handled by the Linux side (`btmgmt`): the firmware needs nothing. LoRa later.

## 5. Kuzey (`hardware/`)

Fill in the **Pinout** section of `docs/CONTRACTS.md` with: door micro switch, NFC reader, LTC2941 (battery), AHT20 and
light sensor. The LoRa module (Wio-E5) is needed only later.

## 6. Who has what

| Who | What they receive | How |
|---|---|---|
| Developers | the whole repo | `git pull` |
| Arduino UNO Q | only the code that runs on the board: the network in `~/HackTurin-mdgb/comms` (15 files), the vision in `~/HackTurin-mdgb/ai`, the firmware on the MCU | `comms/deploy/push_to_arduino.sh` (Lorenzo); Paolo and Salvatore for their parts |
| Operator (Mac or Windows PC) | only the app: `MDGB-Centrale-mac.zip` or `MDGB-Centrale-windows.zip` (broker included, no installation) | Mac: `./app/desktop/build_mac.sh`; Windows: GitHub → Actions → "App centrale per Windows" → Artifacts. Then the zip via USB stick/mail |

The operator opens the app (the first time: Mac right-click → Open; Windows "More info" → "Run anyway"), allows
Bluetooth and incoming connections (Windows Firewall: private networks). At the top **`Arduino → 192.168.x.y:1883`**
appears: it is the address of the broker, which `push_to_arduino.sh` puts by itself in the configuration of the Arduino
if you run it from that PC.

## 7. Arduino UNO Q

The UNO Q has Linux (Debian) on board. Needed only once:

1. **Wi-Fi and IP**: with Arduino App Lab (first start of the board) connect the UNO Q **to the same Wi-Fi network as the
   PC**. On the board `hostname -I` tells its address. If the network of the venue isolates the devices (the PC does not
   see the board), use a phone hotspot or your own router for PC and board.
2. **Access**: from the PC `ssh arduino@<board IP>` (user and password chosen at the first start; `TODO(verify)` the user
   name). **Common folder: `~/HackTurin-mdgb`** (also used by Paolo's guide): the vision writes the events in
   `~/HackTurin-mdgb/logs/c3/` and the network reads them from there.
3. **Network (Lorenzo)**, with the central office app open, from the PC in the repo folder:
   ```bash
   ./comms/deploy/push_to_arduino.sh arduino@<board IP> --service --tools
   ```
   It copies only the network files, creates `~/venv` with the dependencies, writes `comms/.env` with broker = this PC,
   installs the automatic start and starts the node (it asks the sudo password). Without ssh: `--pack` creates
   `mdgb-nodo.tar.gz` to copy by hand. `--tools` is needed only for the acceptance test (point 5): when everything works,
   it can be run again without it.
4. **Vision (Paolo)**: `ai/docs/DEPLOY_UNOQ.md` (same `~/venv`, model and calibration, service `ai/deploy/mdgb-ai.service`).
5. **Acceptance test**, in this order:
   - **network**: `journalctl -u mdgb-comms -f` on the board shows `backup BLE reale (btmgmt)` and then `rete=ONLINE`;
     in the app the camera `nodo01` turns green;
   - **Bluetooth** (2 minutes): `sudo systemctl stop mdgb-comms`, then
     `cd ~/HackTurin-mdgb && sudo ~/venv/bin/python -m comms.tools.ble_beacon_test --seconds 60`: in the app the camera
     shows the BLE channel with the signal; then `sudo systemctl start mdgb-comms`;
   - **traffic light over the Bridge** (Salvatore): `c1_send --port bridge`, see section 4;
   - **everything together**: vision + firmware + network, then the test of section 9.

   Until the vision writes its files, the network can be tested with test events written in the same files:
   `cd ~/HackTurin-mdgb && ~/venv/bin/python -m comms.tools.c3_sim --rate 1 --duration 7200`.

## 8. What is real and what is a test

| Part | On the board / in the app |
|---|---|
| MQTT | real: Mosquitto (MQTT 5 broker) inside the app on the PC, the node connects over Wi-Fi |
| Bluetooth | real: beacons of the UNO Q radio (`btmgmt`), received by the Bluetooth of the PC. Without BlueZ the node does not start |
| Bridge (vision ↔ MCU) | real: official library `arduino-router-bridge`. Only the sketch side is missing (section 4) |
| Events | real: the node reads only the files written by the vision and by the MCU. Test events only if you run `c3_sim` by hand |
| Cameras on the map | only `nodo01`, the real node (position to change in `nodes.json` from the app, **Cartella** button). Another Arduino with another `NODE_ID` appears by itself |

Who produces what in the dashboard:

| In the dashboard | Where it comes from |
|---|---|
| traffic (pedestrians, cyclists, vehicles, animals), incidents, near misses, give way, vulnerable pedestrians | Paolo, C3 lines in `logs/c3/` |
| traffic-light state and FPS | Paolo, `status` line every ~5 s |
| battery, temperature/humidity/light, tampering, lamp fault, fail-safe | Salvatore, C5 lines of the MCU |
| channel (Wi-Fi or Bluetooth), queue, lost events, duplicates, diagnosis "network down / node healthy / ..." | Lorenzo, the network |

## 9. Full test "Wi-Fi off / on again"

| Step | Where | What | What you see in the app |
|---|---|---|---|
| 1 | PC | app open, node on | green camera, "nodo OK", Wi-Fi/MQTT channel |
| 2 | UNO Q | `sudo iptables -A OUTPUT -p tcp --dport 1883 -j DROP` (cuts only MQTT, ssh stays up) | queue of the node growing |
| 3 | — | wait 30–40 s | yellow camera, "rete giù, nodo sano" (network down, node healthy), BLE channel with the signal |
| 4 | UNO Q | `sudo iptables -D OUTPUT -p tcp --dport 1883 -j DROP` | queue going back to 0 |
| 5 | — | wait 60 s | camera green again over Wi-Fi/MQTT |
| 6 | PC | "Rete" (network) box | **Lost events = 0** |

For the demo in front of the jury the Wi-Fi of the board can also really be turned off (ssh falls too):
`sudo nohup sh -c 'nmcli radio wifi off; sleep 120; nmcli radio wifi on' &` (`TODO(verify)`: `nmcli` on the UNO Q).

## 10. What is missing

- **Salvatore**: `mdgb_line` and `Bridge.notify("mcu_event", ...)` in the sketch (section 4).
- **Paolo**: the vision on the board (section 3).
- **Tests on real hardware** (never done so far): Bluetooth of the UNO Q (permissions, several beacons together, range),
  permissions of the `arduino-router` socket for the vision user, network of the venue.
- LoRa backup and broker in the cloud: after the hackathon, same code.
