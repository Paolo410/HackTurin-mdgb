"""Features, model, fusion and service of the expected-flow model (ai/forecast), the training pipeline, and the
promises the control-room app relies on: the runtime needs only the standard library and is all in the bundle.
No network, no hardware."""
import ast
import json
import math
import os
import re
import sys
import time

import pytest

from forecast import features, fusion
from forecast.context import Context
from forecast.model import MODEL_PATH, Model
from forecast.service import ANOMALY_MIN_EXPECTED, HISTORY_WINDOWS, OUTLOOK_HOURS, Forecaster
from forecast_helpers import CENTRE, MONDAY_18, NODE, SUBURB, forecaster, local, windows

FORECAST_DIR = os.path.dirname(MODEL_PATH)
REPO = os.path.dirname(os.path.dirname(FORECAST_DIR))
RUNTIME = ("features", "model", "fusion", "sources", "context", "service")      # what the app imports
TRAINING = ("simulate", "train")                                                # needs numpy and scikit-learn


@pytest.fixture(scope="module")
def model():
    return Model.load()


# ---------------------------------------------------------------- features
def test_weather_is_the_closest_hour_or_nothing():
    hourly = {"hourly": [[1000, 10.0, 0.0], [4600, 11.0, 0.5], [8200, 12.0, 2.0]]}
    assert features.weather_at(hourly, 4000) == (11.0, 0.5) and features.weather_at(hourly, 2700) == (10.0, 0.0)
    assert features.weather_at(hourly, 8200 + 5400) == (12.0, 2.0), "an hour and a half is still that hour's weather"
    assert features.weather_at(hourly, 8200 + 5401) is None and features.weather_at(hourly, -5000) is None
    assert features.weather_at(None, 0) is None and features.weather_at({}, 0) is None and features.weather_at({"hourly": []}, 0) is None


def test_row_has_every_feature_and_follows_the_local_calendar():
    empty = features.row(local(25, 9, 30, month=12), {})
    assert tuple(empty) == features.FEATURES, "one value per feature, in the order the model was trained on"
    assert (empty["hour"], empty["dow"], empty["holiday"]) == (9.5, 4, 1), "Christmas 2026 is a Friday"
    assert all(empty[k] is None for k in features.FEATURES if k not in ("hour", "dow", "holiday"))
    week = [[d + h / 100.0 for h in range(24)] for d in range(7)]
    sunday_23 = features.row(local(18, 23, 59), {"google": {"open_week": week}})
    assert sunday_23["open_share"] == 6.23, "opening hours are looked up by local day (Monday first) and hour"
    assert features.row(local(19, 0, 0), {"google": {"open_week": week}})["open_share"] == 0.0


def test_row_treats_stale_and_partial_sources_as_missing():
    ctx = {"traffic": {"ratio": 1.3, "at": MONDAY_18 - 3601}, "weather": {"hourly": [[MONDAY_18 - 7200, 9.0, 1.0]]},
           "esa": {"built": 0.5}, "poi": {"food": 3}}
    f = features.row(MONDAY_18, ctx, env={"t_c": None})
    assert f["traffic"] is None and f["temp_c"] is None and f["rain_mm"] is None, "old traffic, old weather, no thermometer"
    assert (f["esa_built"], f["esa_green"], f["poi_food"], f["poi_shop"], f["road"]) == (0.5, None, 3, None, None)
    assert features.row(MONDAY_18, dict(ctx, traffic={"ratio": 1.3, "at": MONDAY_18 - 3600}))["traffic"] == 1.3


def test_holidays_over_the_years():
    assert [features.easter(y) for y in (2024, 2025, 2026, 2038)] == [(3, 31), (4, 20), (4, 5), (4, 25)]
    hol = lambda *a, **k: features.is_holiday(time.localtime(local(*a, **k)))
    assert hol(1, 12, month=4, year=2024), "Easter Monday 2024 falls in the month after Easter Sunday"
    assert all(hol(d, 12, month=m) for m, d in ((1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 26)))
    assert not hol(24, 12, month=12) and not hol(7, 12, month=4), "Christmas Eve and the Tuesday after Easter are working days"


