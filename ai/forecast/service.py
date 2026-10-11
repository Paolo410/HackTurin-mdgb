"""Expected flow of one crossing, as the control-room dashboard shows it. Standard library only.

    Forecaster().forecast(node, windows) -> dict (JSON-serialisable)

node: the camera as in app/nodes.json ({"id", "lat", "lon", ...}); windows: what the node measured, oldest
first, as built by app/dashboard.py ({"t0", "t1", "ped_in", "ped_out", "cyclist", "vehicles", "env"}), empty
for a camera that has never sent data. All rates are counts per 15-minute window.

Three steps: the gradient boosting model turns calendar and surroundings into an expectation; the node's
history says how much this crossing differs from it (calibration: on average, and lately); the last windows are
fused with the expectation into the estimate of the flow right now. The outlook (now, then the next 24 clock hours) starts
from that estimate and goes back to the calibrated model as the hours pass.
"""
import os
import tempfile
import time

from . import features, fusion
from .context import Context, default_fetchers
from .model import Model

HISTORY_WINDOWS = 96            # what the calibration looks at: 24 h of 15-minute windows (96 min in the demo)
OUTLOOK_HOURS = 24              # forecast: the next 24 clock hours, after "now"
PERSISTENCE_HALF_LIFE_H = 1.0   # what is unusual right now (a crowd, an empty street) fades by half every hour
ANOMALY_MIN_EXPECTED = 20       # below this many expected pedestrians an "unusual" hour is just noise
ANOMALY_LIMITS = (0.6, 1.6)
EVIDENCE = 80.0                 # expected counts the estimate of now looks back for: a busy crossing is told by its
                                # last window, a quiet one needs many of them
QUALITY_WINDOWS = 48            # the estimate is checked on the last 48 measured windows...
QUALITY_MIN_HISTORY = 12        # ...each predicted from at least 12 earlier ones
QUALITY_MIN_WINDOWS = 8         # fewer checks than this say nothing


def default_cache_file():
    """Next to the app's settings (MDGB_HOME) or, from source, in the temporary folder."""
    home = os.environ.get("MDGB_HOME") or os.path.join(tempfile.gettempdir(), "mdgb-forecast")
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "forecast-context.json")


def nowcast(seen, mu_now, target, now):
    """Rate of `target` at `now` (counts per 15 minutes) from the model and the windows measured before.

    The prior is the model at the crossing's usual level (calibration), worth fusion.SHRINK counts. The recent
    windows are observations of the present rate. How far back to look depends on how much there is to count:
    windows are added, newest first, until they are expected to hold EVIDENCE counts, so a busy crossing
    follows its last window and a quiet one averages many. (Tried and dropped: moving the old counts along the
    model's daily rhythm. It helps when the crossing follows that rhythm and hurts more when it does not, and
    the rhythm comes from simulated data.)

    A prior that the counts contradict is not allowed to hold the estimate back: its weight is divided by
    1 + z^2, where z is how many standard deviations the recent counts are from what the prior expected. With
    counts in line with the prior nothing changes; when the node sees ten times the people, the node wins at once
    instead of after an hour. seen: [(window, exposure, model expectation)] of the earlier windows; mu_now: the
    model now.
    """
    usual = mu_now[target] * fusion.calibration(sum(w[target] for w, _, _ in seen),
                                                sum(mu[target] * exposure for _, exposure, mu in seen))
    usual = max(usual, fusion.MIN_RATE)
    recent, wanted = [], EVIDENCE
    for w, exposure, mu in reversed(seen):
        age = now - w["t1"]
        if age > 4 * fusion.HALF_LIFE_S or wanted <= 0:
            break
        recent.append((w[target], exposure, age))
        wanted -= usual * exposure * 0.5 ** (max(age, 0.0) / fusion.HALF_LIFE_S)
    weights = [0.5 ** (max(age, 0.0) / fusion.HALF_LIFE_S) for _, _, age in recent]
    counted = sum(w * count for w, (count, _, _) in zip(weights, recent))
    awaited = usual * sum(w * exposure for w, (_, exposure, _) in zip(weights, recent))
    surprise = (counted - awaited) ** 2 / (awaited + awaited ** 2 / fusion.SHRINK) if awaited > 0 else 0.0
    return fusion.posterior(usual, recent, strength=fusion.SHRINK / (1 + surprise) / usual)


def quality(seen):
    """How the estimate did on what the node measured afterwards (pedestrians, both directions, per window).

    Every one of the last windows is predicted with the information available before it started (the model, the
    calibration and the fusion on the earlier windows only) and compared with its count. Two yardsticks: repeating
    the count of the window before ("persistence") and the model alone, without the node. seen: [(window,
    exposure, model expectation)], oldest first. None while the node has measured too little.
    """
    start = max(QUALITY_MIN_HISTORY, len(seen) - QUALITY_WINDOWS)
    if len(seen) - start < QUALITY_MIN_WINDOWS:
        return None
    err = {"estimate": 0.0, "persistence": 0.0, "model": 0.0}
    predicted = counted = 0.0
    for i in range(start, len(seen)):
        w, exposure, mu = seen[i]
        earlier, begins = seen[:i], w["t0"]
        estimate = 0.0
        for t in ("ped_in", "ped_out"):
            estimate += nowcast(earlier, mu, t, begins)["mean"] * exposure
        real = w["ped_in"] + w["ped_out"]
        last = earlier[-1]
        err["estimate"] += abs(estimate - real)
        err["persistence"] += abs((last[0]["ped_in"] + last[0]["ped_out"]) * exposure / last[1] - real)
        err["model"] += abs((mu["ped_in"] + mu["ped_out"]) * exposure - real)
        predicted, counted = predicted + estimate, counted + real
    n = len(seen) - start
    return {"windows": n, "window_s": round(sum(x[0]["t1"] - x[0]["t0"] for x in seen[start:]) / n),
            "mean_count": round(counted / n, 2),
            "mae": round(err["estimate"] / n, 2), "mae_persistence": round(err["persistence"] / n, 2),
            "mae_model": round(err["model"] / n, 2),
            "bias": round(predicted / counted - 1, 3) if counted else None}


