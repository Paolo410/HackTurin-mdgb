"""Thermal camera (MLX90621, 16x4) and its fusion with the RGB camera (spec §6 and §8)."""
import numpy as np
import pytest

from smartcrossing.config import load_config
from smartcrossing.rules import PedestrianInfo, RuleEngine, Scene, pedestrian_speed
from smartcrossing.sim import run_scenario
from smartcrossing.thermal import (
    McuThermalSource, SimThermalSource, ThermalFusion, load_thermal_calib, make_thermal_source, warm_columns,
)

CFG = load_config()
DARK, BRIGHT = 10.0, 120.0


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def fusion_with(columns_at, **kwargs):
    """A fusion fed by a scripted sensor. columns_at(t) -> warm columns."""
    clock = Clock()
    source = SimThermalSource(CFG, script=columns_at, clock=clock)
    return ThermalFusion(CFG, source, **kwargs), clock


def step(fusion, clock, t, luminance, pedestrians=()):
    clock.t = t
    return fusion.update(Scene(W=7.0, pedestrians=list(pedestrians)), t, luminance)


def make_night(fusion, clock):
    """Dark for longer than the delay: night mode. Returns the time reached."""
    for i in range(int(CFG["thermal"]["night_after_s"] * 10) + 2):
        step(fusion, clock, i / 10, DARK)
    assert fusion.night
    return clock.t


def test_example_calibration_covers_the_16_columns_once():
    zones = load_thermal_calib(CFG)["zones"]
    columns = [c for cols in zones.values() for c in cols]
    assert sorted(columns) == list(range(16))
    assert set(zones) == {"waiting_zone_left", "crosswalk", "waiting_zone_right"}


def test_a_column_is_warm_above_ambient_plus_three_degrees():
    frame = np.full((4, 16), 14.0, dtype=np.float32)
    frame[2, 5] = 17.5      # +3.5: warm
    frame[1, 9] = 16.5      # +2.5: not enough
    warm, ambient = warm_columns(frame, 3.0)
    assert ambient == 14.0 and np.flatnonzero(warm).tolist() == [5]


def test_night_mode_needs_five_dark_seconds_and_five_bright_to_leave():
    fusion, clock = fusion_with(lambda t: [])
    delay = CFG["thermal"]["night_after_s"]
    step(fusion, clock, 0.0, DARK)
    step(fusion, clock, delay - 0.1, DARK)
    assert not fusion.night
    step(fusion, clock, delay + 0.1, DARK)
    assert fusion.night
    step(fusion, clock, delay + 1.0, BRIGHT)             # one bright frame (headlights): still night
    assert fusion.night
    step(fusion, clock, delay + 2.0, DARK)
    step(fusion, clock, delay + 3.0, BRIGHT)
    step(fusion, clock, 2 * delay + 3.2, BRIGHT)
    assert not fusion.night


def test_heat_without_rgb_for_0_6_s_at_night_is_an_unclassified_pedestrian():
    # (spec §8) warm blob in the waiting zone, no RGB detection, 0.6 s, night mode.
    fusion, clock = fusion_with(lambda t: [2, 3] if t >= 6.0 else [])
    make_night(fusion, clock)
    assert step(fusion, clock, 6.0, DARK).pedestrians == []          # heat just appeared
    assert step(fusion, clock, 6.4, DARK).pedestrians == []          # 0.4 s: not yet
    scene = step(fusion, clock, 6.6, DARK)                           # 0.6 s
    assert len(scene.pedestrians) == 1
    ped = scene.pedestrians[0]
    assert ped.thermal_only and ped.zone == "waiting_zone_left" and ped.track_id < 0
    assert pedestrian_speed(ped, CFG) == 0.8
    assert fusion.recovered == ["waiting_zone_left"]
    out = RuleEngine(CFG).step(step(fusion, clock, 7.8, DARK), 7.8)
    assert out["state"] == "PRESENCE" and out["reason"] == "pedone non classificato in attesa"


def test_thermal_pedestrian_disappears_with_the_heat():
    fusion, clock = fusion_with(lambda t: [2, 3] if 6.0 <= t < 8.0 else [])
    make_night(fusion, clock)
    step(fusion, clock, 6.0, DARK)
    assert len(step(fusion, clock, 7.0, DARK).pedestrians) == 1
    assert step(fusion, clock, 8.1, DARK).pedestrians == []
    # Heat again: the 0.5 s start over.
    fusion.source._script = lambda t: [2, 3]
    assert step(fusion, clock, 8.2, DARK).pedestrians == []
    assert len(step(fusion, clock, 8.8, DARK).pedestrians) == 1


def test_no_recovery_in_daylight():
    fusion, clock = fusion_with(lambda t: [2, 3])
    for i in range(80):
        scene = step(fusion, clock, i / 10, BRIGHT)
    assert not fusion.night and scene.pedestrians == [] and fusion.warm[[2, 3]].all()