# ---------------------------------------------------------------- model
TINY = {"features": ["a", "b"], "targets": {"y": {"baseline": 1.0, "trees": [
    # if a <= 5 (missing goes left): 0.5, else: if b <= 2 (missing goes right): -1.0 else 2.0
    {"f": [0, 0, 1, 0, 0], "t": [5.0, 0, 2.0, 0, 0], "l": [1, -1, 3, -1, -1], "r": [2, -1, 4, -1, -1],
     "v": [0, 0.5, 0, -1.0, 2.0], "m": [1, 0, 0, 0, 0]}]}}}


def test_tree_walk_thresholds_and_missing_values():
    m = Model(TINY)
    y = lambda **x: math.log(m.predict(x)["y"])
    assert y(a=5, b=0) == pytest.approx(1.5) and y(a=5.0001, b=2) == pytest.approx(0.0), "<= goes left"
    assert y(a=9, b=3) == pytest.approx(3.0)
    assert y(a=None, b=3) == pytest.approx(1.5), "missing value: this node sends it left"
    assert y(a=9, b=None) == pytest.approx(3.0), "this one sends it right"
    assert y(b=3, a=9, unknown=1) == pytest.approx(3.0), "values are taken by name, extra ones ignored"
    assert y() == pytest.approx(1.5), "a feature that is not given is missing"
    assert m.meta == {"features": ["a", "b"]}


def test_shipped_model_reports_how_good_it_is(model):
    meta = model.meta
    assert meta["trained_on"] == "simulated" and meta["sites_test"] >= 30 and meta["rows_train"] > 100000
    for target in features.TARGETS:
        m = meta["metrics"][target]
        assert m["d2"] > m["d2_naive"] and m["mae"] <= m["mae_naive"], "better than the average week, on unseen crossings"
        assert 0 < len(model.targets[target]["trees"]) <= 200
    assert os.path.getsize(MODEL_PATH) < 1_000_000, "small enough to live in the repository and in the app"


def test_model_is_sane_over_a_whole_week(model):
    for ctx in (CENTRE, SUBURB, {}):
        week = [model.predict(features.row(local(12, 0) + h * 3600, ctx)) for h in range(7 * 24)]
        assert all(math.isfinite(v) and 0 < v < 2000 for p in week for v in p.values())
        peds = [p["ped_in"] + p["ped_out"] for p in week]
        nights = [peds[d * 24 + 3] for d in range(7)]
        assert max(nights) < 0.2 * max(peds), "3 a.m. is quiet every day"
    centre = [model.predict(features.row(local(12, 0) + h * 3600, CENTRE)) for h in range(7 * 24)]
    assert centre[8]["ped_in"] > 2 * centre[5 * 24 + 8]["ped_in"], "Monday 8 a.m. against Saturday 8 a.m.: commuters"
    assert centre[8]["ped_in"] > centre[8]["ped_out"] and centre[18]["ped_out"] > centre[18]["ped_in"], \
        "the morning flow goes one way, the evening one comes back"


# ---------------------------------------------------------------- fusion
def test_gamma_quantiles_are_close_to_the_exact_ones():
    # exact values of the Gamma quantile function (shape, rate 1): scipy.stats.gamma.ppf
    exact = {(10, 0.1): 6.221, (10, 0.5): 9.669, (10, 0.9): 14.206, (2, 0.1): 0.532, (2, 0.9): 3.890, (50, 0.5): 49.667}
    for (shape, p), value in exact.items():
        assert fusion.gamma_quantile(shape, 1.0, p) == pytest.approx(value, rel=0.03)
    assert fusion.gamma_quantile(10, 4.0, 0.5) == pytest.approx(9.669 / 4, rel=0.03), "the rate only rescales"
    qs = [fusion.gamma_quantile(3.0, 1.0, p) for p in (0.05, 0.25, 0.5, 0.75, 0.95)]
    assert qs == sorted(qs) and qs[0] > 0
    assert fusion.gamma_quantile(1e-9, 1.0, 0.1) == 0.0, "nearly no evidence of anything: zero, never negative"


