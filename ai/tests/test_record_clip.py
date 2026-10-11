"""The clip recorder (development tool): it writes a clip and reports the dark frames, with a video as the camera."""
import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np

_SPEC = importlib.util.spec_from_file_location(
    "record_clip", Path(__file__).resolve().parent.parent / "scripts" / "record_clip.py")
record_clip = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(record_clip)


def test_dark_runs_groups_consecutive_dark_frames():
    levels = [100, 101, 1, 2, 99, 30, 100, 0.5]
    times = [i / 10 for i in range(len(levels))]
    runs, usual = record_clip.dark_runs(levels, times, dark_ratio=0.35)
    assert usual > 90                                   # half of the frames are dark: the good level still holds
    assert [(r["first_frame"], r["frames"], r["darkest"]) for r in runs] == [(2, 2, 1), (5, 1, 30), (7, 1, 0.5)]
    assert runs[0]["t_s"] == 0.2
    assert record_clip.dark_runs([], [], 0.35) == ([], 0.0)
    assert record_clip.dark_runs([100, 98, 102], [0, 1, 2], 0.35)[0] == []      # a steady clip has none


def test_records_a_clip_and_reports_its_dark_frames(tmp_path, capsys):
    source = str(tmp_path / "camera.avi")       # a recorded "camera": grey frames, three of them black
    writer = cv2.VideoWriter(source, cv2.VideoWriter_fourcc(*"MJPG"), 50.0, (160, 120))
    rng = np.random.default_rng(0)
    for i in range(60):
        level = 0 if i in (30, 31, 45) else 120
        writer.write(np.clip(rng.normal(level, 4, (120, 160, 3)), 0, 255).astype(np.uint8))
    writer.release()

    out = tmp_path / "clips"
    code = record_clip.main(["--source", source, "--seconds", "1.2", "--fps", "50", "--name", "prova",
                             "--out", str(out), "--settle-s", "0.2"])
    assert code == 0
    report = json.loads((out / "prova.json").read_text())
    assert (out / "prova.mp4").stat().st_size > 0
    assert report["frames"] > 20 and report["size"] == [160, 120]
    assert report["dark_frames"] == 3 and [r["frames"] for r in report["dark_runs"]] == [2, 1]
    assert report["brightness"]["usual"] > 100
    assert "fotogrammi scuri: 3" in capsys.readouterr().out
    recorded = cv2.VideoCapture(str(out / "prova.mp4"))
    assert int(recorded.get(cv2.CAP_PROP_FRAME_COUNT)) == report["frames"]
    recorded.release()


def test_a_busy_camera_is_said_clearly(tmp_path, capsys):
    assert record_clip.main(["--source", str(tmp_path / "missing.avi"), "--out", str(tmp_path)]) == 2
    assert "Camera non aperta" in capsys.readouterr().err
