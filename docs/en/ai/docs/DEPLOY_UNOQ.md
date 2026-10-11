# Bringing `ai/` to the Arduino UNO Q

> English translation of [`ai/docs/DEPLOY_UNOQ.md`](../../../../ai/docs/DEPLOY_UNOQ.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

**Tested on the board on 10/10/2026:** copy, Python environment, real camera, 9.2 FPS, and with the `mdgb` app running
the traffic light driven through the Bridge (emergency red, fail-safe): see `DECISIONS.md`, point 33.
**Not yet tested:** a request coming from a real scene (calibration needed), the technician page from the phone, the
automatic start.

To start one app or the other (only one runs at a time, because they load the sketch on the microcontroller):
`arduino-app-cli app start user:mdgb` or `arduino-app-cli app start user:test`, or from App Lab.

Order decided by the team: **first sketch + vision**, then the network towards the central office (Lorenzo).

**How the board is set up since the night of 11/10** (`DECISIONS.md`, points 37–42):
- app `mdgb`, default App Lab app: sketch with the buzzer muted for the technician and Lorenzo's `mdgb_link.py` in the
  `main.py`. The sketch does not send `mcu_event`: shock, badge and fail-safe go through `mdgb_link.py`;
- vision as the `mdgb-ai` service and network as the `mdgb-comms` service (broker on Lorenzo's PC): they start by
  themselves;
- all the events in a single folder, `~/ArduinoApps/mdgb/data/c3`, chosen by
  `push_to_arduino.sh --bridge --applab mdgb`:
  - `c3-*.jsonl`: the vision;
  - `applab-*.jsonl`: sensors, shock, badge and fail-safe, written by `mdgb_link.py`.
- Backup of the old sketch and of the `main.py` in `~/HackTurin-mdgb/backups/`.

## How the system is laid out on the board

| What | Where it runs | Whose |
|---|---|---|
| Sketch: traffic light, buzzer, sensors, RFID, anti-theft | microcontroller | Salvatore |
| `main.py` of the App Lab app: receives the data of the sketch | App Lab container | Salvatore |
| App `mdgb` in `~/ArduinoApps/` (10/10): copy of `test` with the sketch listening to the vision and without camera | as above | Paolo's proposal, to review with Salvatore |
| **Vision** (`smartcrossing.app`): camera, rules, commands to the traffic light, technician page | Linux, outside App Lab | Paolo |
| Network towards the central office and backup | Linux | Lorenzo, later |

- **The vision stays outside App Lab**, in `~/venv`: same code tested on the PC, dependencies isolated from the App Lab
  ones. It talks to the sketch through the `arduino-router` service of the board (`--actuator bridge`).
- **Only the vision opens the camera.** The `main.py` of the App Lab app must not open it: a camera cannot be read by
  two programs together.
- **To talk to the sketch** the vision uses three files already written by Lorenzo (`comms/actuators.py`, `jsonl.py`,
  `__init__.py`). They are the vision–sketch link, not the network: `--bridge` copies them.

## 1. Access to the board

```bash
ssh arduino@<board-name>.local      # user arduino, password chosen at the first start with App Lab
```

To avoid typing the password at every copy: `ssh-copy-id arduino@<board>` (once).
If ssh warns that the host key has changed, do not ignore it: first understand why (another device that had that
address, board reinstalled), then `ssh-keygen -R <address>` on the PC.

Checks to do at once on the board:

```bash
cat /etc/os-release; python3 --version    # found: Debian 13, Python 3.13.5
nproc; free -h; df -h ~                   # found: 4 cores, 3.6 GB of RAM, 16 GB free
ls ~/ArduinoApps; arduino-app-cli app list   # Salvatore's app and whether it is running
cam -l; ls -l /var/run/arduino-router.sock   # the camera as seen by libcamera; the router (writable by everybody)
```

## 2. Copy the vision

**Where to type:** on the PC (not on the board), in the Terminal, inside the repo folder.

```bash
cd ~/dev/HackTurin-mdgb
./ai/deploy/push_to_arduino.sh arduino@<board> --bridge
```

What it does, in order:

1. it packs only what runs on the board (vision code, `config.yaml`, model, calibration if there is an `ai/calib.json`:
   3.5 MB) and copies it over ssh to `~/HackTurin-mdgb/ai` on the board. No tests, videos or documents. `git pull` is
   not used on the board: the repo is private and a token would be needed there;
2. with `--bridge` it also copies Lorenzo's three files into `~/HackTurin-mdgb/comms`;
3. on the board it creates the Python environment `~/venv` (only the first time) and installs the dependencies. It
   needs Internet on the board and a couple of minutes. The board lacks `python3-venv` and `sudo` asks for the password:
   the script creates the environment without pip and installs into it with the system pip, without touching anything
   else;
4. it checks and prints: installed versions, camera, router, events folder, technician credentials.

Running it again updates the code. Without ssh: `--pack` creates `mdgb-ai.tar.gz` to copy by hand.

## 3. Technician credentials

On the board, once (typed by whoever must know them; they are not in the repo):

```bash
cd ~/HackTurin-mdgb/ai && ~/venv/bin/python scripts/operator_login.py
```

It asks for user and password and saves in `ai/.env` the name and only the fingerprint of the password. Without this
step nobody can enter the technician page.

## 4. Calibration

There is no window on the board. Calibration is done on the PC on a video or a frame shot by the mounted camera
(`scripts/calibrate.py --source ...`), `ai/calib.json` is saved and `push_to_arduino.sh` is run again.
Without `calib.json` the vision counts the crossings but does not measure speeds and does not apply the rules.

## 5. Camera

The camera of the board is an **IMX219 sensor on CSI**, read by libcamera: it is not a webcam and OpenCV alone does not
open it. It is enough to start the program with `libcamerify` in front (package `libcamera-v4l2`, already on the board):
OpenCV sees it as `/dev/video0`, 632x480.

- If the App Lab app is running with the old `main.py`, the camera is busy and the board is much slower (that program
  alone uses 140% of CPU): the `main.py` without camera must be used.
- A USB webcam, should it ever be needed, opens without `libcamerify` with its index.

## 6. Manual test, in order

On the board, in `~/HackTurin-mdgb/ai`:

```bash
libcamerify ~/venv/bin/python scripts/bench.py 0 --profile unoq     # 1. ms per stage with the real camera
libcamerify ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator sim --operator-port 8090                             # 2. vision without traffic light
libcamerify ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \
    --actuator bridge --operator-port 8090                          # 3. with the traffic light (needs the sketch with mdgb_line)
```

What to look at:

1. **FPS:** 9.2 measured end-to-end with the `unoq` profile (320 px, detector one frame out of two). The numbers are in
   `ai/README.md`, "Measured performance".
2. **Traffic light:** stopping the vision (`Ctrl+C`) it goes back to the normal cycle within half a second. With an
   unaccompanied child or a free animal the red comes after a short yellow; with someone walking slowly the vehicle red
   lasts longer. Calibration and the new sketch are needed.
3. **Technician:** from the phone on the same Wi-Fi, `http://<board>:8090/` says "BLOCCATO" (locked). Swiping the badge
   it asks for user and password, to be given within 2 minutes; after the login it shows numbers and live view until
   "Esci" (log out). Five wrong passwords: the badge must be swiped again. From the badge to the logout the buzzer does
   not sound (needs the sketch with `tech`).
4. **Anti-theft:** shaking the board, the page shows "ultimo urto N s fa" (last shock N s ago). The vision keeps working.

If `--actuator bridge` writes "no sketch provides mdgb_line", the board still has the sketch without `mdgb_line`: the
vision runs anyway, the traffic light does its normal cycle and badge and anti-theft do not reach the vision.

## 7. Turning the vision on and off

**On the demo board the vision is a service since 11/10** (`mdgb-ai`, starts by itself at power-on):
`sudo systemctl restart mdgb-ai` (or `stop` / `start`), log with `journalctl -u mdgb-ai -f`. After a code update:
`push_to_arduino.sh ... --bridge --applab mdgb`, then `sudo sh ~/mdgb-tools/installa_servizio_visione.sh`.
`run_vision.sh` is only needed where the service is not installed: if the service is active, it does not start.

### Benchmarks and tests on a recorded video, as if it came from the camera

The test videos and the calibrations are in `~/HackTurin-mdgb/ai/samples/` on the board (copied by hand:
`push_to_arduino.sh` does not bring them). Without `sudo`, from `~/HackTurin-mdgb/ai`:

```bash
deploy/run_vision.sh video samples/Torino_1.mp4 --calib samples/calib/torino_1.json   # in a loop, until you go back to the camera
deploy/run_vision.sh video samples/Torino_night_1.mp4 --once                          # one pass, then the timing table
deploy/run_vision.sh camera                                                            # back to the camera
journalctl -u mdgb-ai | grep -a -A8 "^pass "                                          # per-stage times of every pass
```

- Everything else works as with the camera: commands to the traffic light, technician page (live view with the boxes),
  events to the central office. To avoid moving the real traffic light: `--actuator sim` at the end of the command.
- The events of the video reach the central office as `nodo01`: the statistics of the day include them.
- The video runs at real speed: if the board is slower, it skips the late frames as it would with the camera
  (`source.file_drop_late`).
- **From the technician page** (after badge and login), only when the source is a video: buttons *Video prima* /
  *Video dopo* (previous / next video: the videos of the same folder, each with its calibration from `samples/calib/`
  if present) and *Indietro* / *Avanti* (back / forward) by 10 s (`operator.video_seek_s`). The switch happens inside
  the vision: the technician session stays open, tracks and counts restart for the new scene. With the camera the
  buttons are not there.

By hand, without `sudo`, in the background (it stays on even closing ssh):

```bash
ssh arduino@<board> '~/HackTurin-mdgb/ai/deploy/run_vision.sh start'    # stop | status | log
```

The log is in `~/HackTurin-mdgb/logs/vision.log`. After changing credentials, calibration or code: `stop`, then `start`.

### Automatic start at power-on

```bash
./ai/deploy/push_to_arduino.sh arduino@<board> --bridge --service    # asks the sudo password
ssh arduino@<board> 'journalctl -u mdgb-ai -f'
```

## 8. Technician page

`--operator-port 8090`. From the phone, over Wi-Fi, on the same network as the board.

- **Two-step access:** badge on the reader, then user and password within 2 minutes (`operator.login_s`). The session
  stays open until the technician presses "Esci" (`operator.session_s: 0`). Login and logout consume the badge: to get
  back in it must be swiped again.
- **Buzzer muted while the technician is there:** from the badge to the logout, or at 2 minutes if they do not log in,
  the C1 command carries `"tech": true` and the sketch does not sound (only the badge confirmation beep). The sketch
  keeps the 2 minutes from the badge by itself, even without vision; without heartbeat the field is no longer valid and
  the buzzer is active again.
- **What it shows**, after the access, in three tabs:
  - **Status:** a sentence at the top ("Tutto funziona" = all working, "Una cosa da controllare" = one thing to
    check...), then the parts to fix with the "what to do" and one row for every working part
    (`smartcrossing/health.py`): camera, recognition, link with the sketch, App Lab app and sketch, temperature and
    humidity, air, light, anti-theft, badge reader, event saving. On the side the traffic light (rule state and reason)
    and the vision details;
  - **Live view:** the camera with the boxes, the video buttons, the counted crossings;
  - **Log:** the last 100 events in memory (node parts, traffic, accesses and alarms), downloadable as text.
  The board sensors arrive from the `env` lines of `mdgb_link.py` every 10 s, which repeat the last value: from here one
  sees the App Lab app or the sketch stopping and impossible values, not a single sensor getting disconnected.
  Every state change of a part also goes in the service log (`journalctl -u mdgb-ai | grep diagnosi`).
- **Logo:** the placeholder of `docs/brand/` (symbol inside the page, no extra file to copy).
- **Image switch:** `operator.share_images: false` in `config.yaml` turns off the live view and leaves only the
  statistics. It is the setting meant for production: no image leaves the program.
- **Images are never saved**: they exist in memory only while a connected technician is watching.
- **Limit:** the page is plain HTTP. On the local network the password travels unencrypted: on the street HTTPS is
  needed. For the demo it is fine, with a password used only here.

## 9. To verify on the real hardware

- [x] Full `pip install` in `~/venv`: two minutes, numpy 2.4.6, onnxruntime 1.30.0, opencv 4.14.0, supervision 0.30.5.
- [x] FPS and ms per stage: see `ai/README.md`.
- [x] Camera read by OpenCV outside App Lab: yes, with `libcamerify`.
- [x] The `arduino` user can use `/var/run/arduino-router.sock`: yes.
- [x] Sketch with `mdgb_line`: commands and heartbeat received, emergency red, fail-safe in about half a second.
- [x] Anti-theft and sensors in the events folder, written by `mdgb_link.py`; the network brings them to the central office.
- [x] Network towards the central office: MQTT to Lorenzo's PC, heartbeat every 10 s with state and FPS of the vision.
- [x] Bluetooth backup: the central office receives it (−41 dBm) when the network falls, 0 events lost (`btmgmt` fixed in `comms/`).
- [x] Automatic start after a reboot of the board: vision, network and `mdgb` app.
- [ ] Badge → page → login from the phone, with the buzzer muted until the logout.
- [ ] Technician page from the phone: login, cost of the live view on the FPS, login time.
- [ ] Temperature and slowdowns after 10 minutes of operation.
- [ ] Vision and App Lab app together: CPU load and memory.
- [ ] Automatic start after a reboot of the board.
- [ ] Camera image: in the evening it is dark and the libcamera processing is not tuned for this sensor.