def test_posterior_weights_and_interval():
    assert fusion.posterior(0.0, [])["mean"] == pytest.approx(fusion.MIN_RATE), "a rate is never exactly zero"
    one = fusion.posterior(8.0, [(20, 1.0, 0.0)])
    assert one["mean"] == pytest.approx((8 + 20) / 2) and one["weight"] == pytest.approx(0.5), "model and one window weigh the same"
    assert fusion.posterior(8.0, [(20, 1.0, -30.0)]) == one, "a window that ends a moment in the future is just fresh"
    half = fusion.posterior(8.0, [(20, 1.0, fusion.HALF_LIFE_S)])
    assert half["mean"] == pytest.approx((8 + 10) / 1.5) and half["weight"] == pytest.approx(1 / 3)
    few, many = fusion.posterior(8.0, [(8, 1.0, 0.0)]), fusion.posterior(8.0, [(8, 1.0, 0.0)] * 12)
    assert many["hi"] - many["lo"] < 0.5 * (few["hi"] - few["lo"]), "more counts, narrower interval"
    assert all(p["lo"] < p["mean"] < p["hi"] for p in (one, half, few, many))
    wide = fusion.posterior(8.0, [(8, 1.0, 0.0)], level=0.95)
    assert wide["lo"] < few["lo"] and wide["hi"] > few["hi"]


# ---------------------------------------------------------------- service
def test_outlook_starts_at_the_next_clock_hour_whatever_the_minute(model):
    now = local(12, 18, 37)
    look = forecaster(model, now=now).forecast(NODE, [], now=now)["outlook"]
    assert len(look) == 1 + OUTLOOK_HOURS and look[0]["now"] and (look[0]["t0"], look[0]["t1"]) == (now, now + 3600)
    assert look[1]["t0"] == local(12, 19) and all(b["t0"] - a["t0"] == 3600 for a, b in zip(look[1:], look[2:]))
    assert all(x["t1"] - x["t0"] == 3600 and "now" not in x for x in look[1:])
    assert set(look[5]) == set(features.TARGETS) | {"t0", "t1"}
    at_19_sharp = forecaster(model, now=local(12, 19)).forecast(NODE, [], now=local(12, 19))["outlook"]
    assert at_19_sharp[1]["t0"] == local(12, 20), "on the hour, the next hour is the one after"


def test_counts_of_hours_ago_calibrate_but_are_not_the_present(model):
    f = forecaster(model)
    base = f.forecast(NODE, [])["estimate"]["ped_in"]["model"]
    old = windows(MONDAY_18, 8, 900, ped_in=round(3 * base), end=MONDAY_18 - 3 * 3600)
    out = f.forecast(NODE, old)
    assert out["mode"] == "model_only" and out["history_windows"] == 8, "nothing counted in the last two hours"
    assert out["estimate"]["ped_in"]["node_weight"] == 0 and out["anomaly"] is None
    assert out["calibration"]["ped_in"] > 1.3, "but the node did say this crossing is busier than its surroundings"
    assert out["estimate"]["ped_in"]["mean"] == pytest.approx(base * out["calibration"]["ped_in"], rel=0.02)


def test_windows_that_cannot_be_right_are_ignored(model):
    f = forecaster(model)
    good = windows(MONDAY_18, 4, 900, ped_in=50)
    future = windows(MONDAY_18, 2, 900, ped_in=9999, end=MONDAY_18 + 7200)
    empty = [dict(good[0], t0=good[0]["t1"], ped_in=9999)]
    assert f.forecast(NODE, good + future + empty) == f.forecast(NODE, good), "a wrong clock or an empty window"
    assert f.forecast(NODE, good)["history_windows"] == 4


