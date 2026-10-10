"""Geometry in metres, speed, attributes, and the whole chain on scripted scenes (no camera, no model)."""
import numpy as np
import pytest

from smartcrossing.actuator import Commander, SimActuator, make_actuator
from smartcrossing.attributes import AidClassifier, AttributeEstimator, public_attrs
from smartcrossing.config import load_config
from smartcrossing.geometry import (
    Geometry, apply_homography, build_metric_calib, find_homography, point_in_polygon,
)
from smartcrossing.sim import (
    virtual_camera_config,
    DEMO_ALONG_M, DEMO_CORNERS, DEMO_WIDTH_M, FRAME_SIZE, Actor, demo_calib, detections_at, drive,
    run_scenario, walk_then_wait,
)
from smartcrossing.sources import frame_fault
from smartcrossing.tracking import Tracker

CFG = virtual_camera_config(load_config())   # scripted actors may be outside the image


def geometry():
    g = Geometry(demo_calib(CFG), CFG)
    g.set_frame_size(*FRAME_SIZE)
    return g


# ---------------------------------------------------------------- geometry

def test_homography_maps_the_four_corners_exactly():
    ground = [[0, 0], [4, 0], [4, 7], [0, 7]]
    h = find_homography(DEMO_CORNERS, ground)
    for corner, expected in zip(DEMO_CORNERS, ground):
        assert apply_homography(h, *corner) == pytest.approx(expected, abs=1e-9)


def test_pixel_to_metres_round_trip_and_known_points():
    g = geometry()
    w, h = FRAME_SIZE
    # Near-left corner of the stripes = origin; far-right corner = (along, W).
    assert g.to_ground(0.40 * (w - 1), 0.80 * (h - 1)) == pytest.approx((0.0, 0.0), abs=1e-6)
    assert g.to_ground(0.57 * (w - 1), 0.50 * (h - 1)) == pytest.approx((DEMO_ALONG_M, DEMO_WIDTH_M), abs=1e-6)
    for point in [(2.0, 3.5), (-12.0, 1.0), (30.0, 6.0), (1.0, -1.2)]:
        assert g.to_ground(*g.to_image(*point)) == pytest.approx(point, abs=1e-6)


def test_zones_and_lines_are_derived_from_the_corners():
    calib = demo_calib(CFG)
    g = geometry()
    assert calib["W"] == DEMO_WIDTH_M and calib["along"] == DEMO_ALONG_M
    assert g.zone_of(2.0, 3.5) == "crosswalk"
    assert g.zone_of(2.0, -0.7) == "waiting_zone_left"
    assert g.zone_of(2.0, 7.5) == "waiting_zone_right"
    assert g.zone_of(-30.0, 2.0) == "carriageway"
    assert g.zone_of(2.0, -5.0) is None and g.zone_of(2.0, 12.0) is None
    assert set(calib["lines"]) == {"ped", "veh"}
    # The pedestrian line runs in the middle of the road: both ends map back to y = W / 2.
    h = np.array(calib["homography"])
    for end in ("start", "end"):
        assert apply_homography(h, *calib["lines"]["ped"][end])[1] == pytest.approx(DEMO_WIDTH_M / 2, abs=0.05)


def test_point_in_polygon():
    square = [[0, 0], [2, 0], [2, 2], [0, 2]]
    assert point_in_polygon(1, 1, square) and not point_in_polygon(3, 1, square)
    assert not point_in_polygon(1, -0.1, square)


def test_sizes_in_metres_from_box_and_foot_point():
    g = geometry()
    for position in [(2.0, -0.7), (2.0, 6.0), (-8.0, 3.0)]:
        fx, fy = g.to_image(*position)
        scale = g.pixels_per_metre(fx, fy)
        assert g.size_in_metres(1.7 * scale, fx, fy) == pytest.approx(1.7, rel=1e-6)
    # Farther away the same metre covers fewer pixels.
    near, far = g.to_image(2.0, 0.5), g.to_image(2.0, 6.5)
    assert g.pixels_per_metre(*near) > g.pixels_per_metre(*far)


def test_build_metric_calib_rejects_bad_sizes():
    with pytest.raises(ValueError):
        build_metric_calib(DEMO_CORNERS, 0, 7, CFG)


# ---------------------------------------------------------------- speed and attributes

def track_one(actor, seconds, fps=10.0):
    g = geometry()
    tracker = Tracker(CFG, frame_rate=fps)
    estimator = AttributeEstimator(CFG)
    state = None
    for i in range(int(seconds * fps) + 1):
        t = i / fps
        tracked = tracker.update(detections_at([actor], t, g), t, g)
        if len(tracked):
            state = tracker.tracks[int(tracked.tracker_id[0])]
            estimator.update(state, 1 / fps)
    return state


def test_speed_of_a_car_at_50_kmh():
    state = track_one(Actor("car", 1.5, 4.4, drive(-40.0, 1.75, 50 / 3.6)), seconds=3)
    assert state.speed == pytest.approx(13.9, rel=0.02)
    assert state.velocity[0] == pytest.approx(13.9, rel=0.02) and abs(state.velocity[1]) < 0.1
    assert abs(state.accel) < 0.5
    assert state.length_m == pytest.approx(4.4, rel=0.01)


