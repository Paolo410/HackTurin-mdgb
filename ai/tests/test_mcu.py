"""Lines of the microcontroller (C5): technician's badge, anti-theft shock, sensors; the technician's page
(badge, login, live view that can be switched off); the app on a video."""
import http.client
import importlib.util
import json
import os
import secrets
import stat
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
import supervision as sv

from smartcrossing import app
from smartcrossing.actuator import SimActuator
from smartcrossing.config import load_config, resolve_path
from smartcrossing.mcu import C5FileTail, McuState
from smartcrossing.pipeline import Pipeline
from smartcrossing.sim import FRAME_SIZE, demo_calib
from smartcrossing.status_page import HASH_VAR, USER_VAR, OperatorPage, check_password, hash_password, load_credentials

CFG = load_config()
SHOCK = {"v": 1, "src": "mcu", "type": "tamper", "code": 1}
BADGE = {"v": 1, "src": "mcu", "type": "tamper", "code": 3}
USER, PASSWORD = "tecnico", secrets.token_urlsafe(12)     # made up for each run: never a real password
# The whole app loads the detector: its weights are not in git (same rule as in test_detector.py).
needs_model = pytest.mark.skipif(not resolve_path(CFG["model"]["path"]).is_file(),
                                 reason="model not prepared (bash scripts/get_model.sh)")


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def request(port, method, path, body=None, cookie=None):
    """(status, body, Set-Cookie) of one request to the page."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Cookie": cookie} if cookie else {}
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data, (response.getheader("Set-Cookie") or "").split(";")[0]


def page_with_login(monkeypatch, images=True, mcu=None, clock=None, session_s=None):
    cfg = load_config()
    cfg["operator"]["share_images"] = images
    if session_s is not None:
        cfg["operator"]["session_s"] = session_s
    monkeypatch.setenv(USER_VAR, USER)
    monkeypatch.setenv(HASH_VAR, hash_password(PASSWORD, iterations=1000))   # few iterations: fast tests
    clock = clock or time.monotonic
    mcu = mcu or McuState(cfg, monotonic=clock)
    return OperatorPage(0, mcu, cfg, host="127.0.0.1", monotonic=clock), mcu  # port 0: any free port


def login(page, user=USER, password=PASSWORD):
    return request(page.port, "POST", "/login", body=f"user={user}&password={password}")


def test_a_shock_is_the_anti_theft_alarm_and_does_not_change_the_vision():
    clock = Clock()
    mcu = McuState(CFG, monotonic=clock)
    assert mcu.fault() is None and mcu.snapshot()["shock_s_ago"] is None
    mcu.on_line(SHOCK)
    clock.t += 7
    assert mcu.fault() is None                      # the vision keeps working: the alarm is for the central
    assert mcu.snapshot()["shock_s_ago"] == 7       # the technician sees it


def test_the_badge_gives_two_minutes_to_log_in_and_a_second_badge_only_adds_time():
    clock = Clock()
    mcu = McuState(CFG, monotonic=clock)
    assert CFG["operator"]["login_s"] == 120
    assert not mcu.unlocked() and mcu.window == 0
    mcu.on_line(BADGE)
    assert mcu.unlocked() and mcu.window == 1 and mcu.snapshot()["login_s_left"] == 120
    clock.t += CFG["operator"]["login_s"] - 10
    mcu.on_line(BADGE)                              # still open: same window, more time
    assert mcu.window == 1
    clock.t += 20
    assert mcu.unlocked()
    clock.t += CFG["operator"]["login_s"]
    assert not mcu.unlocked()                       # it closes by itself
    mcu.on_line(BADGE)
    assert mcu.window == 2                          # a new window: old sessions do not come back to life
    mcu.lock()
    assert not mcu.unlocked()


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


def test_password_is_stored_only_as_a_salted_hash(tmp_path, monkeypatch):
    stored = hash_password(PASSWORD, iterations=1000)
    assert PASSWORD not in stored and check_password(PASSWORD, stored)
    assert not check_password(PASSWORD + "x", stored) and not check_password(PASSWORD, "not a hash")
    assert hash_password(PASSWORD, iterations=1000) != stored            # a new salt every time

    spec = importlib.util.spec_from_file_location(
        "operator_login", Path(__file__).resolve().parent.parent / "scripts" / "operator_login.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    path = tmp_path / ".env"
    path.write_text("OTHER=1\n" + USER_VAR + "=old\n")
    tool.write_credentials(path, USER, PASSWORD)
    text = path.read_text()
    assert "OTHER=1" in text and "old" not in text and PASSWORD not in text
    if os.name != "nt":   # Windows has no POSIX permissions: chmod only sets the read-only flag, stat gives 0o666
        assert stat.S_IMODE(path.stat().st_mode) == 0o600                # readable by the owner only

    monkeypatch.delenv(USER_VAR, raising=False)
    monkeypatch.delenv(HASH_VAR, raising=False)
    cfg = load_config()
    cfg["operator"]["credentials_file"] = str(path)
    user, stored = load_credentials(cfg)
    assert user == USER and check_password(PASSWORD, stored)
    cfg["operator"]["credentials_file"] = str(tmp_path / "missing")
    assert load_credentials(cfg) is None


def test_technician_page_needs_the_badge_and_then_the_login(monkeypatch):
    page, mcu = page_with_login(monkeypatch)
    try:
        page.update({"state": "PRESENCE", "reason": "pedone in attesa", "fps": 9.5})
        assert request(page.port, "GET", "/")[0] == 200                   # the page itself holds no data
        assert request(page.port, "GET", "/status.json")[0] == 403        # no badge
        assert login(page)[0] == 403                                      # right password, no badge: no
        mcu.on_line(BADGE)
        assert request(page.port, "GET", "/status.json")[0] == 401        # badge, not logged in
        assert login(page, password="wrong")[0] == 401
        assert login(page, user="someone")[0] == 401
        code, _, cookie = login(page)
        assert code == 200 and cookie.startswith("mdgb_session=")
        code, body, _ = request(page.port, "GET", "/status.json", cookie=cookie)
        status = json.loads(body)
        assert code == 200 and status["state"] == "PRESENCE" and status["session_s_left"] is None  # until logout
        assert request(page.port, "GET", "/status.json", cookie="mdgb_session=guess")[0] == 403    # badge used
        assert login(page)[0] == 403                                      # a second login needs a new badge
        request(page.port, "POST", "/logout", cookie=cookie)
        assert request(page.port, "GET", "/status.json", cookie=cookie)[0] == 403
        mcu.on_line(BADGE)                                                # next badge: the old session is dead
        assert request(page.port, "GET", "/status.json", cookie=cookie)[0] == 401
    finally:
        page.close()


def test_too_many_wrong_passwords_close_the_page_until_the_next_badge(monkeypatch):
    page, mcu = page_with_login(monkeypatch)
    try:
        mcu.on_line(BADGE)
        for _ in range(CFG["operator"]["max_failed_logins"]):
            assert login(page, password="wrong")[0] == 401
        assert login(page)[0] == 403 and not mcu.unlocked()               # even the right one: badge again
        mcu.on_line(BADGE)
        assert login(page)[0] == 200
    finally:
        page.close()


def test_two_minutes_to_log_in_after_the_badge(monkeypatch):
    clock = Clock()
    page, mcu = page_with_login(monkeypatch, clock=clock)
    try:
        mcu.on_line(BADGE)
        code, body, _ = request(page.port, "GET", "/status.json")
        assert code == 401 and json.loads(body)["login_s_left"] == 120   # the form shows the seconds left
        clock.t += 121
        assert request(page.port, "GET", "/status.json")[0] == 403
        assert login(page)[0] == 403                                      # too late: badge again
        mcu.on_line(BADGE)
        clock.t += 100
        assert login(page)[0] == 200                                      # in time
    finally:
        page.close()


def test_the_technician_is_present_from_the_badge_to_the_logout(monkeypatch):
    clock = Clock()
    page, mcu = page_with_login(monkeypatch, clock=clock)
    try:
        assert not page.technician_present()
        mcu.on_line(BADGE)
        assert page.technician_present()                                  # quiet from the badge on
        _, _, cookie = login(page)
        clock.t += 3600                                                   # no time limit once logged in
        assert page.technician_present()
        assert request(page.port, "GET", "/status.json", cookie=cookie)[0] == 200
        request(page.port, "POST", "/logout", cookie="mdgb_session=guess")  # not a session: changes nothing
        assert page.technician_present()
        request(page.port, "POST", "/logout", cookie=cookie)
        assert not page.technician_present()                              # the buzzer is back at once
        mcu.on_line(BADGE)
        clock.t += 121                                                    # badge and no login: back after 2 min
        assert not page.technician_present()
    finally:
        page.close()


def test_a_badge_while_logged_in_does_not_leave_a_window_open(monkeypatch):
    clock = Clock()
    page, mcu = page_with_login(monkeypatch, clock=clock)
    try:
        mcu.on_line(BADGE)
        _, _, cookie = login(page)
        mcu.on_line(BADGE)                                                # e.g. the same badge read twice
        assert page.technician_present() and not mcu.unlocked()
        request(page.port, "POST", "/logout", cookie=cookie)
        assert not page.technician_present()                              # logout still ends it at once
    finally:
        page.close()


def test_with_a_session_limit_the_session_ends_and_a_badge_starts_it_again(monkeypatch):
    clock = Clock()
    page, mcu = page_with_login(monkeypatch, clock=clock, session_s=600)
    try:
        mcu.on_line(BADGE)
        _, _, cookie = login(page)
        code, body, _ = request(page.port, "GET", "/status.json", cookie=cookie)
        assert code == 200 and json.loads(body)["session_s_left"] == 600
        clock.t += 500
        mcu.on_line(BADGE)                                                # more time
        assert page.technician_present()                                  # the vision loop asks at every frame
        clock.t += 500
        assert request(page.port, "GET", "/status.json", cookie=cookie)[0] == 200
        clock.t += 101
        assert request(page.port, "GET", "/status.json", cookie=cookie)[0] == 403
        assert not page.technician_present()
    finally:
        page.close()


def test_video_buttons_only_for_a_logged_in_technician_and_only_with_a_video(monkeypatch):
    page, mcu = page_with_login(monkeypatch)
    asked = []
    try:
        assert request(page.port, "POST", "/video", body="action=next")[0] == 403          # no badge
        mcu.on_line(BADGE)
        assert request(page.port, "POST", "/video", body="action=next")[0] == 401          # badge, no login
        _, _, cookie = login(page)
        assert request(page.port, "POST", "/video", body="action=next", cookie=cookie)[0] == 404   # camera: none
        page.video_control = lambda action: asked.append(action) or action in ("prev", "next", "back", "fwd")
        assert request(page.port, "POST", "/video", body="action=fwd", cookie=cookie)[0] == 200
        assert request(page.port, "POST", "/video", body="action=next", cookie=cookie)[0] == 200
        assert request(page.port, "POST", "/video", body="action=reboot", cookie=cookie)[0] == 400
        assert asked == ["fwd", "next", "reboot"]
    finally:
        page.close()


def test_without_credentials_on_the_board_nobody_gets_in(monkeypatch, tmp_path):
    monkeypatch.delenv(USER_VAR, raising=False)
    monkeypatch.delenv(HASH_VAR, raising=False)
    cfg = load_config()
    cfg["operator"]["credentials_file"] = str(tmp_path / "missing")
    mcu = McuState(cfg)
    page = OperatorPage(0, mcu, cfg, host="127.0.0.1")
    try:
        mcu.on_line(BADGE)
        assert login(page, user="", password="")[0] == 503
        assert request(page.port, "GET", "/status.json")[0] == 401
    finally:
        page.close()


def test_live_view_only_for_a_logged_in_technician_who_is_watching(monkeypatch):
    page, mcu = page_with_login(monkeypatch, images=True)
    frame = np.full((480, 640, 3), 90, dtype=np.uint8)
    try:
        mcu.on_line(BADGE)
        assert request(page.port, "GET", "/stream.mjpg")[0] == 401
        assert not page.wants_frame()                                     # nobody watching: no frame is made
        _, _, cookie = login(page)
        stop = threading.Event()
        close = threading.Timer(0.5, lambda: request(page.port, "POST", "/logout", cookie=cookie))

        def vision_loop():
            while not stop.is_set():
                if page.wants_frame():
                    page.push_frame(frame)
                time.sleep(0.01)

        feeder = threading.Thread(target=vision_loop)
        feeder.start()
        conn = http.client.HTTPConnection("127.0.0.1", page.port, timeout=5)
        conn.request("GET", "/stream.mjpg", headers={"Cookie": cookie})
        response = conn.getresponse()
        assert response.status == 200 and "multipart/x-mixed-replace" in response.getheader("Content-Type")
        data = response.read(3000)
        start = data.index(b"\xff\xd8")                                 # a JPEG starts here
        assert b"Content-Type: image/jpeg" in data[:start]
        length = int(data[:start].split(b"Content-Length: ")[1].split(b"\r\n")[0])
        jpeg = (data + response.read(max(0, start + length - len(data))))[start:start + length]
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert image.shape[1] == CFG["operator"]["stream_width"]          # reduced for the phone
        close.start()                                                     # logout: the stream ends
        response.read()
        close.join()
        conn.close()
        stop.set()
        feeder.join()
        deadline = time.monotonic() + 3
        while page._viewers and time.monotonic() < deadline:
            time.sleep(0.02)
        assert page._viewers == 0 and page._jpeg is None                  # no image is kept once nobody watches
    finally:
        page.close()


def test_with_images_switched_off_only_the_statistics_remain(monkeypatch):
    page, mcu = page_with_login(monkeypatch, images=False)
    try:
        mcu.on_line(BADGE)
        _, _, cookie = login(page)
        page.update({"state": "IDLE"})
        code, body, _ = request(page.port, "GET", "/status.json", cookie=cookie)
        assert code == 200 and json.loads(body)["images"] is False
        assert request(page.port, "GET", "/stream.mjpg", cookie=cookie)[0] == 404
        assert not page.wants_frame()                                     # the vision never draws or encodes a frame
    finally:
        page.close()


def test_a_fault_of_the_microcontroller_puts_the_rule_in_degraded():
    pipeline = Pipeline(CFG, frame_rate=10, calib=demo_calib(CFG), load_detector=False)
    assert pipeline.process(sv.Detections.empty(), 0.0, FRAME_SIZE).command["state"] == "IDLE"
    pipeline.external_fault = "lamp_fault"
    command = pipeline.process(sv.Detections.empty(), 0.1, FRAME_SIZE).command
    assert command["state"] == "DEGRADED" and "lampada" in command["reason"]
    assert pipeline.no_frame(0.2)["state"] == "DEGRADED"
    pipeline.external_fault = None
    for i in range(3, 30):                               # back to normal after the hold time of the rule
        command = pipeline.process(sv.Detections.empty(), i / 10.0, FRAME_SIZE).command
    assert command["state"] == "IDLE"


def test_the_technician_reaches_the_sketch_in_the_command_at_once():
    sim = SimActuator()
    pipeline = Pipeline(CFG, frame_rate=10, calib=demo_calib(CFG), actuator=sim, load_detector=False)
    assert pipeline.process(sv.Detections.empty(), 0.0, FRAME_SIZE).command["tech"] is False
    pipeline.technician = True
    result = pipeline.process(sv.Detections.empty(), 0.1, FRAME_SIZE)
    assert result.sent and sim.sent[-1]["tech"] is True               # a change: sent now, not at the 1 s repeat
    assert sim.sent[-1]["state"] == "IDLE"                            # the rule does not change
    pipeline.technician = False
    assert pipeline.no_frame(0.2)["tech"] is False and sim.sent[-1]["tech"] is False


@needs_model
def test_the_app_reads_the_files_of_the_sketch_app_and_serves_the_page(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv(USER_VAR, raising=False)
    monkeypatch.delenv(HASH_VAR, raising=False)
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
    assert f"mcu_files={tmp_path}/applab-*.jsonl" in out and "operator_page=:" in out and "images=on" in out


@needs_model
def test_with_the_example_calibration_crossings_stay_on_the_screen(tmp_path, capsys, monkeypatch):
    """The counting lines of the example are not on the stripes of the real scene: their crossings must not reach
    the central as real ones. With the calibration of the view they do."""
    from smartcrossing.config import resolve_path
    video = str(tmp_path / "texture.avi")
    writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (320, 240))
    rng = np.random.default_rng(1)
    for _ in range(8):
        writer.write(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8))
    writer.release()
    real_step = app.Pipeline.step

    def step(self, frame, t):                         # one crossing on every frame
        result = real_step(self, frame, t)
        result.events.append({"type": "crossing", "track_id": 1, "cls": "pedestrian", "dir": "in", "line": "ped"})
        return result

    monkeypatch.setattr(app.Pipeline, "step", step)
    example = resolve_path(CFG["counting"]["example_calib_path"])
    own = tmp_path / "calib_of_this_view.json"
    own.write_text(example.read_text())
    for calib, expected in ((example, 0), (own, 8)):
        c3 = tmp_path / f"c3_{expected}"
        assert app.main(["--source", video, "--headless", "--c3-dir", str(c3), "--calib", str(calib),
                         "--max-frames", "8"]) == 0
        lines = [json.loads(line) for f in c3.glob("c3-*.jsonl") for line in f.read_text().splitlines()]
        assert sum(line["type"] == "crossing" for line in lines) == expected
    assert "NOT sent to the central" in capsys.readouterr().out
