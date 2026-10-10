"""Rule tests from the specification (§8), with the numbers checked by hand."""
import pytest

from smartcrossing.config import load_config
from smartcrossing.rules import (
    PRIORITY, AnimalInfo, PedestrianInfo, RuleEngine, Scene, VehicleInfo, evaluate, green_time, lcd_text,
    pedestrian_speed, stopping_distance, time_needed, time_to_collision,
)

CFG = load_config()
W = 7.0
V_CAR = 13.9   # 50 km/h


def elderly(zone="waiting_zone_left", waiting_s=3.0):
    return PedestrianInfo(track_id=12, zone=zone, waiting_s=waiting_s, slow=True, walk_speed_ms=0.8)


def car(d, a=0.0, v=V_CAR):
    return VehicleInfo(track_id=31, d=d, v=v, a=a)


def run(scene, t=0.0):
    return RuleEngine(CFG).step(scene, t)


def test_formulas_match_the_spec_numbers():
    assert stopping_distance(V_CAR, CFG) == pytest.approx(27.7, abs=0.05)   # 13.9 + 13.9^2 / 14
    assert time_needed(W, 0.8, CFG) == pytest.approx(9.75)                   # 7 / 0.8 + 1
    assert time_to_collision(60, V_CAR) == pytest.approx(4.3, abs=0.05)


def test_elderly_and_fast_car_far_away_warns_the_driver():
    out = run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(60)]))
    assert out["state"] == "WARN_DRIVER" and out["led"] == "AMBER_BLINK_2HZ"
    assert out["reason"] == "pedone lento 0.8 m/s; car 50 km/h a 60 m; TTC 4.3 s < T_need 9.8 s"
    # The warning is for the driver's display; the signal is asked nothing more than the extra green.
    assert out["req"] == {"ped_green_extend_s": 3, "veh_red_hold": False, "veh_red_now": False, "flash": False}
    assert out["lcd"] == "PEDONE  50 km/h RALLENTA" and out["oled"] == "ATTENDI auto 50km/h"


def test_same_car_close_and_not_braking_warns_the_pedestrian():
    out = run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(25)]))
    assert out["state"] == "WARN_PEDESTRIAN" and out["led"] == "RED_GROUND_BLINK"
    assert "non frena" in out["reason"] and "37.7 m" in out["reason"]   # d_stop + 10


def test_close_car_that_brakes_is_yielding():
    out = run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(25, a=-3.0)]))
    assert out["state"] == "PRESENCE"


def test_no_vehicle_is_presence():
    out = run(Scene(W=W, pedestrians=[elderly()]))
    assert out["state"] == "PRESENCE" and out["led"] == "WHITE_ON"
    assert out["reason"] == "pedone lento in attesa"
    assert out["req"] == {"ped_green_extend_s": 3, "veh_red_hold": False, "veh_red_now": False,
                          "flash": False}   # 10.75 - 7.83


def test_no_video_for_one_and_a_half_seconds_is_degraded():
    out = run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(25)], video_age_s=1.5))
    assert out["state"] == "DEGRADED" and out["led"] == "YELLOW_FAILSAFE"
    assert out["req"] == {"ped_green_extend_s": 0, "veh_red_hold": False, "veh_red_now": False, "flash": False}
    assert out["lcd"] == "" and out["oled"] == "" and out["green_s"] == 0


def test_faults_are_degraded_too():
    assert run(Scene(W=W, fault="lens_covered"))["reason"] == "lente coperta"
    assert run(Scene(W=W, fault="glare"))["state"] == "DEGRADED"


def test_green_time():
    assert green_time(12, 0.7, CFG) == pytest.approx(19.1, abs=0.05)   # 12 / 0.7 + 2
    assert green_time(12, 0.3, CFG) == 25                              # capped
    assert green_time(12, 1.2, CFG) == pytest.approx(12.0)


