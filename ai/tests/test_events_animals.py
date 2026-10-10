"""Animals, trajectory events and the C3 log, on scripted scenes (spec §8)."""
import json

import pytest

from smartcrossing.animals import AnimalMonitor, similar_direction, size_class
from smartcrossing.config import load_config
from smartcrossing.logger import C3Logger, flat_counts
from smartcrossing.rules import AnimalInfo, RuleEngine, Scene, VehicleInfo
from smartcrossing.sim import Actor, drive, run_actors, run_scenario

CFG = load_config()


def play(actors, duration, site=None, fps=10.0):
    """Runs the actors and returns (states in order of appearance, all events, pipeline)."""
    states, events = [], []

    def on_step(t, result, pipeline):
        if not states or states[-1] != result.command["state"]:
            states.append(result.command["state"])
        events.extend(result.events)
    pipeline = run_actors(CFG, actors, duration, fps=fps, site=site, on_step=on_step)
    return states, events, pipeline


def kinds(events):
    return [e.get("kind", e["type"]) for e in events]


# ---------------------------------------------------------------- animals

def test_size_classes():
    assert size_class(1.2, 0.7, CFG) == "large"
    assert size_class(0.5, 0.7, CFG) == "large"       # tall enough
    assert size_class(0.5, 0.4, CFG) == "medium"
    assert size_class(0.25, 0.2, CFG) == "small"
    assert size_class(None, None, CFG) == "small"


def test_similar_direction():
    assert similar_direction((1, 0), (1, 0.5), 45, 0.2)
    assert not similar_direction((1, 0), (0, 1), 45, 0.2)
    assert not similar_direction((1, 0), (-1, 0), 45, 0.2)
    assert similar_direction((0, 0), (1, 0), 45, 0.2)   # standing next to each other


def test_boar_on_the_road_raises_an_alert():
    # A 1.2 m animal (a boar, seen by COCO as a bear) walks across the road on the "collina" site.
    boar = Actor("bear", 0.8, 1.2, lambda t: (-6.0, -2.0 + 1.0 * t) if t < 12 else None)
    states, _, _ = play([boar], 16, site="collina")
    assert states == ["IDLE", "ANIMAL_ALERT", "IDLE"]


def test_alert_lamp_and_flash_request():
    engine = RuleEngine(CFG)
    out = engine.step(Scene(W=7, animals=[AnimalInfo(1, "bear", "large", on_road=True, length_m=1.2)]))
    assert out["state"] == "ANIMAL_ALERT" and out["led"] == "AMBER_BLINK_4HZ" and out["req"]["flash"] is True
    assert out["reason"] == "animale grande libero in carreggiata (bear, 1.2 m)"
    assert out["lcd"] == "ANIMALE         IN STRADA"


def test_small_cat_is_only_logged():
    cat = Actor("cat", 0.2, 0.25, lambda t: (-3.0, -2.0 + 1.0 * t) if t < 12 else None)
    states, _, pipeline = play([cat], 14)
    assert states == ["IDLE"]
    # It is still reported once for the log, as a small animal.
    sightings = pipeline.animals.new_sightings(pipeline.scene.animals or pipeline._animals)
    assert pipeline.animals.new_sightings([]) == []
    assert all(s.size == "small" for s in sightings)


def test_dog_next_to_a_person_raises_no_alarm():
    leashed_seen = []
    from smartcrossing.sim import SCENARIOS
    actors = SCENARIOS["loose_dog_and_leashed_dog"]()[0]
    states = []

    def on_step(t, result, pipeline):
        states.append(result.command["state"])
        leashed_seen.extend(a for a in pipeline.scene.animals if not a.free)
    run_actors(CFG, actors, 9.0, on_step=on_step)
    assert "ANIMAL_ALERT" not in states and "ANIMAL_WARN" not in states
    assert leashed_seen and all(a.coco == "dog" and a.size == "medium" for a in leashed_seen)


def run_args(name, until):
    from smartcrossing.sim import SCENARIOS
    actors = SCENARIOS[name]()[0]
    return actors, until


def test_loose_large_dog_alerts_after_the_leashed_one_did_not():
    states, _, _ = play(*run_args("loose_dog_and_leashed_dog", until=18.0))
    assert states.count("ANIMAL_ALERT") == 1
    assert states.index("ANIMAL_ALERT") > states.index("PRESENCE")


