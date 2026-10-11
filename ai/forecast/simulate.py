"""Synthetic history for the expected-flow model. THIS IS NOT REAL DATA.

At the hackathon there is no history of counts (PROMPT_SMART_CROSSING.md §5.3), so the pipeline is trained on
crossings invented here: each has a context (places, land cover, road class), a daily and weekly rhythm that
depends on it, weather effects and a few things no source can see (`site_effect`, `in_bias`), which is what
the node's own counts correct at run time. The shapes are plausible, the numbers are assumptions: with real
aggregates in the control-room database, train.py is run on those instead.

Needs numpy; used only by train.py and by the tests of the training pipeline.
"""
import numpy as np

from .features import FEATURES, TARGETS

WINDOWS_PER_DAY = 96


def bump(h, centre, width):
    """Daily bell around `centre` (hours), wrapping at midnight."""
    d = np.abs(h - centre)
    d = np.minimum(d, 24 - d)
    return np.exp(-0.5 * (d / width) ** 2)


def make_sites(n, rng):
    """Context of n invented crossings, plus the hidden traits that no data source can see."""
    u = rng.beta(2.0, 2.5, n)                                   # 0 = suburb, 1 = city centre
    s = {
        "poi_food": rng.poisson(60 * u ** 2),
        "poi_shop": rng.poisson(140 * u ** 2),
        "poi_transit": rng.poisson(1 + 10 * u),
        "poi_edu": rng.poisson(0.4 + 2.5 * u),
        "poi_leisure": rng.poisson(1 + 60 * u ** 2 * rng.uniform(0.2, 1.6, n)),
        "road": rng.choice(5, n, p=[0.12, 0.28, 0.25, 0.20, 0.15]),
    }
    s["esa_water"] = np.where(rng.random(n) < 0.15, rng.uniform(0.02, 0.25, n), 0.0)
    s["esa_built"] = np.clip(0.30 + 0.65 * u + rng.normal(0, 0.08, n), 0.05, 1.0) * (1 - s["esa_water"])
    s["esa_green"] = (1 - s["esa_built"] - s["esa_water"]) * rng.uniform(0.6, 1.0, n)
    busy = rng.normal(0, 1, n)                                  # how reviewed the local places are
    listed = sum(np.minimum(s[k], 20) for k in ("poi_food", "poi_shop", "poi_transit", "poi_edu", "poi_leisure"))
    s["poi_pop"] = listed * np.clip(4.5 + 0.9 * busy, 1.0, 8.0)  # sum of log(1 + reviews), 20 places per category
    s["nightlife"] = rng.uniform(0, 1, n)                       # seen only through the opening hours
    # hidden: explained in part by the reviews, the rest only by the node's own counts
    s["site_effect"] = np.exp(0.30 * busy + rng.normal(0, 0.20, n))
    s["road_effect"] = np.exp(rng.normal(0, 0.25, n))
    s["congestion"] = rng.uniform(0.3, 1.5, n)
    s["in_bias"] = rng.normal(0, 0.35, n)
    return s


