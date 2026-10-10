"""What real video taught us: boxes jitter, IDs jump, and one odd frame is not a fault."""
import numpy as np
import pytest
import supervision as sv

from smartcrossing.config import load_config
from smartcrossing.detector import COCO_CLASSES
from smartcrossing.geometry import Geometry
from smartcrossing.pipeline import Pipeline
from smartcrossing.sim import virtual_camera_config, FRAME_SIZE, Actor, demo_calib, detections_at, drive, run_actors
from smartcrossing.sources import frame_fault
from smartcrossing.tracking import Tracker

CFG = virtual_camera_config(load_config())   # scripted actors may be outside the image


def geometry():
    g = Geometry(demo_calib(CFG), CFG)
    g.set_frame_size(*FRAME_SIZE)
    return g


def jittered(detections: sv.Detections, rng, pixels: float) -> sv.Detections:
    noise = rng.uniform(-pixels, pixels, detections.xyxy.shape).astype(np.float32)
    return sv.Detections(xyxy=detections.xyxy + noise, confidence=detections.confidence, class_id=detections.class_id)


def test_standing_car_with_jittering_box_is_not_moving():
    # A car standing 12 m before the stripes, box edges moving by up to 2 px at 30 frames per second.
    g, rng = geometry(), np.random.default_rng(1)
    tracker = Tracker(CFG, frame_rate=30)
    car = Actor("car", 1.5, 4.4, lambda t: (-12.0, 1.75))
    speeds = []
    for i in range(120):
        tracked = tracker.update(jittered(detections_at([car], i / 30, g), rng, 2.0), i / 30, g)
        state = tracker.tracks[int(tracked.tracker_id[0])]
        if state.speed_samples > 5:
            speeds.append(state.speed)
    assert np.median(speeds) < 0.3 and max(speeds) < CFG["rules"]["vehicle_min_speed_ms"]


def test_moving_car_keeps_its_speed_with_jitter_and_any_frame_rate():
    g = geometry()
    for fps in (10, 30):
        rng = np.random.default_rng(2)
        tracker = Tracker(CFG, frame_rate=fps)
        car = Actor("car", 1.5, 4.4, drive(-40.0, 1.75, 13.9))
        for i in range(int(2.5 * fps)):
            tracked = tracker.update(jittered(detections_at([car], i / fps, g), rng, 2.0), i / fps, g)
        state = tracker.tracks[int(tracked.tracker_id[0])]
        assert state.speed == pytest.approx(13.9, rel=0.08), fps


def test_new_track_at_speed_is_not_a_hard_brake():
    # A car already at 110 km/h when it enters the view, box jittering: the first speed estimates wobble.
    rng = np.random.default_rng(6)
    pipeline = Pipeline(CFG, frame_rate=30, calib=demo_calib(CFG), load_detector=False)
    car = Actor("car", 1.5, 4.4, drive(-70.0, 1.75, 30.5))
    events = []
    for i in range(60):
        result = pipeline.process(jittered(detections_at([car], i / 30, geometry()), rng, 3.0), i / 30, FRAME_SIZE)
        events += result.events
    assert [e for e in events if e.get("kind") == "hard_brake"] == []


def test_id_jumping_to_another_object_does_not_become_a_speed():
    g = geometry()
    tracker = Tracker(CFG, frame_rate=10)
    person = COCO_CLASSES.index("person")

    def box_at(x, y):
        fx, fy = g.to_image(x, y)
        return np.array([[fx - 15, fy - 80, fx + 15, fy]], dtype=np.float32)
    state = None
    for i in range(10):
        tracked = tracker.update(sv.Detections(xyxy=box_at(2.0, 3.0), confidence=np.array([0.9], np.float32),
                                               class_id=np.array([person])), i / 10, g)
        state = tracker.tracks[int(tracked.tracker_id[0])]
    # Same track, suddenly 40 m away (as if the ID had moved to somebody else).
    state_before = state.speed
    tracker._update_metric(state, box_at(42.0, 3.0)[0], g.to_image(42.0, 3.0), 1.0, g)
    assert state_before < 0.2 and state.speed == 0.0 and state.speed_samples == 0
    assert len(state.ground_history) == 1          # the past of the other object is forgotten


def test_standing_cars_do_not_produce_yield_events_or_warnings():
    waiting = Actor("person", 1.75, 0.5, lambda t: (2.0, -0.7))
    queue = [Actor("car", 1.5, 4.4, lambda t, x=x: (x, 1.75)) for x in (-8.0, -15.0)]
    rng = np.random.default_rng(3)
    pipeline = Pipeline(CFG, frame_rate=30, calib=demo_calib(CFG), load_detector=False)
    states, events = set(), []
    for i in range(300):
        result = pipeline.process(jittered(detections_at([waiting] + queue, i / 30, pipeline.geometry or geometry(), ), rng, 2.0),
                                  i / 30, FRAME_SIZE)
        states.add(result.command["state"])
        events += result.events
    assert states <= {"IDLE", "PRESENCE"}
    assert [e for e in events if e["type"] in ("yield", "near_miss", "incident")] == []


