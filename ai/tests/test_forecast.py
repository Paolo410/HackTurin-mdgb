"""Expected-flow model (ai/forecast): no network, no hardware. The sources are tested on canned answers."""
import json
import math
import struct
import threading
import time
import zlib

import pytest

from forecast import features, fusion, sources
from forecast.context import RETRY_S, TTL_S, Context
from forecast.model import Model
from forecast.service import NEXT_WINDOWS, Forecaster

CENTRE = {"poi": {"food": 60, "shop": 140, "transit": 10, "edu": 2, "leisure": 60, "road": 0},
          "esa": {"built": 0.95, "green": 0.03, "water": 0.0}}
SUBURB = {"poi": {"food": 2, "shop": 8, "transit": 2, "edu": 1, "leisure": 3, "road": 4},
          "esa": {"built": 0.6, "green": 0.35, "water": 0.0}}


def local(day, hour, minute=0, month=10, year=2026):
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


MONDAY_18 = local(12, 18)           # 12 October 2026 is a Monday


@pytest.fixture(scope="module")
def model():
    return Model.load()


# ---------------------------------------------------------------- model
def test_model_file_is_the_one_the_code_expects(model):
    assert tuple(model.features) == features.FEATURES
    assert tuple(model.targets) == features.TARGETS
    assert model.meta["trained_on"] == "simulated" and model.meta["window_s"] == features.WINDOW_S


def test_model_follows_the_day_the_place_and_the_weather(model):
    p = lambda ts, ctx: model.predict(features.row(ts, ctx))
    peds = lambda x: x["ped_in"] + x["ped_out"]
    rush, night = p(MONDAY_18, CENTRE), p(local(12, 3), CENTRE)
    assert peds(rush) > 10 * peds(night), "rush hour against 3 a.m."
    assert peds(rush) > 3 * peds(p(MONDAY_18, SUBURB)), "city centre against suburb"
    assert rush["vehicles"] < 0.1 * p(MONDAY_18, SUBURB)["vehicles"], "pedestrian street against main road"
    wet = dict(CENTRE, weather={"hourly": [[MONDAY_18, 14.0, 4.0]]})
    dry = dict(CENTRE, weather={"hourly": [[MONDAY_18, 14.0, 0.0]]})
    assert peds(p(MONDAY_18, wet)) < 0.8 * peds(p(MONDAY_18, dry)), "rain keeps people at home"
    assert p(MONDAY_18, wet)["cyclist"] < 0.5 * p(MONDAY_18, dry)["cyclist"], "and cyclists even more"


def test_model_works_with_no_source_at_all(model):
    out = model.predict(features.row(MONDAY_18, {}))
    assert set(out) == set(features.TARGETS)
    assert all(math.isfinite(v) and v > 0 for v in out.values())


def test_training_export_matches_scikit_learn():
    np = pytest.importorskip("numpy")
    ensemble = pytest.importorskip("sklearn.ensemble")
    from forecast.simulate import simulate
    from forecast.train import export_trees

    X, Y, site = simulate(n_sites=12, days=2, seed=3)
    assert X.shape == (12 * 2 * 96, len(features.FEATURES)) and Y.shape == (len(X), len(features.TARGETS))
    assert np.isnan(X).any() and (Y >= 0).all()
    est = ensemble.HistGradientBoostingRegressor(loss="poisson", max_iter=8, max_leaf_nodes=6).fit(X, Y[:, 0])
    small = Model({"features": list(features.FEATURES), "targets": {"ped_in": export_trees(est)}})
    for i in range(0, len(X), 97):
        row = {k: None if math.isnan(v) else float(v) for k, v in zip(features.FEATURES, X[i])}
        assert small.predict(row)["ped_in"] == pytest.approx(float(est.predict(X[i:i + 1])[0]), rel=1e-4)


