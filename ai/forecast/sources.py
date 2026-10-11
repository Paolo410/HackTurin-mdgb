"""Data sources of the expected-flow model. Standard library only: this module runs inside the control-room app.

Every function does a few HTTP requests, returns a plain dict and raises on failure: context.py caches the
results and decides what to do when a source is unreachable. Only the coordinates of the crossing are sent.

  No key, free:
    osm_pois         places and road class around the crossing   https://wiki.openstreetmap.org/wiki/Overpass_API
    open_meteo       weather of the next hours                   https://open-meteo.com/en/docs
    esa_worldcover   ESA WorldCover 10 m 2021 v200 (land cover)  https://registry.opendata.aws/esa-worldcover-vito/
  With GOOGLE_MAPS_API_KEY (free monthly quota, see README.md):
    google_places    reviews and opening hours   https://developers.google.com/maps/documentation/places/web-service/nearby-search
    google_traffic   live congestion             https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes
"""
import json
import math
import ssl
import struct
import urllib.parse
import urllib.request
import zlib

from .features import CATEGORIES

USER_AGENT = "MDGB-Centrale/1.0 (HackTurin; github.com/Paolo410/HackTurin-mdgb)"
TIMEOUT_S = 12
OVERPASS_TIMEOUT_S = 45            # the public server is shared and often slow; asked once a month per crossing
M_PER_DEG = 111320.0

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WORLDCOVER_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                  "ESA_WorldCover_10m_2021_v200_%s_Map.tif")
PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def _ssl_context():
    try:                                    # a packaged app on macOS may not find the system CA bundle
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def http(url, data=None, headers=None, timeout=TIMEOUT_S):
    """One HTTP exchange -> response body (bytes). POST when data is given."""
    req = urllib.request.Request(url, data=data, headers=dict({"User-Agent": USER_AGENT}, **(headers or {})))
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        return r.read()


# ---------------------------------------------------------------- OpenStreetMap (Overpass)
_OSM_FILTERS = {
    "food": ['[amenity~"^(restaurant|cafe|bar|pub|fast_food|ice_cream|food_court)$"]'],
    "shop": ["[shop]", '[amenity~"^(marketplace|bank|pharmacy|post_office)$"]'],
    "transit": ["[highway=bus_stop]", '[railway~"^(station|halt|tram_stop|subway_entrance)$"]',
                "[amenity=bus_station]"],
    "edu": ['[amenity~"^(school|university|college|kindergarten|library)$"]'],
    "leisure": ["[tourism]", '[amenity~"^(theatre|cinema|arts_centre|nightclub)$"]',
                '[leisure~"^(park|playground|sports_centre|fitness_centre)$"]'],
}
ROAD_RANK = {"pedestrian": 0, "footway": 0, "living_street": 1, "residential": 1, "service": 1,
             "unclassified": 2, "tertiary": 2, "secondary": 3, "primary": 4, "trunk": 4, "motorway": 4}


def osm_pois(lat, lon, radius_m=300, road_m=30, http=http):
    """Places within radius_m, by category, and the class of the biggest road within road_m of the crossing."""
    around = "(around:%d,%.6f,%.6f)" % (radius_m, lat, lon)
    query = "[out:json][timeout:20];"
    for c in CATEGORIES:
        query += "(" + "".join("nw%s%s;" % (around, f) for f in _OSM_FILTERS[c]) + ");out count;"
    query += "way(around:%d,%.6f,%.6f)[highway];out tags;" % (road_m, lat, lon)
    body = http(OVERPASS_URL, data=urllib.parse.urlencode({"data": query}).encode(), timeout=OVERPASS_TIMEOUT_S)
    elements = json.loads(body)["elements"]
    counts = [int(e["tags"]["total"]) for e in elements if e.get("type") == "count"]
    if len(counts) != len(CATEGORIES):
        raise ValueError("Overpass: %d counts instead of %d" % (len(counts), len(CATEGORIES)))
    out = dict(zip(CATEGORIES, counts))
    ranks = [ROAD_RANK[e["tags"]["highway"].replace("_link", "")] for e in elements
             if e.get("type") == "way" and e["tags"]["highway"].replace("_link", "") in ROAD_RANK]
    out["road"] = max(ranks) if ranks else None
    return out


# ---------------------------------------------------------------- Open-Meteo
def open_meteo(lat, lon, hours=6, http=http):
    """Hourly temperature (°C) and rain (mm in the hour) from the current hour on: [[epoch_s, temp_c, rain_mm], ...]."""
    query = urllib.parse.urlencode({"latitude": "%.4f" % lat, "longitude": "%.4f" % lon,
                                    "hourly": "temperature_2m,precipitation", "forecast_hours": hours,
                                    "timeformat": "unixtime", "timezone": "UTC"})
    h = json.loads(http(OPEN_METEO_URL + "?" + query))["hourly"]
    return {"hourly": [list(x) for x in zip(h["time"], h["temperature_2m"], h["precipitation"])]}