def test_c1_example_of_the_spec():
    # W = 12 m, pedestrian at 0.7 m/s: green 19 s, 7 s more than the standard 12 s.
    ped = PedestrianInfo(1, "crosswalk", walk_speed_ms=0.7, slow=True)
    out = run(Scene(W=12, pedestrians=[ped]))
    assert out["green_s"] == 19 and out["req"]["ped_green_extend_s"] == 7
    assert out["req"]["veh_red_hold"] is True          # somebody is on the stripes
    assert out["lcd"] == "PEDONE          SULLE STRISCE" and out["oled"] == "TEMPO VERDE 19 s"


def test_green_extension_never_exceeds_the_controller_limit():
    very_slow = PedestrianInfo(1, "crosswalk", walk_speed_ms=0.3, slow=True)
    out = run(Scene(W=W, pedestrians=[very_slow]))
    assert out["green_s"] == 25 and out["req"]["ped_green_extend_s"] == 15    # 25 - 7.83 = 17, capped


def test_pedestrian_speed():
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk"), CFG) == 1.2
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk", child=True), CFG) == 0.8
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk", aid="wheelchair"), CFG) == 0.8
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk", aid="normal"), CFG) == 1.2
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk", thermal_only=True), CFG) == 0.8
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk", walk_speed_ms=0.5), CFG) == 0.5
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk", walk_speed_ms=0.05), CFG) == 0.3   # floor
    assert pedestrian_speed(PedestrianInfo(1, "crosswalk", walk_speed_ms=1.6), CFG) == 1.2    # never above default


def test_intention_is_needed_for_a_warning():
    just_arrived = PedestrianInfo(1, "waiting_zone_right", waiting_s=0.2)
    assert run(Scene(W=W, pedestrians=[just_arrived], vehicles=[car(60)]))["state"] == "PRESENCE"
    walking_in = PedestrianInfo(1, "waiting_zone_right", waiting_s=0.2, toward_road_ms=1.0)
    assert run(Scene(W=W, pedestrians=[walking_in], vehicles=[car(40)]))["state"] == "WARN_DRIVER"
    crossing = PedestrianInfo(1, "crosswalk")
    assert run(Scene(W=W, pedestrians=[crossing], vehicles=[car(20)]))["state"] == "WARN_PEDESTRIAN"


def test_nobody_or_only_passers_by_is_idle():
    assert run(Scene(W=W))["state"] == "IDLE"
    passer_by = PedestrianInfo(1, None)
    out = run(Scene(W=W, pedestrians=[passer_by], vehicles=[car(30)]))
    assert out["state"] == "IDLE" and out["led"] == "OFF" and out["green_s"] == 0


def test_slow_or_distant_vehicles_do_not_warn():
    assert run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(60, v=0.5)]))["state"] == "PRESENCE"   # almost still
    assert run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(200)]))["state"] == "PRESENCE"        # TTC 14 s
    assert run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(-5)]))["state"] == "PRESENCE"         # already past


def test_most_important_state_wins_with_several_vehicles():
    out = run(Scene(W=W, pedestrians=[elderly()], vehicles=[car(60), car(25)]))
    assert out["state"] == "WARN_PEDESTRIAN"
    assert PRIORITY.index("WARN_PEDESTRIAN") < PRIORITY.index("WARN_DRIVER") < PRIORITY.index("PRESENCE")


def test_state_steps_up_at_once_and_down_after_the_hold_time():
    engine = RuleEngine(CFG)
    hold = CFG["rules"]["hold_s"]
    assert engine.step(Scene(W=W, pedestrians=[elderly()]), t=0.0)["state"] == "PRESENCE"
    assert engine.step(Scene(W=W, pedestrians=[elderly()], vehicles=[car(60)]), t=0.1)["state"] == "WARN_DRIVER"
    assert engine.step(Scene(W=W, pedestrians=[elderly()], vehicles=[car(25)]), t=0.2)["state"] == "WARN_PEDESTRIAN"
    # The car is gone: the warning is held, then released.
    assert engine.step(Scene(W=W, pedestrians=[elderly()]), t=0.2 + hold / 2)["state"] == "WARN_PEDESTRIAN"
    assert engine.step(Scene(W=W, pedestrians=[elderly()]), t=0.2 + hold + 0.01)["state"] == "PRESENCE"
    assert engine.step(Scene(W=W), t=0.3 + hold)["state"] == "PRESENCE"          # held again
    assert engine.step(Scene(W=W), t=0.3 + 2 * hold + 0.02)["state"] == "IDLE"


