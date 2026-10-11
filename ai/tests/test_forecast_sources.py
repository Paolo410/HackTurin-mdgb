"""Data sources and cache of the expected-flow model (ai/forecast/sources.py, context.py).

No Internet: what the services would answer is canned, and where the HTTP exchange itself matters (headers,
range requests, errors, timeouts) a small web server runs on this machine.
"""
import http.server
import json
import math
import threading
import time
import urllib.error
import urllib.parse
from types import SimpleNamespace

import pytest

from forecast import features, sources
from forecast.context import RETRY_S, TTL_S, Context, default_fetchers
from forecast_helpers import ranged, tiled_tiff

HALF_BUILT = [[50 if c < 32 else 10 for c in range(64)] for r in range(64)]     # left built-up, right trees
MIDDLE = (48.0 - 32 / 12000.0, 6.0 + 32 / 12000.0)                              # centre of a 64x64 image


@pytest.fixture
def server():
    """A web server on this machine: .routes maps a path to its bytes (or to a function), .seen lists the requests."""
    class Handler(http.server.BaseHTTPRequestHandler):
        routes, seen = {}, []

        def log_message(self, *args):
            pass

        def answer(self, body=None):
            self.seen.append({"method": self.command, "path": self.path, "body": body,
                              "headers": {k.lower(): v for k, v in self.headers.items()}})
            found = self.routes.get(self.path.split("?")[0])
            if found is None:
                return self.send_error(404)
            data = found(self) if callable(found) else found
            if self.headers.get("Range"):
                a, b = map(int, self.headers["Range"].split("=")[1].split("-"))
                data = data[a:b + 1]
            self.send_response(206 if self.headers.get("Range") else 200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except OSError:
                pass                                    # the client gave up (timeout test)

        def do_GET(self):
            self.answer()

        def do_POST(self):
            self.answer(self.rfile.read(int(self.headers.get("Content-Length", 0))))

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield SimpleNamespace(url="http://127.0.0.1:%d" % srv.server_port, routes=Handler.routes, seen=Handler.seen)
    srv.shutdown()
    srv.server_close()


# ---------------------------------------------------------------- the HTTP exchange
def test_http_get_post_ranges_errors_and_timeouts(server):
    server.routes["/data"] = b"0123456789"
    assert sources.http(server.url + "/data") == b"0123456789"
    assert server.seen[-1]["method"] == "GET" and server.seen[-1]["headers"]["user-agent"] == sources.USER_AGENT
    assert sources.http(server.url + "/data", headers={"Range": "bytes=2-5"}) == b"2345"
    assert sources.http(server.url + "/data", data=b"q=1", headers={"X-Goog-Api-Key": "K"}) == b"0123456789"
    last = server.seen[-1]
    assert (last["method"], last["body"], last["headers"]["x-goog-api-key"]) == ("POST", b"q=1", "K")
    with pytest.raises(urllib.error.HTTPError):
        sources.http(server.url + "/missing")
    server.routes["/slow"] = lambda handler: time.sleep(1.0) or b"late"
    started = time.time()
    with pytest.raises(OSError):                        # URLError and socket.timeout are both OSError
        sources.http(server.url + "/slow", timeout=0.2)
    assert time.time() - started < 0.9, "a source that hangs is dropped, the app does not wait for it"


def test_worldcover_downloads_only_pieces_of_the_file(server, monkeypatch):
    blob = tiled_tiff(HALF_BUILT) + bytes(200000)       # the real file is 100 MB: here the tail is just weight
    server.routes["/N45E006.tif"] = blob
    monkeypatch.setattr(sources, "WORLDCOVER_URL", server.url + "/%s.tif")
    out = sources.esa_worldcover(*MIDDLE, radius_m=100)
    assert out["built"] == pytest.approx(0.5, abs=0.03) and out["green"] == pytest.approx(0.5, abs=0.03)
    assert all(r["headers"].get("range") for r in server.seen), "every request asks for a range of bytes"
    asked = [tuple(map(int, r["headers"]["range"].split("=")[1].split("-"))) for r in server.seen]
    assert asked[0] == (0, 32767) and sum(b - a + 1 for a, b in asked[1:]) < 1000, "header, then four tiny tiles"


# ---------------------------------------------------------------- ESA WorldCover
def test_worldcover_tile_names():
    assert sources.worldcover_tile(45.0614, 7.6581) == "N45E006"
    assert sources.worldcover_tile(45.0, 6.0) == "N45E006" and sources.worldcover_tile(47.999, 8.999) == "N45E006"
    assert sources.worldcover_tile(48.0, 9.0) == "N48E009"
    assert sources.worldcover_tile(0.5, -0.5) == "N00W003" and sources.worldcover_tile(-0.5, 0.5) == "S03E000"
    assert sources.worldcover_tile(-33.9, -70.6) == "S36W072"


def test_worldcover_ignores_no_data_and_refuses_an_empty_answer():
    half_missing = [[0 if c < 32 else 50 for c in range(64)] for r in range(64)]
    out = sources.esa_worldcover(*MIDDLE, radius_m=100, http=ranged(tiled_tiff(half_missing)))
    assert out["built"] == 1.0 and 230 < out["pixels"] < 330, "shares are over the pixels that have a class"
    nothing = [[0] * 64 for r in range(64)]
    with pytest.raises(ValueError, match="no data"):
        sources.esa_worldcover(*MIDDLE, radius_m=100, http=ranged(tiled_tiff(nothing)))


def test_worldcover_at_the_corner_of_the_file():
    asked = []
    out = sources.esa_worldcover(48.0, 6.0, radius_m=100, http=ranged(tiled_tiff(HALF_BUILT), asked))
    assert out["built"] == 1.0, "the corner is in the built-up half"
    assert 100 < out["pixels"] < 180, "a quarter of the circle: the rest is outside the file"
    assert len(asked) == 2, "the header and the one tile at the corner"


def test_worldcover_reads_tile_tables_beyond_the_first_block():
    # 10000 small tiles: the tables of offsets and sizes (80 kB) do not fit in the 32 kB read at the start
    grass = [[30] * 400 for r in range(400)]
    asked = []
    blob = tiled_tiff(grass, tile=4)
    out = sources.esa_worldcover(48.0 - 390 / 12000.0, 6.0 + 390 / 12000.0, radius_m=30, http=ranged(blob, asked))
    assert out == {"built": 0.0, "green": 1.0, "water": 0.0, "pixels": out["pixels"]} and 30 < out["pixels"] < 70
    assert any(a > 32768 and b - a + 1 == 4 for url, a, b in asked), "single table entries are fetched on demand"
    assert sum(b - a + 1 for url, a, b in asked[1:]) < 2000 and len(blob) > 100000, "a sliver of a big file"


def test_worldcover_refuses_files_it_cannot_read():
    with pytest.raises(ValueError, match="layout"):
        sources.esa_worldcover(*MIDDLE, http=ranged(tiled_tiff(HALF_BUILT, compression=5)))     # LZW
    with pytest.raises(ValueError, match="little-endian"):
        sources.esa_worldcover(*MIDDLE, http=ranged(tiled_tiff(HALF_BUILT, byte_order=b"MM")))
    with pytest.raises(OSError):
        sources.esa_worldcover(*MIDDLE, http=lambda url, **k: (_ for _ in ()).throw(OSError("no network")))


# ---------------------------------------------------------------- OpenStreetMap
def test_overpass_query_asks_for_every_category_and_the_roads():
    seen = {}

    def http(url, data=None, headers=None, timeout=None):
        seen.update(url=url, timeout=timeout, query=urllib.parse.parse_qs(data.decode())["data"][0])
        return json.dumps({"elements": [{"type": "count", "tags": {"total": "1"}}] * 5}).encode()

    out = sources.overpass_pois(45.0614, 7.6581, http=http)
    assert out == {"food": 1, "shop": 1, "transit": 1, "edu": 1, "leisure": 1, "road": None}, "no road nearby"
    q = seen["query"]
    assert seen["url"] == sources.OVERPASS_URL and seen["timeout"] == sources.OVERPASS_TIMEOUT_S
    assert q.count("out count;") == len(features.CATEGORIES) and q.endswith("way(around:30,45.061400,7.658100)[highway];out tags;")
    assert 'nw(around:300,45.061400,7.658100)[amenity~"^(restaurant|cafe|bar|pub|fast_food|ice_cream|food_court)$"];' in q
    assert "nw(around:300,45.061400,7.658100)[shop];" in q and "[tourism];" in q and '[highway~"^(bus_stop)$"];' in q


def osm_xml(*elements):
    return ("<osm>" + "".join(elements) + "</osm>").encode()


def osm_node(i, north, east=0.0, **tags):
    lat, lon = 45.0 + north / sources.M_PER_DEG, 7.0 + east / sources.M_PER_DEG / math.cos(math.radians(45.0))
    inner = "".join('<tag k="%s" v="%s"/>' % kv for kv in tags.items())
    return '<node id="%d" lat="%.7f" lon="%.7f">%s</node>' % (i, lat, lon, inner)


def osm_way(i, refs, **tags):
    inner = "".join('<nd ref="%d"/>' % r for r in refs) + "".join('<tag k="%s" v="%s"/>' % kv for kv in tags.items())
    return '<way id="%d">%s</way>' % (i, inner)


def test_osm_api_roads_links_and_things_to_ignore():
    api = lambda *elements: sources.osm_api_pois(45.0, 7.0, http=lambda url, **k: osm_xml(*elements))
    ends = [osm_node(1, 10, east=-200), osm_node(2, 10, east=200)]
    assert api(*ends, osm_way(9, [1, 2], highway="motorway_link"))["road"] == 4, "a link counts as its road"
    assert api(*ends, osm_way(9, [1, 2], highway="proposed"))["road"] is None, "not a road yet"
    assert api(*ends, osm_way(9, [1, 2], highway="footway"), osm_way(8, [1, 2], highway="tertiary"))["road"] == 2
    far = [osm_node(1, 60, east=-200), osm_node(2, 60, east=200)]
    assert api(*far, osm_way(9, [1, 2], highway="primary"))["road"] is None, "60 m away is another street"
    assert api(osm_way(9, [1, 2], shop="mall")) == dict(dict.fromkeys(features.CATEGORIES, 0), road=None), \
        "a way whose nodes are not in the extract cannot be placed"
    untagged = api(osm_node(1, 5), osm_node(2, 5, name="Bar Sport"))
    assert sum(untagged[c] for c in features.CATEGORIES) == 0, "a name alone is not a place of a known category"
    both = api(osm_node(1, 5, amenity="theatre", tourism="attraction"))
    assert both["leisure"] == 1, "one place is counted once per category, whatever the number of matching tags"


def test_osm_gives_up_only_when_both_services_fail():
    calls = []

    def down(url, **k):
        calls.append(url)
        raise OSError("no network")

    with pytest.raises(OSError):
        sources.osm_pois(45.0, 7.0, http=down)
    assert [u.split("?")[0] for u in calls] == [sources.OVERPASS_URL, sources.OSM_API_URL]


# ---------------------------------------------------------------- Open-Meteo
def test_open_meteo_request_and_broken_answers():
    seen = {}

    def http(url, **k):
        seen["url"] = url
        return json.dumps({"hourly": {"time": [10], "temperature_2m": [1.5], "precipitation": [0.2]}}).encode()

    assert sources.open_meteo(45.0614, 7.6581, http=http) == {"hourly": [[10, 1.5, 0.2]]}
    params = urllib.parse.parse_qs(urllib.parse.urlparse(seen["url"]).query)
    assert seen["url"].startswith(sources.OPEN_METEO_URL + "?")
    assert params == {"latitude": ["45.0614"], "longitude": ["7.6581"], "hourly": ["temperature_2m,precipitation"],
                      "forecast_hours": ["30"], "timeformat": ["unixtime"], "timezone": ["UTC"]}
    with pytest.raises(KeyError):
        sources.open_meteo(45.0, 7.0, http=lambda url, **k: b'{"error": true, "reason": "too many requests"}')
    with pytest.raises(ValueError):
        sources.open_meteo(45.0, 7.0, http=lambda url, **k: b"<html>busy</html>")


# ---------------------------------------------------------------- Google Maps Platform (documented answers)
def test_open_week_minutes_and_the_end_of_the_week():
    hours = lambda periods: {"regularOpeningHours": {"periods": periods}}
    p = lambda day, hour, minute=0: {"day": day, "hour": hour, "minute": minute}
    week = sources.open_week([hours([{"open": p(2, 9, 30), "close": p(2, 19, 30)}])])       # Tuesday 9:30-19:30
    assert week[1][8] == 0 and week[1][9] == 1 and week[1][19] == 1 and week[1][20] == 0, "open during part of the hour"
    night = sources.open_week([hours([{"open": p(0, 22), "close": p(1, 2)}])])              # Sunday 22 - Monday 2
    assert night[6][21:] == [0, 1, 1] and night[0][:3] == [1, 1, 0], "over the end of the week, Monday comes first"
    assert sum(map(sum, night)) == 4
    both = sources.open_week([hours([{"open": p(1, 8), "close": p(1, 12)}, {"open": p(1, 15), "close": p(1, 19)}]), {}])
    assert both[0][10] == 1 and both[0][13] == 0 and both[0][16] == 1, "lunch break; the place without hours is left out"


def test_google_places_one_request_per_category_and_no_half_answers():
    calls = []

    def http(url, data=None, headers=None, timeout=None):
        calls.append(json.loads(data))
        if len(calls) == 3:
            raise urllib.error.HTTPError(url, 403, "API not enabled", None, None)
        return b'{"places": []}'

    with pytest.raises(urllib.error.HTTPError):
        sources.google_places(45.0614, 7.6581, "KEY", http=http)
    assert len(calls) == 3, "a refused request stops the round: it is retried later, not stored half done"

    calls.clear()
    empty = sources.google_places(45.0614, 7.6581, "KEY", http=lambda url, data=None, **k: calls.append(json.loads(data)) or b"{}")
    assert empty == {"counts": dict.fromkeys(features.CATEGORIES, 0), "pop": 0, "open_week": None}
    assert [c["includedTypes"] for c in calls] == [sources._GOOGLE_TYPES[c] for c in features.CATEGORIES]
    centre = calls[0]["locationRestriction"]["circle"]["center"]
    assert (centre["latitude"], centre["longitude"]) == (45.0614, 7.6581)


def test_google_traffic_request_and_odd_answers():
    seen = {}

    def http(url, data=None, headers=None, timeout=None):
        seen.update(url=url, body=json.loads(data), headers=headers)
        return json.dumps({"routes": [{"duration": "90s", "staticDuration": "0s"}]}).encode()

    assert sources.google_traffic(45.0614, 7.6581, "KEY", http=http) == {"ratio": 90.0}, "no division by zero"
    body = seen["body"]
    a, b = body["origin"]["location"]["latLng"], body["destination"]["location"]["latLng"]
    assert seen["url"] == sources.ROUTES_URL and seen["headers"]["X-Goog-FieldMask"] == "routes.duration,routes.staticDuration"
    assert (body["travelMode"], body["routingPreference"]) == ("DRIVE", "TRAFFIC_AWARE")
    assert a["latitude"] > 45.0614 > b["latitude"] and a["longitude"] < 7.6581 < b["longitude"], "a drive across the crossing"
    assert (a["latitude"] - b["latitude"]) * sources.M_PER_DEG == pytest.approx(600, rel=0.01)
    with pytest.raises((KeyError, IndexError)):
        sources.google_traffic(45.0, 7.0, "KEY", http=lambda *a, **k: b'{"routes": []}')


# ---------------------------------------------------------------- cache of the surroundings
def test_default_fetchers_with_and_without_a_google_key():
    assert list(default_fetchers()) == ["weather", "esa", "poi"], "quickest first, and no Google without a key"
    assert list(default_fetchers("KEY")) == ["weather", "esa", "poi", "google", "traffic"]
    assert set(default_fetchers("KEY")) == set(TTL_S), "every source has an expiry"


def test_context_keeps_the_last_good_answer_when_a_source_breaks(tmp_path):
    clock, working = [5e8], [True]

    def weather(lat, lon):
        if not working[0]:
            raise OSError("no network")
        return {"hourly": [[clock[0], 12.0, 0.0]]}

    ctx = Context(str(tmp_path / "ctx.json"), {"weather": weather}, clock=lambda: clock[0], background=False)
    ctx.refresh(45.0, 7.0)
    first = ctx.get(45.0, 7.0)["weather"]
    working[0] = False
    clock[0] += TTL_S["weather"] + 1
    ctx.refresh(45.0, 7.0)
    assert ctx.get(45.0, 7.0)["weather"] == first, "an old answer is better than none"
    assert ctx.get(45.0, 7.0)["pending"] is False, "and it is not asked again at every request"
    working[0] = True
    clock[0] += RETRY_S + 1
    ctx.refresh(45.0, 7.0)
    assert ctx.get(45.0, 7.0)["weather"]["at"] == clock[0], "back to fresh data when the source is back"


def test_context_starts_empty_from_a_damaged_cache_file(tmp_path):
    path = tmp_path / "ctx.json"
    path.write_text('{"45.00000,7.00000": {"poi": ')            # the app was closed while writing
    ctx = Context(str(path), {"poi": lambda lat, lon: {"food": 3}}, background=False)
    assert ctx.get(45.0, 7.0) == {"pending": False}
    ctx.refresh(45.0, 7.0)
    assert json.loads(path.read_text())["45.00000,7.00000"]["poi"]["data"] == {"food": 3}, "and the file is good again"
    assert not (tmp_path / "ctx.json.tmp").exists(), "written to a temporary file, then moved into place"


def test_context_keeps_cameras_apart():
    ctx = Context(None, {"poi": lambda lat, lon: {"food": round(lat * 1000)}}, background=False)
    ctx.refresh(45.0614, 7.6581)
    ctx.refresh(45.0679, 7.6829)
    assert ctx.get(45.0614, 7.6581)["poi"]["food"] == 45061 and ctx.get(45.0679, 7.6829)["poi"]["food"] == 45068
    assert "poi" not in ctx.get(45.0615, 7.6581), "ten metres away is another camera"
    assert ctx.get(45.06140001, 7.65810001)["poi"]["food"] == 45061, "the same point, written with more digits"


def test_context_asks_one_camera_at_a_time():
    active, most, done = [0], [0], threading.Event()
    lock = threading.Lock()

    def slow(lat, lon):
        with lock:
            active[0] += 1
            most[0] = max(most[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return {"food": 1}

    ctx = Context(None, {"poi": slow, "esa": slow})
    cameras = [(45.0 + i / 100.0, 7.0) for i in range(4)]
    assert all(ctx.get(lat, lon)["pending"] for lat, lon in cameras), "four cameras, four background refreshes"
    for _ in range(200):
        if all("esa" in ctx.get(lat, lon) and not ctx.get(lat, lon)["pending"] for lat, lon in cameras):
            done.set()
            break
        time.sleep(0.02)
    assert done.is_set() and most[0] == 1, "the public servers refuse bursts: never two requests together"


def test_context_does_not_start_two_refreshes_for_the_same_camera():
    calls, release = [], threading.Event()

    def slow(lat, lon):
        calls.append(1)
        release.wait(5)
        return {"food": 1}

    ctx = Context(None, {"poi": slow})
    for _ in range(5):
        assert ctx.get(45.0, 7.0)["pending"] is True
    release.set()
    for _ in range(200):
        if "poi" in ctx.get(45.0, 7.0):
            break
        time.sleep(0.02)
    assert len(calls) == 1, "the page asks every few seconds while the first answer is on its way"