def test_braking_car_has_negative_acceleration():
    def braking(t):   # from 14 m/s, -4 m/s^2
        return -40.0 + 14.0 * t - 2.0 * t * t, 1.75
    state = track_one(Actor("car", 1.5, 4.4, braking), seconds=2.5)
    assert state.accel == pytest.approx(-4.0, abs=0.6)


def test_child_is_decided_from_the_height():
    child = track_one(Actor("person", 1.10, 0.4, walk_then_wait((0.0, -0.7), (3.0, -0.7), 1.0)), seconds=2)
    adult = track_one(Actor("person", 1.75, 0.5, walk_then_wait((0.0, -0.7), (3.0, -0.7), 1.0)), seconds=2)
    assert child.attrs["child"] is True and adult.attrs["child"] is False


def test_slow_needs_two_seconds_of_walking_and_ignores_standing():
    slow = track_one(Actor("person", 1.65, 0.5, walk_then_wait((-0.8, -0.7), (3.0, -0.7), 0.8)), seconds=4)
    assert slow.attrs["slow"] is True and slow.attrs["walk_speed"] == pytest.approx(0.8, abs=0.05)
    brisk = track_one(Actor("person", 1.75, 0.5, walk_then_wait((-0.8, -0.7), (4.5, -0.7), 1.5)), seconds=4)
    assert brisk.attrs["slow"] is False
    standing = track_one(Actor("person", 1.75, 0.5, lambda t: (2.0, -0.7)), seconds=5)
    assert standing.attrs["slow"] is None and standing.attrs["walk_speed"] is None
    just_arrived = track_one(Actor("person", 1.65, 0.5, walk_then_wait((-0.8, -0.7), (3.0, -0.7), 0.8)), seconds=1.5)
    assert just_arrived.attrs["slow"] is None      # not enough walking yet


def test_aid_is_none_without_the_optional_model():
    assert AidClassifier.load(CFG) is None
    state = track_one(Actor("person", 1.75, 0.5, lambda t: (2.0, -0.7)), seconds=1)
    assert public_attrs(state.attrs) == {"child": False, "slow": None, "aid": None}


def test_aid_classifier_votes_on_crops(tmp_path):
    onnx = pytest.importorskip("onnx")
    from onnx import TensorProto, helper
    # A tiny stand-in model: the score of class k is the mean of channel k (class 3 gets a constant 0).
    weights = np.zeros((4, 3), dtype=np.float32)
    weights[0, 0] = weights[1, 1] = weights[2, 2] = 1.0
    graph = helper.make_graph(
        [helper.make_node("GlobalAveragePool", ["x"], ["pooled"]),
         helper.make_node("Flatten", ["pooled"], ["flat"]),
         helper.make_node("Gemm", ["flat", "w"], ["scores"], transB=1)],
        "aid", [helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 96, 96])],
        [helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 4])],
        [helper.make_tensor("w", TensorProto.FLOAT, [4, 3], weights.flatten())])
    path = tmp_path / "aid_cls.onnx"
    onnx.save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)], ir_version=8), str(path))

    cfg = load_config()
    cfg["attributes"]["aid_model_path"] = str(path)
    classifier = AidClassifier.load(cfg)
    green = np.zeros((200, 80, 3), dtype=np.uint8)
    green[..., 1] = 255                                    # channel 1 -> class "wheelchair"
    assert classifier.classify(green) == "wheelchair"

    estimator = AttributeEstimator(cfg, classifier)
    g = geometry()
    tracker = Tracker(cfg, frame_rate=10)
    frame = np.zeros((FRAME_SIZE[1], FRAME_SIZE[0], 3), dtype=np.uint8)
    frame[..., 1] = 255
    actor = Actor("person", 1.4, 0.7, lambda t: (2.0, -0.7))
    for i in range(40):
        tracked = tracker.update(detections_at([actor], i / 10, g), i / 10, g)
        state = tracker.tracks[int(tracked.tracker_id[0])]
        estimator.update(state, 0.1, frame, tracked.xyxy[0])
    assert state.attrs["aid"] == "wheelchair"


# ---------------------------------------------------------------- camera self-check

def test_frame_fault_detects_covered_lens_and_glare():
    rng = np.random.default_rng(0)
    textured = rng.integers(0, 200, (240, 320, 3), dtype=np.uint8)
    assert frame_fault(textured, CFG) is None
    assert frame_fault(np.full((240, 320, 3), 12, dtype=np.uint8), CFG) == "lens_covered"
    assert frame_fault(np.full((240, 320, 3), 255, dtype=np.uint8), CFG) == "glare"


# ---------------------------------------------------------------- actuator and heartbeat

