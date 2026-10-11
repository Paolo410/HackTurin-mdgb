"""Metrics of a crossing (ai/forecast/analytics.py) and the check of the estimate against what the node counted
afterwards (service.quality, service.nowcast). No network, no hardware."""
import json
import math
import random

import pytest

from forecast import analytics, features, fusion
from forecast.model import Model
from forecast.service import EVIDENCE, QUALITY_MIN_HISTORY, QUALITY_MIN_WINDOWS, QUALITY_WINDOWS, nowcast, quality
from forecast_helpers import CENTRE, MONDAY_18, NODE, SUBURB, forecaster, local, windows


@pytest.fixture(scope="module")
def model():
    return Model.load()


def poisson(rng, lam):
    if lam > 50:
        return max(0, round(rng.gauss(lam, lam ** 0.5)))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


# ---------------------------------------------------------------- traffic
def test_traffic_totals_by_period():
    ws = windows(MONDAY_18, 30 * 4, 900, ped_in=3, ped_out=1, vehicles=10, cyclist=2)        # 30 hours of quarters
    t = analytics.traffic(ws, MONDAY_18)
    assert t["last_hour"] == {"ped_in": 12, "ped_out": 4, "cyclist": 8, "vehicles": 40, "animals": 0}
    assert t["last_24h"]["ped_in"] == 24 * 12 and t["today"]["ped_in"] == 18 * 12, "today starts at local midnight"
    assert t["coverage_24h"] == 1.0 and t["provisional_share"] == 0 and t["share_in"] == 0.75
    assert t["pedestrians_per_hour"] == 16.0
    assert json.loads(json.dumps(t)) == t


def test_traffic_hour_by_hour_with_gaps():
    now = local(12, 18, 20)                                              # 18:20: the current hour is one third done
    ws = windows(now, 4, 900, ped_in=5, end=local(12, 17))               # 16:00-17:00, complete
    ws += windows(now, 1, 900, ped_in=40, end=local(12, 17, 15))         # 17:00-17:15 only: the node went silent
    ws += windows(now, 20, 60, ped_in=1, ped_out=1, end=now)             # 18:00-18:20, one-minute windows
    t = analytics.traffic(ws, now)
    hours = {h["t0"]: h for h in t["hourly"]}
    assert len(t["hourly"]) == 24 and t["hourly"][-1]["t0"] == local(12, 18) and t["hourly"][0]["t0"] == local(11, 19)
    assert (hours[local(12, 16)]["ped_in"], hours[local(12, 16)]["coverage"]) == (20, 1.0)
    assert (hours[local(12, 17)]["ped_in"], hours[local(12, 17)]["coverage"]) == (40, 0.25)
    assert (hours[local(12, 18)]["ped_in"], hours[local(12, 18)]["ped_out"], hours[local(12, 18)]["coverage"]) == (20, 20, 0.33)
    assert hours[local(12, 9)] == {"ped_in": 0, "ped_out": 0, "cyclist": 0, "vehicles": 0, "animals": 0,
                                   "t0": local(12, 9), "t1": local(12, 10), "coverage": 0.0}
    assert t["peak_hour"] == {"t0": local(12, 16), "t1": local(12, 17), "pedestrians": 20}, \
        "17-18 has more people but was measured for a quarter of an hour: not a peak anyone can vouch for"
    assert t["coverage_24h"] == pytest.approx((3600 + 900 + 1200) / 86400, abs=0.001)
    assert t["last_hour"]["ped_in"] == 20, "the hour that ends now, whatever the clock hour"


def test_traffic_of_a_node_that_measured_little_or_nothing():
    empty = analytics.traffic([], MONDAY_18)
    assert empty["last_24h"] == dict.fromkeys(analytics.CLASSES, 0) and empty["peak_hour"] is None
    assert (empty["pedestrians_per_hour"], empty["share_in"], empty["provisional_share"], empty["coverage_24h"]) == (None, None, None, 0.0)
    brief = analytics.traffic(windows(MONDAY_18, 10, 60, ped_in=2), MONDAY_18)
    assert brief["pedestrians_per_hour"] is None, "ten minutes are not enough for an hourly average"
    old = windows(MONDAY_18, 4, 900, ped_in=9, end=MONDAY_18 - 2 * 86400)
    future = windows(MONDAY_18, 4, 900, ped_in=9, end=MONDAY_18 + 7200)
    assert analytics.traffic(old + future, MONDAY_18) == empty, "two days ago and a wrong clock do not count"
    bluetooth = windows(MONDAY_18, 4, 900, ped_in=1)
    bluetooth[0]["provisional"] = bluetooth[1]["provisional"] = True
    assert analytics.traffic(bluetooth, MONDAY_18)["provisional_share"] == 0.5


