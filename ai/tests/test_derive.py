import numpy as np
import supervision as sv

from smartcrossing.config import load_config
from smartcrossing.derive import derive_roles, iou_matrix
from smartcrossing.detector import COCO_CLASSES
from smartcrossing.tracking import Tracker

CFG = load_config()
# A rider (tall box) on a two-wheeler (wide box under it): IoU about 0.34, rider's centre above.
RIDER = [100, 50, 160, 200]
WHEELS = [90, 120, 190, 220]


def test_iou_matrix():
    a = np.array([[0, 0, 10, 10]], dtype=np.float32)
    b = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]], dtype=np.float32)
    assert iou_matrix(a, b)[0].tolist() == [1.0, np.float32(50 / 150), 0.0]
    assert iou_matrix(a, np.zeros((0, 4), np.float32)).shape == (1, 0)


def test_rider_fixture_is_above_the_iou_threshold():
    iou = iou_matrix(np.array([RIDER], np.float32), np.array([WHEELS], np.float32))[0, 0]
    assert iou > CFG["derive"]["rider_iou"]


def test_person_on_bicycle_is_a_cyclist_and_the_bicycle_is_ridden():
    roles = derive_roles(np.array([RIDER, WHEELS], dtype=np.float32), ["person", "bicycle"], CFG)
    assert roles == ["cyclist", "ridden"]


def test_person_on_motorcycle_is_a_motorcyclist():
    roles = derive_roles(np.array([WHEELS, RIDER], dtype=np.float32), ["motorcycle", "person"], CFG)
    assert roles == ["ridden", "motorcyclist"]


def test_person_far_from_the_bicycle_stays_a_pedestrian():
    far = [300, 50, 360, 200]
    roles = derive_roles(np.array([far, WHEELS], dtype=np.float32), ["person", "bicycle"], CFG)
    assert roles == ["pedestrian", "bicycle"]


def test_person_below_the_bicycle_is_not_its_rider():
    # Enough overlap, but the person's box is lower than the bicycle's (e.g. a bike on a rack behind).
    person = [100, 130, 160, 250]
    wheels = [90, 120, 190, 220]
    assert iou_matrix(np.array([person], np.float32), np.array([wheels], np.float32))[0, 0] > CFG["derive"]["rider_iou"]
    roles = derive_roles(np.array([person, wheels], dtype=np.float32), ["person", "bicycle"], CFG)
    assert roles == ["pedestrian", "bicycle"]


def test_one_rider_per_two_wheeler():
    passenger = [105, 55, 165, 205]
    roles = derive_roles(np.array([RIDER, passenger, WHEELS], dtype=np.float32),
                         ["person", "person", "bicycle"], CFG)
    assert sorted(roles) == ["cyclist", "pedestrian", "ridden"]


def test_animals_birds_and_vehicles():
    boxes = np.zeros((5, 4), dtype=np.float32)
    roles = derive_roles(boxes, ["dog", "bear", "bird", "car", "truck"], CFG)
    assert roles == ["animal", "animal", "bird", "car", "truck"]


def test_track_role_is_the_majority_of_its_frames():
    tracker = Tracker(CFG, frame_rate=30)
    person = COCO_CLASSES.index("person")
    frame_roles = ["pedestrian", "cyclist", "cyclist", "pedestrian", "cyclist"]
    for i, role in enumerate(frame_roles):
        tracked = tracker.update(sv.Detections(
            xyxy=np.array([RIDER], dtype=np.float32) + 2 * i,
            confidence=np.array([0.9], dtype=np.float32),
            class_id=np.array([person]),
        ), t=i / 30)
        voted = tracker.vote_roles(tracked, [role])
    assert voted == ["cyclist"]
    assert tracker.class_names(tracked) == ["person"]
