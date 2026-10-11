"""Features of the expected-flow model: one row per crossing and 15-minute window. Standard library only.

The same names are used by simulate.py (training) and by service.py (inference). A missing value is None
(NaN in training): the trees have a branch for it, so the model works with any subset of the sources.
"""
import time

CATEGORIES = ("food", "shop", "transit", "edu", "leisure")
TARGETS = ("ped_in", "ped_out", "cyclist", "vehicles")
FEATURES = (
    "hour", "dow", "holiday",                       # calendar, local time of the control room
    "road",                                         # OpenStreetMap: 0 pedestrian street ... 4 main road
    "poi_food", "poi_shop", "poi_transit", "poi_edu", "poi_leisure",   # places within 300 m
    "poi_pop", "open_share",                        # Google Places: reviews and share of places open now
    "esa_built", "esa_green", "esa_water",          # ESA WorldCover: land cover within 300 m
    "temp_c", "rain_mm",                            # weather (mm of rain in the hour)
    "traffic",                                      # Google Routes: travel time with traffic / without
)
WINDOW_S = 900

_FIXED_HOLIDAYS = {(1, 1), (1, 6), (4, 25), (5, 1), (6, 2), (8, 15), (11, 1), (12, 8), (12, 25), (12, 26)}


def easter(year):
    """Easter Sunday as (month, day): anonymous Gregorian algorithm."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 19 * m) // 433
    month = (h + m - 7 * n + 90) // 25
    return month, (h + m - 7 * n + 33 * month + 19) % 32


def is_holiday(lt):
    """Italian national holidays (fixed dates, Easter Sunday and Easter Monday). lt: time.struct_time."""
    if (lt.tm_mon, lt.tm_mday) in _FIXED_HOLIDAYS:
        return True
    month, day = easter(lt.tm_year)
    monday = (month, day + 1) if day < 31 else (month + 1, 1)
    return (lt.tm_mon, lt.tm_mday) in ((month, day), monday)


def weather_at(weather, ts, tolerance_s=5400):
    """(temp_c, rain_mm) of the hourly record closest to ts, or None if the closest one is too far."""
    best = None
    for t, temp, rain in (weather or {}).get("hourly", []):
        if best is None or abs(t - ts) < abs(best[0] - ts):
            best = (t, temp, rain)
    if best is None or abs(best[0] - ts) > tolerance_s:
        return None
    return best[1], best[2]


def row(ts, ctx, env=None):
    """Feature dict of the window centred on ts.

    ctx: what Context.get() returns ({"poi": ..., "google": ..., "esa": ..., "weather": ..., "traffic": ...},
    every part optional). env: the node's own sensors for that window (C4 `agg.env`), used when there is no
    weather service.
    """
    lt = time.localtime(ts)
    f = dict.fromkeys(FEATURES)
    f.update(hour=lt.tm_hour + lt.tm_min / 60.0, dow=lt.tm_wday, holiday=int(is_holiday(lt)))
    poi, google = ctx.get("poi") or {}, ctx.get("google") or {}
    counts = poi if poi else google.get("counts") or {}
    for c in CATEGORIES:
        f["poi_" + c] = counts.get(c)
    f["road"] = poi.get("road")
    f["poi_pop"] = google.get("pop")
    week = google.get("open_week")
    f["open_share"] = week[lt.tm_wday][lt.tm_hour] if week else None
    esa = ctx.get("esa") or {}
    f.update(esa_built=esa.get("built"), esa_green=esa.get("green"), esa_water=esa.get("water"))
    w = weather_at(ctx.get("weather"), ts)
    if w is not None:
        f["temp_c"], f["rain_mm"] = w
    elif env and env.get("t_c") is not None:
        f["temp_c"] = env["t_c"]
    traffic = ctx.get("traffic") or {}
    if traffic.get("ratio") is not None and abs(ts - traffic.get("at", 0)) <= 3600:
        f["traffic"] = traffic["ratio"]            # live value: says nothing about other hours
    return f