# ---------------------------------------------------------------- safety
def test_safety_rates_of_the_last_day():
    ev = lambda type_, age, **k: dict({"type": type_, "ts": MONDAY_18 - age}, **k)
    events = [ev("crossing", 60 * i, cls="pedestrian", dir="in", attrs={"child": i < 2, "aid": "wheelchair" if i == 5 else None})
              for i in range(20)]
    events += [ev("crossing", 30, cls="car", dir="in"), ev("crossing", 40, cls="pedestrian", dir="in", line="veh"),
               ev("crossing", 50, cls="pedestrian", dir="out", attrs={"aid": "normal"})]
    events += [ev("yield", 100, yielded=True), ev("yield", 200, yielded=True), ev("yield", 300, yielded=False)]
    events += [ev("near_miss", 500), ev("near_miss", 90000), ev("incident", 700, kind="hard_brake"),
               ev("incident", 800, kind="hard_brake"), ev("incident", 900, kind="person_down"), ev("incident", 950),
               {"type": "near_miss"}, ev("status", 10)]
    s = analytics.safety(events, MONDAY_18)
    assert s["pedestrian_crossings"] == 21, "pedestrians over the stripes: not the car, not the walk along the road"
    assert (s["vulnerable"], s["vulnerable_share"]) == (3, round(3 / 21, 3)), "two children and a wheelchair"
    assert (s["vehicles_met"], s["yield_rate"]) == (3, 0.67)
    assert (s["near_miss"], s["near_miss_per_1000_crossings"]) == (1, round(1000 / 21, 1)), "yesterday's and the undated one are out"
    assert s["incidents"] == 4 and s["incidents_by_kind"] == {"hard_brake": 2, "person_down": 1, "unknown": 1}
    nothing = analytics.safety([], MONDAY_18)
    assert (nothing["yield_rate"], nothing["vulnerable_share"], nothing["near_miss_per_1000_crossings"]) == (None, None, None)
    assert nothing["incidents_by_kind"] == {} and nothing["pedestrian_crossings"] == 0


def test_summary_puts_the_two_together():
    out = analytics.summary(windows(MONDAY_18, 8, 900, ped_in=5), [{"type": "near_miss", "ts": MONDAY_18 - 5}], MONDAY_18)
    assert set(out) == {"now", "traffic", "safety"} and out["now"] == MONDAY_18
    assert out["traffic"]["last_hour"]["ped_in"] == 20 and out["safety"]["near_miss"] == 1
    assert json.loads(json.dumps(out)) == out


# ---------------------------------------------------------------- the estimate of now
def seen_from(ws, mu):
    return [(w, (w["t1"] - w["t0"]) / 900.0, mu) for w in ws]


def test_nowcast_follows_the_last_window_of_a_busy_crossing_and_averages_a_quiet_one():
    flat = dict.fromkeys(features.TARGETS, 100.0)                       # the model: 100 pedestrians a quarter
    busy = windows(MONDAY_18, 8, 900, ped_in=100)
    busy[-1]["ped_in"] = 160                                            # the last quarter was different
    post = nowcast(seen_from(busy, flat), flat, "ped_in", MONDAY_18)
    assert post["mean"] == pytest.approx(160, rel=0.08), "100 expected counts in the last window: enough evidence"
    assert post["weight"] > 0.9

    rare = dict.fromkeys(features.TARGETS, 2.0)                         # 2 a quarter: one window says little
    quiet = windows(MONDAY_18, 8, 900, ped_in=2)
    quiet[-1]["ped_in"] = 6
    post = nowcast(seen_from(quiet, rare), rare, "ped_in", MONDAY_18)
    assert 2.2 < post["mean"] < 3.6, "one odd count among few does not move the estimate to 6"
    assert EVIDENCE > 10 * 2.0, "the test relies on a quiet crossing needing many windows"


def test_nowcast_lets_the_node_win_at_once_when_it_contradicts_the_model():
    # found with the node simulator at 6 in the morning: the model expected one person a quarter, the node
    # counted 32 a minute, and for the first hour the estimate stayed at a fifth of what was being counted
    mu = dict.fromkeys(features.TARGETS, 1.0)
    for minutes in (1, 4, 15):
        post = nowcast(seen_from(windows(MONDAY_18, minutes, 60, ped_in=32), mu), mu, "ped_in", MONDAY_18)
        assert post["mean"] == pytest.approx(480, rel=0.03) and post["weight"] > 0.95, "%d minutes of counts" % minutes
    empty_street = dict.fromkeys(features.TARGETS, 300.0)              # and the other way round
    post = nowcast(seen_from(windows(MONDAY_18, 4, 900, ped_in=3), empty_street), empty_street, "ped_in", MONDAY_18)
    assert post["mean"] < 10
    in_line = dict.fromkeys(features.TARGETS, 2.0)                     # counts that agree with the model change nothing
    agree = nowcast(seen_from(windows(MONDAY_18, 3, 60, ped_in=0), in_line), in_line, "ped_in", MONDAY_18)
    assert agree["mean"] == pytest.approx(2.0, rel=0.1) and agree["weight"] < 0.1, "three empty minutes are no news"