def simulate(n_sites=200, days=21, seed=0):
    """-> X (rows x len(FEATURES), NaN = missing), Y (rows x len(TARGETS)), site index of every row."""
    rng = np.random.default_rng(seed)
    s = make_sites(n_sites, rng)
    per_site = days * WINDOWS_PER_DAY
    site = np.repeat(np.arange(n_sites), per_site)
    day = np.tile(np.repeat(np.arange(days), WINDOWS_PER_DAY), n_sites)
    h = np.tile((np.arange(WINDOWS_PER_DAY) + 0.5) / 4.0, n_sites * days)
    site_day = site * days + day
    dow = (rng.integers(0, 7, n_sites)[site] + day) % 7
    holiday = (rng.random(n_sites * days) < 0.04)[site_day]
    doy = (rng.integers(0, 365, n_sites)[site] + day) % 365

    # weather: seasonal and daily temperature, rain in spells of a few hours on about one day in four
    temp = (13 + 10 * np.cos(2 * np.pi * (doy - 200) / 365) + 4 * np.cos(2 * np.pi * (h - 15) / 24)
            + rng.normal(0, 2.5, n_sites * days)[site_day])
    wet = (rng.random(n_sites * days) < 0.28)[site_day]
    start = rng.uniform(0, 24, n_sites * days)[site_day]
    length = rng.uniform(2, 10, n_sites * days)[site_day]
    intensity = rng.exponential(1.2, n_sites * days)[site_day]
    rain = np.where(wet & (h >= start) & (h < start + length), intensity * rng.uniform(0.5, 1.5, h.size), 0.0)

    work = (dow < 5) & ~holiday
    sat, rest = dow == 5, (dow == 6) | holiday
    commute = (bump(h, 8.0, 0.9) + bump(h, 18.0, 1.3)) * np.where(work, 1.0, 0.2)
    lunch = bump(h, 13.0, 0.9)
    dinner = bump(h, 20.5, 1.4) * np.where(sat | (dow == 4), 1.4, 1.0)
    shopping = (0.6 * bump(h, 11.0, 1.5) + bump(h, 17.0, 1.8)) * np.where(sat, 1.5, np.where(rest, 0.5, 1.0))
    school = (bump(h, 7.9, 0.35) + bump(h, 13.3, 0.4) + 0.7 * bump(h, 16.3, 0.4)) * work
    stroll = bump(h, 16.5, 2.8) * np.where(work, 1.0, 1.7)
    daytime = bump(h, 14.0, 4.5)
    night = bump(h, 23.5, 1.5)

    g = lambda k: s[k][site]
    rain_ped = 1 - 0.45 * (1 - np.exp(-rain / 1.5))
    rain_cyc = 1 - 0.80 * (1 - np.exp(-rain / 1.0))
    temp_ped = np.clip(1 - 0.012 * np.abs(temp - 20), 0.6, 1.0)
    temp_cyc = np.clip(1 - 0.030 * np.abs(temp - 22), 0.25, 1.0)
    road = g("road")

    ped = (0.3 + 4.0 * g("esa_built") * daytime
           + 2.2 * g("poi_transit") * commute
           + 0.40 * g("poi_food") * (lunch + 1.1 * dinner)
           + 0.60 * g("poi_food") * g("nightlife") * night
           + 0.18 * g("poi_shop") * shopping
           + 6.0 * g("poi_edu") * school
           + 0.30 * g("poi_leisure") * stroll * (1 + g("esa_green")))
    ped *= g("site_effect") * rain_ped * temp_ped * np.array([1.6, 1.1, 1.0, 0.95, 0.9])[road]
    toward = g("poi_transit") / (g("poi_transit") + 4.0)        # morning flows go one way, evening ones come back
    share_in = 1 / (1 + np.exp(-(g("in_bias") + 0.9 * toward * (bump(h, 8.0, 0.9) - bump(h, 18.0, 1.3)) * work)))

    cyc = (0.15 + 1.6 * commute * (0.5 + g("esa_built")) + 0.5 * stroll * (0.3 + 2 * g("esa_green")))
    cyc *= np.sqrt(g("site_effect")) * rain_cyc * temp_cyc

    load = np.clip(0.10 + bump(h, 8.0, 1.2) * work + 0.7 * bump(h, 13.0, 2.5) + bump(h, 18.0, 1.6)
                   * np.where(work, 1.0, 0.7), 0, 1.3)
    shock = np.exp(rng.normal(0, 0.15, n_sites * days))[site_day]   # strikes, events, road works: a different day
    veh = np.array([0.6, 9.0, 26.0, 55.0, 95.0])[road] * load * shock * g("road_effect") * (1 + 0.06 * np.minimum(rain, 3))
    traffic = 1 + 0.5 * g("congestion") * (load * shock) ** 2 * (road > 0) + rng.normal(0, 0.03, h.size)

    shop_open = ((h >= 9) & (h < 19.5)) * np.where(rest, 0.3, 1.0)
    food_open = ((h >= 7) & (h < 15)) | (h >= 18)
    n_food, n_shop = g("poi_food") + 1.0, g("poi_shop") + 1.0
    open_share = np.clip((n_shop * shop_open + n_food * (food_open + 0.6 * g("nightlife") * night)) / (n_shop + n_food)
                         + rng.normal(0, 0.03, h.size), 0, 1)

    noise = lambda: rng.gamma(10.0, 0.1, h.size)                # more spread than a pure Poisson
    lam = {"ped_in": ped * share_in, "ped_out": ped * (1 - share_in), "cyclist": cyc, "vehicles": veh}
    Y = np.column_stack([rng.poisson(lam[t] * noise()) for t in TARGETS]).astype(float)

    cols = {"hour": h, "dow": dow, "holiday": holiday, "road": road, "temp_c": temp, "rain_mm": rain,
            "traffic": np.maximum(traffic, 0.8), "open_share": open_share}
    cols.update({k: g(k) for k in FEATURES if k not in cols})
    X = np.column_stack([np.asarray(cols[k], dtype=float) for k in FEATURES])

    # every source can be missing, independently: the app runs with whatever it has
    col = {k: i for i, k in enumerate(FEATURES)}
    drop = lambda names, rows: X.__setitem__((np.ix_(rows, [col[k] for k in names])), np.nan)
    by_site = lambda p: np.flatnonzero((rng.random(n_sites) < p)[site])
    drop(["poi_pop", "open_share"], by_site(0.5))               # no Google key
    drop(["traffic"], np.flatnonzero((rng.random(n_sites) < 0.5)[site] | (rng.random(h.size) < 0.3)))
    drop(["esa_built", "esa_green", "esa_water"], by_site(0.1))
    drop(["road", "poi_food", "poi_shop", "poi_transit", "poi_edu", "poi_leisure"], by_site(0.08))
    drop(["road"], by_site(0.1))
    drop(["temp_c", "rain_mm"], np.flatnonzero(rng.random(h.size) < 0.1))
    drop(["rain_mm"], np.flatnonzero(rng.random(h.size) < 0.1))  # only the node's thermometer
    return X, Y, site
