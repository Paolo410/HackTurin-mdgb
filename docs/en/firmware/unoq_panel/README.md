<img src="../../../../firmware/unoq_mcu/assets/logo.svg" alt="MDGB" width="56" align="right">

# unoq_panel — the old "mdgb" with the technician panel, without the vision inside

> English translation of [`firmware/unoq_panel/README.md`](../../../../firmware/unoq_panel/README.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

Owner: Salvatore Gullotta. It is the App Lab app `mdgb` of `code1.zip` (the vision runs **outside** App Lab, as a
service of `ai/`) plus the technician panel of `unoq_mcu/assets/`.

What stays identical to `code1.zip`: the sketch (taken from `unoq_mcu/sketch/`, which is identical byte for byte),
`app.yaml` and every line of `python/main.py`. In `main.py` there are only **added lines**: one per callback, which
passes the value to the panel, plus the import and the start. Without them the page would receive nothing.

The panel does not open the camera and does not talk to the vision:

- sensors, traffic-light phase, badge and alarm come from the callbacks of the sketch;
- the vision → sketch link from the `led_status` messages of the sketch ("VISIONE collegata" / "FAIL-SAFE");
- camera, recognition, counts and crossings from the C3 lines the vision writes in `data/c3` of the app
  (`~/ArduinoApps/mdgb/data/c3`). The vision must be installed with `push_to_arduino.sh --applab mdgb`; if it writes
  elsewhere, the Camera and Recognition cards stay red with the "what to do".
- The live view with the boxes stays on the vision page (port 8090): the panel has a button for it.

It does not register `mcu_event` on the Bridge: the vision already receives those lines and the router accepts only one
receiver.

**Towards the central office** (added by Paolo on 11/10, with the team's ok): `main.py` also passes the values to
Lorenzo's `mdgb_link.py` (taken from `comms/applab/` when the zip is built). It writes sensors, shock, badge and
fail-safe in `data/c3/applab-*.jsonl`, which the network brings to the central office also when the vision is off. The
vision does not make a second copy (`mcu.save_bridge_lines: false` in `ai/config.yaml`).

**Technician badge:** the code is no longer in the sketch. It is in `../unoq_mcu/sketch/arduino_secrets.h`, ignored by
git: create it from `arduino_secrets.h.example`. Without that file `build_applab_zip.py` stops and says so.

## Build the zip and start

```bash
python firmware/tools/build_applab_zip.py --panel
```

It writes `firmware/dist/mdgb-pannello.zip` (folder `mdgb` inside, 12 files, no model). In App Lab: delete or rename
the existing `mdgb` app, import the zip, Run. Page on `http://<board-ip>:7000`. No dependency to install. Then the
vision as before:

```bash
~/HackTurin-mdgb/ai/deploy/run_vision.sh start
```

## Tested

On the PC with fake `arduino.*` modules and a fake vision service writing C3 lines: status, counts, crossings, near
misses, missing sensors and badge appear in the panel. To verify on the board: that `/app/data/c3` of the container is
`~/ArduinoApps/mdgb/data/c3`.
