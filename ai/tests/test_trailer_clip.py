"""Clip of what the camera sees for the trailer (scripts/trailer_clip.py): the words of a label and where it goes."""
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import trailer_clip  # noqa: E402


def track(speed_kmh=0.0, samples=1, **attrs):
    return SimpleNamespace(speed=speed_kmh / trailer_clip.KMH, speed_samples=samples, attrs=attrs)


def test_label_says_kind_speed_and_what_matters_for_the_rule():
    assert trailer_clip.label_text("car", track(31.6)) == "car  32 km/h"
    assert trailer_clip.label_text("pedestrian", track(3.0, slow=True, child=False)) == "pedestrian  3 km/h  slow"
    assert trailer_clip.label_text("pedestrian", track(4.0, aid="wheelchair")) == "pedestrian  4 km/h  wheelchair"
    assert trailer_clip.label_text("pedestrian", track(4.0, aid="normal")) == "pedestrian  4 km/h"


def test_label_has_no_speed_when_still_or_not_measured():
    assert trailer_clip.label_text("car", track(0.4)) == "car"                 # standing at the red light
    assert trailer_clip.label_text("car", track(30.0, samples=0)) == "car"      # no metric calibration
    assert trailer_clip.label_text("dog", None) == "dog"


def test_label_stays_inside_the_frame():
    labels = trailer_clip.Labels(20)
    green = (80, 200, 80)
    for x, bottom in ((-50, 5), (10_000, 10_000), (30, 60)):
        frame = np.zeros((120, 160, 3), np.uint8)
        labels.paste(frame, "car", green, x, bottom)
        painted = np.argwhere(frame.any(axis=2))
        assert len(painted) and painted.min() >= 0 and painted[:, 0].max() < 120 and painted[:, 1].max() < 160
    assert list(labels.cache) == [("car", green)]                               # drawn once, pasted three times
