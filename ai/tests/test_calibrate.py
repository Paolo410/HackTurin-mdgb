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


def test_metric_calibration_from_four_clicked_corners():
    cfg = load_config()
    points = [(256, 384), (384, 384), (365, 240), (275, 240)]   # near kerb, then far kerb going around
    calib = calibrate.metric_from_points(points, W, H, along=4.0, road=7.0, cfg=cfg)
    assert calib["W"] == 7.0 and calib["along"] == 4.0
    assert set(calib["zones"]) == {"crosswalk", "carriageway", "waiting_zone_left", "waiting_zone_right"}
    assert set(calib["lines"]) == {"ped", "veh"}
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    view = calibrate.draw(frame, points, cfg, calib, lines_only=False)
    assert view.any() and not frame.any()
    for n in range(len(points) + 1):                            # while clicking, before the sizes are known
        assert calibrate.draw(frame, points[:n], cfg, None, lines_only=False).shape == frame.shape


def test_lines_only_save_keeps_the_metric_part(tmp_path):
    import json
    cfg = load_config()
    out = tmp_path / "calib.json"
    points = [(256, 384), (384, 384), (365, 240), (275, 240)]
    calibrate.write_calib(out, calibrate.metric_from_points(points, W, H, 4.0, 7.0, cfg), replace_all=True)
    new_lines = calibrate.build_lines([(320, 0), (320, 480), (0, 240), (640, 240)], W, H)
    calibrate.write_calib(out, {"lines": new_lines}, replace_all=False)
    saved = json.loads(out.read_text())
    assert saved["lines"] == new_lines and saved["W"] == 7.0 and "homography" in saved