def test_nowcast_without_counts_is_the_model_with_a_wide_interval():
    mu = dict.fromkeys(features.TARGETS, 40.0)
    alone = nowcast([], mu, "ped_in", MONDAY_18)
    assert alone["mean"] == pytest.approx(40.0) and alone["weight"] == pytest.approx(0.0)
    assert alone["lo"] < 30 and alone["hi"] > 52, "the surroundings alone leave a third of uncertainty either way"
    assert alone["lo"] / 40 == pytest.approx(nowcast([], dict.fromkeys(features.TARGETS, 4.0), "ped_in", MONDAY_18)["lo"] / 4, rel=1e-6), \
        "in proportion, the same for a quiet crossing"
    stale = seen_from(windows(MONDAY_18, 8, 900, ped_in=80, end=MONDAY_18 - 5 * 3600), mu)
    old = nowcast(stale, mu, "ped_in", MONDAY_18)
    assert old["weight"] == pytest.approx(0.0) and old["mean"] == pytest.approx(40 * fusion.calibration(640, 320)), \
        "counts of five hours ago are not the present, but they did set the usual level"
    assert nowcast([], dict.fromkeys(features.TARGETS, 0.0), "ped_in", MONDAY_18)["mean"] > 0


# ---------------------------------------------------------------- checking the estimate on later counts
def test_quality_needs_enough_windows():
    mu = dict.fromkeys(features.TARGETS, 10.0)
    enough = QUALITY_MIN_HISTORY + QUALITY_MIN_WINDOWS
    assert quality(seen_from(windows(MONDAY_18, enough - 1, 900, ped_in=10), mu)) is None
    q = quality(seen_from(windows(MONDAY_18, enough, 900, ped_in=10, ped_out=10), mu))
    assert q["windows"] == QUALITY_MIN_WINDOWS and q["window_s"] == 900 and q["mean_count"] == 20
    assert quality(seen_from(windows(MONDAY_18, 300, 60, ped_in=1), mu))["windows"] == QUALITY_WINDOWS
    assert quality([]) is None


def test_quality_on_counts_that_never_change():
    mu = dict.fromkeys(features.TARGETS, 10.0)                          # the model says 10 + 10, the node counts 30 + 30
    q = quality(seen_from(windows(MONDAY_18, 60, 900, ped_in=30, ped_out=30), mu))
    assert q["mae_persistence"] == 0 and q["mae_model"] == 40, "repeating the last count is perfect, the model alone is 40 off"
    assert q["mae"] < 3 and abs(q["bias"]) < 0.05, "the estimate has learned the level of this crossing"
    assert quality(seen_from(windows(MONDAY_18, 60, 900, ped_in=0), mu))["bias"] is None, "nobody counted: no ratio"


def test_estimate_beats_both_yardsticks_where_counts_are_few(model):
    rng = random.Random(4)
    f = forecaster(model, parts=SUBURB)
    ws = windows(MONDAY_18, 96, 60, ped_in=0)                           # the demo: one-minute windows
    for w in ws:
        mu = model.predict(features.row((w["t0"] + w["t1"]) / 2, SUBURB))
        w["ped_in"], w["ped_out"] = poisson(rng, 3 * mu["ped_in"] / 15), poisson(rng, 3 * mu["ped_out"] / 15)
    q = f.forecast(NODE, ws)["quality"]
    assert q["windows"] == QUALITY_WINDOWS and q["window_s"] == 60 and q["mean_count"] > 1
    assert q["mae"] < q["mae_persistence"], "a few people a minute: averaging beats repeating the last minute"
    assert q["mae"] < q["mae_model"], "and the node says this crossing has three times the people the surroundings suggest"
    assert abs(q["bias"]) < 0.15


def test_estimate_stays_close_to_persistence_where_counts_are_many(model):
    rng = random.Random(5)
    f = forecaster(model, parts=CENTRE)
    for shift in (0, 3600):                                             # the crossing's day: the model's, or one hour late
        ws = windows(MONDAY_18, 60, 900, ped_in=0)
        for w in ws:
            mu = model.predict(features.row((w["t0"] + w["t1"]) / 2 - shift, CENTRE))
            w["ped_in"], w["ped_out"] = poisson(rng, 1.8 * mu["ped_in"]), poisson(rng, 1.8 * mu["ped_out"])
        q = f.forecast(NODE, ws)["quality"]
        assert q["mae"] < 1.35 * q["mae_persistence"], "a busy crossing is told by its last window: never much worse than that"
        assert q["mae"] < 0.6 * q["mae_model"]


def test_quality_is_part_of_the_forecast_only_when_there_is_something_to_check(model):
    f = forecaster(model)
    assert f.forecast(NODE, [])["quality"] is None
    assert f.forecast(NODE, windows(MONDAY_18, 8, 900, ped_in=40))["quality"] is None
    out = f.forecast(NODE, windows(MONDAY_18, 40, 900, ped_in=40, ped_out=30))
    assert set(out["quality"]) == {"windows", "window_s", "mean_count", "mae", "mae_persistence", "mae_model", "bias"}
    assert json.loads(json.dumps(out)) == out