# ---------------------------------------------------------------- features
def test_holidays():
    assert features.easter(2026) == (4, 5) and features.easter(2027) == (3, 28)
    hol = lambda *a, **k: features.is_holiday(time.localtime(local(*a, **k)))
    assert hol(25, 12, month=12) and hol(1, 12, month=5)
    assert hol(6, 12, month=4), "Easter Monday 2026"
    assert not hol(13, 12), "an ordinary Tuesday"


def test_row_takes_what_each_source_gives():
    ctx = dict(CENTRE, google={"counts": {"food": 20}, "pop": 310.5, "open_week": [[0.5] * 24] * 7},
               weather={"hourly": [[MONDAY_18 - 600, 14.5, 0.3]]}, traffic={"ratio": 1.4, "at": MONDAY_18 - 900})
    f = features.row(MONDAY_18, ctx)
    assert (f["hour"], f["dow"], f["holiday"], f["road"]) == (18.0, 0, 0, 0)
    assert (f["poi_food"], f["poi_pop"], f["open_share"]) == (60, 310.5, 0.5), "counts from OpenStreetMap, not capped at 20"
    assert (f["esa_built"], f["temp_c"], f["rain_mm"], f["traffic"]) == (0.95, 14.5, 0.3, 1.4)
    later = features.row(MONDAY_18 + 3 * 3600, ctx, env={"t_c": 9.0})
    assert later["traffic"] is None, "live traffic says nothing about three hours from now"
    assert (later["temp_c"], later["rain_mm"]) == (9.0, None), "no forecast that far: the node's thermometer"
    assert features.row(MONDAY_18, {"google": {"counts": {"food": 20}}})["poi_food"] == 20, "Google if OSM is down"


# ---------------------------------------------------------------- fusion
def test_fusion_goes_from_the_model_to_the_node():
    alone = fusion.posterior(10.0, [])
    assert alone["mean"] == pytest.approx(10.0) and alone["weight"] == 0
    assert alone["lo"] < 10.0 < alone["hi"]
    many = fusion.posterior(10.0, [(30, 1.0, 60.0)] * 20)
    assert many["mean"] == pytest.approx(30.0, rel=0.1) and many["weight"] > 0.85
    assert many["hi"] - many["lo"] < alone["hi"] - alone["lo"] + 10, "more evidence, no wider interval"
    one_recent, one_old = fusion.posterior(10.0, [(30, 1.0, 0.0)]), fusion.posterior(10.0, [(30, 1.0, 7200.0)])
    assert one_recent["mean"] > one_old["mean"] > 10.0, "an old window weighs less"


def test_fusion_understands_short_windows():
    # the demo sends 60 s windows: 2 pedestrians a minute are 30 every quarter of an hour
    minute = [(2, 60 / 900.0, 60.0 * i) for i in range(30)]
    assert fusion.posterior(30.0, minute)["mean"] == pytest.approx(30.0, rel=0.02)
    assert 15.0 < fusion.posterior(5.0, minute)["mean"] < 30.0, "half an hour of counts against a model that says 5"


def test_calibration_needs_evidence():
    assert fusion.calibration(0, 0) == 1.0
    assert 1.0 < fusion.calibration(6, 2) < 2.0, "few counts: pulled towards 1"
    assert fusion.calibration(600, 200) == pytest.approx(3.0, rel=0.05)
    assert fusion.calibration(10000, 10) == 5.0 and fusion.calibration(0, 10000) == 0.2


# ---------------------------------------------------------------- sources (canned answers)
def test_osm_counts_and_road_class():
    seen = {}

    def http(url, data=None, headers=None, timeout=None):
        seen["query"] = data.decode()
        els = [{"type": "count", "tags": {"total": str(n)}} for n in (76, 178, 14, 2, 94)]
        els += [{"type": "way", "tags": {"highway": "footway"}}, {"type": "way", "tags": {"highway": "secondary_link"}},
                {"type": "way", "tags": {"highway": "construction"}}]
        return json.dumps({"elements": els}).encode()

    out = sources.osm_pois(45.0679, 7.6829, http=http)
    assert out == {"food": 76, "shop": 178, "transit": 14, "edu": 2, "leisure": 94, "road": 3}
    assert "around%3A300%2C45.067900%2C7.682900" in seen["query"]
    with pytest.raises(ValueError):
        sources.osm_pois(45.0, 7.0, http=lambda *a, **k: b'{"elements": []}')


