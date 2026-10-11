import numpy as np
import supervision as sv

from smartcrossing.config import load_config
from smartcrossing.detector import COCO_CLASSES
from smartcrossing.tracking import Tracker

PERSON, DOG = COCO_CLASSES.index("person"), COCO_CLASSES.index("dog")


def _detection(x, class_id=PERSON, score=0.9):
    return sv.Detections(
        xyxy=np.array([[x, 100.0, x + 40.0, 200.0]], dtype=np.float32),
        confidence=np.array([score], dtype=np.float32),
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


def test_weak_boxes_keep_a_track_alive_but_do_not_vote():
    """Boxes between 0.1 and the activation threshold reach ByteTrack (model.conf 0.1): they hold the track
    through dark or half-hidden frames, but only confident boxes decide the class (and the height)."""
    cfg = load_config()
    assert cfg["model"]["conf"] <= 0.1 < cfg["tracking"]["measure_min_conf"]
    tracker = Tracker(cfg, frame_rate=10)
    ids = set()
    scores = [0.9, 0.9, 0.2, 0.15, 0.2, 0.9]              # two weak frames in the middle: same track
    classes = [PERSON, PERSON, DOG, DOG, DOG, PERSON]      # the weak boxes say "dog": they must not count
    for i, (score, class_id) in enumerate(zip(scores, classes)):
        tracked = tracker.update(_detection(100.0 + 2 * i, class_id, score), t=i / 10)
        assert len(tracked) == 1
        ids.add(int(tracked.tracker_id[0]))
    assert len(ids) == 1
    state = tracker.tracks[ids.pop()]
    assert state.class_votes[DOG] == 0 and state.class_name == "person"


def test_a_track_first_seen_on_a_weak_box_still_has_a_class(monkeypatch):
    """ByteTrack may hand over a track for the first time on a weak box (it was created one frame earlier)."""
    tracker = Tracker(load_config(), frame_rate=10)
    weak = _detection(100.0, DOG, 0.2)
    weak.tracker_id = np.array([7])
    monkeypatch.setattr(tracker._bytetrack, "update_with_detections", lambda detections: weak)
    tracked = tracker.update(weak, t=0.0)
    assert tracker.class_names(tracked) == ["dog"]


def _track_fast_object(box_buffer):
    """A 40 px wide box that moves 34 px per detector frame (a car at 5-6 detections per second).
    Returns the IDs given and the boxes of the frames in which it was tracked."""
    cfg = load_config()
    cfg["tracking"]["box_buffer"] = box_buffer
    tracker = Tracker(cfg, frame_rate=6)
    ids, boxes = set(), []
    for i in range(8):
        tracked = tracker.update(_detection(100.0 + 34 * i, score=0.5), t=i / 6)
        ids.update(int(k) for k in tracked.tracker_id)
        boxes += tracked.xyxy.tolist()
    return ids, boxes


def test_buffered_boxes_keep_the_id_of_a_fast_object_and_give_back_the_real_box():
    ids, boxes = _track_fast_object(0.3)
    assert len(ids) == 1 and len(boxes) == 8
    assert boxes[-1] == [100.0 + 34 * 7, 100.0, 140.0 + 34 * 7, 200.0]   # real size, not the enlarged one
    # Without the buffer two boxes in a row barely overlap: ByteTrack never confirms a track after the first frame.
    _, boxes = _track_fast_object(0.0)
    assert len(boxes) < 4