class Forecaster:
    def __init__(self, model=None, context=None, clock=time.time):
        self.model = model or Model.load()
        if context is None:
            context = Context(default_cache_file(), default_fetchers(os.environ.get("GOOGLE_MAPS_API_KEY", "")))
        self.context, self.clock = context, clock

    def forecast(self, node, windows, now=None):
        now = self.clock() if now is None else now
        ctx = self.context.get(node.get("lat"), node.get("lon"))
        expect = lambda ts, env=None: self.model.predict(features.row(ts, ctx, env))
        W = features.WINDOW_S

        # what the node measured against what the model expected for the same windows
        history = [w for w in windows if w["t1"] <= now + 1 and w["t1"] > w["t0"]][-HISTORY_WINDOWS:]
        measured = dict.fromkeys(features.TARGETS, 0.0)
        expected = dict.fromkeys(features.TARGETS, 0.0)
        last_hour = {"measured": 0.0, "expected": 0.0}      # pedestrians, both directions
        before = {"measured": 0.0, "expected": 0.0}         # the same, for the windows older than one hour
        seen = []                                           # (window, exposure, model expectation per 15 min)
        for w in history:
            exposure = (w["t1"] - w["t0"]) / float(W)
            mu = expect((w["t0"] + w["t1"]) / 2.0, w.get("env"))
            seen.append((w, exposure, mu))
            for t in features.TARGETS:
                measured[t] += w[t]
                expected[t] += mu[t] * exposure
            part = last_hour if w["t1"] > now - 3600 else before
            part["measured"] += w["ped_in"] + w["ped_out"]
            part["expected"] += (mu["ped_in"] + mu["ped_out"]) * exposure
        cal = {t: fusion.calibration(measured[t], expected[t]) for t in features.TARGETS}

        mu_now = expect(now)
        estimate = {}
        for t in features.TARGETS:
            post = nowcast(seen, mu_now, t, now)
            estimate[t] = {"mean": round(post["mean"], 2), "lo": round(post["lo"], 2), "hi": round(post["hi"], 2),
                           "model": round(mu_now[t], 2), "node_weight": round(post["weight"], 2)}

        # is the last hour unusual for this crossing? Its usual level comes from the hours before, so that a
        # crowd does not hide itself by raising the level it is compared with
        usual = last_hour["expected"] * fusion.calibration(before["measured"], before["expected"])
        anomaly = None
        if usual >= ANOMALY_MIN_EXPECTED:
            ratio = last_hour["measured"] / usual
            anomaly = {"ratio": round(ratio, 2), "measured": round(last_hour["measured"]), "expected": round(usual),
                       "level": "low" if ratio < ANOMALY_LIMITS[0] else "high" if ratio > ANOMALY_LIMITS[1] else "normal"}

        # counts per hour: the estimate of now, then the next clock hours from the calibrated model
        quarters = 3600 // W
        outlook = [dict({t: round(estimate[t]["mean"] * quarters, 1) for t in features.TARGETS},
                        t0=now, t1=now + 3600, now=True)]
        unusual = {t: min(max(estimate[t]["mean"] / max(mu_now[t] * cal[t], fusion.MIN_RATE), 0.25), 4.0)
                   for t in features.TARGETS}
        first = (int(now // 3600) + 1) * 3600
        for i in range(OUTLOOK_HOURS):
            t0 = first + i * 3600
            fade = 0.5 ** ((t0 + 1800 - now) / 3600.0 / PERSISTENCE_HALF_LIFE_H)
            hour = dict.fromkeys(features.TARGETS, 0.0)
            for q in range(quarters):
                mu = expect(t0 + (q + 0.5) * W)
                for t in features.TARGETS:
                    hour[t] += mu[t] * cal[t] * unusual[t] ** fade
            outlook.append(dict({t: round(v, 1) for t, v in hour.items()}, t0=t0, t1=t0 + 3600))

        now_row = features.row(now, ctx)
        return {
            "available": True, "node": node.get("id"), "now": now, "window_s": W,
            "mode": "fused" if any(now - w["t1"] <= 4 * fusion.HALF_LIFE_S for w, _, _ in seen) else "model_only",
            "estimate": estimate, "outlook": outlook, "anomaly": anomaly,
            "calibration": {t: round(c, 2) for t, c in cal.items()}, "history_windows": len(seen),
            "quality": quality(seen),
            "inputs": {k: now_row[k] for k in features.FEATURES if k not in ("hour", "dow")},
            "sources": {"places": "osm" if ctx.get("poi") else "google" if ctx.get("google") else None,
                        "google": bool(ctx.get("google")), "esa": bool(ctx.get("esa")),
                        "weather": features.weather_at(ctx.get("weather"), now) is not None,
                        "traffic": now_row["traffic"] is not None,
                        "google_key": "google" in self.context.fetchers,
                        "located": node.get("lat") is not None and node.get("lon") is not None,
                        "pending": ctx.get("pending", False)},
            "model": {k: self.model.meta.get(k) for k in ("trained_on", "trained_at", "sites_train", "metrics")},
        }