def test_rgb_person_with_heat_is_confirmed_and_not_duplicated():
    fusion, clock = fusion_with(lambda t: [12])                       # heat in the far waiting zone
    t = make_night(fusion, clock)
    seen = PedestrianInfo(7, "waiting_zone_right", waiting_s=2.0)
    for k in range(1, 12):
        scene = step(fusion, clock, t + k / 10, DARK, [seen])
    assert [p.track_id for p in scene.pedestrians] == [7] and fusion.unconfirmed == set() and fusion.recovered == []


def test_rgb_person_without_heat_at_night_is_flagged_but_still_protected():
    fusion, clock = fusion_with(lambda t: [])
    t = make_night(fusion, clock)
    poster = PedestrianInfo(9, "waiting_zone_left", waiting_s=5.0)
    scene = step(fusion, clock, t + 0.1, DARK, [poster])
    assert fusion.unconfirmed == {9} and [p.track_id for p in scene.pedestrians] == [9]
    # A zone the sensor does not look at is never flagged.
    elsewhere = PedestrianInfo(10, None)
    step(fusion, clock, t + 0.2, DARK, [elsewhere])
    assert fusion.unconfirmed == set()


def test_drop_unconfirmed_is_an_option():
    cfg = load_config()
    cfg["thermal"]["drop_unconfirmed"] = True
    clock = Clock()
    fusion = ThermalFusion(cfg, SimThermalSource(cfg, script=lambda t: [], clock=clock), force_night=True)
    clock.t = 1.0
    scene = fusion.update(Scene(W=7.0, pedestrians=[PedestrianInfo(9, "crosswalk")]), 1.0, DARK)
    assert scene.pedestrians == []


def test_force_night_and_summary():
    fusion, clock = fusion_with(lambda t: [0, 15], force_night=True)
    step(fusion, clock, 0.0, BRIGHT)
    assert fusion.night
    assert fusion.summary() == "thermal NIGHT [#..............#] ambient 14C"


def test_mcu_source_reads_c5_thermal_lines():
    clock = Clock()
    source = McuThermalSource(CFG, clock=clock)
    assert source.read()[0] is None                                   # nothing received yet
    values = [20.0 + i * 0.1 for i in range(64)]
    source.on_mcu_line({"v": 1, "src": "mcu", "type": "thermal", "t": values})
    frame, _ = source.read()
    assert frame.shape == (4, 16)
    assert frame[0, 1] == pytest.approx(20.1) and frame[1, 0] == pytest.approx(21.6)    # row by row
    # Other C5 lines and malformed ones do not touch the frame.
    source.on_mcu_line({"v": 1, "src": "mcu", "type": "env", "t_c": 14.2})
    source.on_mcu_line({"v": 1, "src": "mcu", "type": "thermal", "t": [1.0] * 10})
    source.on_mcu_line({"v": 1, "src": "mcu", "type": "thermal", "t": ["x"] * 64})
    assert source.read()[0][0, 1] == pytest.approx(20.1)
    clock.t += CFG["thermal"]["max_frame_age_s"] + 0.1                # too old: not trusted
    assert source.read()[0] is None


def test_no_thermal_frames_means_no_thermal_pedestrians():
    clock = Clock()
    fusion = ThermalFusion(CFG, McuThermalSource(CFG, clock=clock), force_night=True)
    scene = fusion.update(Scene(W=7.0, pedestrians=[PedestrianInfo(1, "crosswalk")]), 1.0, DARK)
    assert [p.track_id for p in scene.pedestrians] == [1] and fusion.unconfirmed == set() and not fusion.warm.any()


def test_make_thermal_source():
    assert make_thermal_source("none", CFG) is None
    assert isinstance(make_thermal_source("sim", CFG), SimThermalSource)

    class FakeActuator:
        listener = None

        def set_listener(self, cb):
            self.listener = cb
    actuator = FakeActuator()
    source = make_thermal_source("mlx90621", CFG, actuator)
    assert isinstance(source, McuThermalSource) and actuator.listener == source.on_mcu_line
    for missing in ("mlx90640", "uvc"):
        with pytest.raises(RuntimeError):
            make_thermal_source(missing, CFG)


def test_night_scenario_warns_for_a_pedestrian_only_the_heat_can_see():
    timeline = []
    pipeline = run_scenario(CFG, "night_pedestrian_seen_by_heat",
                            on_step=lambda t, cmd, p: timeline.append((t, cmd["state"], cmd["reason"])))
    states = [s for _, s, _ in timeline]
    order = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
    assert order == ["IDLE", "PRESENCE", "WARN_DRIVER", "WARN_PEDESTRIAN", "PRESENCE"]
    first_presence = next(t for t, s, _ in timeline if s == "PRESENCE")
    assert 6.5 <= first_presence <= 6.7                               # heat at 6.0 s + 0.5 s
    warn = next(r for _, s, r in timeline if s == "WARN_DRIVER")
    assert warn.startswith("pedone non classificato 0.8 m/s; car 50 km/h") and "T_need 9.8 s" in warn
    assert pipeline.thermal.night