def test_history_is_limited_to_the_most_recent_windows(model):
    f = forecaster(model)
    quiet_then_busy = windows(MONDAY_18, 300, 60, ped_in=0, end=MONDAY_18 - HISTORY_WINDOWS * 60) + \
        windows(MONDAY_18, HISTORY_WINDOWS, 60, ped_in=3)
    out = f.forecast(NODE, quiet_then_busy)
    assert out["history_windows"] == HISTORY_WINDOWS
    assert out == f.forecast(NODE, quiet_then_busy[-HISTORY_WINDOWS:]), "five hours of zeros before that do not matter"


def test_each_class_follows_its_own_counts(model):
    f = forecaster(model, parts=SUBURB)
    plain = f.forecast(NODE, [])["estimate"]
    cars = f.forecast(NODE, windows(MONDAY_18, 8, 900, ped_in=round(plain["ped_in"]["model"]),
                                    ped_out=round(plain["ped_out"]["model"]), vehicles=round(3 * plain["vehicles"]["model"]),
                                    cyclist=round(plain["cyclist"]["model"])))["estimate"]
    assert cars["vehicles"]["mean"] > 2 * plain["vehicles"]["mean"], "three times the cars"
    assert cars["ped_in"]["mean"] == pytest.approx(plain["ped_in"]["mean"], rel=0.35), "and the usual pedestrians"


def test_anomaly_needs_enough_people_and_goes_both_ways(model):
    f = forecaster(model)
    base = f.forecast(NODE, [])["estimate"]["ped_in"]["model"]
    usual = windows(MONDAY_18, 8, 900, ped_in=round(base))
    assert f.forecast(NODE, usual)["anomaly"]["level"] == "normal"
    empty_hour = [dict(w, ped_in=0) if i >= 4 else w for i, w in enumerate(usual)]
    low = f.forecast(NODE, empty_hour)["anomaly"]
    assert low["level"] == "low" and low["measured"] == 0 and low["expected"] >= ANOMALY_MIN_EXPECTED
    assert low["ratio"] == 0.0 and f.forecast(NODE, empty_hour)["estimate"]["ped_in"]["mean"] < base

    night = local(13, 3)                                             # 3 a.m.: a handful of people expected
    quiet = forecaster(model, parts=SUBURB, now=night)
    out = quiet.forecast(NODE, windows(night, 8, 900, ped_in=2), now=night)
    assert out["anomaly"] is None, "three people instead of one is not a crowd: too few to tell"
    assert out["mode"] == "fused"


def test_estimate_narrows_as_the_node_counts(model):
    f = forecaster(model)
    base = f.forecast(NODE, [])["estimate"]["ped_in"]
    counted = f.forecast(NODE, windows(MONDAY_18, 8, 900, ped_in=round(base["model"])))["estimate"]["ped_in"]
    assert (counted["hi"] - counted["lo"]) < 0.7 * (base["hi"] - base["lo"])
    assert counted["model"] == base["model"], "what the surroundings alone suggest does not depend on the counts"
    assert 0 < counted["node_weight"] < 1 and base["node_weight"] == 0


def test_forecast_is_plain_data_with_stable_keys(model):
    out = forecaster(model).forecast(NODE, windows(MONDAY_18, 8, 900, ped_in=40, ped_out=35, vehicles=3))
    assert json.loads(json.dumps(out)) == out, "numbers, strings, lists and dicts: it goes to the page as JSON"
    assert set(out) == {"available", "node", "now", "window_s", "mode", "estimate", "outlook", "anomaly", "calibration",
                        "history_windows", "inputs", "sources", "model"}, "the dashboard reads these"
    assert set(out["estimate"]["ped_in"]) == {"mean", "lo", "hi", "model", "node_weight"}
    assert set(out["anomaly"]) == {"ratio", "measured", "expected", "level"}
    assert set(out["sources"]) == {"places", "google", "esa", "weather", "traffic", "google_key", "located", "pending"}
    assert set(out["inputs"]) == set(features.FEATURES) - {"hour", "dow"} and out["window_s"] == 900
    assert out["node"] == "nodo01" and out["now"] == MONDAY_18