# ---------------------------------------------------------------- ESA WorldCover (Cloud Optimized GeoTIFF)
# Class codes of the product: 10 tree cover, 20 shrubland, 30 grassland, 40 cropland, 50 built-up, 60 bare,
# 70 snow, 80 water, 90 wetland, 95 mangroves, 100 moss. https://worldcover2021.esa.int
WC_BUILT, WC_GREEN, WC_WATER = (50,), (10, 20, 30), (80,)
_TIFF_FMT = {1: "B", 3: "H", 4: "I", 12: "d", 16: "Q"}          # BYTE, SHORT, LONG, DOUBLE, LONG8


def worldcover_tile(lat, lon):
    """Name of the 3x3 degree tile that contains the point, e.g. N45E006 (south-west corner)."""
    la, lo = int(math.floor(lat / 3.0)) * 3, int(math.floor(lon / 3.0)) * 3
    return "%s%02d%s%03d" % ("N" if la >= 0 else "S", abs(la), "E" if lo >= 0 else "W", abs(lo))


def _tiff_values(head, fetch, entry, first=0, n=None):
    """Values of one IFD entry of a little-endian classic TIFF; reads beyond `head` with range requests."""
    typ, count, value = entry
    fmt = _TIFF_FMT[typ]
    size = struct.calcsize(fmt)
    n = count - first if n is None else n
    if count * size <= 4:                                        # stored inline in the entry
        raw = struct.pack("<I", value)[first * size:(first + n) * size]
    else:
        a, b = value + first * size, value + (first + n) * size
        raw = head[a:b] if b <= len(head) else fetch(a, b - a)
    return struct.unpack("<%d%s" % (n, fmt), raw)


