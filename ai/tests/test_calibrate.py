import importlib.util
from pathlib import Path

import numpy as np

from smartcrossing.config import load_config

_SPEC = importlib.util.spec_from_file_location(
    "calibrate", Path(__file__).resolve().parent.parent / "scripts" / "calibrate.py")
calibrate = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(calibrate)

W, H = 641, 481


def test_build_lines_normalizes_the_clicked_points():
    points = [(320, 0), (320, 480), (0, 240), (640, 240)]
    assert calibrate.build_lines(points, W, H) == {
        "ped": {"start": [0.5, 0.0], "end": [0.5, 1.0]},
        "veh": {"start": [0.0, 0.5], "end": [1.0, 0.5]},
    }


def test_incomplete_line_is_left_out():
    assert list(calibrate.build_lines([(320, 0), (320, 480), (0, 240)], W, H)) == ["ped"]
    assert calibrate.build_lines([(320, 0)], W, H) == {}


def test_invert_swaps_the_last_complete_line():
    points = [(320, 0), (320, 480), (0, 240)]
    calibrate.invert_last_line(points)
    assert points == [(320, 480), (320, 0), (0, 240)]
    points.append((640, 240))
    calibrate.invert_last_line(points)
    assert points == [(320, 480), (320, 0), (640, 240), (0, 240)]


def test_draw_handles_every_number_of_points():
    cfg = load_config()
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    points = [(320, 0), (320, 480), (0, 240), (640, 240)]
    for n in range(len(points) + 1):
        view = calibrate.draw(frame, points[:n], cfg)
        assert view.shape == frame.shape
    assert not frame.any()   # the original frame is not modified
