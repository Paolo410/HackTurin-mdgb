<img src="../../brand/mdgb-simbolo.svg" alt="MDGB" width="56" align="right">

# ai/ — vision and rules of MDGB

> English translation of [`ai/README.md`](../../../ai/README.md), from `main` at `1f9a131` (11 October 2026), updated with the counting benchmark of 11 October (PR #22). The Italian original is the reference: if the two differ, the original wins.

**Owner:** Paolo Malugani (data scientist).

## Purpose

The `smartcrossing` package runs on the Linux side of the UNO Q (and identically on a PC). From a camera it:

1. detects and follows pedestrians, cyclists, vehicles and animals (YOLOX-nano ONNX + ByteTrack);
2. counts the crossings per direction, without duplicates;
3. measures position and speed on the ground and derives the attributes of the pedestrian (child, slow, walking aids);
4. decides the state of the signalling with an explicit rule (`rules.py`) and sends it to the firmware (contracts C1
   and C2);
5. writes the anonymous events for `comms/` and `app/` (contract C3).

It never saves frames to disk. Everything works without internet.

Decisions, numbers, interfaces and open questions: [DECISIONS.md](DECISIONS.md). How well it counts, with the method
to measure it again: [docs/BENCHMARK.md](docs/BENCHMARK.md). For the AI assistant that takes over (demo launch and
model improvement): [`ai/docs/ISTRUZIONI_AI.md`](../../../ai/docs/ISTRUZIONI_AI.md) (Italian).
Full specification: [`PROMPT_SMART_CROSSING.md`](../PROMPT_SMART_CROSSING.md), §5.1.

Next to `smartcrossing` there is [`forecast/`](forecast/README.md): the model of the expected flow that the central
office shows for every camera (gradient boosting on calendar, nearby places, ESA WorldCover and weather, corrected with
the counts of the node).

## Status

| Milestone | Content | Status |
|---|---|---|
| AI-M1 | video source + detector + tracker + overlay, `bench.py` | done |
| AI-M2 | counting per direction + cyclist/motorcyclist | done |
| AI-M3 | calibration, speed, attributes, rules, `SimActuator` | done |
| AI-M4 | events, animals, logger, C3 output | done |
| AI-M5 | thermal camera | done in simulation, to be tried with the sensor |
| AI-M6 | `unoq` profile, test on the board, benchmark | the vision runs on the board and drives the traffic light of the `mdgb` app; since 11 Oct detector on every frame (5.9 FPS with a video, to be measured again with the camera). Counting checked on 8 still-camera videos: [docs/BENCHMARK.md](docs/BENCHMARK.md). The calibration on the crossing is missing. Guide in [docs/DEPLOY_UNOQ.md](docs/DEPLOY_UNOQ.md) |

## How to start it

First time:

```bash
cd ai
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
bash scripts/get_model.sh          # downloads yolox_nano.onnx (3.7 MB) into ai/models/ and creates its free-input copy
```

Then, with the virtualenv active and inside `ai/`:

```bash
python -m smartcrossing.app --source 0                     # webcam, window with the overlay (q or Esc to quit)
python -m smartcrossing.app --source samples/video.mp4     # video file
python -m smartcrossing.app --source 0 --emulate-unoq      # nominal limits of the specification: 10 FPS, 4 threads
python -m smartcrossing.app --source 0 --headless          # no window, one status line per second
python -m smartcrossing.app --source 0 --operator-port 8090  # plus the technician page (badge + login)
python scripts/operator_login.py                           # sets user and password of the technician
python scripts/calibrate.py --source samples/video.mp4     # calibrates the framing and saves calib.json (see below)
python scripts/scenario.py                                 # list of the simulated scenes (no camera)
python scripts/scenario.py elderly_fast_car                # slow pedestrian + car at 50 km/h: rules and actuator
python scripts/animal_probe.py photo_folder                # how the detector sees animals not covered by COCO
python scripts/evaluate.py samples/video.mp4 --calib c.json  # numbers and annotated frames of a test video
python scripts/bench.py samples/video.mp4                  # mean and p95 ms per stage
python scripts/benchmark.py score scheda_prima scheda_nuova  # crossings counted against the reference (docs/BENCHMARK.md)
pytest                                                     # tests, without hardware
```

- Without `--source` the first video in `ai/samples/` is used (ignored by git); if it is empty, the webcam.
- On macOS the terminal must be authorised the first time: System Settings > Privacy & Security > Camera.
- `--actuator sim` (default) needs no hardware. `--actuator serial --port ...` uses `comms/actuators.py`.
- `--site urbano|lungofiume|collina` (urban, riverside, hill) chooses which animals count (default `urbano`).
- The C3 events end up in `logs/c3/` in the root of the repo (ignored by git). `--c3-dir` changes the folder,
  `--no-c3` turns them off.
- `--thermal mlx90621` uses the Grove 16x4 thermal camera read by the microcontroller; `--thermal sim` simulates one.
  `--night` forces night mode to try the fusion by day.
- **Do not keep the repo in a synced folder** (Desktop or Documents with iCloud, OneDrive, Dropbox): the virtualenv and
  `.git` get moved to the cloud and the start stays blocked.

On screen: one box per track with `#ID role score speed attributes` (grey until the track has 5 frames), the zones and
the counting lines with the arrow of the IN direction, the counts, FPS and milliseconds per stage. At the bottom the
state, the lamp, the reason of the decision, the texts of the two displays and the requests to the controller.
Every crossing and every state change are also printed on the terminal.

## Calibration

Done once for every camera position, with `scripts/calibrate.py`:

1. click the four corners of the zebra crossing: first the two on the near kerb (1, 2), then the two on the far kerb
   going around (3 opposite 2, 4 opposite 1);
2. give two measures in metres: `--along` is the distance 1–2 (the crossing measured along the road), `--width` is the
   distance 2–3 (the road from kerb to kerb). Without the options the script asks for them;
3. the script shows the derived zones and lines: `s` saves `calib.json`, `r` starts over.

From these data it derives: metres and speeds, the two waiting zones on the pavements, the crossing, the carriageway and
the two counting lines. The margins are in `config.yaml` (`geometry`).
With `--lines-only` only the two counting lines are drawn, without measures: enough to count, not for the rules.
Without a calibration in metres the state stays `IDLE`.

Calibration is manual: a person does it at installation time, and it must be redone if the camera is moved. There is no
automatic calibration. Two helps:

- **measures without a tape:** in Italy zebra stripes are 50 cm wide with 50 cm gaps, and at least 2.50 m long
  (regulation of the Highway Code, D.P.R. 495/1992, art. 145). Counting the stripes from kerb to kerb gives the width
  of the road: one stripe plus one gap make one metre;
- **plausibility check:** from the four points and the two measures the script reconstructs where the camera is and
  prints its height above the ground. If the number is far from the truth, or if the warning appears that the points do
  not fit a real camera, a corner or a measure is wrong. It holds for normal cameras (webcam, phone), not for images
  cropped on one side.

The height of the people (attribute `child`) uses the reconstructed position of the camera: from a camera high up a
person looks shorter than the road next to them is wide, and without this correction adults come out as children.
`child` is decided only when the height is measurable: a calibration that fits a real camera and a box at least
30 pixels tall (`attributes.height_min_box_px`). Otherwise it stays undecided, and the measured walking speed applies.

## On the board: microcontroller and technician

On the UNO Q the vision runs as a separate program next to the App Lab app of the sketch. How to copy and test it:
[`docs/DEPLOY_UNOQ.md`](docs/DEPLOY_UNOQ.md) and `deploy/push_to_arduino.sh`.

- **What comes from the microcontroller** (`smartcrossing/mcu.py`, C5 lines of the contract):
  - technician badge: gives 2 minutes to enter the technician page (`operator.login_s`);
  - shock: it is the anti-theft of the node. The vision keeps working and shows it to the technician; the warning to
    the central office is the job of the network (`comms/`), to be connected when the two parts are joined;
  - lamp fault: `DEGRADED` as long as the firmware reports it.
- **Technician page** (`--operator-port`, `smartcrossing/status_page.py`), from the phone over Wi-Fi:
  - two-step access: badge on the reader, then user and password within 2 minutes. The session stays open until the
    technician presses "Esci" (log out) (`operator.session_s: 0`; with a limit, a badge restarts it).
    Five wrong passwords close the page until the next badge;
  - **buzzer muted while the technician is there:** from the badge to the logout (or at 2 minutes without login) the C1
    command carries `"tech": true` and the sketch does not sound (only the badge confirmation beep remains). If the
    vision stops, the sketch sounds again: without heartbeat the field is no longer valid. New field of contract C1,
    to be confirmed with Lorenzo;
  - it shows state, reason, FPS, times, counts, sensors and the live view with the boxes of the vision;
  - `operator.share_images: false` turns off the images and leaves only the statistics (for production);
  - images are never saved: they exist in memory only while a connected technician is watching;
  - credentials: `python scripts/operator_login.py` saves in `ai/.env` (ignored by git) the user name and only the
    fingerprint of the password. Limit: plain HTTP, on the street HTTPS is needed.

## Rule

`rules.py` is a state machine in pure Python. Every decision reports in `reason` the numbers that produced it.

| State | When | Lamp |
|---|---|---|
| `IDLE` | no pedestrian waiting or on the crossing | `OFF` |
| `PRESENCE` | pedestrian waiting or on the crossing, no dangerous vehicle | `WHITE_ON` |
| `WARN_DRIVER` | pedestrian who wants to cross, `TTC < T_need` and vehicle beyond `d_stop + 10 m` | `AMBER_BLINK_2HZ` |
| `WARN_PEDESTRIAN` | vehicle within `d_stop + 10 m` that does not brake (`a > −2 m/s²`) | `RED_GROUND_BLINK` |
| `DEGRADED` | video missing for more than 1 s, lens covered, camera dazzled | `YELLOW_FAILSAFE` |

- `d_stop = v·1.0 + v²/(2·7.0)`, `T_need = W/v_ped + 1.0`, `TTC = d/v`, `green_s = min(25, max(W/1.2, W/v_ped) + 2)`.
- `v_ped`: 1.2 m/s; 0.8 for a child, a slow pedestrian or one with a walking aid; the measured speed if it is lower.
- Speeds are measured over a window of half a second, not between one frame and the next: the box of a still object
  shakes by a few pixels and from frame to frame it would seem to move. The speed is not measured when the box is cut by
  the edge of the image, nor where the calibration is too coarse (one pixel worth more than half a metre).
- The pedestrian "wants to cross" if they are on the crossing, or in the waiting zone for more than 1 s, or walking
  towards the road.
- The state goes up at once and goes down only after 1 s, so the lamps do not flicker.
- The requested green can only grow while someone is there: an oscillating speed estimate does not change the request
  at every frame, and a time already promised is not withdrawn.
- The C1 command leaves at every change and is repeated at least every second. The C2 heartbeat leaves every 100 ms from
  a separate thread, but only if the vision loop is alive: if the vision freezes the heartbeat stops and the firmware
  goes into fail-safe by itself.
- On the pedestrian display the AI never writes to cross: it does not know the phase of the traffic light.

What it asks the traffic light (field `req` of the command), in two cases only:

| Who is there | Request | Field |
|---|---|---|
| someone who needs more time: walks below 0.9 m/s (`slow`) or has an aid (`aid`: wheelchair, walker, stroller) | longer pedestrian green, up to 15 s; vehicle red held while they are on the crossing | `ped_green_extend_s`, `veh_red_hold` |
| an unaccompanied child at the crossing or on the road, or a free animal on the carriageway (not the small ones, not the dog on a leash) | red to the vehicles at once, held while they are there | `veh_red_now`, `veh_red_hold` |

- Any other pedestrian, or a child with an adult within 2 m (`rules.supervision_distance_m`), does not change the cycle.
- `veh_red_now` is a new field compared with the draft of contract C1: it must be confirmed by Lorenzo.
- The calibration in metres is needed (height, walking speed, distances) and, for the aids, the optional classifier,
  which does not exist today: wheelchairs and walkers are recognised only if their user walks slowly.

Attributes of the pedestrian, decided once per track: `child` (median height over 5 frames below 1.30 m), `slow`
(walking speed below 0.9 m/s, measured for at least 2 s while walking), `aid` (optional classifier
`models/aid_cls.onnx`: if missing it stays unknown).

Simulated scenes (`scripts/scenario.py`): they run tracker, geometry, rules and actuator without a camera. With
`--realtime --actuator serial --port ...` they move real lamps and displays.

| Scene | What it shows |
|---|---|
| `elderly_fast_car` | slow pedestrian waiting, car at 50 km/h: WARN_DRIVER, then WARN_PEDESTRIAN |
| `pedestrian_crossing` | a pedestrian crosses: one count, no request to the traffic light |
| `loose_dog_and_leashed_dog` | dog on a leash (no alarm), then a large free dog (ANIMAL_ALERT) |
| `car_yields` | a car slows down for the waiting pedestrian: yield rate 100% |
| `night_pedestrian_seen_by_heat` | at night the camera does not see the pedestrian, the thermal camera does: the warning fires |

## Animals

- `animal` = dog, cat, horse, sheep, cow, bear; the original COCO class stays in the events (`coco`).
- Size from the calibration: `large` (length ≥ 0.8 m or height ≥ 0.6 m), `medium` (0.3–0.8 m), `small` (log only).
- `large` free on the carriageway → `ANIMAL_ALERT` (`AMBER_BLINK_4HZ`), even without vehicles. `medium` free →
  `ANIMAL_WARN` only with a vehicle within `d_stop` + 30 m (40 m on the `collina` site).
- On a leash (person within 2 m, same direction, for at least 1 s): no alarm of its own.
- Herd (animals within 3 m): alert until the last one is on the carriageway, plus 2 s.
- `bird` counts only on the `lungofiume` site, on the ground on the carriageway, at least 0.5 m long and present for
  more than 2 s.
- No acoustic signal towards the animals.

## Night: thermal camera

Optional, with `--thermal`. The sensor of the kit is the Grove MLX90621: 16 columns by 4 rows. With 4 rows no shapes
are searched: the sensor looks along the kerb and every column is a slice of pavement.

- **Hot column:** at least one point 3 °C above the ambient temperature (median of the image).
- **Zones:** `calib_thermal.json` says which columns look at which zone (`waiting_zone_left`, `crosswalk`,
  `waiting_zone_right`). Without that file `calib_thermal.example.json` is used.
- **Night mode:** the camera image is dark (mean brightness below 50) for more than 5 s. It exits with the same wait.
- **Recovery:** at night, heat in a zone without any person seen there by the camera for at least 0.5 s becomes an
  "unclassified pedestrian", treated as vulnerable (`v_ped` 0.8 m/s).
- **Confirmation:** a person seen by the camera without heat in their zone, at night, is marked as unconfirmed. They
  stay protected anyway: to ignore them `thermal.drop_unconfirmed` must be enabled.
- The data come from the microcontroller with the C5 `thermal` lines (64 temperatures). This path is not yet tested on
  the real sensor.

## Events (contract C3)

From the trajectories, without video models. Every event is emitted only once, on the terminal and in the C3 files.

| Event | Rule |
|---|---|
| `crossing` | crossing of a counting line, with `attrs` for pedestrians and `coco` for animals |
| `near_miss` | vehicle heading towards a pedestrian or an animal with TTC < 1 s, or passage over the same point less than 1 s apart (PET) |
| `incident` `collision` | two tracks less than 1 m apart, both still, one of the two was above 3 m/s less than 1.5 s earlier |
| `incident` `person_down` | box wider than tall (ratio > 1.2) for more than 3 s on the carriageway |
| `incident` `hard_brake` | deceleration above 6 m/s² |
| `incident` `vehicle_on_crosswalk` | vehicle stopped on the crossing for more than 10 s |
| `yield` | for every vehicle arriving with a pedestrian waiting: did it slow below 2 m/s before the crossing? |
| `status` | every 5 s: state, FPS, ms per stage, counts |

On screen and at the end of the run: yield rate, near misses and incidents.

## Counting

- **Roles:** `pedestrian`, `cyclist`, `motorcyclist`, `car`, `bus`, `truck`, `animal`, `bird`. A cyclist is a person
  overlapping a bicycle (IoU > 0.3, person higher up); the bicycle with its cyclist becomes `ridden` and is not counted.
  The role of a track is the one of the majority of its frames.
- **Lines** (in `calib.json`, normalised coordinates 0–1):
  - `ped`, along the crossing at mid-carriageway: counts `pedestrian`, `cyclist`, `animal`;
  - `veh`, across the lane: counts `car`, `bus`, `truck`, `motorcyclist`, `cyclist`.
- **No duplicates:** the bottom-centre point of the box counts, 3 frames beyond the line are needed, and every track
  counts at most once per direction on each line.
- **Valid tracks:** a track counts after 5 frames (specification). In the board profiles (`unoq`, `--emulate-unoq`) 2
  are enough: five frames would be half a second, and a car would pass the line before counting.
- **A line counts only between its two ends:** whoever passes beyond the end of the segment is not counted. Better draw
  it longer than needed. The coordinates can go outside the image (less than 0, more than 1).
- **Direction:** the arrow on screen indicates IN. To swap IN and OUT the two points of the line are swapped (key `i` in
  `calibrate.py`).
- Without `calib.json`, `calib.example.json` is used: a vertical `ped` line in the middle, continuing beyond the edges
  of the image. It is for trying with the webcam moving from one side to the other.

## Measured performance

### On the Arduino UNO Q (10/10/2026)

Debian 13, Python 3.13, onnxruntime 1.30 CPU only, input 416x256 (320 px budget). Board without other programs.

Full chain on a crowded 720p test video (`scripts/bench.py`):

| Setting | detect | track | total per frame | FPS |
|---|---|---|---|---|
| 320 px, 4 threads, detector at every frame | 148 ms | 24 ms | 172 ms | 5.8 |
| 320 px, 3 threads | 143 ms | 24 ms | 166 ms | 6.0 |
| 256 px, 3 threads | 95 ms | 19 ms | 114 ms | 8.8 |
| **320 px, 3 threads, detector one frame out of two (`unoq` profile)** | 139 ms | 24 ms | 82 ms on average | **12.3** |

With the real camera of the board (IMX219 on CSI, empty scene), `unoq` profile of that time (detector one frame out
of two): **9.2 FPS end-to-end**, detect 129 ms, track 1 ms. Target of the specification: at least 8.

**Since 11 Oct the `unoq` profile runs the detector on every frame** (`DECISIONS.md`, point 47). Measured on the board
with Torino_1 as the source, `mdgb-ai` service running:

| Setting | FPS | analysed per second | detect |
|---|---|---|---|
| 320 px, detector one frame out of two (until 10 Oct) | 8.4 | 4.2 | 126 ms |
| **320 px, detector on every frame (`unoq` profile since 11 Oct)** | **5.9** | **5.9** | 130 ms |
| 416 px, detector on every frame | 3.8 | 3.8 | 205 ms |

Fewer FPS but every frame is analysed: with the tracking fixed on 11 Oct the crossings counted on 8 still-camera videos
go from 9 to 13 out of 23 pedestrians and from 24 to 47 out of 77 vehicles, always in the right direction
([docs/BENCHMARK.md](docs/BENCHMARK.md)). To be measured again with the real camera.

- **Why one frame out of two and not 256 px until 10 Oct:** on the Turin video, with the same load, 256 px counted 8
  vehicles, 320 px with the detector one frame out of two 16 (reference at 30 FPS and 512 px: 35). The tracker of
  that time lost fast objects between two detections: fixed on 11 Oct, one frame out of two is no longer needed.
- **Three threads and not four:** the fourth core is needed by the camera, the tracker and the rest; with four it is
  the same or worse.
- **The camera costs** about 20% of a core at 10 reads per second.
- **With the App Lab app keeping the camera open** (140% of CPU) the detector at every frame dropped to 3.1 FPS:
  the `mdgb` app does not open the camera, but an app that does slows the vision down.

### On PC

On PC (Apple M1, onnxruntime CPU only). `--emulate-unoq` limits FPS and threads but does not slow the cores down: these
numbers do **not** predict the speed on the UNO Q.

Detector, 4 threads, same 300 frames alternated between the two sizes:

| Input | detect (median / p95) |
|---|---|
| 320 px (default) | 11.5 / 15.3 ms |
| 416 px | 17.6 / 24.3 ms |

320 costs 65% of 416. The tracker weighs 0.5–0.7 ms.

Webcam, 416 px input (before the switch to 320):

| Mode | detect (mean / p95) | FPS end-to-end |
|---|---|---|
| `pc` profile | 12.7 / 17.4 ms | 26.6 (the webcam gives about 30) |
| `--emulate-unoq` | 16.9 / 24.0 ms | 9.8 (imposed limit: 10) |

## Resolution: image shape and region of interest

Testing on real videos the main limit turned out to be the size of the pedestrians: in a wide framing, at 320 px, a
distant person covers about ten pixels and is not seen. Two remedies, at no extra cost:

- **Image-shaped input** (`model.match_aspect`, on): the same number of pixels as 320x320, but with the proportions of
  the image (416x256 for 16:9). No pixels wasted on empty borders: on the test videos the people found are about
  double, with the same compute time.
- **Region of interest** (`"roi": [x0, y0, x1, y1]` in `calib.json`, or `calibrate.py --roi`): the detector looks only
  at the part of the image that matters, i.e. the crossing and the road before it. Objects become larger at the same
  cost. On the New York video, pedestrians found on the crossing per frame: 3.4 on the whole image, 5.1 on the band of
  the crossing, 8.8 raising the budget to 416.

The practical rule for whoever mounts the camera: the crossing and the waiting zones must fill the framing.

## Model

`scripts/get_model.sh` downloads the official file `yolox_nano.onnx`, which declares a fixed 416 px input, and creates
`yolox_nano_dynamic.onnx` with `scripts/make_dynamic_model.py`. The copy has the same weights and a free input size: at
416 px it gives an output identical to the original, and it also accepts 320 px (`model.input_size` in `config.yaml`,
multiple of 32). On the UNO Q the `models/` folder already prepared on the PC is copied.

## Dependencies

At runtime (`requirements.txt`, pinned versions): numpy 2.4.6, onnxruntime 1.30.0, opencv-python 4.14.0.94 (headless
variant on Linux aarch64, chosen automatically), supervision 0.30.5, pyyaml 6.0.3.
No torch or ultralytics. Every package has the wheel for Linux aarch64.

- supervision also installs scipy, matplotlib, pillow, av, requests and tqdm: the environment weighs about 490 MB.
- supervision must stay below 0.31: there `sv.ByteTrack` is removed.
- pyserial comes when needed (serial actuator).

For development (`requirements-dev.txt`): pytest 9.1.1 and onnx 1.23.0 (only needed to prepare the model, it does not
go on the board).

## Python version

- Development: Python 3.12 on macOS Apple Silicon.
- The pinned versions work with Python 3.11, 3.12 and 3.13.
- UNO Q: Debian's `python3` inside a venv (the system pip is blocked). The version must be read on the board: it is
  open question 9 in DECISIONS.md.

## Folder rules

- All the thresholds are in `config.yaml`, no numbers in the code.
- Code comments in English.
- Firmware, controller and dashboard are not in this folder: here the contracts and a local `SimActuator` are used.