def test_herd_keeps_the_alert_until_the_last_one_leaves():
    # Three medium animals cross one after the other, close together: a herd.
    def member(delay):
        return lambda t: (-6.0, -2.0 + 1.0 * (t - delay)) if delay <= t < delay + 11 else None
    herd = [Actor("sheep", 0.5, 0.7, member(d)) for d in (0.0, 1.5, 3.0)]
    timeline = []
    run_actors(CFG, herd, 18, site="collina", on_step=lambda t, r, p: timeline.append((t, r.command["state"])))
    alert = [t for t, s in timeline if s == "ANIMAL_ALERT"]
    # The last member is on the road (y from 0 to 7) between t = 5 and t = 12.
    assert alert and alert[0] < 4.0
    assert 11.5 <= alert[-1] <= 12.0 + CFG["rules"]["animal_alert_hold_s"] + 0.3
    assert all(s == "ANIMAL_ALERT" for t, s in timeline if alert[0] <= t <= alert[-1])


def test_medium_animal_warns_only_with_a_vehicle_near():
    dog = AnimalInfo(1, "dog", "medium", on_road=True, x=0.0)
    engine = RuleEngine(CFG)
    assert engine.step(Scene(W=7, animals=[dog]))["state"] == "IDLE"
    car_near = VehicleInfo(2, d=-1, v=10, x=-30.0, vx=10.0)       # d_stop(10) = 17.1 m, + 30 m margin
    out = RuleEngine(CFG).step(Scene(W=7, animals=[dog], vehicles=[car_near]))
    assert out["state"] == "ANIMAL_WARN" and out["led"] == "AMBER_BLINK_2HZ" and out["req"]["flash"] is False
    car_far = VehicleInfo(2, d=-1, v=10, x=-60.0, vx=10.0)
    assert RuleEngine(CFG).step(Scene(W=7, animals=[dog], vehicles=[car_far]))["state"] == "IDLE"
    assert RuleEngine(CFG).step(Scene(W=7, animals=[dog], vehicles=[car_far], animal_margin_m=50))["state"] == "ANIMAL_WARN"
    car_leaving = VehicleInfo(2, d=-1, v=10, x=20.0, vx=10.0)
    assert RuleEngine(CFG).step(Scene(W=7, animals=[dog], vehicles=[car_leaving]))["state"] == "IDLE"


def test_leashed_or_off_road_animals_do_not_alarm():
    engine = RuleEngine(CFG)
    assert engine.step(Scene(W=7, animals=[AnimalInfo(1, "dog", "large", on_road=True, free=False)]))["state"] == "IDLE"
    assert engine.step(Scene(W=7, animals=[AnimalInfo(1, "dog", "large", on_road=False)]))["state"] == "IDLE"


def test_site_decides_which_animals_and_birds_count():
    cow = Actor("cow", 1.4, 2.0, lambda t: (-6.0, -2.0 + 1.0 * t) if t < 12 else None)
    assert play([cow], 14, site="urbano")[0] == ["IDLE"]                       # not an urban animal
    assert "ANIMAL_ALERT" in play([cow], 14, site="collina")[0]
    swan = Actor("bird", 0.9, 1.0, lambda t: (-6.0, 3.0))                     # sitting on the road
    assert play([swan], 6, site="urbano")[0] == ["IDLE"]
    assert "ANIMAL_ALERT" in play([swan], 6, site="lungofiume")[0]
    pigeon = Actor("bird", 0.2, 0.3, lambda t: (-6.0, 3.0))
    assert play([pigeon], 6, site="lungofiume")[0] == ["IDLE"]
    assert AnimalMonitor(CFG, "collina").margin_m == 40 and AnimalMonitor(CFG).margin_m == 30


def test_priority_between_people_and_animals():
    from smartcrossing.rules import PedestrianInfo
    waiting = PedestrianInfo(1, "waiting_zone_left", waiting_s=3)
    large = AnimalInfo(5, "bear", "large", on_road=True)
    car = VehicleInfo(9, d=60, v=13.9, x=-60.0, vx=13.9)
    assert RuleEngine(CFG).step(Scene(W=7, pedestrians=[waiting], animals=[large]))["state"] == "ANIMAL_ALERT"
    assert RuleEngine(CFG).step(Scene(W=7, pedestrians=[waiting], animals=[large], vehicles=[car]))["state"] == "ANIMAL_ALERT"
    close = VehicleInfo(9, d=25, v=13.9, x=-25.0, vx=13.9)
    assert RuleEngine(CFG).step(Scene(W=7, pedestrians=[waiting], animals=[large], vehicles=[close]))["state"] == "WARN_PEDESTRIAN"


# ---------------------------------------------------------------- events