def test_one_yield_event_per_vehicle_even_if_it_lingers_on_the_stripes():
    waiting = Actor("person", 1.75, 0.5, lambda t: (2.0, -0.7))
    car = Actor("car", 1.5, 4.4, lambda t: (min(-30.0 + 6.0 * t, 2.0), 1.75))     # arrives and stops on the stripes
    events = []
    run_actors(CFG, [waiting, car], 14, on_step=lambda t, r, p: events.extend(r.events))
    assert [e["yielded"] for e in events if e["type"] == "yield"] == [False]


def test_camera_self_check_thresholds_follow_the_measured_scenes():
    # Smooth tarmac with little texture (variance about 17 on the test videos) is a normal scene.
    rng = np.random.default_rng(4)
    tarmac = np.clip(rng.normal(128, 2.2, (540, 960)), 0, 255).astype(np.uint8)
    tarmac = np.dstack([tarmac] * 3)
    assert frame_fault(tarmac, CFG) is None
    assert frame_fault(np.full((540, 960, 3), 40, dtype=np.uint8), CFG) == "lens_covered"


def test_a_fault_needs_to_be_confirmed_by_the_next_checks():
    cfg = load_config()
    cfg["selfcheck"]["every_n_frames"] = 1
    pipeline = Pipeline(cfg, frame_rate=10, calib=demo_calib(cfg), load_detector=False)

    class NoDetector:
        def detect(self, frame):
            return sv.Detections.empty()
    pipeline.detector = NoDetector()
    rng = np.random.default_rng(5)
    good = rng.integers(0, 200, (240, 320, 3), dtype=np.uint8)
    covered = np.full((240, 320, 3), 12, dtype=np.uint8)
    states = [pipeline.step(frame, i / 10).command["state"] for i, frame in enumerate([good, covered, good, covered, covered, covered, good])]
    assert states[1] == "IDLE"                       # one dark frame alone is ignored
    assert states[4] == "DEGRADED" and states[5] == "DEGRADED"
    assert pipeline.fault is None                    # the good frame at the end clears the fault


def _track_with_boxes(cfg, boxes_at, steps=20, fps=10):
    g = Geometry(demo_calib(cfg), cfg)
    g.set_frame_size(*FRAME_SIZE)
    tracker = Tracker(cfg, frame_rate=fps)
    car = COCO_CLASSES.index("car")
    state = None
    for i in range(steps):
        tracked = tracker.update(sv.Detections(xyxy=np.array([boxes_at(i)], dtype=np.float32),
                                               confidence=np.array([0.9], np.float32), class_id=np.array([car])), i / fps, g)
        state = tracker.tracks[int(tracked.tracker_id[0])]
    return state, g


def test_no_speed_for_a_box_cut_by_the_image_border():
    cfg = load_config()                       # a real camera: the image has borders
    width, height = FRAME_SIZE
    # A car leaving through the bottom: its box grows but its lower edge is stuck on the border.
    leaving, _ = _track_with_boxes(cfg, lambda i: [500 + 4 * i, 500 - 6 * i, 700 + 4 * i, height - 1])
    assert leaving.speed_samples == 0 and leaving.speed == 0.0 and leaving.ground is not None
    # The same box fully inside the image is measured.
    inside, _ = _track_with_boxes(cfg, lambda i: [500 + 4 * i, 400, 700 + 4 * i, 600])
    assert inside.speed_samples > 0 and inside.speed > 0.1


def test_no_speed_where_the_calibration_is_too_coarse():
    cfg = load_config()
    g = Geometry(demo_calib(cfg), cfg)
    g.set_frame_size(*FRAME_SIZE)
    # Farther from the camera one pixel covers more ground.
    near_y, far_y = 0.80 * (FRAME_SIZE[1] - 1), 0.40 * (FRAME_SIZE[1] - 1)
    near_res, far_res = g.metres_per_pixel(640, near_y), g.metres_per_pixel(640, far_y)
    assert near_res < far_res
    cfg["kinematics"]["max_metres_per_px"] = (near_res + far_res) / 2    # a limit between the two
    far, _ = _track_with_boxes(cfg, lambda i: [600 + 2 * i, far_y - 30, 660 + 2 * i, far_y])
    assert far.speed_samples == 0 and far.ground is not None
    near, _ = _track_with_boxes(cfg, lambda i: [600 + 2 * i, near_y - 60, 660 + 2 * i, near_y])
    assert near.speed_samples > 0


def test_standing_pedestrian_with_jittering_box_is_not_slow():
    from smartcrossing.attributes import AttributeEstimator
    g, rng = geometry(), np.random.default_rng(7)
    tracker = Tracker(CFG, frame_rate=30)
    estimator = AttributeEstimator(CFG)
    person = Actor("person", 1.75, 0.5, lambda t: (2.0, -0.7))        # waiting at the kerb for 10 s
    for i in range(300):
        tracked = tracker.update(jittered(detections_at([person], i / 30, g), rng, 2.0), i / 30, g)
        state = tracker.tracks[int(tracked.tracker_id[0])]
        estimator.update(state, 1 / 30)
    assert state.attrs["slow"] is None and state.attrs["walk_speed"] is None