def test_forecaster_default_setup_reads_the_key_and_a_cache_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("MDGB_HOME", str(tmp_path))
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "KEY")
    with_key = Forecaster()
    assert with_key.context.cache_file == str(tmp_path / "forecast-context.json"), "next to the app's settings"
    assert {"google", "traffic"} <= set(with_key.context.fetchers)
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "")
    assert set(Forecaster().context.fetchers) == {"weather", "esa", "poi"}, "an empty key is no key"
    out = Forecaster(context=Context(None, {}, background=False)).forecast({"id": "x"}, [])
    assert out["sources"]["google_key"] is False and out["sources"]["located"] is False


# ---------------------------------------------------------------- simulated history and training
def test_simulation_is_reproducible_and_plausible():
    np = pytest.importorskip("numpy")
    from forecast.simulate import WINDOWS_PER_DAY, simulate

    X, Y, site = simulate(n_sites=40, days=4, seed=7)
    again = simulate(n_sites=40, days=4, seed=7)
    assert np.array_equal(X, again[0], equal_nan=True) and np.array_equal(Y, again[1]), "same seed, same history"
    assert not np.array_equal(Y, simulate(n_sites=40, days=4, seed=8)[1])
    assert X.shape == (40 * 4 * WINDOWS_PER_DAY, len(features.FEATURES)) and (np.bincount(site) == 4 * WINDOWS_PER_DAY).all()
    col = {k: X[:, i] for i, k in enumerate(features.FEATURES)}
    inside = lambda k, lo, hi: np.nanmin(col[k]) >= lo and np.nanmax(col[k]) <= hi
    assert inside("hour", 0, 24) and inside("dow", 0, 6) and inside("holiday", 0, 1) and inside("road", 0, 4)
    assert all(inside(k, 0, 1) for k in ("esa_built", "esa_green", "esa_water", "open_share")) and inside("rain_mm", 0, 50)
    assert (np.nansum([col["esa_built"], col["esa_green"], col["esa_water"]], axis=0) <= 1.0001).all()
    assert (Y >= 0).all() and (Y == np.round(Y)).all(), "counts"
    for name in ("poi_pop", "traffic", "esa_built", "poi_food", "temp_c", "rain_mm"):
        assert 0.02 < np.isnan(col[name]).mean() < 0.8, "%s is sometimes missing, as in the field" % name
    assert not np.isnan(col["hour"]).any() and not np.isnan(col["dow"]).any(), "the calendar is always known"

    peds = Y[:, 0] + Y[:, 1]
    day, night = (col["hour"] > 8) & (col["hour"] < 20), col["hour"] < 5
    assert peds[day].mean() > 5 * peds[night].mean()
    busy = col["poi_transit"] >= np.nanpercentile(col["poi_transit"], 75)
    calm = col["poi_transit"] <= np.nanpercentile(col["poi_transit"], 25)
    assert peds[busy].mean() > 1.5 * peds[calm].mean(), "more stops and places, more people"
    cyclists, wet, dry = Y[:, 2], col["rain_mm"] > 1, col["rain_mm"] == 0
    assert cyclists[wet & day].mean() < 0.7 * cyclists[dry & day].mean(), "rain keeps the bicycles at home"
    main, footpath = col["road"] == 4, col["road"] == 0
    assert Y[main, 3].mean() > 20 * Y[footpath, 3].mean(), "cars are on the main roads"


def test_naive_profile_is_the_average_of_each_quarter_hour_of_the_week():
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    from forecast.train import naive_profile

    X = np.full((4, len(features.FEATURES)), np.nan)
    hour, dow = features.FEATURES.index("hour"), features.FEATURES.index("dow")
    X[:, hour], X[:, dow] = [8.1, 8.2, 8.3, 20.0], [0, 0, 1, 0]             # Monday 8:00-8:15 twice, Tuesday, Monday 20
    predict = naive_profile(X, np.array([10.0, 20.0, 7.0, 3.0]))
    assert list(predict(X)) == [15.0, 15.0, 7.0, 3.0]
    never_seen = np.array(X[:1])
    never_seen[0, dow] = 6
    assert predict(never_seen)[0] == 0.0


