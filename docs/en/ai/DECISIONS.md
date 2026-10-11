# ai/ — decisions, numbers and interfaces

> English translation of [`ai/DECISIONS.md`](../../../ai/DECISIONS.md), from `main` at `1f9a131` (11 October 2026), updated with the counting benchmark of 11 October (PR #22). The Italian original is the reference: if the two differ, the original wins.

Owner: Paolo Malugani (data scientist). Extracted from `PROMPT_SMART_CROSSING.md` (the § refer to that file).
If this file and the specification differ, the specification wins; if the specification and `docs/CONTRACTS.md`
differ, `CONTRACTS.md` wins.

## 1. Decisions taken

| Topic | Decision | Source |
|---|---|---|
| Detector | YOLOX-nano COCO in ONNX (Apache-2.0), run with onnxruntime. Input 320, 416 optional | §2 |
| Tracking | `supervision.ByteTrack` | §2 |
| Counting per direction | `supervision.LineZone` with `minimum_crossing_threshold` + minimum track age. Every ID counts at most once per direction | §2, §5.1.6 |
| Pedestrian type | Cascade: generic COCO detector, then attributes computed once per track | §2 |
| Child | Height in metres from the homography. No model | §2 |
| Elderly / slow | Measured walking speed. Age is not estimated | §2 |
| Aids (wheelchair, walker, stroller) | Optional ONNX classifier on 96x96 crops, trained separately. If the file is missing `aid = None` and the system works anyway | §2, §5.1.7 |
| Cyclist / motorcyclist | Derived: person overlapping bicycle/motorcycle. Final class of the track by majority | §5.1.4 |
| Incidents | Rules on trajectories, no video model | §2 |
| Safety | Physical rule (TTC, stopping distance) in `rules.py` + fail-safe in the firmware via heartbeat. Safety does not depend on Linux | §2 |
| Rules | `rules.py` is an explicit state machine in pure Python, without OpenCV, testable. It produces a dict compliant with C1 with a readable `reason` | §5.1.11 |
| Privacy | Never save frames to disk: metadata only | §2, §5.1.12 |
| Runtime dependencies | numpy, opencv-python(-headless), onnxruntime, supervision, pyyaml, pyserial. No torch/ultralytics (weight, AGPL licence) | §2 |
| Portability | The same Python code runs on PC (macOS Apple Silicon, Linux) and on the UNO Q (Debian aarch64) | §1 |
| Night | Optional thermal camera (`--thermal`). Available hardware: Grove MLX90621 16x4 → heat strip along the kerb, presence per column. No 2D blobs, no classification | §6 |
| Animals | `animal` = dog, cat, horse, sheep, cow, bear; the original COCO class stays in the logs. No acoustic signal towards the animals | §7 |
| Animal fine-tuning | Decided with `scripts/animal_probe.py`: "at least one animal" recall > 70% on wild boar and roe deer → no training | §7 |
| Tests | pytest, must pass on PC without hardware | §8 |
| External APIs | No invented APIs: official documentation linked in the comment, otherwise stub + `TODO(verify)` | §0 |
| Language | Code comments in English | line 16 |

Work order (§9): AI-M1 source + detector + tracker + overlay + `bench.py` → AI-M2 counting + derive →
AI-M3 calibration + speed + attributes + rules + SimActuator (full demo on PC with `--emulate-unoq`) →
AI-M4 events + animals + logger + C3 output → AI-M5 thermal → AI-M6 `unoq` profile, test on the board, benchmark in the
README.

Work constraints (from Paolo's session brief, not from the specification):
- every dependency must have the aarch64 wheel;
- all thresholds in `config.yaml`, no numbers in the code;
- `requirements.txt` in `ai/` with pinned versions;
- test videos in `ai/samples/` (ignored by git), otherwise webcam;
- every test is repeated with `--emulate-unoq`, reporting FPS and ms per stage.

## 2. Parameters and numbers

They all end up in `config.yaml`. "n.s." = value not specified, see §6 of this file.

### Performance
| Parameter | Value | Source |
|---|---|---|
| Target on the UNO Q | ≥ 8 FPS end-to-end at 320 px | §1 |
| `--emulate-unoq` | 10 FPS, input 320, onnxruntime with 4 threads | §5.1.13 |
| Known references on the UNO Q | YOLOv8n 640 px with OpenCV DNN 1–2 FPS; App Lab's yolox-nano about 10 FPS; Edge Impulse YOLOv5-pico 224 px about 17 FPS | §1 |
| UNO Q | 4x Cortex-A53 at 2.0 GHz, no NPU, 2/4 GB of RAM | §1 |

### Detector and tracking
| Parameter | Value | Source |
|---|---|---|
| `input_size` | 320 (416 optional) | §5.1.2 |
| Preprocess | letterbox with padding 114, BGR, no normalisation | §5.1.2 |
| Classes kept | person, bicycle, car, motorcycle, bus, truck, dog, cat, horse, sheep, cow, bear, bird | §5.1.2 |
| `conf`, `nms`, `intra_op_num_threads`, `detect_every_n` | n.s. | §5.1.2 |
| `min_track_age` | 5 frames | §5.1.3 |
| ByteTrack parameters | n.s. | §5.1.3 |
| Cyclist | person/bicycle IoU > 0.3 and person box above the bicycle box | §5.1.4 |

### Geometry and counting
| Parameter | Value | Source |
|---|---|---|
| Calibration | 4 points on the ground (corners of the crossing) + measures in metres → homography in `calib.json` | §5.1.5 |
| Content of `calib.json` | homography, polygons `waiting_zone_left/right`, `crosswalk`, `carriageway`, counting lines, width `W` | §5.1.5 |
| Reference point | bottom-centre of the box | §5.1.5 |
| Speed | EMA over 5 samples | §5.1.5 |
| Lines | `ped_line` along the crossing, `veh_line` across the lane | §5.1.6 |
| `minimum_crossing_threshold` | n.s. | §5.1.6 |

### Pedestrian attributes
| Attribute | Rule | Source |
|---|---|---|
| `child` | median height over 5 frames < 1.30 m | §5.1.7 |
| `slow` | mean speed in the waiting zone or on the crossing < 0.9 m/s for at least 2 s | §5.1.7 |
| `aid` | classes normal / wheelchair / walking_aid / stroller, 96x96 crops, vote over 3–5 crops | §5.1.7 |

### Rules (`rules.py`)
| Quantity | Formula or value | Source |
|---|---|---|
| Stopping distance | `d_stop = v*1.0 + v^2/(2*7.0)` (reaction 1.0 s, deceleration 7.0 m/s²) | §5.1.11 |
| Time needed by the pedestrian | `T_need = W/v_ped + 1.0` | §5.1.11 |
| Time to collision | `TTC = d/v` | §5.1.11 |
| `v_ped` | 1.2 m/s by default; 0.8 if child, slow, aid or pedestrian seen only in thermal; if lower, the measured speed | §5.1.11 |
| State priority | DEGRADED > WARN_PEDESTRIAN > ANIMAL_ALERT > WARN_DRIVER > ANIMAL_WARN > PRESENCE > IDLE | §5.1.11 |
| Pedestrian intention | in the waiting zone for more than 1 s, or moving towards the carriageway | §5.1.11 |
| WARN_DRIVER | intention + `TTC < T_need` + `d > d_stop + 10` | §5.1.11 |
| WARN_PEDESTRIAN | `d ≤ d_stop + 10` and vehicle not decelerating (`a > −2 m/s²`) | §5.1.11 |
| Pedestrian green | `green_s = min(25, max(W/1.2, W/v_ped) + 2)` | §5.1.11 |
| DEGRADED | video missing for more than 1 s, or failed self-check (Laplacian variance below threshold, saturated histogram) | §5.1.11 |
| Self-check thresholds | n.s. | §5.1.11 |

Check values of the tests (§8): elderly 0.8 m/s, W = 7 m, car at 13.9 m/s at 60 m → T_need 9.75 s, TTC 4.3 s,
d_stop 27.7 m → WARN_DRIVER; same car at 25 m without deceleration → WARN_PEDESTRIAN; W = 12 m with v_ped 0.7 → 19.1 s;
with v_ped 0.3 → 25 s.

### Events (`events.py`)
| Event | Rule | Source |
|---|---|---|
| Collision | ground distance < 1 m between two tracks, at least one previously at > 3 m/s, then both < 0.3 m/s within 1.5 s | §5.1.10 |
| Person down | width/height > 1.2 for more than 3 s on the carriageway | §5.1.10 |
| Hard braking | deceleration > 6 m/s² | §5.1.10 |
| Near miss | TTC < 1 s or PET < 1 s between vehicle and pedestrian/animal | §5.1.10 |
| Vehicle stopped on the crossing | more than 10 s | §5.1.10 |
| Yield rate | share of vehicles that, with a pedestrian in the waiting zone, slow below 2 m/s before the crossing | §5.1.10 |

### Animals
| Parameter | Value | Source |
|---|---|---|
| `bird` | counts only on the ground on the carriageway, length ≥ 0.5 m, present for more than 2 s | §7 |
| Dog on a leash | person within 2.0 m on the ground, similar direction (< 45°) for at least 1 s → same `group_id`, no alarm of its own | §7 |
| Size | `large` length ≥ 0.8 m or height ≥ 0.6 m; `medium` 0.3–0.8 m; `small` < 0.3 m (log only) | §7 |
| Herd | animals within 3 m → same `herd_id`; alert active until the last one leaves, +2 s | §7 |
| `large` free on the carriageway | ANIMAL_ALERT (`AMBER_BLINK_4HZ`), even without vehicles | §7 |
| `medium` free | ANIMAL_WARN only with a vehicle at `d < d_stop + margin`; margin 30 m, 40 m in the `collina` profile | §7 |
| `--site` profiles | `urbano` pedestrians and dogs, bird excluded; `lungofiume` + large birds on the ground; `collina` + ungulates and herds, more sensitive night thresholds | §7 |

### Thermal camera
| Parameter | Value | Source |
|---|---|---|
| Available sensor | Grove MLX90621, 16x4, FOV 60°x16° | §6 |
| Ground resolution | at 4 m each column covers about 29 cm; a person covers about 2 columns | §6 |
| Presence per column | T > ambient + 3 °C; the waiting zone is a set of columns | §6 |
| Reading | I2C from the MCU, forwarded over the Bridge as an array of 64 temperatures | §6 |
| Night mode | mean luminance of the RGB frame below threshold for more than 5 s, or photoresistor via the MCU. Threshold n.s. | §6 |
| Recovery | heat in the waiting zone or on the crossing without RGB detection for at least 0.5 s → "unclassified pedestrian" with v_ped 0.8 | §6 |
| Confirmation | RGB person with overlapping heat → confidence up; person without heat in night mode → confidence down | §6 |
| Zones | drawn on the thermal image in `calib_thermal.json`, without a full homography | §6 |

### Contracts (draft §4)
| Parameter | Value | Source |
|---|---|---|
| C1 | one JSON line per message: `v`, `seq`, `t_ms`, `state`, `led`, `green_s`, `req`, `lcd`, `oled`, `reason` | §4 |
| `req` | `ped_green_extend_s`, `veh_red_hold`, `flash`; plus `veh_red_now`, added on 11/10 (point 31), to be confirmed with Lorenzo | §4 |
| `lcd` | at most 2x16 characters | §4 |
| Serial | 115200 baud | §4 |
| C2 heartbeat | every 100 ms; the firmware goes into fail-safe after more than 500 ms without | §4 |
| Controller limits on the `req` | pedestrian green extension ≤ 15 s, vehicle red held ≤ 20 s, minimum vehicle green 8 s (constants in the firmware) | §5.2 |
| C3 | events `crossing`, `near_miss`, `incident`, `status` in JSONL on file + local HTTP endpoint | §4 |

## 3. Existing code

- There is no code in `ai/` yet: the folder is born with this file.
- Reused components, not written by us: YOLOX-nano COCO weights in ONNX from the official Megvii-BaseDetection/YOLOX
  releases (URL to verify, §5.1.2); `supervision` for ByteTrack and LineZone (§2).
- The specification mentions already-tested code only for the store & forward of `comms/` (806/806 events, §5.3): it
  does not belong to `ai/`.

## 4. What I need from the others

| From | What | For which milestone | Source |
|---|---|---|---|
| Lorenzo (comms) | Confirmation of the contracts of §4 and `docs/CONTRACTS.md` v1 | AI-M3 (C1/C2), AI-M4 (C3) | §4, CM-M1 |
| Lorenzo (comms) | `comms/actuators.py` with the `Actuator` interface (sim, serial; bridge in CM-M4). Until then I use a local `SimActuator` | AI-M3 onwards | §3, §4 |
| Salvatore (firmware) | C1/C2 parser and fail-safe (FW-M1) to test `rules.py` on real LEDs and displays | after AI-M3 | §5.2 |
| Salvatore (firmware) | Forwarding over the Bridge of the array of 64 temperatures of the MLX90621; light reading; `tamper` event | AI-M5 | §5.2, §6 |
| Salvatore (firmware) | Joint work on `ai/docs/DEPLOY_UNOQ.md` and test on the board | AI-M6 | §10 |
| Kuzey (hardware) | Camera working on the UNO Q and powered USB-C hub if the webcam is used | AI-M6 | §1, §5.4 |
| Kuzey (hardware) | MLX90621 thermal camera mounted, with position and orientation relative to the kerb | AI-M5 | §5.4, §6 |

## 5. What I provide to the others

| To whom | What | Source |
|---|---|---|
| Salvatore (firmware) | C1 commands generated by `rules.py` (`state`, `led`, `green_s`, `req`, `lcd`, `oled`, `reason`) and C2 heartbeat every 100 ms, sent through `Actuator` | §4, §5.1.11 |
| Lorenzo (comms/app) | C3 events (`crossing`, `near_miss`, `incident`, `status` with FPS, ms per stage and counts) in JSONL; `--headless` mode for the dashboard | §4, §5.1.12–13 |
| Everybody | Entry point `python -m smartcrossing.app` with `--source`, `--profile`, `--site`, `--headless`, `--emulate-unoq`, `--actuator`, `--thermal` | §5.1.13 |
| Everybody | Scripts: `calibrate.py` (homography and zones), `bench.py` (mean and p95 ms per stage), `animal_probe.py`, `get_model.sh` | §5.1 |
| Salvatore (firmware) | `ai/docs/DEPLOY_UNOQ.md`, written together | §10 |
| Pitch | Numbers on screen: FPS, ms per stage, yield rate, near misses; benchmark on the board in the README | §9, §11 |
| Lorenzo (stretch) | Pipeline for forecasting the flows with simulated data in `ai/forecast/` | §5.3 |

## 6. Open questions

1. **Camera on the UNO Q.** The specification expects a USB webcam, file or RTSP (§5.1.1). `hardware/BOM.md` indicates
   as main camera the Sony IMX219 on the Media Carrier (CSI), with the USB webcam as plan B. It must be understood how
   to read the IMX219 from Python on the board. For Kuzey and Salvatore. It does not block AI-M1…M5 on PC.
   **Closed on 10/10 (point 32):** the board mounts the IMX219; it opens with `libcamerify`.
2. **Value of `--thermal`.** The option expects `none|uvc|mlx90640` (§5.1.13) and AI-M5 talks about a "simulated
   MLX90640", but the available sensor is the MLX90621 16x4 (§6). The value `mlx90621` and a 16x4 simulator are needed.
   The test of §8 also talks about a "hot blob", which with 4 rows becomes "hot columns".
3. **Data from the MCU to Linux.** In §4 there is no contract for: thermal array, light, `tamper`, `lamp_fault`
   (§5.2 says "extend C3"). They are needed by `thermal.py` and by the DEGRADED state. For Lorenzo and Salvatore.
4. **How `req` is computed.** The specification gives `green_s` but does not say how to derive `ped_green_extend_s`
   (the base duration of the controller's pedestrian green is missing) nor when `veh_red_hold` and `flash` apply. For
   Salvatore and Lorenzo. **Decided by Paolo on 10/10 (point 31).**
5. **Texts of `lcd` and `oled`.** There are only two examples (§1, §4). The text for each state is missing, and which
   speed appears in "PEDONE 47 km/h".
6. **Transport of C3.** "JSONL on file + local HTTP endpoint" (§4): it is not written who exposes the endpoint. Flask
   is foreseen only for the dashboard (§2). For Lorenzo.
7. **Pedestrian seen only in thermal.** It is not defined how it appears in C3 (value of `cls`). For Lorenzo.
8. **Unspecified values**, to be chosen and put in `config.yaml`: `conf`, `nms`, onnxruntime threads on PC,
   `detect_every_n`, ByteTrack parameters, `minimum_crossing_threshold`, self-check thresholds, luminance threshold of
   night mode.
9. **Python version on the UNO Q.** The specification does not state it; it decides which versions to pin in
   `requirements.txt`. To be read on the board. For Salvatore.
10. **Measures of the crossing.** The calibration asks for 4 points with measures in metres and the width `W` (§5.1.5):
    it is not written who provides them for the model.
11. **C1 example in §4.** `green_s: 19` does not match the scenario of its `reason` (W = 7 m and v_ped 0.8 give
    10.75 s). It is only illustrative: the values of the tests in §8 are the reference.
12. **`docs/CONTRACTS.md` does not exist yet.** Until Lorenzo publishes it, `ai/` works against the draft of §4.
13. **Input at 320 px: solved.** The official model declares a fixed 416 px input, but the network has no fixed sizes
    inside. `scripts/make_dynamic_model.py` creates a free-input copy (same weights, identical output at 416 px). The
    default is now 320 px, as in the specification; 416 stays available from `config.yaml`.
14. **`sv.ByteTrack` is deprecated** in supervision and disappears from 0.31. With the pinned version (0.30.5) it works:
    the pin must not be raised without changing tracker.
15. **Values chosen in AI-M1** for the unspecified parameters (point 8), all in `config.yaml` and to be tuned on a real
    video: `conf` 0.30, `nms` 0.45, `detect_every_n` 1, ByteTrack parameters at the supervision defaults with
    activation threshold 0.30. Plus `nms_cross_class` 0.85: two almost coinciding boxes of different classes are the
    same object, the best score stays (overlapping person and bicycle both stay).
16. **Choices of AI-M2**, all in `config.yaml`:
    - `minimum_crossing_threshold` 3 frames;
    - role names aligned with Lorenzo's draft of `docs/CONTRACTS.md` (`pedestrian`, `cyclist`, `motorcyclist`, `car`,
      `bus`, `truck`, `animal`, `bird`);
    - `ped` line: `pedestrian`, `cyclist`, `animal`; `veh` line: `car`, `bus`, `truck`, `motorcyclist`, `cyclist`;
    - a bicycle or motorcycle without a recognised person on it is not counted;
    - the lines are in `calib.json` in normalised coordinates (0–1), so they do not depend on the resolution.
17. **Choices of AI-M3 to confirm with Salvatore and Lorenzo** (they answer points 4 and 5). They are in `config.yaml`
    (`rules`) and in `rules.py`:
    - lamp per state: IDLE `OFF`, PRESENCE `WHITE_ON`, WARN_DRIVER `AMBER_BLINK_2HZ`, WARN_PEDESTRIAN
      `RED_GROUND_BLINK`, ANIMAL_WARN `AMBER_BLINK_2HZ`, ANIMAL_ALERT `AMBER_BLINK_4HZ`, DEGRADED `YELLOW_FAILSAFE`;
    - `ped_green_extend_s` = `green_s` minus the standard green `W/1.2 + 2`, rounded, at most 15 s
      (with W = 12 m and 0.7 m/s it gives 19 s and +7 s, as in the example of §4);
    - `veh_red_hold` true in WARN_DRIVER, in WARN_PEDESTRIAN and as long as someone is on the crossing
      (**superseded by point 31**: now only for those who need time, unaccompanied child or animal);
    - `flash` true only in ANIMAL_ALERT;
    - `lcd` on two lines of 16 ASCII characters: `PEDONE / IN ATTESA` (pedestrian / waiting), `PEDONE / SULLE STRISCE`
      (pedestrian / on the crossing), `PEDONE  47 km/h / RALLENTA` (slow down), `FRENA!  47 km/h / PEDONE` (brake!);
      the speed is the one of the approaching vehicle;
    - `oled`: `TEMPO VERDE 11 s` (green time) in PRESENCE, `ATTENDI auto 45km/h` (wait, car) in WARN_DRIVER,
      `FERMO! auto 45km/h` (stop!) in WARN_PEDESTRIAN. Never an invitation to cross.
18. **Other choices of AI-M3**:
    - in WARN_PEDESTRIAN a nearby vehicle that brakes (a ≤ −2 m/s²) is considered one that gives way: the state stays
      PRESENCE;
    - the state goes down only after 1 s (`rules.hold_s`);
    - the walking speed is the median of the speeds while the pedestrian walks, not the mean: so starts and stops do not
      lower it. Whoever stands still at the kerb does not come out as slow;
    - height and length in metres come from the local scale of the homography at the ground point: it is an
      approximation, to be tuned with `geometry.height_scale` on a person of known height;
    - a vehicle counts for the rule only if it is on the carriageway and approaching the crossing at more than 1 m/s;
    - waiting zones 1.5 m deep and as wide as the crossing plus 1 m per side;
    - self-check thresholds: Laplacian variance below 15 = lens covered, more than 50% of saturated pixels = glare. To be
      tuned on the real camera;
    - contract of the aid classifier (not yet trained): input 1x3x96x96, BGR, 0–255.
19. **Closed by Lorenzo's draft of `docs/CONTRACTS.md`** (branch `lorenzo/ble-backup`): point 3 (data from the
    microcontroller: contract C5), point 6 (C3 only on file in `logs/c3/`), point 7 (thermal-only pedestrian:
    `attrs.thermal_only`).
20. **Choices of AI-M4**, all in `config.yaml`:
    - which COCO classes count per site: `urbano` dog and cat; `lungofiume` as urban plus the large birds; `collina`
      also horse, sheep, cow, bear (wild boars and roe deer are seen as one of these);
    - a herd is made of at least 2 free animals within 3 m: it counts as an alert even if they are medium-sized;
    - near miss by TTC only if the pedestrian is within 1.5 m sideways of the trajectory of the vehicle; by PET the two
      must pass within 1 m of the same point;
    - hard braking applies only to vehicles that were going at least 3 m/s;
    - a collision requires at least one vehicle among the two tracks;
    - `yield`: counts the vehicle arriving while a pedestrian is in the waiting zone; it gave way if it went below 2 m/s
      before the crossing, even if it then restarted;
    - the C3 files go in `logs/c3/` (or `$MDGB_C3_DIR`), a new file every hour, as in Lorenzo's draft.
21. **To propose to Lorenzo**: a C3 `animal` event (track_id, coco, size, free) for the sightings, including the small
    animals that the specification wants "only in the log". For now they are only printed on the terminal, because the
    draft of the contract does not foresee that type.
22. **Choices of AI-M5**, all in `config.yaml` (`thermal`):
    - `--thermal` accepts `mlx90621` (the kit sensor) and `sim`; `mlx90640` and `uvc` stay in the list but answer that
      the sensor is not there (closes point 2);
    - with 16x4 the zones are sets of columns, not polygons: they are in `calib_thermal.json`;
    - the ambient temperature is the median of the 64 readings;
    - the pedestrian recovery applies only in night mode: by day a hot bonnet would give false alarms;
    - the person seen by the camera but without heat is only flagged, not ignored: when in doubt, protect;
    - darkness threshold: mean brightness below 50 out of 255. To be tuned on the real camera;
    - **to verify:** in the dark the "lens covered" self-check (image without detail) might fire and send everything to
      DEGRADED. A real night video is needed to tune the two thresholds together;
    - **to verify with Salvatore and Lorenzo:** format of the C5 `thermal` line and `Actuator.set_listener` (draft of
      `docs/CONTRACTS.md`), never tested on the firmware.
23. **Stability of the commands** (found while testing AI-M5): the requested green only grows while someone is there,
    and a change of the `reason` alone does not trigger a new C1 before the once-per-second repetition.
24. **Towards AI-M6**: `docs/DEPLOY_UNOQ.md` is a draft not tested on the board. From unofficial sources the UNO Q runs
    Debian 13 (hence Python 3.13, compatible with the pinned versions: point 9) and for the CSI camera an App Lab option
    must be enabled (point 1). Both things must be verified on the board.
25. **Changes born from the test on real videos** (branch `paolo/ai-video-tests`):
    - image-shaped input (`model.match_aspect`) and region of interest (`roi` in `calib.json`): more pixels on the
      objects at the same cost;
    - speed over a 0.5 s window (`kinematics.window_s`), with the EMA of the specification applied on top; acceleration
      only after a full window of speeds;
    - no speed for boxes cut by the edge, for impossible jumps (ID change) and where one pixel is worth more than 0.5 m
      on the ground;
    - walking speed = net progress over the last 2 s, measured only if the pedestrian moved for all that time: whoever
      waits still does not come out as slow;
    - events: `yield` only once per vehicle, when it reaches the crossing; near miss by TTC only above 3 m/s; braking
      and collisions only within 30 m of the crossing and only for tracks with a known speed;
    - self-check: Laplacian threshold from 15 to 4 (real scenes measured: from 8 upwards; covered lens: below 2) and
      fault confirmed only if it repeats at the next check.
26. **Limits that emerged from the videos**, not solved:
    - in dense crowds (Shibuya, New York) the detector sees part of the pedestrians and the tracks last less than a
      second: the counts in those scenes are not reliable;
    - `child` depends on the estimated height, which with a camera very high up came out too low: corrected in point 27;
    - with a calibration estimated by eye the speeds are good near the crossing and unreliable far away;
    - still objects mistaken for vehicles (a road panel seen as `bus`) stay as tracks.
27. **Changes born from the Turin videos** (branch `paolo/ai-video-tests`):
    - vehicle line in the middle of the crossing (`geometry.veh_line_offset_m: middle`). With the line 2 m before the
      crossing, the vehicles of one direction entered from the edge of the image already beyond the line and were not
      counted;
    - the calibration accepts four points that are not the corners of the crossing (`ground` in `build_metric_calib`),
      for when a kerb is covered or outside the image. In Turin the points are the ends of two stripes 10 m apart,
      counted one by one: stripes and gaps are 50 cm (regulation of the Highway Code, D.P.R. 495/1992, art. 145);
    - **height of people.** Before, the height of a box was converted into metres with the same scale as the width: from
      a camera high up a person looks shortened and an adult came out 1.3–1.5 m tall. Now from the calibration the
      focal length and position of the camera are reconstructed (Zhang 2000, the two constraints on the first two
      columns of the homography) and the height is the exact one along the vertical above the feet. Assumptions: square
      pixels and optical axis at the centre of the image. On four simulated cameras, for a person of 1.70 m: 1.70 m
      without click errors; with 3 px of error on the four corners 90% of the estimates are between 1.51 and 1.88 m
      (before between 1.23 and 1.86 m, with a median of 1.41 m from the highest camera);
    - **calibration check** (`geometry.camera_tolerance: 0.2`). If the four points and the two measures do not fit a
      real camera, the position is not reconstructed and `calibrate.py` says so. With 0.2 at least 86% of the correct
      calibrations clicked with 4 px of error pass (simulation, 4 camera positions); swapped corners or wrong measures
      do not pass. It holds for normal lenses, not for images cropped on one side;
    - `child` is decided only if the calibration passes the check and the box is at least 30 px tall
      (`attributes.height_min_box_px`) and does not touch the top edge. Otherwise it stays undecided: not a child, and
      the measured walking speed applies. Animal sizes still use the approximate height;
    - `scripts/evaluate.py`: `--stabilize` compensates the shake of a hand-held video (only for tests: the product
      assumes a fixed camera), `--save-video` writes the annotated video, and the report shows the estimated heights and
      the reconstructed camera.
    - **at 10 FPS a track is valid after 2 frames, not 5** (`tracking.min_track_age` in the `unoq` and `--emulate-unoq`
      profiles; on PC it stays 5 as in the specification). Five frames at 10 FPS are half a second: a car at 30 km/h
      passes the line before its track counts. Vehicles counted on Torino_1 (one direction + the other):

      | | 512 px | 320 px |
      |---|---|---|
      | 30 FPS, valid after 5 | 22 + 13 | 21 + 9 |
      | 10 FPS, valid after 5 | 11 + 5 | 11 + 0 |
      | 10 FPS, valid after 2 | 20 + 8 | 18 + 2 |

      It is an exception to the default of the specification (§5.1.3), limited to the 10 FPS profiles: to be confirmed.
28. **Limits that emerged from the Turin videos**, not solved:
    - pedestrians are seen in part: about 4 per frame when there are between 6 and 10 (512 budget), 2.4 with the 320
      budget planned for the board. The files are 478x850 and heavily compressed, a pedestrian is 30–50 px tall;
    - with the board limits (10 FPS, 320 px) the far direction of the vehicles is almost not counted (2 instead of 13);
    - cyclists, scooters and riders are not recognised: the bicycle, small, is not detected;
    - `child`: on Torino_1 4 false ones out of 24 pedestrians remain. The pedestrian boxes are shorter than the
      calibration expects for an adult (47 px against 56–71): either the model cuts the small figures, or the
      calibration by eye has a 15% error. A person of known height in a video is needed;
    - the calibration of Torino_2 does not pass the check and I could not correct it by eye: the speeds and heights of
      that video are not valid;
    - an intersection with turning vehicles (Torino_3) cannot be counted with a single straight line;
    - distant pedestrians read as `bird`, a dark car read as `motorcycle`.
29. **Integration on the UNO Q** (branch `paolo/ai-unoq`, decided with Paolo and the team on the evening of 10/10):
    - **order:** first sketch (Salvatore) + vision, tested on the board; the network towards the central office and the
      backup (Lorenzo) later;
    - **the vision runs on Linux outside App Lab**. Rejected alternative "inside the `main.py` of the app": onnxruntime
      and supervision would have to be installed in the App Lab container, never tried, with the risk of conflicts with
      its libraries;
    - **only the vision opens the camera**: the `main.py` of the App Lab app today opens it to show it on a web page,
      and it must be removed from there (proposal delivered to Salvatore);
    - **to talk to the sketch Lorenzo's `comms/actuators.py` is used as it is** (`BridgeActuator`): it is the
      vision–sketch link, not the network. Until it is on main, `push_to_arduino.sh --bridge` takes it from his branch.
      Dependency on the board: `arduino-router-bridge==0.5.1`, as in `comms/requirements.txt`;
    - **the shock is the anti-theft of the node and does not change the state of the vision.** (The first version put
      the vision in `DEGRADED`, as §5.2 of the specification says: Paolo clarified that this is not the purpose.) The
      vision shows it to the technician and that is all;
    - **technician page:** badge, then login with user and password, over Wi-Fi. It shows numbers and live view.
      `operator.share_images: false` leaves only the statistics: it is the switch for production. Images are never
      saved (specification: "never save frames to disk") and are produced only while a connected technician is
      watching. A video would not pass over Bluetooth: BLE does not have the bandwidth;
    - **credentials:** user name and PBKDF2 fingerprint of the password in `ai/.env`, never in the repo. Known limit:
      plain HTTP;
    - **sketch proposal for Salvatore** (outside the repo): `mdgb_line` for C1/C2, simulated controller on the three
      LEDs, fail-safe at 500 ms, RFID lock and beep without `delay()`, badge and anti-theft also towards the vision
      (`mcu_event`). Logic tested on PC with a fake Arduino, not compiled for the board. Open: the vision state used as
      a pedestrian call (vehicle green from 20 to 8 s) is not written in the contract.
30. **To do when Lorenzo's network is merged:**
    - **anti-theft towards the central office:** the alarm of the accelerometer must reach his application. The
      `mcu_event` lines of the sketch already go through `comms/actuators.py`, which writes them in `mcu-*.jsonl` for
      the node; to be verified on the board, and the alarm must not arrive twice (`mdgb_link.py` also forwards it);
    - single events folder (`--applab`, `MDGB_C3_DIR`) and write permissions in `~/ArduinoApps/<app>/data`;
    - "tampered" node state in the central office: how it looks and who resets it (the technician badge?).
31. **What is asked of the traffic light, decided by Paolo on the evening of 10/10** (changes what is written in point 17):
    - **red at once** for an unaccompanied child or a free animal on the road, with a short yellow before;
    - **longer pedestrian green only for those who need it**: `slow` (walks below 0.9 m/s) or `aid`. No longer for
      every pedestrian slower than 1.2 m/s, nor for children as such;
    - **the red is no longer held** for anyone on the crossing nor in the warning states: only for those who need time
      and for an unaccompanied child or animal;
    - "unaccompanied" = nobody who is not a child within 2 m on the ground (`rules.supervision_distance_m`, the same
      criterion as the dog on a leash). A pedestrian whose height is unknown counts as an adult;
    - animals: free, on the carriageway, medium or large size (`rules.red_now_animal_sizes`);
    - **new field `req.veh_red_now` in the C1 command**: it is a change to the contract, to be confirmed by Lorenzo.
      It is only an addition: whoever does not know it ignores it;
    - `T_need` and the warnings to drivers and pedestrians do not change: for those the child stays at 0.8 m/s.
32. **First test on the board (evening of 10/10)**, numbers in `README.md`:
    - at 320 px with the detector at every frame the board does 5.8 FPS, below the target of 8. `unoq` profile:
      detector one frame out of two, 3 threads, cap at 12 FPS. With the real camera: 9.2 FPS;
    - the camera is an IMX219 on CSI: it opens with `libcamerify` (closes open question 1);
    - the board lacks `python3-venv`: the environment is created without pip and installed with the system pip;
    - the FPS shown were a mean of times between consecutive frames: with the detector one frame out of two it gave
      absurd numbers (220). Now it is the rate over the last 30 frames.
33. **`mdgb` app on the board and first test of the driven traffic light (10/10, 23:30)**. At Paolo's request the
    proposed sketch does not replace Salvatore's: it is in a new app, `~/ArduinoApps/mdgb`, a copy of his `test` (the
    version on the board, with buzzer on A5 and light on A0) plus `mdgb_line`. `test` is intact. Measures from the app
    logs:
    - the sketch compiles for the board (129 kB, 16%) and starts;
    - normal cycle: green 20.0 s, yellow 3.0 s, red 10.0 s; badge, alarm and sensors as before;
    - emergency red requested through the Bridge with `comms/actuators.py` when the green had been on for 5 s: the
      sketch waited for the minimum green (yellow at 8.0 s), short yellow of 1.5 s, red held 24.5 s while the request
      lasted, then green;
    - heartbeats stopped: fail-safe and normal cycle after about half a second (the logs have one-second precision on
      the vision side, they do not allow saying more);
    - real vision with the camera connected to the sketch: "visione collegata" (vision connected), no line rejected;
      stopping it, fail-safe. In that test 7.4 FPS: an `apt` was also running on the board.
    Not yet tested on the hardware: a request coming from a real scene (calibration needed), badge → technician page →
    login from the phone, anti-theft shown on the page.
