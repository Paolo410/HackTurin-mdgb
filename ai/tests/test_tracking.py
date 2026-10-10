import numpy as np
import supervision as sv

from smartcrossing.config import load_config
from smartcrossing.detector import COCO_CLASSES
from smartcrossing.tracking import Tracker

PERSON, DOG = COCO_CLASSES.index("person"), COCO_CLASSES.index("dog")


def _detection(x, class_id=PERSON):
    return sv.Detections(
        xyxy=np.array([[x, 100.0, x + 40.0, 200.0]], dtype=np.float32),
        confidence=np.array([0.9], dtype=np.float32),
        class_id=np.array([class_id]),
    )


def test_moving_box_keeps_one_id_and_becomes_valid_after_min_age():
    cfg = load_config()
    tracker = Tracker(cfg, frame_rate=30)
    min_age = cfg["tracking"]["min_track_age"]
    ids = []
    for i in range(min_age + 3):
        tracked = tracker.update(_detection(100.0 + 3 * i), t=i / 30)
        assert len(tracked) == 1
        ids.append(int(tracked.tracker_id[0]))
        assert tracker.is_valid(ids[-1]) == (i + 1 >= min_age)
        assert tracker.valid_mask(tracked).tolist() == [i + 1 >= min_age]
    assert len(set(ids)) == 1
    state = tracker.tracks[ids[0]]
    assert state.age == min_age + 3
    # History holds (t, x of the bottom centre, y of the bottom edge).
    t, x, y = state.history[-1]
    assert x == 100.0 + 3 * (min_age + 2) + 20.0 and y == 200.0


def test_class_is_decided_by_majority_vote():
    tracker = Tracker(load_config(), frame_rate=30)
    classes = [PERSON, PERSON, DOG, PERSON, DOG, PERSON]
    for i, class_id in enumerate(classes):
        tracked = tracker.update(_detection(100.0, class_id), t=i / 30)
    state = tracker.tracks[int(tracked.tracker_id[0])]
    assert state.class_name == "person"


def test_empty_frame_returns_no_tracks():
    tracker = Tracker(load_config(), frame_rate=30)
    tracked = tracker.update(sv.Detections.empty(), t=0.0)
    assert len(tracked) == 0 and tracker.valid_mask(tracked).tolist() == []