def esa_worldcover(lat, lon, radius_m=300, http=http):
    """Share of built-up, green and water pixels within radius_m, read from the public ESA WorldCover file.

    The file is a tiled, deflate-compressed GeoTIFF of 36000x36000 pixels: only the header and the one or two
    tiles around the point are downloaded, with HTTP range requests.
    """
    url = WORLDCOVER_URL % worldcover_tile(lat, lon)
    fetch = lambda a, n: http(url, headers={"Range": "bytes=%d-%d" % (a, a + n - 1)})
    head = fetch(0, 32768)
    if head[:4] != b"II*\x00":
        raise ValueError("WorldCover: not a little-endian classic TIFF")
    (ifd_at,) = struct.unpack("<I", head[4:8])
    (n_entries,) = struct.unpack("<H", head[ifd_at:ifd_at + 2])
    ifd = {}
    for i in range(n_entries):
        tag, typ, count, value = struct.unpack("<HHII", head[ifd_at + 2 + 12 * i:ifd_at + 14 + 12 * i])
        ifd[tag] = (typ, count, value)
    one = lambda tag, default=None: _tiff_values(head, fetch, ifd[tag])[0] if tag in ifd else default
    width, height, tile_w, tile_h = one(256), one(257), one(322), one(323)
    if one(259) not in (8, 32946) or one(258) != 8 or one(317, 1) != 1 or not tile_w:
        raise ValueError("WorldCover: unexpected TIFF layout")
    sx, sy = _tiff_values(head, fetch, ifd[33550])[:2]           # ModelPixelScale: degrees per pixel
    lon0, lat0 = _tiff_values(head, fetch, ifd[33922])[3:5]      # ModelTiepoint: top-left corner

    d_lat = radius_m / M_PER_DEG
    d_lon = d_lat / math.cos(math.radians(lat))
    cx, cy = (lon - lon0) / sx, (lat0 - lat) / sy                # centre, in pixels
    c0, c1 = max(0, int((lon - d_lon - lon0) / sx)), min(width - 1, int((lon + d_lon - lon0) / sx))
    r0, r1 = max(0, int((lat0 - lat - d_lat) / sy)), min(height - 1, int((lat0 - lat + d_lat) / sy))
    kx, ky = sx * M_PER_DEG * math.cos(math.radians(lat)), sy * M_PER_DEG      # metres per pixel
    across = (width + tile_w - 1) // tile_w
    hist = {}
    for tr in range(r0 // tile_h, r1 // tile_h + 1):
        for tc in range(c0 // tile_w, c1 // tile_w + 1):
            index = tr * across + tc
            (offset,) = _tiff_values(head, fetch, ifd[324], index, 1)
            (nbytes,) = _tiff_values(head, fetch, ifd[325], index, 1)
            tile = zlib.decompress(fetch(offset, nbytes))
            for r in range(max(r0, tr * tile_h), min(r1, (tr + 1) * tile_h - 1) + 1):
                base = (r - tr * tile_h) * tile_w - tc * tile_w
                dy2 = ((r + 0.5 - cy) * ky) ** 2
                for c in range(max(c0, tc * tile_w), min(c1, (tc + 1) * tile_w - 1) + 1):
                    if dy2 + ((c + 0.5 - cx) * kx) ** 2 <= radius_m ** 2:
                        v = tile[base + c]
                        hist[v] = hist.get(v, 0) + 1
    total = sum(n for v, n in hist.items() if v != 0)            # 0 = no data
    if not total:
        raise ValueError("WorldCover: no data around the point")
    share = lambda classes: round(sum(hist.get(v, 0) for v in classes) / total, 3)
    return {"built": share(WC_BUILT), "green": share(WC_GREEN), "water": share(WC_WATER), "pixels": total}


# ---------------------------------------------------------------- Google Maps Platform (optional, needs a key)
# TODO(verify): written from the official documentation linked above, not yet run with a real key.
_GOOGLE_TYPES = {
    "food": ["restaurant", "cafe", "bar", "bakery"],
    "shop": ["store", "supermarket", "shopping_mall", "clothing_store"],
    "transit": ["bus_station", "bus_stop", "subway_station", "train_station", "light_rail_station"],
    "edu": ["school", "primary_school", "secondary_school", "university", "library"],
    "leisure": ["tourist_attraction", "museum", "movie_theater", "park", "art_gallery", "night_club"],
}


def open_week(places):
    """Share of places open in each hour of the week: [[24 values] x 7], Monday first. None without hours.

    places: `places` items of the Places API; a period is {"open": {"day", "hour", "minute"}, "close": {...}}
    with day 0 = Sunday, and no "close" for a place that never closes.
    """
    slots, known = [0] * 168, 0
    for p in places:
        periods = (p.get("regularOpeningHours") or {}).get("periods")
        if not periods:
            continue
        known += 1
        hours = set()
        for per in periods:
            if "close" not in per:
                hours = set(range(168))
                break
            at = lambda x: ((x["day"] + 6) % 7) * 24 + x.get("hour", 0) + x.get("minute", 0) / 60.0
            start, end = at(per["open"]), at(per["close"])
            if end <= start:
                end += 168
            hours.update(k % 168 for k in range(int(start), int(math.ceil(end))))
        for k in hours:
            slots[k] += 1
    if not known:
        return None
    return [[round(slots[d * 24 + h] / known, 3) for h in range(24)] for d in range(7)]


def google_places(lat, lon, key, radius_m=300, http=http):
    """The 20 most popular places per category: how reviewed they are and when they are open.

    Nearby Search returns at most 20 places per request, so the counts saturate: they are used only when
    OpenStreetMap is unreachable. One request per category (5 per crossing, repeated once a month).
    """
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": key,
               "X-Goog-FieldMask": "places.userRatingCount,places.regularOpeningHours"}
    counts, found = {}, []
    for c in CATEGORIES:
        body = {"includedTypes": _GOOGLE_TYPES[c], "maxResultCount": 20,
                "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon},
                                                   "radius": float(radius_m)}}}
        places = json.loads(http(PLACES_URL, data=json.dumps(body).encode(), headers=headers)).get("places", [])
        counts[c] = len(places)
        found += places
    return {"counts": counts, "pop": round(sum(math.log1p(p.get("userRatingCount", 0)) for p in found), 2),
            "open_week": open_week(found)}


def google_traffic(lat, lon, key, span_m=300, http=http):
    """Travel time with traffic divided by the time without, on a short drive across the crossing (1.0 = free)."""
    d_lat = span_m / M_PER_DEG
    d_lon = d_lat / math.cos(math.radians(lat))
    point = lambda la, lo: {"location": {"latLng": {"latitude": la, "longitude": lo}}}
    body = {"origin": point(lat + d_lat, lon - d_lon), "destination": point(lat - d_lat, lon + d_lon),
            "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE"}
    headers = {"Content-Type": "application/json", "X-Goog-Api-Key": key,
               "X-Goog-FieldMask": "routes.duration,routes.staticDuration"}
    route = json.loads(http(ROUTES_URL, data=json.dumps(body).encode(), headers=headers))["routes"][0]
    seconds = lambda s: float(str(s).rstrip("s"))
    return {"ratio": round(seconds(route["duration"]) / max(seconds(route["staticDuration"]), 1.0), 3)}