def test_green_request_only_grows_while_somebody_is_there():
    engine = RuleEngine(CFG)
    ped = lambda speed: PedestrianInfo(1, "crosswalk", walk_speed_ms=speed, slow=True)
    greens = [engine.step(Scene(W=12, pedestrians=[ped(v)]), t=i * 0.1)["green_s"]
              for i, v in enumerate([0.9, 0.7, 0.75, 0.72, 0.8, 1.0])]
    # 0.9 is not below the 0.8 of a slow pedestrian: 12 / 0.8 + 2 = 17; then 12 / 0.7 + 2 = 19 and no way back.
    assert greens == [17, 19, 19, 19, 19, 19]
    hold = CFG["rules"]["hold_s"]
    assert engine.step(Scene(W=12), t=1.0 + hold + 0.1)["green_s"] == 0          # everybody left
    brisk = PedestrianInfo(2, "crosswalk", walk_speed_ms=1.1)
    # A new pedestrian starts afresh, and one who does not need more time gets the standard green: 12 / 1.2 + 2.
    assert engine.step(Scene(W=12, pedestrians=[brisk]), t=5.0)["green_s"] == 12


def test_more_green_only_for_who_needs_more_time_to_cross():
    def req(*people):
        return run(Scene(W=12, pedestrians=list(people)))["req"]

    # An adult, an adult who is not fast, a child with its parent: the standard green, the red is not held.
    parent = PedestrianInfo(2, "crosswalk", x=0.5, y=3.0)
    for people in ([PedestrianInfo(1, "crosswalk")], [PedestrianInfo(1, "crosswalk", walk_speed_ms=1.0)],
                   [PedestrianInfo(1, "crosswalk", child=True, x=0.0, y=3.0), parent]):
        assert req(*people) == {"ped_green_extend_s": 0, "veh_red_hold": False, "veh_red_now": False, "flash": False}
    # Wheelchair, walking aid, stroller, measured slow walker: more green, and the red held while they cross.
    for ped in (PedestrianInfo(1, "crosswalk", aid="wheelchair"), PedestrianInfo(1, "crosswalk", aid="walking_aid"),
                PedestrianInfo(1, "crosswalk", aid="stroller"), PedestrianInfo(1, "crosswalk", slow=True, walk_speed_ms=0.6)):
        assert req(ped)["ped_green_extend_s"] > 0 and req(ped)["veh_red_hold"] is True
    waiting = PedestrianInfo(1, "waiting_zone_left", aid="wheelchair")
    assert req(waiting)["ped_green_extend_s"] == 5 and req(waiting)["veh_red_hold"] is False   # 12 / 0.8 - 12 / 1.2
    # With an adult and a slow walker together, the slow walker sets the time.
    both = Scene(W=12, pedestrians=[PedestrianInfo(1, "crosswalk"), PedestrianInfo(2, "crosswalk", slow=True, walk_speed_ms=0.6)])
    assert run(both)["req"]["ped_green_extend_s"] == 10


