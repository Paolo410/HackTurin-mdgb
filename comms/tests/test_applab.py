"""App Lab side of the sketch (comms/applab): main.py with mdgb_link.py, run with stand-ins for the App Lab modules,
called the way the sketch's Bridge.notify calls it; the node then reads the lines it wrote."""
import glob
import importlib
import json
import os
import runpy
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APPLAB = os.path.join(ROOT, "comms", "applab")
for p in (ROOT, os.path.join(ROOT, "comms", "node"), APPLAB):
    if p not in sys.path:
        sys.path.insert(0, p)


def fake_app_lab(monkeypatch):
    """arduino.app_utils / app_bricks / app_peripherals exist only inside App Lab: minimal stand-ins."""
    provided = {}
    utils = types.ModuleType("arduino.app_utils")
    utils.Bridge = types.SimpleNamespace(provide=lambda name, fn: provided.__setitem__(name, fn))
    utils.App = types.SimpleNamespace(run=lambda: None)
    utils.Logger = lambda name: types.SimpleNamespace(info=lambda msg: None)
    web = types.ModuleType("arduino.app_bricks.web_ui")
    web.WebUI = lambda: types.SimpleNamespace(expose_camera=lambda path, cam: None)
    cam = types.ModuleType("arduino.app_peripherals.camera")
    cam.Camera = lambda **kw: types.SimpleNamespace(start=lambda: None)
    for name, mod in {"arduino.app_utils": utils, "arduino.app_bricks": types.ModuleType("arduino.app_bricks"),
                      "arduino.app_bricks.web_ui": web, "arduino.app_peripherals": types.ModuleType("x"),
                      "arduino.app_peripherals.camera": cam}.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return provided


def lines(d):
    return [json.loads(line) for f in sorted(glob.glob(os.path.join(d, "applab-*.jsonl"))) for line in open(f)]


def test_main_py_forwards_the_sketch_notifications(tmp_path, monkeypatch):
    c3 = str(tmp_path / "c3")
    monkeypatch.setenv("MDGB_C3_DIR", c3)
    provided = fake_app_lab(monkeypatch)
    import mdgb_link
    importlib.reload(mdgb_link)                     # reads MDGB_C3_DIR at import
    runpy.run_path(os.path.join(APPLAB, "main.py"), run_name="__main__")
    assert set(provided) == {"alarm_status", "led_status", "sensor_movement", "sensor_env", "sensor_air",
                             "sensor_light", "rfid_data", "rfid_status"}, "all of Salvatore's Bridge names, unchanged"

    t = [1000.0]
    monkeypatch.setattr(mdgb_link.time, "time", lambda: t[0])
    for _ in range(30):                             # 9 s of samples every 300 ms, as the sketch sends them
        provided["sensor_env"](23.46, 45.04)
        provided["sensor_light"](512.0)
        provided["sensor_air"](400.0, 7.0)
        provided["sensor_movement"](0.0, 0.0, 1.0)
        provided["led_status"]("LED VERDE acceso (Pin 13)")
        t[0] += 0.3
    for _ in range(5):                              # the theft alarm repeats at every sample
        provided["alarm_status"]("ALLARME: TENTATO FURTO! Accelerazione anomala rilevata!")
        t[0] += 0.3
    provided["rfid_data"]("430052353713")
    provided["rfid_status"]("ACCESSO NEGATO (Errore 1/3)")
    provided["rfid_status"]("ACCESSO CONSENTITO (Granted)")
    provided["sensor_env"](24.0, 50.0)              # > 10 s after the first env line: a second one
    provided["led_status"]("FAIL-SAFE: visione assente, ciclo normale")   # the vision stopped
    provided["led_status"]("VISIONE collegata: semaforo adattivo")
    provided["led_status"]("FAIL-SAFE: visione assente, ciclo normale")   # again within 10 s: not repeated

    out = lines(c3)
    assert [o["type"] for o in out] == ["env", "tamper", "tamper", "env", "failsafe"], out
    assert out[4]["reason"] == "hb_timeout", "the fail-safe reaches the central even with the vision off"
    assert out[0] == {"v": 1, "src": "mcu", "ts": 1000.0, "type": "env", "t_c": 23.5, "rh": 45.0}
    assert (out[1]["code"], out[2]["code"]) == (1, 3), "theft alarm once (code 1), then the technician badge (code 3)"
    assert out[3]["t_c"] == 24.0 and out[3]["light"] == 512 and out[3]["eco2_ppm"] == 400
    assert "430052353713" not in json.dumps(out), "the badge code never leaves the board"


def test_node_reads_the_app_lab_lines(tmp_path, monkeypatch):
    from event_source import C3FileSource
    from outbox import Outbox
    c3 = str(tmp_path / "c3")
    monkeypatch.setenv("MDGB_C3_DIR", c3)
    import mdgb_link
    importlib.reload(mdgb_link)
    mdgb_link.env(21.0, 60.0)
    mdgb_link.theft_alarm()
    ob, infos, events = Outbox(str(tmp_path / "o.db")), [], []
    assert C3FileSource(c3, ob).poll(infos.append, events.append) == 1
    assert infos[0]["type"] == "env" and events[0]["type"] == "tamper" and ob.backlog() == 1
    assert C3FileSource(c3, ob).poll() == 0, "read once, also after a restart"


def test_a_broken_disk_never_breaks_main_py(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    monkeypatch.setenv("MDGB_C3_DIR", str(blocker / "c3"))
    import mdgb_link
    importlib.reload(mdgb_link)
    mdgb_link.env(20.0, 50.0)                       # cannot write: printed, not raised
    assert "mdgb_link: env fallita" in capsys.readouterr().out
