"""Expected flow of one crossing, as the control-room dashboard shows it. Standard library only.

    Forecaster().forecast(node, windows) -> dict (JSON-serialisable)

node: the camera as in app/nodes.json ({"id", "lat", "lon", ...}); windows: what the node measured, oldest
first, as built by app/dashboard.py ({"t0", "t1", "ped_in", "ped_out", "cyclist", "vehicles", "env"}), empty
for a camera that has never sent data. All rates are counts per 15-minute window.

Three steps: the gradient boosting model turns calendar and surroundings into an expectation; the node's
recent history says how much this crossing differs from it (calibration); the last windows are fused with the
expectation into the estimate of the flow right now. The outlook (now, then the next 24 clock hours) starts
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


def default_cache_file():
    """Next to the app's settings (MDGB_HOME) or, from source, in the temporary folder."""
    home = os.environ.get("MDGB_HOME") or os.path.join(tempfile.gettempdir(), "mdgb-forecast")
    os.makedirs(home, exist_ok=True)
    return os.path.join(home, "forecast-context.json")


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
            recent = [(w[t], exposure, now - w["t1"]) for w, exposure, _ in seen if now - w["t1"] <= 4 * fusion.HALF_LIFE_S]
            post = fusion.posterior(mu_now[t] * cal[t], recent)
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