def test_a_child_on_its_own_calls_the_red_for_the_vehicles_at_once():
    child = PedestrianInfo(1, "waiting_zone_left", child=True, x=1.0, y=-0.5)
    out = run(Scene(W=W, pedestrians=[child]))
    assert out["req"]["veh_red_now"] is True and out["req"]["veh_red_hold"] is True
    assert out["req"]["ped_green_extend_s"] == 0
    assert out["state"] == "PRESENCE" and out["reason"] == "bambino in attesa; rosso ai veicoli: bambino non accompagnato"

    def red_now(*people):
        return run(Scene(W=W, pedestrians=list(people)))["req"]["veh_red_now"]

    near, far = CFG["rules"]["supervision_distance_m"] - 0.5, CFG["rules"]["supervision_distance_m"] + 3
    assert red_now(child, PedestrianInfo(2, "waiting_zone_left", x=1.0 + near, y=-0.5)) is False   # an adult beside
    assert red_now(child, PedestrianInfo(2, "waiting_zone_left", x=1.0 + far, y=-0.5)) is True     # an adult far away
    assert red_now(child, PedestrianInfo(2, "waiting_zone_left", child=True, x=1.5, y=-0.5)) is True   # two children
    assert red_now(PedestrianInfo(1, "carriageway", child=True, x=9.0, y=3.0)) is True              # on the road
    assert red_now(PedestrianInfo(1, None, child=True, x=1.0, y=-9.0)) is False                     # far from the crossing
    assert red_now(PedestrianInfo(1, "crosswalk")) is False                                         # an adult
    assert red_now(PedestrianInfo(1, "crosswalk", child=None, x=1.0, y=3.0)) is False               # height not known


def test_a_free_animal_on_the_road_calls_the_red_but_not_a_small_or_leashed_one():
    def req(animal):
        return run(Scene(W=W, animals=[animal]))["req"]

    out = run(Scene(W=W, animals=[AnimalInfo(1, "dog", "medium", on_road=True)]))
    assert out["req"]["veh_red_now"] is True and out["req"]["veh_red_hold"] is True
    assert out["state"] == "IDLE" and out["reason"].endswith("rosso ai veicoli: animale libero in carreggiata (dog)")
    assert req(AnimalInfo(1, "cow", "large", on_road=True))["veh_red_now"] is True
    assert req(AnimalInfo(1, "dog", "medium", on_road=True, free=False))["veh_red_now"] is False   # on a leash
    assert req(AnimalInfo(1, "cat", "small", on_road=True))["veh_red_now"] is False
    assert req(AnimalInfo(1, "dog", "medium", on_road=False))["veh_red_now"] is False              # on the pavement


def test_degraded_asks_nothing_of_the_signal():
    child = PedestrianInfo(1, "crosswalk", child=True, x=1.0, y=3.0)
    out = run(Scene(W=W, pedestrians=[child], animals=[AnimalInfo(2, "dog", "medium", on_road=True)], fault="glare"))
    assert out["state"] == "DEGRADED"
    assert out["req"] == {"ped_green_extend_s": 0, "veh_red_hold": False, "veh_red_now": False, "flash": False}


def test_lcd_text_is_two_rows_of_16():
    assert lcd_text("PEDONE", "IN ATTESA") == "PEDONE          IN ATTESA"
    assert len(lcd_text("X" * 40, "Y" * 40)) == 32
    assert lcd_text("PEDONE") == "PEDONE"


def test_every_output_is_a_complete_c1_command():
    scenes = [Scene(W=W), Scene(W=W, pedestrians=[elderly()]), Scene(W=W, pedestrians=[elderly()], vehicles=[car(60)]),
              Scene(W=W, pedestrians=[elderly()], vehicles=[car(25)]), Scene(W=W, video_age_s=3)]
    for scene in scenes:
        out = run(scene)
        assert set(out) == {"state", "led", "green_s", "req", "lcd", "oled", "reason"}
        assert set(out["req"]) == {"ped_green_extend_s", "veh_red_hold", "veh_red_now", "flash"}
        assert out["lcd"].isascii() and out["oled"].isascii() and len(out["lcd"]) <= 32
        assert 0 <= out["req"]["ped_green_extend_s"] <= 15      # firmware limit
        assert evaluate(scene, CFG).state == out["state"]