def test_training_writes_a_model_the_app_can_read(tmp_path, monkeypatch, capsys):
    pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    from forecast import train

    out = tmp_path / "model.json"
    monkeypatch.setattr(sys, "argv", ["train", "--sites", "36", "--test-sites", "12", "--days", "3", "--out", str(out)])
    monkeypatch.setattr(train, "PARAMS", dict(train.PARAMS, max_iter=15))
    train.main()
    assert "pure-Python predictor vs scikit-learn" in capsys.readouterr().out
    small = Model.load(str(out))
    assert tuple(small.features) == features.FEATURES and tuple(small.targets) == features.TARGETS
    assert small.meta["sites_train"] == 24 and small.meta["sites_test"] == 12 and small.meta["trained_on"] == "simulated"
    assert all(len(small.targets[t]["trees"]) == 15 for t in features.TARGETS)
    rush, night = small.predict(features.row(MONDAY_18, CENTRE)), small.predict(features.row(local(12, 3), CENTRE))
    assert rush["ped_in"] > 3 * night["ped_in"], "even a small model learns the day"
    assert forecaster(small).forecast(NODE, [])["available"]


def test_training_refuses_a_model_that_does_not_match(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    from forecast import train

    out = tmp_path / "model.json"
    monkeypatch.setattr(sys, "argv", ["train", "--sites", "36", "--test-sites", "12", "--days", "3", "--out", str(out)])
    monkeypatch.setattr(train, "PARAMS", dict(train.PARAMS, max_iter=5))
    broken = lambda est: dict(train_export(est), baseline=0.0)
    train_export = train.export_trees
    monkeypatch.setattr(train, "export_trees", broken)
    with pytest.raises(SystemExit, match="does not match"):
        train.main()
    assert not out.exists(), "a wrong model.json never reaches the app"


# ---------------------------------------------------------------- what the app relies on
def source_of(name):
    with open(os.path.join(FORECAST_DIR, name + ".py"), encoding="utf-8") as f:
        return f.read()


def test_every_module_is_either_runtime_or_training():
    modules = {f[:-3] for f in os.listdir(FORECAST_DIR) if f.endswith(".py")} - {"__init__"}
    assert modules == set(RUNTIME) | set(TRAINING), "a new module must be declared here, and in the app bundle if runtime"


def test_runtime_modules_need_only_the_standard_library():
    allowed = set(sys.stdlib_module_names) | {"certifi"}            # certifi is optional: sources.py works without
    for name in RUNTIME + ("__init__",):
        for node in ast.walk(ast.parse(source_of(name))):
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [] if node.level else [node.module.split(".")[0]]
                assert node.level == 0 or (node.module or "") not in TRAINING, "%s imports the training code" % name
            else:
                continue
            assert set(roots) <= allowed, "%s imports %s: the app has no such package" % (name, roots)


def test_runtime_modules_are_valid_python_3_9():
    for name in RUNTIME + ("__init__",):
        ast.parse(source_of(name), feature_version=(3, 9))          # the app supports Python 3.9 (app/README.md)


def test_app_bundle_contains_the_runtime_and_the_model():
    with open(os.path.join(REPO, "app", "desktop", "centrale.spec"), encoding="utf-8") as f:
        spec = f.read()
    listed = re.search(r'\["forecast\." \+ m for m in \(([^)]*)\)\]', spec)
    assert listed, "the spec lists the forecast modules to put in the app"
    assert set(re.findall(r'"(\w+)"', listed.group(1))) == set(RUNTIME), "every runtime module, and no training code"
    assert 'os.path.join(AI, "forecast", "model.json"), "forecast"' in spec, "the trained model goes next to model.py"
    assert "pathex=[APP, AI]" in spec
    with open(os.path.join(REPO, "app", "requirements.txt"), encoding="utf-8") as f:
        packages = {line.split("==")[0].strip().lower() for line in f if line.strip() and not line.startswith("#")}
    assert not packages & {"numpy", "scikit-learn", "scipy"}, "the app stays light: inference is pure Python"