def test_open_meteo_hours():
    body = {"hourly": {"time": [1791684000, 1791687600], "temperature_2m": [12.6, 12.5], "precipitation": [0.0, 1.2]}}
    out = sources.open_meteo(45.0679, 7.6829, http=lambda url, **k: json.dumps(body).encode())
    assert out == {"hourly": [[1791684000, 12.6, 0.0], [1791687600, 12.5, 1.2]]}
    assert features.weather_at(out, 1791687000) == (12.5, 1.2)
    assert features.weather_at(out, 1791687600 + 3 * 3600) is None


def tiled_tiff(pixels, tile=32, lon0=6.0, lat0=48.0, scale=1 / 12000.0):
    """A small GeoTIFF laid out like ESA WorldCover: little-endian, 8 bit, deflate, square tiles."""
    h, w = len(pixels), len(pixels[0])
    tiles = [zlib.compress(bytes(pixels[r][c] for r in range(tr, tr + tile) for c in range(tc, tc + tile)))
             for tr in range(0, h, tile) for tc in range(0, w, tile)]
    n = len(tiles)
    entries = [(256, 3, 1, w), (257, 3, 1, h), (258, 3, 1, 8), (259, 3, 1, 8), (317, 3, 1, 1), (322, 3, 1, tile),
               (323, 3, 1, tile), (324, 4, n, None), (325, 4, n, None), (33550, 12, 3, None), (33922, 12, 6, None)]
    at = 8 + 2 + 12 * len(entries) + 4
    extra = {324: at, 325: at + 4 * n, 33550: at + 8 * n, 33922: at + 8 * n + 24}
    data_at = at + 8 * n + 24 + 48
    offsets = [data_at + sum(len(t) for t in tiles[:i]) for i in range(n)]
    out = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", len(entries))
    for tag, typ, count, value in entries:
        out += struct.pack("<HHII", tag, typ, count, extra.get(tag, value))
    out += struct.pack("<I", 0) + struct.pack("<%dI" % n, *offsets) + struct.pack("<%dI" % n, *map(len, tiles))
    out += struct.pack("<3d", scale, scale, 0.0) + struct.pack("<6d", 0.0, 0.0, 0.0, lon0, lat0, 0.0)
    return out + b"".join(tiles)


def test_worldcover_reads_the_tiles_around_the_point():
    # 64x64 pixels, 4 tiles: left half built-up (50), right half trees (10), one corner of water far from the point
    pixels = [[80 if r < 4 and c < 4 else 50 if c < 32 else 10 for c in range(64)] for r in range(64)]
    blob, asked = tiled_tiff(pixels), []

    def http(url, data=None, headers=None, timeout=None):
        a, b = map(int, headers["Range"].split("=")[1].split("-"))
        asked.append((url, a, b))
        return blob[a:b + 1]

    lat, lon = 48.0 - 32 / 12000.0, 6.0 + 32 / 12000.0            # centre of the image
    out = sources.esa_worldcover(lat, lon, radius_m=100, http=http)
    assert "ESA_WorldCover_10m_2021_v200_N45E006_Map.tif" in asked[0][0]
    assert out["built"] == pytest.approx(0.5, abs=0.03) and out["green"] == pytest.approx(0.5, abs=0.03)
    assert out["water"] == 0 and 500 < out["pixels"] < 600, "a circle of 100 m (pixels of 9 x 6 m), not the image"
    assert len(asked) == 1 + 4, "the header, then the four tiles around the point"
    assert sources.worldcover_tile(45.07, 7.68) == "N45E006" and sources.worldcover_tile(-33.9, -70.6) == "S36W072"
    with pytest.raises(ValueError):
        sources.esa_worldcover(lat, lon, http=lambda url, **k: b"not a tiff")


