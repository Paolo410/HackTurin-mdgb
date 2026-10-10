"""Lines of the microcontroller (C5): shock, technician's badge, sensors; the status page; the app on a video."""
import json
import urllib.error
import urllib.request

import cv2
import numpy as np
import supervision as sv

from smartcrossing import app
from smartcrossing.config import load_config
from smartcrossing.mcu import C5FileTail, McuState
from smartcrossing.pipeline import Pipeline
from smartcrossing.sim import FRAME_SIZE, demo_calib
from smartcrossing.status_page import PAGE, OperatorPage

CFG = load_config()
SHOCK = {"v": 1, "src": "mcu", "type": "tamper", "code": 1}
BADGE = {"v": 1, "src": "mcu", "type": "tamper", "code": 3}


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def test_a_shock_means_degraded_for_a_while_and_the_badge_clears_it():
    clock = Clock()
    mcu = McuState(CFG, monotonic=clock)
    assert mcu.fault() is None and not mcu.unlocked()
    mcu.on_line(SHOCK)
    assert mcu.fault() == "tamper"
    clock.t += CFG["mcu"]["tamper_hold_s"] - 1
    assert mcu.fault() == "tamper"
    clock.t += 2
    assert mcu.fault() is None                      # the hold time is over
    mcu.on_line(SHOCK)
    mcu.on_line(BADGE)
    assert mcu.fault() is None and mcu.unlocked()   # the technician checked: cleared at once
    clock.t += CFG["operator"]["unlock_s"] + 1
    assert not mcu.unlocked()                       # the page closes by itself


def test_without_a_hold_time_only_the_badge_clears_a_shock():
    cfg = load_config()
    cfg["mcu"]["tamper_hold_s"] = None
    clock = Clock()
    mcu = McuState(cfg, monotonic=clock)
    mcu.on_line(SHOCK)
    clock.t += 86400
    assert mcu.fault() == "tamper"
    mcu.on_line(BADGE)
    assert mcu.fault() is None


def test_sensors_lamp_fault_and_lines_we_do_not_know():
    clock = Clock()
    mcu = McuState(CFG, monotonic=clock)
    mcu.on_line({"v": 1, "src": "mcu", "ts": 1.0, "type": "env", "t_c": 21.5, "rh": 40.0})
    mcu.on_line({"v": 1, "src": "mcu", "type": "env", "light": 512})
    mcu.on_line({"type": "something_new", "x": 1})
    mcu.on_line("not a dict")
    assert mcu.env == {"t_c": 21.5, "rh": 40.0, "light": 512}
    mcu.on_line({"type": "lamp_fault", "pattern": "AMBER_BLINK_2HZ"})
    assert mcu.fault() == "lamp_fault"
    clock.t += CFG["mcu"]["lamp_fault_hold_s"] + 1
    assert mcu.fault() is None
    mcu.on_line({"type": "failsafe", "reason": "hb_timeout"})
    assert mcu.snapshot()["firmware_failsafe"]["reason"] == "hb_timeout"


def test_file_reader_skips_the_past_and_follows_new_lines_and_new_files(tmp_path):
    old = tmp_path / "applab-20261010-100000.jsonl"
    old.write_text(json.dumps(BADGE) + "\n")           # written before the vision started: not for today
    (tmp_path / "c3-20261010-100000.jsonl").write_text(json.dumps(SHOCK) + "\n")   # another series: not ours
    seen = []
    tail = C5FileTail(tmp_path, "applab", seen.append, poll_s=0.01)
    assert tail.poll() == 0 and seen == []
    with open(old, "a") as fh:
        fh.write(json.dumps(SHOCK) + "\n" + '{"type":"env","t_c"')   # second line still being written
    assert tail.poll() == 1 and seen == [SHOCK]
    with open(old, "a") as fh:
        fh.write(':20.0}\nnot json\n')
    assert tail.poll() == 1 and seen[-1] == {"type": "env", "t_c": 20.0}
    (tmp_path / "applab-20261010-110000.jsonl").write_text(json.dumps(BADGE) + "\n")   # rotation
    assert tail.poll() == 1 and seen[-1] == BADGE
    assert tail.poll() == 0


def test_status_page_answers_only_after_the_badge_and_never_shows_images():
    mcu = McuState(CFG)
    page = OperatorPage(0, mcu, host="127.0.0.1")      # port 0: any free port
    try:
        page.update({"state": "PRESENCE", "reason": "pedone in attesa", "fps": 9.5})
        assert get(page.port, "/")[0] == 200
        code, body = get(page.port, "/status.json")
        assert code == 403 and json.loads(body) == {"locked": True}
        mcu.on_line(BADGE)
        code, body = get(page.port, "/status.json")
        status = json.loads(body)
        assert code == 200 and status["state"] == "PRESENCE" and status["mcu"]["unlock_s_left"] > 0
        assert get(page.port, "/frame.jpg")[0] == 404
    finally:
        page.close()
    for tag in ("<img", "<video", "<canvas"):
        assert tag not in PAGE


def test_a_fault_of_the_microcontroller_puts_the_rule_in_degraded():
    pipeline = Pipeline(CFG, frame_rate=10, calib=demo_calib(CFG), load_detector=False)
    assert pipeline.process(sv.Detections.empty(), 0.0, FRAME_SIZE).command["state"] == "IDLE"
    pipeline.external_fault = "tamper"
    command = pipeline.process(sv.Detections.empty(), 0.1, FRAME_SIZE).command
    assert command["state"] == "DEGRADED" and "urtato" in command["reason"]
    assert pipeline.no_frame(0.2)["state"] == "DEGRADED"
    pipeline.external_fault = None
    for i in range(3, 30):                               # back to normal after the hold time of the rule
        command = pipeline.process(sv.Detections.empty(), i / 10.0, FRAME_SIZE).command
    assert command["state"] == "IDLE"


def test_the_app_reads_the_files_of_the_sketch_app_and_serves_the_page(tmp_path, capsys):
    video = str(tmp_path / "grey.avi")
    writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (320, 240))
    rng = np.random.default_rng(0)
    for _ in range(8):
        writer.write(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8))   # texture: not a covered lens
    writer.release()
    code = app.main(["--source", video, "--headless", "--no-c3", "--c3-dir", str(tmp_path),
                     "--operator-port", "0", "--max-frames", "8"])
    out = capsys.readouterr().out
    assert code == 0
    assert f"mcu_files={tmp_path}/applab-*.jsonl" in out and "operator_page=:" in out
