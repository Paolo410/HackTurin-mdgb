"""Check of the parts of the node (health.py) and what the technician's page shows of it: status of each part,
the Registro with accesses and events, the vision going on when the event file cannot be written."""
import http.client
import importlib.util
import json
import secrets
from pathlib import Path

import cv2
import numpy as np
import pytest

from smartcrossing import app
from smartcrossing.config import load_config
from smartcrossing.health import FAULT, OK, UNTESTED, WAITING, WARN, Health
from smartcrossing.logger import C3Logger
from smartcrossing.mcu import McuState
from smartcrossing.operator_ui import PAGE
from smartcrossing.status_page import HASH_VAR, USER_VAR, OperatorPage, hash_password

ENV = {"v": 1, "src": "mcu", "type": "env", "t_c": 21.4, "rh": 48.0, "light": 512, "eco2_ppm": 600, "tvoc_ppb": 30}
CAMERA = {"w": 640, "h": 480, "fault": None, "lum": 120.0}
USER, PASSWORD = "tecnico", secrets.token_urlsafe(12)     # made up for each run: never a real password


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def statuses(health):
    return {c["key"]: c["status"] for c in health.evaluate()["checks"]}


def test_parts_wait_at_the_start_then_a_silent_camera_is_a_fault():
    clock, changes = Clock(), []
    health = Health(clock=clock, on_change=lambda level, text: changes.append((level, text)))
    assert set(statuses(health).values()) <= {WAITING, UNTESTED}
    health.seen("camera", CAMERA)
    assert statuses(health)["camera"] == OK
    clock.t += 20                                        # no frame for 20 s, past the start
    check = {c["key"]: c for c in health.evaluate()["checks"]}["camera"]
    assert check["status"] == FAULT and "nessuna immagine da 20 s" in check["detail"] and check["hint"]
    assert any(level == "warning" and text.startswith("Camera non funziona") for level, text in changes)


def test_the_lines_of_the_board_feed_its_sensors_and_impossible_values_are_seen():
    clock = Clock()
    health = Health(clock=clock)
    health.on_mcu_line(ENV)
    s = statuses(health)
    assert s["board"] == s["env"] == s["air"] == s["light"] == OK
    health.on_mcu_line({**ENV, "t_c": -50.0, "rh": 0.0})          # AHT20 that does not answer
    assert statuses(health)["env"] == FAULT
    for _ in range(6):                                             # one minute of light at 0
        health.on_mcu_line({**ENV, "light": 0})
    assert statuses(health)["light"] == WARN
    clock.t += 40                                                  # App Lab app or sketch stopped
    assert statuses(health)["board"] == FAULT


def test_badge_and_shock_are_tested_live():
    health = Health(clock=Clock())
    s = statuses(health)
    assert s["badge"] == s["shock"] == UNTESTED
    health.on_mcu_line({"v": 1, "src": "mcu", "type": "tamper", "code": 3})
    health.on_mcu_line({"v": 1, "src": "mcu", "type": "tamper", "code": 1})
    s = statuses(health)
    assert s["badge"] == s["shock"] == OK


def test_summary_counts_the_problems_first():
    clock = Clock()
    health = Health(clock=clock)
    clock.t += 60
    health.seen("camera", {**CAMERA, "fault": "lens_covered"})
    report = health.evaluate()
    assert report["summary"]["overall"] == FAULT                  # nothing else ever arrived
    assert {c["key"]: c["status"] for c in report["checks"]}["camera"] == WARN


def request(port, method, path, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers={"Cookie": cookie} if cookie else {})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    return response.status, data, (response.getheader("Set-Cookie") or "").split(";")[0]


def test_page_shows_the_check_and_writes_accesses_in_the_registro(monkeypatch):
    cfg = load_config()
    monkeypatch.setenv(USER_VAR, USER)
    monkeypatch.setenv(HASH_VAR, hash_password(PASSWORD, iterations=1000))
    mcu = McuState(cfg)
    page = OperatorPage(0, mcu, cfg, host="127.0.0.1")
    try:
        code, body, _ = request(page.port, "GET", "/")
        assert code == 200 and b"Pagina del tecnico" in body and b"Avvicina il badge" in body
        mcu.on_line({"v": 1, "src": "mcu", "type": "tamper", "code": 3})          # badge
        code, body, _ = request(page.port, "GET", "/status.json")
        assert code == 401 and json.loads(body)["login_s"] == float(cfg["operator"]["login_s"])
        assert request(page.port, "POST", "/login", body=f"user={USER}&password=wrong")[0] == 401
        code, _, cookie = request(page.port, "POST", "/login", body=f"user={USER}&password={PASSWORD}")
        assert code == 200
        page.health = Health(clock=Clock()).evaluate()
        code, body, _ = request(page.port, "GET", "/status.json", cookie=cookie)
        status = json.loads(body)
        assert code == 200 and status["health"]["summary"]["total"] == 10
        texts = [line["text"] for line in status["log"]]
        assert texts == ["utente o password sbagliati", "il tecnico è entrato"]
        request(page.port, "POST", "/logout", cookie=cookie)
        assert page.log[-1]["text"] == "il tecnico è uscito"
        page.note("alarm", "urto")
        page.note("alarm", "urto")                                               # repeated at once: one line
        assert [line["text"] for line in page.log].count("urto") == 1
    finally:
        page.close()


def test_every_copy_of_the_logo_has_its_own_ids():
    for i in (1, 2, 3):
        assert f'id="lg{i}-glow"' in PAGE and f"url(#lg{i}-glow)" in PAGE
    assert 'id="lg-glow"' not in PAGE


def test_logo_of_the_page_is_the_one_of_the_brand():
    """smartcrossing/brand.py is written by docs/brand/genera_logo.py: it must not be left behind by a new drawing."""
    repo = Path(__file__).resolve().parents[2]
    script = repo / "docs" / "brand" / "genera_logo.py"
    if not script.exists():                                  # on the board there is only ai/
        pytest.skip("docs/brand is not here")
    spec = importlib.util.spec_from_file_location("genera_logo", script)
    brand = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(brand)
    written = (repo / "ai" / "smartcrossing" / "brand.py").read_text(encoding="utf-8")
    assert written == brand.page_module(), "lancia: python docs/brand/genera_logo.py"


def test_a_c3_file_that_cannot_be_written_does_not_stop_the_vision(tmp_path, capsys, monkeypatch):
    video = str(tmp_path / "texture.avi")
    writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (320, 240))
    rng = np.random.default_rng(2)
    for _ in range(8):
        writer.write(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8))
    writer.release()

    def full_disk(self, *args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(C3Logger, "write", full_disk)
    monkeypatch.setattr(C3Logger, "status_due", lambda self: True)
    assert app.main(["--source", video, "--headless", "--c3-dir", str(tmp_path / "c3"), "--max-frames", "8"]) == 0