def test_google_places_reviews_and_opening_hours():
    shop = {"userRatingCount": 99, "regularOpeningHours": {"periods": [
        {"open": {"day": 1, "hour": 9, "minute": 0}, "close": {"day": 1, "hour": 19, "minute": 30}}]}}   # Monday 9-19:30
    club = {"userRatingCount": 9, "regularOpeningHours": {"periods": [
        {"open": {"day": 6, "hour": 22, "minute": 0}, "close": {"day": 0, "hour": 4, "minute": 0}}]}}    # Saturday night
    always = {"regularOpeningHours": {"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]}}
    week = sources.open_week([shop, club, always, {"userRatingCount": 5}])
    third = pytest.approx(1 / 3, abs=0.001)
    assert week[0][8] == third and week[0][9] == week[0][19] == pytest.approx(2 / 3, abs=0.001)
    assert week[5][23] == week[6][3] == pytest.approx(2 / 3, abs=0.001) and week[6][4] == third
    assert sources.open_week([{"userRatingCount": 5}]) is None

    calls = []

    def http(url, data=None, headers=None, timeout=None):
        calls.append((json.loads(data), headers))
        return json.dumps({"places": [shop, club]}).encode()

    out = sources.google_places(45.0679, 7.6829, "KEY", http=http)
    assert len(calls) == len(features.CATEGORIES) and calls[0][1]["X-Goog-Api-Key"] == "KEY"
    assert calls[0][0]["locationRestriction"]["circle"]["radius"] == 300.0 and calls[0][0]["maxResultCount"] == 20
    assert out["counts"]["food"] == 2 and out["pop"] == pytest.approx(5 * (math.log(100) + math.log(10)), abs=0.01)
    assert out["open_week"][0][10] == 0.5


def test_google_traffic_ratio():
    http = lambda url, **k: json.dumps({"routes": [{"duration": "150s", "staticDuration": "100s"}]}).encode()
    assert sources.google_traffic(45.0679, 7.6829, "KEY", http=http) == {"ratio": 1.5}


# ---------------------------------------------------------------- context cache
def test_context_caches_retries_and_survives_restarts(tmp_path):
    clock, calls = [1000000.0], {"poi": 0, "weather": 0}

    def poi(lat, lon):
        calls["poi"] += 1
        return dict(CENTRE["poi"])

    def weather(lat, lon):
        calls["weather"] += 1
        raise OSError("no network")

    path = str(tmp_path / "ctx.json")
    ctx = Context(path, {"poi": poi, "weather": weather}, clock=lambda: clock[0], background=False)
    assert ctx.get(45.0, 7.0) == {"pending": False}, "nothing cached yet, and get() never asks the network itself"
    ctx.refresh(45.0, 7.0)
    got = ctx.get(45.0, 7.0)
    assert got["poi"]["food"] == 60 and got["poi"]["at"] == clock[0] and "weather" not in got
    ctx.refresh(45.0, 7.0)
    assert calls == {"poi": 1, "weather": 1}, "fresh data is not asked again, a failure not before a few minutes"
    clock[0] += RETRY_S + 1
    ctx.refresh(45.0, 7.0)
    assert calls == {"poi": 1, "weather": 2}
    clock[0] += TTL_S["poi"]
    ctx.refresh(45.0, 7.0)
    assert calls["poi"] == 2

    again = Context(path, {}, clock=lambda: clock[0], background=False)
    assert again.get(45.0, 7.0)["poi"]["food"] == 60, "the cache is on disk"
    assert again.get(None, None) == {"pending": False}, "a camera without coordinates"


def test_context_get_does_not_wait_for_the_network():
    release, started = threading.Event(), threading.Event()

    def slow(lat, lon):
        started.set()
        release.wait(5)
        return {"built": 0.9}

    ctx = Context(None, {"esa": slow})
    t = time.time()
    first = ctx.get(45.0, 7.0)
    assert time.time() - t < 0.5 and first == {"pending": True}
    assert started.wait(2) and ctx.get(45.0, 7.0)["pending"] is True
    release.set()
    for _ in range(100):
        if "esa" in ctx.get(45.0, 7.0):
            break
        time.sleep(0.02)
    assert ctx.get(45.0, 7.0)["esa"]["built"] == 0.9


# ---------------------------------------------------------------- service
NODE = {"id": "nodo01", "name": "Via Roma", "lat": 45.0679, "lon": 7.6829}


def forecaster(model, parts=CENTRE, now=MONDAY_18):
    ctx = Context(None, {k: (lambda lat, lon, v=v: dict(v)) for k, v in parts.items()}, clock=lambda: now,
                  background=False)
    ctx.refresh(NODE["lat"], NODE["lon"])
    return Forecaster(model, ctx, clock=lambda: now)


def windows(now, n, length, ped_in, ped_out=0, vehicles=0):
    t1 = int(now // length) * length
    return [{"t0": t1 - (i + 1) * length, "t1": t1 - i * length, "ped_in": ped_in, "ped_out": ped_out, "cyclist": 0,
             "vehicles": vehicles, "animals": 0, "provisional": False, "env": {"t_c": 14.0}} for i in reversed(range(n))]


def test_forecast_for_a_camera_that_never_sent_data(model):
    out = forecaster(model).forecast(NODE, [])
    json.dumps(out)
    assert out["available"] and out["mode"] == "model_only" and out["history_windows"] == 0
    assert out["calibration"] == dict.fromkeys(features.TARGETS, 1.0) and out["anomaly"] is None
    est = out["estimate"]["ped_in"]
    assert est["mean"] == pytest.approx(est["model"], rel=0.01) and est["lo"] < est["mean"] < est["hi"]
    assert len(out["next"]) == NEXT_WINDOWS and out["next"][0]["t0"] <= MONDAY_18 < out["next"][0]["t1"]
    assert out["next"][1]["t0"] - out["next"][0]["t0"] == 900
    assert out["sources"] == {"places": "osm", "google": False, "esa": True, "weather": False, "traffic": False,
                              "google_key": False, "located": True, "pending": False}
    assert out["inputs"]["poi_food"] == 60 and out["inputs"]["esa_built"] == 0.95


def test_forecast_follows_what_the_node_counts(model):
    f = forecaster(model)
    base = f.forecast(NODE, [])["estimate"]["ped_in"]["model"]
    busy = f.forecast(NODE, windows(MONDAY_18, 8, 900, ped_in=round(3 * base)))
    est = busy["estimate"]["ped_in"]
    assert busy["mode"] == "fused" and busy["history_windows"] == 8
    assert est["mean"] > 2 * base and est["node_weight"] > 0.5, "the estimate moves to the counts"
    assert busy["calibration"]["ped_in"] > 1.5, "and the next hours are scaled the same way"
    assert busy["next"][4]["ped_in"] > 1.5 * f.forecast(NODE, [])["next"][4]["ped_in"]
    assert busy["anomaly"]["level"] == "normal", "three times the surroundings, but normal for this crossing"

    quiet_then_crowd = windows(MONDAY_18, 8, 900, ped_in=round(base))
    for w in quiet_then_crowd[-2:]:
        w["ped_in"] = round(8 * base)
    assert f.forecast(NODE, quiet_then_crowd)["anomaly"]["level"] == "high"


def test_forecast_with_the_one_minute_windows_of_the_demo(model):
    out = forecaster(model).forecast(NODE, windows(MONDAY_18, 60, 60, ped_in=4))
    assert out["mode"] == "fused" and out["history_windows"] == 60
    assert out["estimate"]["ped_in"]["mean"] == pytest.approx(60.0, rel=0.2), "4 a minute are 60 every 15 minutes"


def test_forecast_without_coordinates_or_sources(model):
    out = Forecaster(model, Context(None, {}, background=False), clock=lambda: MONDAY_18).forecast({"id": "nodo09"}, [])
    assert out["available"] and out["sources"]["located"] is False and out["sources"]["places"] is None
    assert out["estimate"]["ped_in"]["mean"] > 0