class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_commander_sends_on_change_and_repeats_every_second():
    clock = Clock()
    sim = SimActuator(monotonic=clock)
    commander = Commander(sim, CFG, wall_clock=lambda: 1739012345.678, monotonic=clock)
    fields = {"state": "IDLE", "led": "OFF"}
    assert commander.update(fields) is True
    assert sim.last_cmd == {"v": 1, "seq": 1, "t_ms": 1739012345678, "state": "IDLE", "led": "OFF"}
    clock.t += 0.3
    assert commander.update(dict(fields)) is False                      # unchanged and recent
    assert commander.update({"state": "PRESENCE", "led": "WHITE_ON"}) is True
    clock.t += CFG["actuator"]["c1_repeat_s"] + 0.01
    assert commander.update({"state": "PRESENCE", "led": "WHITE_ON"}) is True   # repeated: a lost line heals
    assert [c["seq"] for c in sim.sent] == [1, 2, 3]
    # Only the wording of the reason changes: no new line until the next repeat.
    assert commander.update({"state": "PRESENCE", "led": "WHITE_ON", "reason": "pedone in attesa"}) is False
    clock.t += CFG["actuator"]["c1_repeat_s"] + 0.01
    assert commander.update({"state": "PRESENCE", "led": "WHITE_ON", "reason": "bambino in attesa"}) is True
    assert sim.last_cmd["reason"] == "bambino in attesa"


def test_heartbeat_stops_when_the_vision_loop_is_stuck():
    clock = Clock()
    sim = SimActuator(failsafe_timeout_s=0.5, monotonic=clock)
    commander = Commander(sim, CFG, monotonic=clock)
    assert sim.failsafe is True                       # nothing received yet
    commander.alive()
    assert commander.beat() is True and sim.heartbeats == 1 and sim.failsafe is False
    clock.t += 0.3
    assert commander.beat() is True                   # the loop was alive 0.3 s ago
    clock.t += 0.2                                    # 0.5 s without alive(): the loop is stuck
    assert commander.beat() is False and sim.heartbeats == 2
    clock.t += 0.5
    assert sim.failsafe is True                       # the firmware would fall back by itself
    commander.alive()
    assert commander.beat() is True and sim.failsafe is False
    assert sim.last_hb_seq == commander.seq


def test_heartbeat_thread_runs_and_stops():
    import time
    sim = SimActuator()
    commander = Commander(sim, CFG)
    commander.start()
    deadline = time.monotonic() + 2.0
    while sim.heartbeats < 3 and time.monotonic() < deadline:
        commander.alive()
        time.sleep(0.02)
    commander.close()
    assert sim.heartbeats >= 3


def test_make_actuator():
    assert isinstance(make_actuator("sim", CFG), SimActuator)


# ---------------------------------------------------------------- whole chain on scripted scenes

def test_scenario_elderly_and_fast_car_warns_driver_then_pedestrian():
    sim = SimActuator()
    timeline = []
    pipeline = run_scenario(CFG, "elderly_fast_car", fps=10, actuator=sim,
                            on_step=lambda t, cmd, p: timeline.append((t, cmd["state"], cmd["reason"])))
    states = [s for _, s, _ in timeline]
    order = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
    assert order == ["IDLE", "PRESENCE", "WARN_DRIVER", "WARN_PEDESTRIAN", "PRESENCE"]

    warn_driver = next(reason for _, s, reason in timeline if s == "WARN_DRIVER")
    assert warn_driver.startswith("pedone lento 0.8 m/s; car 5") and "TTC" in warn_driver and "T_need 9.8 s" in warn_driver
    # The pedestrian warning starts when the car is within d_stop + 10 m = 37.7 m of the stripes.
    first_wp = next(t for t, s, _ in timeline if s == "WARN_PEDESTRIAN")
    car_x = -110.0 + (50 / 3.6) * (first_wp - 4.0)
    step = (50 / 3.6) / 10                        # the car moves 1.39 m per frame at 10 FPS
    assert -37.7 - 0.5 <= car_x <= -37.7 + step + 0.1

    # Every command went through the actuator as a full C1 line, in order.
    assert [c["seq"] for c in sim.sent] == sorted(c["seq"] for c in sim.sent)
    assert {c["state"] for c in sim.sent} >= {"PRESENCE", "WARN_DRIVER", "WARN_PEDESTRIAN"}
    assert all({"v", "seq", "t_ms", "state", "led", "green_s", "req", "lcd", "oled", "reason"} == set(c) for c in sim.sent)
    assert pipeline.counter.totals("veh") in ({"in": 1, "out": 0}, {"in": 0, "out": 1})


def test_scenario_pedestrian_crossing_counts_one_and_holds_the_red():
    sim = SimActuator()
    timeline = []
    pipeline = run_scenario(CFG, "pedestrian_crossing", fps=10, actuator=sim,
                            on_step=lambda t, cmd, p: timeline.append((t, cmd)))
    ped = pipeline.counter.totals("ped")
    assert ped["in"] + ped["out"] == 1
    on_stripes = [cmd for t, cmd in timeline if 3.5 <= t <= 6.5]
    assert all(cmd["state"] == "PRESENCE" and cmd["req"]["veh_red_hold"] for cmd in on_stripes)
    assert timeline[-1][1]["state"] == "IDLE"