34. **Vehicle red at 20 s** (was 10): asked by Paolo so that all pedestrians have time to cross. It is a constant of the
    sketch of the `mdgb` app (`VEH_RED_MS`); the limits become 20 + 15 s of extension and 20 + 20 s of held red.
    Measured on the board: 20.0 s. `deploy/run_vision.sh` turns the vision on and off on the board without `sudo`.
35. **Status at the end of the evening of 11/10 (for whoever resumes the work):**
    - the `mdgb` app runs on the board (buzzer off for now: `BUZZER_ENABLED 0` in the sketch) and the vision, started
      with `deploy/run_vision.sh`. The source of the sketch is not in the repo: it is in `~/ArduinoApps/mdgb` on the
      board and in `mdgb-app-proposta.zip` delivered to Salvatore, who will decide whether and how to put it in
      `firmware/`;
    - the calibration on the real crossing is missing: without it, the vision counts but asks nothing of the traffic
      light;
    - not yet tested: badge → technician page → login from the phone; a request coming from a real scene;
    - PRs #9 and #11 open (#11 on top of #9); Lorenzo's PR #10 is not on main;
    - to do with Lorenzo: point 30 and the `req.veh_red_now` field in the contract.
36. **Technician: 2 minutes for the login and buzzer muted while working** (asked by Paolo on the night of 11/10):
    - from the badge there are 2 minutes to enter (`operator.login_s`); the session stays open until "Esci" (log out)
      (`operator.session_s: 0`, Paolo's choice; with a limit, a badge with the page open restarts it). Login and logout
      consume the badge: a second login, or getting back in after logging out, asks for another badge;
    - from the badge to the logout (or at 2 minutes without login) the C1 command carries the new field
      `"tech": true`. The sketch keeps the buzzer muted; the badge confirmation beep stays (Paolo's choice). The field
      leaves on change, it does not wait for the 1 s repetition;
    - in the sketch: 2 minutes of silence from the badge even without vision, then silence as long as `tech: true`
      arrives. When `tech` goes from true to false (logout) the buzzer comes back at once. Without heartbeat the field
      is not valid: if the vision stops, the anti-theft sounds again. The shock is reported anyway (`mcu_event`,
      central office);
    - Salvatore turned the buzzer back on on 11/10 (`BUZZER_ENABLED 1`) and removed only the beep of the covered light
      sensor, which in the evening sounded continuously;
    - `tech` is a new field of contract C1, like `req.veh_red_now` (point 31): to be written by Lorenzo in
      `docs/CONTRACTS.md`. Whoever does not know it ignores it.
37. **Vision, sketch and network together on the board (11/10, 01:00)**, after the merge of PRs #9, #11 and #10:
    - **single events folder** (point 30): `~/ArduinoApps/mdgb/data/c3`, which the App Lab container sees as
      `/app/data/c3`. The vision gets there with `push_to_arduino.sh --applab mdgb` (file `ai/.c3_dir`, read by
      `run_vision.sh`), the network with the same `--applab` of its script;
    - **shock and badge only once** (point 30): only `mdgb_link.py` writes them, from `alarm_status` and `rfid_status`.
      The sketch no longer sends them as `mcu_event` (only the fail-safe remains). So they arrive also with the vision
      off, and the vision reads them from the same files (`C5FileTail`, every 0.5 s);
    - **`mdgb` app updated** with Paolo's ok:
      - sketch of point 36, on top of Salvatore's 00:23 version (shock threshold 1.15 g);
      - current `main.py`, without camera, with the 5 lines of `mdgb_link`;
      - package and test on PC in `mdgb-app-tecnico.zip`, delivered to Salvatore;
    - **`~/venv` with its own `pip`** (`python3 -m pip --python ~/venv/bin/python install pip`, without sudo): Lorenzo's
      script uses `~/venv/bin/pip`, which was missing;
    - **network:** `mdgb-comms` service, broker on Lorenzo's PC (192.168.169.12:1883). The broker receives `hb` every
      10 s (state IDLE, 8.7 FPS) and `agg` every 60 s (temperature, humidity);
    - **backup Bluetooth not active:** with BlueZ 5.82 `btmgmt` hangs if the input is `/dev/null`, as under systemd:
      "power on" times out after 5 s. Tested on the board: with `input="\n"` in `subprocess.run`
      (`comms/node/backup_link.py`) it answers at once. Fix for Lorenzo;
    - **live view in Lorenzo's app:** it does not work by choice. The stream of the vision is only for the technician
      with badge and login (point 29).
38. **C1 commands too long for the Bridge (11/10, 01:30)**, found while testing everything on the board:
    - `arduino-router` rejects `mdgb_line` calls over **238 bytes** ("message size exceeds the limit"). Measured on the
      board with test lines that the sketch discards. The C1 contract says 512, and `comms/actuators.py` shortens only
      above 512;
    - in the test scenes the commands reached 361 bytes: PRESENCE, warnings, red at once for an animal or child,
      DEGRADED. **None reached the sketch**; only IDLE and the heartbeats went through. The test of point 33 used short
      lines;
    - now `Commander` sends a line that fits the limit (`actuator.max_line_bytes: 238`). First it shortens `reason`, then
      it removes `oled`, `lcd`, `led`, `green_s`, `t_ms`. `v`, `seq`, `state`, `req` and `tech` always stay, i.e. what
      the sketch uses. The full command stays for logs, overlay and technician page;
    - for Lorenzo: in CONTRACTS the Bridge limit is 238, not 512.
39. **Camera stopped at 01:11 on 11/10.** The stream stopped without software errors; at stop the kernel wrote
    `imx219 ... disabling streaming failed (-6)`: the sensor no longer answers on I2C (CSI cable moved or detached during
    the mounting). From there the `qcom_camss` driver stays in "already streaming" and no program opens the camera
    (`Failed to start streaming: Operation already in progress`), not even `cam`. It unblocks only by checking the cable
    and rebooting the board. Meanwhile the vision was in DEGRADED ("video assente", video missing).
40. **Test of everything on the board (11/10, 01:30-01:40)**, after the reboot that unblocked the camera (point 39):
    - **automatic start:** vision as the `mdgb-ai` service (it stops with SIGINT like Ctrl+C, status lines in
      `journalctl`), network `mdgb-comms`, `mdgb` app as the default App Lab app. Tested with a reboot: everything
      restarts by itself. At the first start the camera is not ready yet: systemd restarts the vision after 2 s;
    - **shortened commands** (point 38) tested on the Bridge: the full 366-byte line is rejected, the shortened 234-byte
      one arrives and the sketch accepts it;
    - **vision interrupted:** fail-safe of the traffic light after 485 ms; systemd restarts it in 3.8 s; the camera
      reopens; the sketch goes back to "visione collegata" after 7.5 s;
    - **network cut for 100 s:** the central office switches to "rete giù, nodo sano" (network down, node healthy) via
      Bluetooth (−41 dBm). When it reopens it goes back to Wi-Fi in 18 s, with queue 0, 0 events lost and 0 duplicates;
    - **to fix in the central office (Lorenzo):**
      - at the start of the cut, for about 5 s, "nodo distrutto" (node destroyed) appears: the MQTT Last Will arrives
        before the first beacon;
      - the fail-safe of the sketch does not reach the central office when the vision is off: `mcu_event` no longer has
        anyone receiving it;
    - **not yet tested:** badge, login and muted buzzer from the phone (someone with the badge is needed); calibration
      and requests coming from a real scene.
41. **Fixes in the central office agreed with Lorenzo (11/10, 01:50)**, in PR #13 (his area):
    - **"Node destroyed" for 5 s:** for 20 s from when MQTT is lost the central office shows "Wi-Fi perso, attendo il
      Bluetooth" (Wi-Fi lost, waiting for Bluetooth) (yellow), then decides. Lorenzo found 40 s too much. It applies
      after rebuilding the app on his PC;
    - **fail-safe in the central office also with the vision off:** `mdgb_link.py` writes it from the `led_status`
      "FAIL-SAFE" message of the sketch. The sketch of the `mdgb` app no longer sends any `mcu_event`: shock, badge and
      fail-safe all go through `mdgb_link.py`, only once. App updated on the board (backup in
      `~/HackTurin-mdgb/backups/`) and zip for Salvatore updated;
    - **tested:** vision interrupted → fail-safe line after about 0.7 s → the central office shows "nodo guasto
      (semaforo in fail-safe)" (node faulty, traffic light in fail-safe) → with the vision restarted by itself it goes
      back to "nodo OK" after 12 s.
42. **Tracks that do not break (night of 11/10)**, measured on 13 test videos, including the new `Torino_night_1.mp4`
    (night, 4 min 48 s, shot from above, not calibrated):
    - **problem:** with the board limits the tracks lasted less than 1 s in median, at night (0.8 s) as by day
      (Torino_1 0.9 s, Shibuya 0.8 s). A pedestrian crossing became several "people": double counts, attributes never
      decided. It is not an effect of darkness;
    - **cause:** the detector passed to the tracker only the boxes above 0.30, so the second ByteTrack association
      (boxes between 0.1 and the threshold) never worked. With 5–6 detections per second the displacement between two
      detections also exceeded the association tolerance;
    - **choice:** `model.conf` 0.10 and `tracking.minimum_matching_threshold` 0.9 (was 0.8), chosen among 4 variants.
      New tracks are still born only from boxes above 0.4 (ByteTrack rule). Height and class vote only from boxes above
      0.30 (`tracking.measure_min_conf`): the weak ones are often cut and made the false "children" go up;
    - **results** (`--emulate-unoq`, before → after):
      - median track duration: night 0.8 → 1.7 s; Torino_1 0.9 → 1.5 s; Torino_3 1.2 → 2.0 s; Shibuya 0.8 → 1.4 s;
      - tracks under 1 s on Torino_1: 54 → 28;
      - vehicles counted on Torino_1: 20+5 → **23+10** (reference at 30 FPS and 512 px: 22+13);
      - with the detector one frame out of two (as on the board): night, tracks under 1 s 12 → 3; vehicles on Torino_1
        12+0 → 18+0;
    - **on the board:** 8.8 FPS as before, detector 125 ms;
    - **not solved:** the "children" on Torino_1 go up from 9 to 11 with `--emulate-unoq` (they stay 5 with the detector
      one frame out of two). The calibration of that video is by eye (point 28): to be verified with a person of known
      height on the real camera. Still 0 vehicles in the far direction with the detector one frame out of two: it
      depends on counting line and rate, to be looked at separately.
43. **Benchmark on the board with the test videos (11/10, 03:40)**, asked by Paolo to see live, on MQTT and on the
    technician page, how they are analysed:
    - **video instead of the camera, without `sudo`:** `run_vision.sh video <file> [--calib ...] [--once]` and
      `run_vision.sh camera`. The service runs `deploy/vision_service.sh`, which reads the source from
      `ai/.vision_args`. A single password is needed, to install the service in this form;
    - **the video behaves like a camera:** in real time it skips the late frames (`source.file_drop_late`). Before, a
      board slower than the video saw it in slow motion, with numbers not comparable with the camera;
    - **`--loop`:** it restarts from the beginning without stopping, and at every pass it prints the table of the
      per-stage times;
    - **first test:** Torino_1 on the board at 8.4–8.6 FPS, cars counted and arrived in the central office, 0 events
      lost, no command rejected by the Bridge;
    - 21 videos and the calibrations copied into `~/HackTurin-mdgb/ai/samples/` on the board (246 MB, outside git).
44. **Video controls in the technician page (11/10, 04:00)**, asked by Paolo for the live benchmark:
    - buttons previous / next video and back / forward by 10 s, only with badge and login and only when the source is a
      video; the page sends them to the vision (`POST /video`), which executes them between two frames (`playlist.py`);
    - changing video does not restart the process, otherwise the technician session would be lost and another badge
      would be needed. Detector, link with the sketch, page and events stay; tracks, counts and rule restart with the
      calibration of the new video. Without its own calibration the example one applies (counting lines only);
    - the calibration is found from the name: `Torino_1` → `torino_1.json`, `01_…` → `01.json`, `mdgb_mixkit_4194` →
      `4194.json`. The comparison ignores upper/lower case, so the result is the same on macOS and on the board;
    - the jump in the video does not take the time of the vision back: it is like a cut in the scene;
    - tested in the browser on the Mac with a simulated badge and test credentials: the four buttons change video and
      position, and the live view and the caption on the image follow.
45. **8-bit model (INT8): tried, not used (11/10, morning).** `scripts/quantize_model.py` quantizes YOLOX-nano after
    training (onnxruntime, QDQ format, per-channel weights), with the activation scales taken from frames of the test
    videos cut as the detector does:
    - all in 8 bits the objects found collapsed (114 out of 983); keeping the first 4 convolutions (they see the raw
      pixels) and the head in float, it finds the same objects as the float model (395/395 on 65 frames);
    - **but on the UNO Q it is slower:** 283 ms against 208–230 ms. The CPU (Cortex-A53, `/proc/cpuinfo`: no
      `asimddp`) has no 8-bit dot-product instructions, and onnxruntime 1.30 on the board only has the CPU provider
      (no XNNPACK). Worth trying again on a board with a Cortex-A55 or A76.
46. **PP-PicoDet-S instead of YOLOX-nano: tried, not used (11/10, morning).** A more recent light detector
    (PaddleDetection, Apache-2.0), integrated with `model.family: picodet` and `scripts/get_picodet.py`:
    - on 39 test frames it finds more people (183 against 135 for YOLOX-nano, +36%) and more vehicles (162 against
      93); YOLOX-l at 960 px finds 322 and 168;
    - **but on the board it is 2.2 times slower** (486 ms against 225 ms at 320 px, measured with the vision running):
      fewer than 3 detections per second, too few to follow who crosses. The code stays, switched off.
47. **Tracking fixed and detector on every frame (11/10, morning)**, numbers in `docs/BENCHMARK.md`:
    - **cars tracked but never counted:** `sv.ByteTrack` returned a track only if its filtered position covered the
      box by more than 50%; at 4–6 detections per second this did not happen for fast cars (it is the cause of the
      "0 vehicles in the far direction" of point 42). Now every track comes out with the box it was matched with
      (`_ByteTrack` in `tracking.py`, which wraps two methods of supervision 0.30.5: covered by the tests);
    - **boxes enlarged by 50% for the matching** (`tracking.box_buffer`, buffered IoU of the C-BIoU tracker) and **side
      of the line remembered for 30 detections** (`counting.side_memory`; supervision forgot it after 4);
    - **detector on every frame on the board** (`profiles.unoq.model.detect_every_n: 1`): measured on the board with
      Torino_1, 5.9 FPS all analysed against 8.4 FPS of which 4.2 analysed. At 416 px: 3.8 FPS;
    - **result** (8 still-camera videos): pedestrians 9 → 13 out of 23, cyclists 0 → 2 out of 4, vehicles 24 → 47 out
      of 77; right direction 100%, no extra counts, before and after;
    - tried and left off: new tracks from 0.30, confirmation after 2 detections, stitching of tracks across the line
      (`counting.stitch_s`, in the code with its tests).
48. **Benchmark of the counting with a reference checked by eye (11/10, morning)** (`scripts/benchmark.py`,
    `benchmarks/`, `docs/BENCHMARK.md`):
    - reference: YOLOX-l at 960 px on every frame at 15 FPS, confirmation after 0.5 s as on the board; the
      disagreements are looked at (`review`) and recorded (`judge`). So far 2 real crossings added, none removed;
    - the board is emulated at the FPS measured on the real board, also fractional (`sources.py`: 8.4 out of 30 is no
      longer 7.5);
    - the point where the object goes over the line is compared, not that of the confirmation;
    - only the still-camera videos count: NYC, Shibuya and two Mixkit are time-lapses or hand-held;
    - to do: calibrate Torino_4 and Torino_7 (framings different from Torino_3 and 1) and redo everything with the
      camera of the board mounted;
    - **the `Torino_*.mp4` videos on the Mac became unreadable at about 7:00 on 11/10** ("Operation not permitted":
      macOS protects them, attribute `com.apple.macl`, maybe after being opened by an app). The copies on the board
      are intact; for the benchmark `MDGB_VIDEOS=<folder with the copies>`.