def test_hard_braking():
    def car(t):
        if t < 2.0:
            return -60.0 + 14.0 * t, 1.75
        k = min(t - 2.0, 1.75)                      # -8 m/s^2 until it stops
        return -32.0 + 14.0 * k - 4.0 * k * k, 1.75
    _, events, _ = play([Actor("car", 1.5, 4.4, car)], 6)
    assert kinds(events).count("hard_brake") == 1
    gentle = Actor("car", 1.5, 4.4, lambda t: (-60.0 + 14.0 * t - 1.0 * t * t, 1.75) if t < 7 else (-11.0, 1.75))
    assert "hard_brake" not in kinds(play([gentle], 9)[1])


def test_person_lying_on_the_road():
    lying = Actor("person", 0.4, 1.7, lambda t: (2.0, 3.0))
    _, events, _ = play([lying], 5)
    incident = [e for e in events if e["type"] == "incident"]
    assert incident == [{"type": "incident", "kind": "person_down", "track_id": incident[0]["track_id"], "zone": "crosswalk"}]
    standing = Actor("person", 1.75, 0.5, lambda t: (2.0, 3.0))
    assert "person_down" not in kinds(play([standing], 5)[1])
    brief = Actor("person", 0.4, 1.7, lambda t: (2.0, 3.0) if t < 2.5 else None)
    assert "person_down" not in kinds(play([brief], 4)[1])


def test_collision_of_a_car_with_a_pedestrian():
    car = Actor("car", 1.5, 4.4, lambda t: (min(-18.5 + 10.0 * t, 1.5), 1.75))   # stops dead at x = 1.5
    pedestrian = Actor("person", 1.75, 0.5, lambda t: (2.0, 1.75))
    _, events, _ = play([car, pedestrian], 5)
    collisions = [e for e in events if e.get("kind") == "collision"]
    assert len(collisions) == 1 and collisions[0]["zone"] == "crosswalk"
    assert {collisions[0]["track_id"], collisions[0]["other"]} == {1, 2}
    # A car that parks gently next to a standing person is not a collision.
    slow = Actor("car", 1.5, 4.4, lambda t: (min(-3.5 + 1.0 * t, 1.5), 1.75))
    assert "collision" not in kinds(play([slow, pedestrian], 8)[1])


def test_near_miss_by_time_to_collision():
    car = Actor("car", 1.5, 4.4, drive(-40.0, 1.75, 13.9))
    pedestrian = Actor("person", 1.75, 0.5, lambda t: (2.0, 1.75) if t < 2.6 else None)   # jumps away in time
    _, events, _ = play([car, pedestrian], 4)
    near = [e for e in events if e["type"] == "near_miss"]
    assert len(near) == 1 and near[0]["ttc_s"] < 1.0 and near[0]["a"] != near[0]["b"]


def test_near_miss_by_post_encroachment_time():
    # The car passes first; the pedestrian steps on the same point one second later. No TTC warning
    # (the pedestrian was still 1.6 m to the side when the car went by), but a post-encroachment time below 1 s.
    car = Actor("car", 1.5, 4.4, drive(2.0 - 6.0 * 2.0, 1.75, 6.0))                # at x = 2.0 at t = 2.0
    pedestrian = Actor("person", 1.75, 0.5, lambda t: (2.0, 1.75 - 1.5 * (3.05 - t)))   # there at t = 3.05
    _, events, _ = play([pedestrian, car], 5, fps=20)
    near = [e for e in events if e["type"] == "near_miss"]
    assert len(near) == 1 and near[0]["ttc_s"] is None and 0 < near[0]["pet_s"] < 1.0
    late = Actor("person", 1.75, 0.5, lambda t: (2.0, 1.75 - 1.5 * (6.0 - t)))     # 4 s after the car: no conflict
    assert [e for e in play([late, car], 8, fps=20)[1] if e["type"] == "near_miss"] == []


def test_vehicle_standing_on_the_stripes():
    blocked = Actor("car", 1.5, 4.4, lambda t: (2.0, 1.75))
    _, events, _ = play([blocked], 12)
    assert kinds(events).count("vehicle_on_crosswalk") == 1
    assert "vehicle_on_crosswalk" not in kinds(play([blocked], 8)[1])


