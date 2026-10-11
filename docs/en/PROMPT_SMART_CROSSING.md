# MDGB (Mobility Data & Guardian Beacon) — GOMA Smart Crossing challenge — implementation specification

> English translation of [`PROMPT_SMART_CROSSING.md`](../../PROMPT_SMART_CROSSING.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

> MDGB is a module that **is installed on the existing traffic light**: it sees who is arriving, asks the traffic-light
> controller to extend the green or hold the red, warns drivers and pedestrians with two displays and sends only
> anonymous data to the central office. If it breaks, the traffic light goes back to exactly how it was.

> **For the humans.** This file is the shared technical plan. It is used together with `PROMPT_GIT_TEAM.md`
> (git rules and split of the folders). Command to give the AI assistant:
>
> ```text
> Leggi PROMPT_GIT_TEAM.md e PROMPT_SMART_CROSSING.md e seguili. Sono <nome> (<ruolo>). Task: <milestone>.
> ```
>
> ("Read PROMPT_GIT_TEAM.md and PROMPT_SMART_CROSSING.md and follow them. I am <name> (<role>). Task: <milestone>.")

---

From here on the instructions are for you, AI assistant. Answer in Italian, code comments in English.

## 0. Rules of engagement

1. `PROMPT_GIT_TEAM.md` takes precedence: branches, commits, perimeter of the folders, contracts.
2. Implement ONLY the modules of the user's area (see §3). If you need a module of another area that is not ready yet,
   create a mock or a simulator inside the user's folders, written against the contracts of §4.
3. The decisions of §2 are already taken: do not question them without asking the user.
4. No invented APIs. For Arduino App Lab, the UNO Q Bridge, supervision, onnxruntime and the sensors, check the
   official documentation and put the link in the comment. If you cannot verify it: stub + `TODO(verify)`.
5. Every milestone ends with: the exact command to try it, the expected output and the message for the team required
   by PROMPT_GIT_TEAM.md. Then stop and wait for the ok.
6. Hackathon: working demo before perfect code. Simple code, few dependencies.

## 1. Context

- GOMA brief: embedded device with computer vision and AI **entirely local** that recognises pedestrians, cyclists,
  vehicles, people with disabilities and animals near a crossing. It must activate a light signal in real time
  according to an **explicit rule**, count the crossings distinguishing their **direction** (without duplicates) and
  work **without internet**.
- **MDGB concept**:
  - **Existing traffic light**: MDGB does not replace the traffic-light controller. It sends it **requests**: extend
    the pedestrian green, hold the vehicle red, activate the flashing light. The controller executes them respecting
    its own minimum times. **Fail-safe = the controller goes back to its normal cycle** (no extra risk compared with
    today).
  - **Crossings without a traffic light**: MDGB drives its own flashing light; there the fail-safe is the flashing
    yellow.
  - **In the prototype** the controller is **simulated in the firmware** (vehicle green/yellow/red cycle + pedestrian
    figure, with minimum times) and the traffic light is made with the WS2813 strips/ring.
  - **Displays**: Grove LCD 16x2 towards the drivers ("PEDONE 47 km/h", pedestrian 47 km/h), OLED towards the
    pedestrians (countdown, "ATTENDI: auto a 45 km/h", wait: car at 45 km/h); optional voice warning (Grove MP3) for
    visually impaired people.
  - **Data**: anonymous metadata + environmental sensors (temperature, humidity, light, IMU) towards a central office
    (MQTT/AWS IoT Core, BLE backup in the prototype and LoRa in production). The flow forecasts are computed on the
    server: open data for the Municipality + paid service for businesses.
- Final hardware: **Arduino UNO Q**.
  - MPU Qualcomm QRB2210: 4x Cortex-A53 at 2.0 GHz, Adreno 702 GPU, no NPU, Debian Linux aarch64, 2/4 GB of RAM.
  - MCU STM32U585 (Zephyr, Arduino sketch). The two parts communicate with the Arduino **Bridge** RPC.
  - A single USB-C port: the USB webcam goes through a powered USB-C hub.
- Development and tests on macOS (Apple Silicon) and Linux. **The same Python code must run on PC and on the UNO Q.**
- Known performance on the UNO Q:
  - YOLOv8n 640 px with OpenCV DNN: 1–2 FPS;
  - App Lab's yolox-nano: about 10 FPS;
  - Edge Impulse YOLOv5-pico at 224 px: about 17 FPS.
  Target: **≥ 8 FPS end-to-end at 320 px**.
- Hackathon setting: on site Sat 10–20 and Sun 9–16. Delivery on Sunday at 16.

## 2. Decisions already taken

| Topic | Decision | Why |
|---|---|---|
| Detector | **YOLOX-nano COCO in ONNX** (Apache-2.0) run with **onnxruntime**, input 320 (416 optional) | Runs on x86/arm64/aarch64, no torch at runtime, free licence |
| Tracking | `supervision.ByteTrack` | MIT, light |
| Directional counting | `supervision.LineZone` with `minimum_crossing_threshold` + minimum track age | Avoids duplicates and oscillations on the line |
| Pedestrian type | **Cascade**: generic COCO detector, then attributes computed **once per track** | No label conflicts between datasets, minimal cost |
| Child | Height in metres (homography), < 1.30 m | No ML, robust |
| Elderly / slow | **Measured walking speed** < 0.9 m/s | The time really needed is measured, not guessed from the age |
| Aids (wheelchair, walker, stroller) | **Optional** ONNX classifier on 96x96 crops (trained separately by the data scientist) | If the model is missing the system works anyway |
| Incidents | **Rules on trajectories**, no video model | Too heavy for the UNO Q |
| Safety | Physical rule (TTC, stopping distance) + **fail-safe in the firmware** (heartbeat) | GOMA's "safety" language: safety does not depend on Linux |
| Privacy | **Never save frames to disk**: metadata only | GDPR / AI Act, pitch argument |
| Python runtime | numpy, opencv-python(-headless), onnxruntime, supervision, pyyaml, pyserial; flask only for the dashboard | No torch/ultralytics at runtime (weight, AGPL licence) |

## 3. Modules → folders → owner

| Area (folder) | Owner | Modules |
|---|---|---|
| `ai/` | Data scientist | package `ai/smartcrossing/`: sources, detector, tracking, derive, geometry, counting, attributes, animals, thermal, events, rules, logger, `app.py` (entry point), calibration/benchmark/probe scripts, tests |
| `firmware/` | Embedded engineer | `firmware/unoq_mcu/` (STM32 of the UNO Q via Bridge), `firmware/serial_mcu/` (Arduino R4/any, for tests from the PC), fail-safe, command parsing, LEDs |
| `comms/`, `app/`, `docs/CONTRACTS.md` | Communication engineer | actuator transports (sim, serial, bridge) in `comms/`, headless web dashboard in `app/`, offline log and sync, optional V2X broadcast, contracts |
| `hardware/` | Electronics engineer | LED schematic, MOSFET driver, power supply, USB-C hub, thermal camera, pinout, BOM |

Integration: `ai/smartcrossing/app.py` imports the actuators from `comms/` through the `Actuator` interface defined in
§4. Until `comms/` is ready, `ai/` uses its own local `SimActuator`.

## 4. Contracts v1 (draft to be confirmed by the communication engineer and then copied into `docs/CONTRACTS.md`)

**C1 — AI → firmware command** (JSON lines, one per message. Serial at 115200 baud or argument of the Bridge call):
```json
{"v":1,"seq":1842,"t_ms":1739012345678,"state":"WARN_DRIVER","led":"AMBER_BLINK_2HZ","green_s":19,"req":{"ped_green_extend_s":7,"veh_red_hold":true,"flash":false},"lcd":"PEDONE  47 km/h","oled":"ATTENDI auto 45km/h","reason":"anziano 0.8 m/s; auto 50 km/h a 60 m; TTC 4.3 s < T_need 9.8 s"}
```
- `req` = requests to the controller (real or simulated): the controller applies them only if they respect its minimum
  times.
- `lcd` (max 2x16 characters) and `oled` = texts for the displays towards drivers and pedestrians.
- `state` ∈ IDLE | PRESENCE | WARN_DRIVER | WARN_PEDESTRIAN | ANIMAL_WARN | ANIMAL_ALERT | DEGRADED
- `led` ∈ OFF | WHITE_ON | AMBER_BLINK_2HZ | AMBER_BLINK_4HZ | RED_GROUND_BLINK | YELLOW_FAILSAFE

**C2 — AI → firmware heartbeat**, every 100 ms: `{"v":1,"hb":1843}`.
If the firmware receives no heartbeat for **more than 500 ms**:
- `signalized` mode (existing traffic light) → **cancel all the requests and leave the controller in the normal cycle**;
- `uncontrolled` mode (zebra crossing without traffic light) → `YELLOW_FAILSAFE`.

**C3 — AI → comms/app events** (JSONL on file + local HTTP endpoint):
```json
{"v":1,"ts":1739012345.67,"type":"crossing","track_id":12,"cls":"pedestrian","attrs":{"child":false,"slow":true,"aid":null},"dir":"in","line":"ped"}
{"v":1,"ts":1739012350.10,"type":"near_miss","a":12,"b":31,"ttc_s":0.8,"pet_s":null}
{"v":1,"ts":1739012399.00,"type":"incident","kind":"person_down","track_id":12,"zone":"carriageway"}
{"v":1,"ts":1739012400.00,"type":"status","state":"PRESENCE","fps":9.6,"lat_ms":{"detect":71,"track":3,"rules":1,"act":2},"counts":{"ped_in":14,"ped_out":11,"car_in":52}}
```

**C4 — Node → central office** (MQTT 5 over TLS towards AWS IoT Core, one X.509 certificate per node; topics
`mdgb/<node_id>/events`, `mdgb/<node_id>/agg`, `mdgb/<node_id>/hb`):
```json
{"v":1,"event_id":"nodo07-000805","node_id":"nodo07","ts":1739012345.67,"type":"crossing", "...": "C3 fields"}
{"v":1,"event_id":"nodo07-000806","node_id":"nodo07","type":"agg","t0":1739011500,"t1":1739012400,"ped":{"in":14,"out":11},"veh":{"car":52,"bike":6},"env":{"t_c":14.2,"rh":81,"lux":120},"yield_rate":0.42}
{"v":1,"node_id":"nodo07","type":"hb","ts":1739012400,"mode":"normal","link":"wifi","batt":null,"queue":0}
```
- Unique `event_id` = `node_id` + **persistent** counter (survives reboots). The server discards IDs already seen
  (QoS 1 = "at least once" → duplicates can arrive).
- Over the backup channel (BLE/LoRa) **only** these go: alarms at once, `hb` every 5 min, `agg` every 15 min, in compact
  format. The full events stay in the store & forward.

**Python interface** (in `comms/actuators.py`, with a mock in `ai/`):
```python
class Actuator:
    def send(self, cmd: dict) -> None: ...      # C1
    def heartbeat(self, seq: int) -> None: ...  # C2
    def close(self) -> None: ...
# implementations: SimActuator (overlay), SerialActuator(port, baud), BridgeActuator (UNO Q)
```

## 5. Specification per area

### 5.1 `ai/` — package `smartcrossing`

1. **`sources.py`**: webcam (index), video file, RTSP. Resizing and `--max-fps`. Returns `(frame, t_monotonic)`.
2. **`detector.py`**:
   - YOLOX-nano ONNX. `scripts/get_model.sh` downloads `yolox_nano.onnx` from the official Megvii-BaseDetection/YOLOX
     releases (check the URL) into `ai/models/` (ignored by git).
   - Correct YOLOX preprocess: letterbox with padding 114, BGR, **no** normalisation.
   - Decoding of grids and strides in numpy, NMS.
   - Parameters: `input_size` 320/416, `conf`, `nms`, `intra_op_num_threads`, `detect_every_n` (in the intermediate
     frames only the tracker works).
   - Classes kept: person, bicycle, car, motorcycle, bus, truck, dog, cat, horse, sheep, cow, bear, bird.
3. **`tracking.py`**: `sv.ByteTrack` with parameters from config. A track is valid after `min_track_age` frames
   (default 5). History per track: ground positions, speeds, class votes.
4. **`derive.py`**:
   - cyclist = person overlapping bicycle (IoU > 0.3 and the person box above the bicycle box);
   - motorcyclist likewise;
   - final class of the track by majority.
5. **`geometry.py`** + **`scripts/calibrate.py`**:
   - click 4 points on the ground (corners of the crossing), enter the measures in metres and save the homography in
     `calib.json`;
   - in the same file: polygons `waiting_zone_left/right`, `crosswalk`, `carriageway`, counting lines, width `W`;
   - API: pixel → metres (bottom-center point), speed (EMA over 5 samples), acceleration, estimated height in metres,
     length on the ground in metres.
6. **`counting.py`**:
   - `ped_line` along the crossing (anchor BOTTOM_CENTER) and `veh_line` across the lane;
   - `minimum_crossing_threshold` from config;
   - IN/OUT counts per class;
   - every tracker_id counted at most once per direction.
7. **`attributes.py`** (computed once per track, then stored):
   - `child`: median height over 5 frames < 1.30 m;
   - `slow`: mean speed in the waiting zone or on the crossing < 0.9 m/s for at least 2 s;
   - `aid`: optional ONNX classifier `ai/models/aid_cls.onnx` on the 96x96 person crops
     (normal / wheelchair / walking_aid / stroller), vote over 3–5 crops. If the file is missing → `None`, without errors.
8. **`animals.py`** (§7).
9. **`thermal.py`** (§6).
10. **`events.py`** (thresholds in config):
    - collision: ground distance < 1 m between two tracks, at least one previously at > 3 m/s, then both < 0.3 m/s
      within 1.5 s;
    - person down: width/height ratio > 1.2 for more than 3 s on the carriageway;
    - hard braking: deceleration > 6 m/s²;
    - near miss: TTC < 1 s or PET < 1 s between vehicle and pedestrian/animal;
    - vehicle stopped on the crossing for more than 10 s;
    - **yield rate**: out of the approaching vehicles with a pedestrian in the waiting zone, how many slowed below
      2 m/s before the crossing.
11. **`rules.py`** — EXPLICIT STATE MACHINE, pure Python, without OpenCV, fully testable:
    - `d_stop = v*1.0 + v^2/(2*7.0)`, `T_need = W/v_ped + 1.0`, `TTC = d/v`;
    - `v_ped` = 1.2 m/s by default; 0.8 if child, slow, aid or unclassified pedestrian seen only in thermal; if lower,
      the measured speed is used;
    - priority: DEGRADED > WARN_PEDESTRIAN > ANIMAL_ALERT > WARN_DRIVER > ANIMAL_WARN > PRESENCE > IDLE;
    - WARN_DRIVER: pedestrian with intention (in the waiting zone for more than 1 s, or moving towards the
      carriageway), TTC < T_need and d > d_stop + 10;
    - WARN_PEDESTRIAN: d ≤ d_stop + 10 and the vehicle does not decelerate (a > −2 m/s²);
    - green extension: `green_s = min(25, max(W/1.2, W/v_ped) + 2)`;
    - DEGRADED: the video source has not arrived for more than 1 s, or the self-check fails (Laplacian variance below
      threshold = lens covered; saturated histogram = glare);
    - output: a dict compliant with C1, with a readable `reason`.
12. **`logger.py`**: C3 events in JSONL with rotation, works offline. Never frames.
13. **`app.py`**: `python -m smartcrossing.app --source 0|file.mp4|rtsp://… --profile pc|unoq --site urbano|lungofiume|collina [--headless] [--emulate-unoq] [--actuator sim|serial|bridge] [--thermal none|uvc|mlx90640]`.
    - Overlay: boxes, IDs, class, attributes, speed in km/h, zones, lines and counts, state with `reason`, FPS and ms
      per stage (detect/track/rules/act).
    - `--emulate-unoq`: 10 FPS, input 320, onnxruntime with 4 threads.
    - `--headless`: no window; publishes C3 for the dashboard of `app/`.
14. **Scripts**:
    - `scripts/bench.py`: mean and p95 ms per stage on a video, prints a table;
    - `scripts/animal_probe.py <folder>`: best COCO class and confidence per image, plus the "at least one animal"
      recall.

### 5.2 `firmware/`

- `serial_mcu/serial_mcu.ino` (UNO R4 or any Arduino) and `unoq_mcu/` (STM32 of the UNO Q via Bridge: check the
  official App Lab APIs, i.e. the Bridge library on the sketch side and on the Python side).
- Parsing of C1 and C2. Mapping `led` → pins, with the pins in `pins.h` taken from the Pinout section of CONTRACTS.md.
- **Simulated controller** (`signal_controller`): vehicle cycle green 20 s → yellow 3 s → red, pedestrian figure
  green/red, pedestrian call (Grove Touch). It applies the `req` of C1 **only** within fixed limits: pedestrian green
  extension ≤ 15 s, vehicle red held ≤ 20 s, minimum vehicle green 8 s. The limits are constants in the firmware, not
  configurable from Linux.
- **Local fail-safe**: no heartbeat for more than 500 ms → in `signalized` the requests are cancelled and the controller
  goes back to the normal cycle; in `uncontrolled` → `YELLOW_FAILSAFE` (yellow at 1 Hz). Hardware watchdog.
  At boot: normal cycle (or yellow) until the first heartbeat arrives.
- Displays: LCD 16x2 (drivers) and OLED (pedestrians) show the `lcd`/`oled` texts of C1; without heartbeat they show
  only the normal cycle / the countdown.
- Environmental sensors (AHT20 temperature/humidity, light sensor, Modulino Movement): read by the MCU every 10 s and
  forwarded to Linux via Bridge for the C4 aggregates.
- **Second safety path (independent of the vision)**: Grove PIR + Modulino Distance (ToF, about 1.3 m) read directly by
  the MCU. If they detect a pedestrian in the waiting zone while the vision is in DEGRADED or there are no heartbeats
  → `AMBER_BLINK_2HZ` instead of the simple yellow.
- **Lamp monitoring**: Grove ACS70331 on the 5 V line of the WS2813 strips. For every pattern there is an expected
  current; if it deviates by more than ±30% → a `lamp_fault` event is sent to the AI/comms (extend C3) and the
  firmware goes into fail-safe.
- Modulino Movement: a shock or a tilt beyond threshold → `tamper` event (the calibration is no longer valid →
  DEGRADED).
- LEDs: Grove WS2813 strip ×2 (vehicles / on the ground) + RGB LED Ring 16 (pedestrian lantern), brightness limited in
  software.
- Panel towards the vehicles: Grove LCD 16x2 (short text + speed).

### 5.3 `comms/` and `app/`

Principle: **safety is local, data is never lost, the node stays visible even when the network falls.**

- `comms/actuators.py`: `SimActuator`, `SerialActuator` (pyserial, automatic reconnection), `BridgeActuator`.
- **Main channel**: MQTT 5 over TLS towards AWS IoT Core via 2.4 GHz Wi-Fi, one certificate per node (revocable
  individually). QoS 1. Only anonymous metadata (C4), never images.
- **Store & forward**: every event is written to disk (e.g. SQLite) **before** sending and deleted only after AWS's
  PUBACK. When the network returns the queue empties by itself; the server deduplicates by `event_id`.
  If tested code already exists (test 806/806 events), it must be integrated here without rewriting it.
- **Failover**: no PUBACK for 30 s → switch to the backup. **Back to Wi-Fi only after 60 s of regular confirmations**
  (hysteresis: no continuous jumps between the channels).
- **Backup**: BLE in the prototype (the demo laptop = central office), LoRa towards a gateway of the central office in
  production (no dependency on the internet; 1% duty cycle rule at 868 MHz → only alarms, hb, agg).
  It is switched with a setting (`backup: ble|lora`).
- **Diagnosis in the central office**: MQTT ❌ + backup ✅ → network down, node healthy; failed self-check → node faulty;
  both ❌ after a dropping battery → battery flat; both ❌ after an IMU/case-opening event → tampering.
- `app/`: dashboard of the central office: map/state of the nodes, active channel, store & forward queue, counts per
  class and direction, yield rate, near misses, alarms, environmental data. MJPEG stream **only** live, only locally
  and only if enabled.
- **Server (stretch, after the base demo)**: history of the aggregates + flow forecasting model (e.g. gradient boosting
  on hour, day, weather, events) in `ai/forecast/`. At the hackathon there is no history: the pipeline is shown with
  simulated data, saying so. External APIs (weather, Google Maps Platform, Copernicus) optional, behind a key in
  `.env`, never essential.
- V2X stretch: UDP or ESP-NOW broadcast of a "VAM-like" message (position, class, direction of the pedestrian) to a
  second device acting as "car dashboard" that shows "PEDONE NASCOSTO A X m" (hidden pedestrian at X m). Measure the
  end-to-end latency.

### 5.4 `hardware/`

- Traffic light of the model: vehicle lanterns (red/yellow/green) and pedestrian lantern (red/green figure) with WS2813
  strips/ring; amber flashing light; MOSFET driver; separate 5 V supply for the LEDs.
- Displays: LCD 16x2 (towards drivers) and OLED (towards pedestrians); call button (Grove Touch).
- Environmental sensors: AHT20, light sensor, Modulino Movement.
- Powered USB-C hub for the webcam (and for the UVC thermal camera).
- Thermal camera (§6): Grove MLX90621 16x4 (available). Components and priorities: `hardware/BOM.md`.
- Pinout in `docs/CONTRACTS.md`, BOM, PNG/PDF export of the schematic.

## 6. Night: thermal camera (optional, enabled with `--thermal`)

Motivation: after the return to standard time (25/10) darkness comes at rush hour. With little light the RGB camera
loses dark-clothed pedestrians. The thermal camera sees the heat and, in addition, **does not allow anyone to be
recognised** (privacy).

Two hardware options, same interface `ThermalSource.read() -> (temp_or_gray_frame, t)`:

| Option | Resolution | What it is used for | Notes |
|---|---|---|---|
| **A0. Grove MLX90621 (16x4, FOV 60°x16°) — THE AVAILABLE ONE** | At 4 m each column covers about 29 cm: a person covers about 2 columns | **Heat strip along the kerb**: for each column, presence if T > ambient + 3 °C; the waiting zone = a set of columns | No 2D blobs or classification. I2C reading from the MCU, forwarded via Bridge as an array of 64 temperatures |
| **A. MLX90640** (I2C, 32x24, FOV 55°x35° or 110°x75°) — not available | A person at 8 m covers about 8 px of height; a wild boar about 4 px | **Presence per zone only**: blobs above the temperature threshold (e.g. > ambient + 4 °C), minimum area, centroid tracking | Cheap. No YOLO. Reading from Linux via I2C or from the MCU and then Bridge (check what is simpler on the UNO Q) |
| **B. UVC thermal camera** (e.g. 256x192) | Person at 8 m: tens of px | Detector on the thermal image: YOLO-Thermal weights / TD4PWMR dataset, or fine-tuning on FLIR ADAS (check licences) | Seen as a webcam by OpenCV: check that the chosen model is UVC |

Fusion logic (`thermal.py`):
- **Night mode**: mean luminance of the RGB frame < threshold for more than 5 s (or photoresistor via MCU).
- **Recovery**: thermal blob in the waiting zone or on the crossing **without** RGB detection for at least 0.5 s
  → "unclassified pedestrian" track with `v_ped` = 0.8 (when in doubt, protect more).
- **Confirmation**: an RGB "person" detection with an overlapping thermal blob raises the confidence;
  a "person" without heat in night mode (reflection, poster) lowers it.
- **Thermal zones**: polygons drawn directly on the thermal image in `calib_thermal.json` (no full homography).
- Tests with synthetic frames (numpy arrays with hot blobs).

## 7. Animals

- Class `animal` = dog, cat, horse, sheep, cow, bear. Keep the original COCO class in the logs.
  `bird` counts **only** if on the ground on the carriageway, length ≥ 0.5 m (goose or swan, not pigeon) and present
  for more than 2 s.
- **Dog on a leash**: animal with a person within 2.0 m on the ground and similar direction of motion (< 45°) for at
  least 1 s → same `group_id`, no alarm of its own (the pedestrian rules apply).
- **Size** from the homography:
  - `large` = length ≥ 0.8 m or height ≥ 0.6 m;
  - `medium` = 0.3–0.8 m;
  - `small` < 0.3 m (log only: hedgehogs, squirrels and distant cats are out of reach of the camera).
- **Herd**: animals within 3 m → same `herd_id`. The alert stays active as long as the last member is on the
  carriageway, +2 s.
- States:
  - `large` free on the carriageway → ANIMAL_ALERT (`AMBER_BLINK_4HZ`), even without vehicles;
  - `medium` free → ANIMAL_WARN only if there is a vehicle with d < d_stop + margin (30 m, 40 m in the `collina`
    profile).
  - **No acoustic signal** towards the animals.
- `--site` profiles:
  - `urbano` (urban): pedestrians and dogs, bird excluded;
  - `lungofiume` (riverside): + large birds on the ground;
  - `collina` (hill): + ungulates and herds, more sensitive night thresholds, thermal recommended.
- `scripts/animal_probe.py` is used to decide whether to fine-tune: if the "at least one animal" recall on the photos
  of wild boar and roe deer exceeds 70%, no training.

## 8. Tests (pytest, must pass on PC without hardware)

- rules: elderly (0.8 m/s), W = 7 m, car at 50 km/h (13.9 m/s) at 60 m → WARN_DRIVER (T_need 9.75 s, TTC 4.3 s,
  d_stop 27.7 m); same car at 25 m without deceleration → WARN_PEDESTRIAN; no vehicle → PRESENCE; video missing for
  1.5 s → DEGRADED.
- green: W = 12 m, v_ped = 0.7 → 19.1 s; v_ped = 0.3 → 25 s (maximum cap).
- counting: a track oscillating on the line does not generate double counts; a real crossing counts 1 in the right
  direction.
- geometry: with a known homography, the pixel→metres conversion is within tolerance.
- events: synthetic tracks of collision, person down and hard braking generate the right event.
- animals: wild boar of 1.2 m on the carriageway → ANIMAL_ALERT; cat of 0.25 m → log only; dog at 1.5 m from a person
  → no alarm; herd of 3 → the alert stays active until the last one leaves.
- thermal: hot blob in the waiting zone without RGB detection for 0.6 s in night mode → unclassified pedestrian with
  v_ped = 0.8.
- firmware (if possible, tests on host): C1/C2 parser and heartbeat timeout.

## 9. Milestones (per area; each closes with commit, PR and message to the team)

**ai/**
- AI-M1: source + detector + tracker + overlay on a video → stable boxes and IDs; `bench.py`.
- AI-M2: counting + derive (cyclist) → correct IN/OUT counts, without duplicates.
- AI-M3: calibration + speed + attributes + rules + SimActuator → the full demo runs on the PC (`--emulate-unoq`).
- AI-M4: events + animals + logger + C3 output.
- AI-M5: thermal (first simulated MLX90640, then the real hardware if available).
- AI-M6: `unoq` profile, test on the board, benchmark numbers in the README.

**firmware/**
- FW-M1: `serial_mcu` with simulated controller, C1/C2 parser, LEDs, displays and fail-safe, tested from the PC with
  `SerialActuator`.
- FW-M2: `unoq_mcu` via Bridge, same behaviour.
- FW-M3: sensors (PIR, ToF, AHT20, light, IMU, ACS70331) + second safety path + lamp monitoring.

**comms/ + app/**
- CM-M1: CONTRACTS.md v1 (from §4) + `actuators.py` (sim/serial).
- CM-M2: MQTT/AWS IoT Core + store & forward (integrating the already-tested code) + server-side dedup.
- CM-M3: BLE failover with hysteresis + diagnosis + central office dashboard.
- CM-M4: BridgeActuator.
- CM-M5 (stretch): V2X "hidden pedestrian" towards a smartphone; forecasting pipeline with simulated data.

**hardware/**
- HW-M1: pinout + LED schematic + BOM.
- HW-M2: thermal camera + hub + case (3D print).

## 10. Deploy on the UNO Q (`ai/docs/DEPLOY_UNOQ.md`, written by the data scientist with the embedded engineer)

ssh to the board; `python3 -m venv ~/venv` (the system pip is blocked); `pip install -r ai/requirements.txt`
(headless version of OpenCV); copy of `models/` and `calib.json`; webcam through a powered USB-C hub;
systemd service for the automatic start; loading of the firmware on the STM32; check of the Bridge.
At the end: the list of what remains to be verified on the real hardware.
Alternatively, if App Lab turns out simpler: packaging as an App Lab app (check the documentation).

## 11. Demo checklist (Sunday by 14:00)

- [ ] Night and day video of a crossing: correct counts shown on screen.
- [ ] Elderly + fast car scenario: WARN_DRIVER with the `reason` visible, then WARN_PEDESTRIAN.
- [ ] **Vision kill test**: the AI process is closed → within 0.5 s the traffic light goes back to the normal cycle
      (or to the flashing yellow without traffic light), and PIR/ToF keep seeing the pedestrian.
- [ ] **Network kill test**: the Wi-Fi is turned off → after 30 s the node switches to BLE and the dashboard shows
      "network down, node healthy"; it is turned back on → the queue empties, events sent = received.
- [ ] Extended pedestrian green and held vehicle red visible on the model's traffic light, with the texts on LCD/OLED.
- [ ] Extended green for a slow pedestrian, with the computation shown.
- [ ] Free animal vs dog on a leash.
- [ ] Numbers on screen: FPS, ms per stage, yield rate, near misses.
- [ ] No frame saved to disk (to say in the pitch).
