<img src="../../../../firmware/unoq_mcu/assets/logo.svg" alt="MDGB" width="56" align="right">

# unoq_mcu — App Lab app "mdgb"

> English translation of [`firmware/unoq_mcu/README.md`](../../../../firmware/unoq_mcu/README.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

Owner: Salvatore Gullotta. A single App Lab app that does everything on the UNO Q:

- `sketch/` — the MCU sketch (simulated traffic light, fail-safe, sensors, RFID), unchanged from `code1.zip`;
- `python/main.py` — the same Bridge callbacks as before, plus `mcu_event` and the start of the vision;
- `python/vision.py` — camera (App Lab `Camera` peripheral) → `smartcrossing` from `ai/` (profile `unoq`) →
  C1/C2 to the sketch with `Bridge.call("mdgb_line", ...)` → web page;
- `python/health.py` — check of every part of the node, once a second (see below);
- `assets/` — technician panel: summary, sensor check, traffic light, live view with the boxes, traffic, log.

## Technician panel (port 7000)

Designed for a technician with a phone, also outdoors: light theme (dark if the device asks for it), colours of road
signs, system fonts (works without internet). Three tabs:

- **Stato** (status): one sentence on top ("Everything works", "One thing to check", "2 things to fix"), then the parts
  to fix with **what to do**, then one line for every part that works; on the side the traffic light and the technical
  details (collapsible).
- **Traffico** (traffic): live view with the boxes (in the panel version, the button to the vision page) and the
  counted crossings.
- **Registro** (log): events written as sentences, filterable (Sensors, Traffic, Security), downloadable as a text file.

The parts that are checked:

| Part | How it is checked | Does not work if |
|---|---|---|
| Camera | images arrive; self-check of the vision | no image for 2 s; lens covered or dazzled = to check |
| Recognition (AI) | frames processed | stopped for 3 s; below 5 FPS = to check |
| Link with the sketch | heartbeats accepted by the sketch | sketch in fail-safe |
| Traffic-light cycle | `led_status` of the sketch | no phase change for 60 s |
| Accelerometer | `sensor_movement` | no data for 5 s or always 0; outside 0.65–1.15 g = shock |
| Temperature and humidity (AHT20) | `sensor_env` | no data for 5 s or a reading of −50 °C (silent sensor) |
| Air quality (SGP30) | `sensor_air` | no data for 5 s |
| Light sensor | `sensor_light` | no data for 5 s; always 0 or always at maximum = to check |
| Badge reader | `rfid_data` | — tested by passing the badge ("to test" until it happens) |
| Event storage | C3 files in `data/` | write error |

In the first 15 s after the start, parts without data are "waiting", not faulty. Every change of status ends up in the
log ("Sensori" tab) and in the App Lab console with the prefix `diagnosi:`. The log keeps the last 100 events in memory
only; "Scarica" (download) saves on the technician's device a text file with the sensor check and the events. The
traffic light does not depend on these checks.

The code of the vision **is not copied here**: the build script puts inside `python/` the `ai/smartcrossing` package,
`config.yaml`, the calibration and the model taken from the repository.

## Build the zip

```bash
python firmware/tools/build_applab_zip.py
```

It writes `firmware/dist/mdgb.zip` (ignored by git). It needs `ai/models/yolox_nano_dynamic.onnx`
(`bash ai/scripts/get_model.sh`), or `--models-dir <folder with the model>`.
If `ai/calib.json` exists it is used, otherwise `calib.example.json` (the boxes are shown anyway; zones, counting lines
and speeds are right only with the calibration of the real camera).

## Start

1. App Lab → My Apps → import `mdgb.zip`; if an app `mdgb` already exists, delete or rename it first.
2. Run. At the first start App Lab installs `python/requirements.txt` (onnxruntime, supervision): it takes a few minutes.
3. Open the page of the app (App Lab button, or `http://<board-ip>:7000`).

Optional environment variables: `MDGB_CAMERA=csi:0` to choose the camera (default: the first free one),
`MDGB_LIVE_VIEW=0` to send the page only boxes and numbers, without the image.

This app uses the camera: do not start `ai/deploy/run_vision.sh` or the `mdgb-ai` service at the same time.

## Tested

- On the PC, with fake `arduino.*` modules and a video instead of the camera: profile `unoq` at about 12 FPS, C1 and
  heartbeat to the sketch, C3 events written, page with the right boxes.
- To verify on the board: installation of `requirements.txt` in the container, colour order of `Camera.capture()`
  (BGR expected), real FPS.

## Technician badge and buzzer (11/10)

- The code of the authorised badge is in `sketch/arduino_secrets.h` (`SECRET_TECH_BADGE`), ignored by git; the
  repository has only `sketch/arduino_secrets.h.example`.
- Buzzer muted while the technician is there: 2 minutes of silence from the badge, even without the vision, then as
  long as the vision sends `"tech": true` in the C1 command, that is until the logout from the page. The confirmation
  beep of the badge stays. Without heartbeat the field no longer counts and the anti-theft sounds again
  (`ai/DECISIONS.md`, point 36).
- Test on the PC, with a fake badge: `firmware/unoq_mcu/host_test/run.sh`, which prints "all checks passed".