def test_yield_rate_counts_who_slows_down_for_a_waiting_pedestrian():
    states, events, pipeline = play(*run_args("car_yields", until=16.0))
    assert [e for e in events if e["type"] == "yield"] == [{"type": "yield", "track_id": 2, "yielded": True}]
    assert pipeline.events.yield_rate == 1.0

    waiting = Actor("person", 1.75, 0.5, lambda t: (2.0, -0.7))
    rude = Actor("car", 1.5, 4.4, drive(-50.0, 1.75, 12.0, t0=1.0, x_end=40.0))
    _, events, pipeline = play([waiting, rude], 10)
    assert [e["yielded"] for e in events if e["type"] == "yield"] == [False]
    assert pipeline.events.summary().startswith("yield 0% (0/1)")

    # Nobody waiting: the vehicle is not part of the yield rate.
    _, events, pipeline = play([rude], 10)
    assert [e for e in events if e["type"] == "yield"] == [] and pipeline.events.yield_rate is None


def test_crossing_events_describe_who_crossed():
    _, events, _ = play(*run_args("pedestrian_crossing", until=12.0))
    crossing = [e for e in events if e["type"] == "crossing"]
    assert len(crossing) == 1
    assert crossing[0]["cls"] == "pedestrian" and crossing[0]["line"] == "ped"
    assert crossing[0]["attrs"] == {"child": False, "slow": False, "aid": None}
    _, events, _ = play(*run_args("loose_dog_and_leashed_dog", until=18.0))
    animals = [e for e in events if e["type"] == "crossing" and e["cls"] == "animal"]
    assert animals and all(e["coco"] == "dog" for e in animals)


# ---------------------------------------------------------------- C3 log

class Clock:
    def __init__(self, t=1739012345.67):
        self.t = t

    def __call__(self):
        return self.t


def test_c3_lines_follow_the_contract(tmp_path):
    clock = Clock()
    log = C3Logger(CFG, tmp_path, clock)
    log.write({"type": "crossing", "track_id": 12, "cls": "pedestrian",
               "attrs": {"child": False, "slow": True, "aid": None}, "dir": "in", "line": "ped"})
    assert log.path.name == "c3-20250208-105905.jsonl"           # UTC time of opening
    text = log.path.read_text()
    assert text == ('{"v":1,"ts":1739012345.67,"type":"crossing","track_id":12,"cls":"pedestrian",'
                    '"attrs":{"child":false,"slow":true,"aid":null},"dir":"in","line":"ped"}\n')


def test_c3_is_append_only_and_rotates(tmp_path):
    clock = Clock()
    log = C3Logger(CFG, tmp_path, clock)
    log.write({"type": "yield", "track_id": 31, "yielded": True})
    first = log.path
    clock.t += 10
    log.write({"type": "incident", "kind": "hard_brake", "track_id": 31, "zone": "carriageway"})
    assert log.path == first and len(first.read_text().splitlines()) == 2
    clock.t += CFG["logger"]["rotate_s"]
    log.write({"type": "near_miss", "a": 12, "b": 31, "ttc_s": 0.8, "pet_s": None})
    assert log.path != first and len(first.read_text().splitlines()) == 2    # the old file is untouched
    assert sorted(p.name for p in tmp_path.iterdir()) == [first.name, log.path.name]
    log.close()
    # A new logger on the same folder never truncates what is there.
    again = C3Logger(CFG, tmp_path, clock)
    again.write({"type": "yield", "track_id": 40, "yielded": False})
    assert len(again.path.read_text().splitlines()) == 2
    for path in tmp_path.iterdir():
        for line in path.read_text().splitlines():
            assert json.loads(line)["v"] == 1


def test_status_event_every_five_seconds(tmp_path):
    clock = Clock()
    log = C3Logger(CFG, tmp_path, clock)
    assert log.status_due()
    counts = {"ped": {"pedestrian": {"in": 14, "out": 11}, "cyclist": {"in": 1, "out": 0}}, "veh": {"car": {"in": 52, "out": 0}}}
    line = log.write_status("PRESENCE", 9.64, {"detect": 71.2, "track": 3.4, "rules": 0.6, "act": None}, flat_counts(counts))
    assert line == {"v": 1, "ts": 1739012345.67, "type": "status", "state": "PRESENCE", "fps": 9.6,
                    "lat_ms": {"detect": 71, "track": 3, "rules": 1},
                    "counts": {"ped_in": 14, "ped_out": 11, "cyclist_in": 1, "car_in": 52}}
    assert not log.status_due()
    clock.t += CFG["logger"]["status_every_s"]
    assert log.status_due()


def test_c3_folder_from_the_environment(tmp_path, monkeypatch):
    from smartcrossing.logger import c3_dir
    monkeypatch.setenv("MDGB_C3_DIR", str(tmp_path / "elsewhere"))
    assert c3_dir(CFG) == tmp_path / "elsewhere"
    monkeypatch.delenv("MDGB_C3_DIR")
    assert c3_dir(CFG).parts[-2:] == ("logs", "c3")
