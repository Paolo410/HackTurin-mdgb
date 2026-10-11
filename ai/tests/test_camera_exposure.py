"""Exposure and gain of the board's camera, set once before it starts (the arithmetic; no camera needed)."""
import importlib.util
from pathlib import Path

import pytest

from smartcrossing.config import load_config

_SPEC = importlib.util.spec_from_file_location(
    "camera_exposure", Path(__file__).resolve().parent.parent / "scripts" / "camera_exposure.py")
camera_exposure = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(camera_exposure)

CAM = load_config(profile="unoq")["camera"]


def test_gain_code_and_factor_of_the_imx219():
    assert camera_exposure.gain_factor(0, CAM) == 1.0
    assert camera_exposure.gain_factor(128, CAM) == 2.0
    assert camera_exposure.gain_code(2.0, CAM) == 128
    assert camera_exposure.gain_code(0.5, CAM) == 0                        # never below 1x
    assert camera_exposure.gain_code(1000.0, CAM) == CAM["gain_max"]       # never above the sensor's top


def test_a_dark_picture_gets_more_gain_and_the_same_exposure():
    # Measured on the board: brightness 53 with gain 0; gain 150 gave 98.
    exposure, gain = camera_exposure.next_settings(53, 1703, 0, CAM)
    assert exposure == 1703
    assert camera_exposure.gain_factor(gain, CAM) == pytest.approx(CAM["target_brightness"] / 53, rel=0.03)


def test_exposure_moves_only_when_the_gain_cannot():
    top = camera_exposure.gain_factor(CAM["gain_max"], CAM)
    exposure, gain = camera_exposure.next_settings(5, 1703, 0, CAM)        # very dark: gain at the top, then exposure
    assert gain == CAM["gain_max"] and 1703 < exposure <= CAM["exposure_max"]
    exposure, gain = camera_exposure.next_settings(250, 1703, 0, CAM)      # too bright at 1x: shorter exposure
    assert gain == 0 and exposure == round(1703 * CAM["target_brightness"] / 250)
    exposure, gain = camera_exposure.next_settings(250, 1703, CAM["gain_max"], CAM)   # too bright with gain: less gain
    assert exposure == 1703 and 1.0 < camera_exposure.gain_factor(gain, CAM) < top


def test_nothing_changes_inside_the_band():
    low, high = CAM["brightness_band"]
    assert camera_exposure.in_band((low + high) / 2, CAM) and not camera_exposure.in_band(low - 1, CAM)
    assert low < CAM["target_brightness"] < high


def test_without_the_sensor_it_says_so_and_does_not_stop_the_vision(capsys, monkeypatch):
    monkeypatch.setattr(camera_exposure, "find_sensor", lambda name: None)
    assert camera_exposure.main([]) == 0
    assert "esposizione lasciata com'è" in capsys.readouterr().out


def test_the_tuning_file_has_no_automatic_exposure():
    text = (camera_exposure.TUNING_DIR / "simple" / "imx219.yaml").read_text()
    algorithms = [line.strip() for line in text.splitlines() if line.strip().startswith("- ")]
    assert algorithms == ["- BlackLevel:", "- Awb:", "- Lut:"]
