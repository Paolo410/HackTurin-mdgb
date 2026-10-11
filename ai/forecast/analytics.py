"""Metrics of one crossing from what its node measured over the last 24 hours. Standard library only.

    summary(windows, events, now) -> dict (JSON-serialisable)

windows: the node's aggregates, oldest first, as built by app/dashboard.py ({"t0", "t1", "ped_in", "ped_out",
"cyclist", "vehicles", "animals", "provisional"}); events: the node's events of the same period as the control
room stores them (contract C3: "crossing", "yield", "near_miss", "incident"). Counts only: the node never sends
images or identities, so nothing here can identify anyone.
"""
import time

CLASSES = ("ped_in", "ped_out", "cyclist", "vehicles", "animals")
DAY_S, HOUR_S = 86400, 3600
MIN_COVERAGE = 0.5              # an hour counts for the peak only if the node measured at least half of it


def _totals(windows):
    return {k: sum(w.get(k, 0) for w in windows) for k in CLASSES}


def _overlap(w, a, b):
    """Seconds of the window that fall in [a, b)."""
    return max(0.0, min(w["t1"], b) - max(w["t0"], a))


def traffic(windows, now):
    """Counts of the last hour, of today and of the last 24 hours, hour by hour, with how much of each was measured."""
    day = [w for w in windows if w["t1"] > now - DAY_S and w["t1"] <= now + 1 and w["t1"] > w["t0"]]
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    first = (int(now // HOUR_S) - 23) * HOUR_S
    hourly = []
    for i in range(24):
        a = first + i * HOUR_S
        inside = [w for w in day if a <= w["t0"] < a + HOUR_S]          # a window belongs to the hour it starts in
        covered = min(1.0, sum(_overlap(w, a, min(a + HOUR_S, now)) for w in day) / HOUR_S)
        hourly.append(dict(_totals(inside), t0=a, t1=a + HOUR_S, coverage=round(covered, 2)))
    full = [h for h in hourly if h["coverage"] >= MIN_COVERAGE]
    peak = max(full, key=lambda h: h["ped_in"] + h["ped_out"], default=None)
    total = _totals(day)
    peds = total["ped_in"] + total["ped_out"]
    covered_s = sum(_overlap(w, now - DAY_S, now) for w in day)
    return {
        "last_hour": _totals([w for w in day if w["t1"] > now - HOUR_S]),
        "today": _totals([w for w in day if w["t0"] >= midnight]),
        "last_24h": total,
        "hourly": hourly,
        "peak_hour": None if peak is None or not peak["ped_in"] + peak["ped_out"] else
        {"t0": peak["t0"], "t1": peak["t1"], "pedestrians": peak["ped_in"] + peak["ped_out"]},
        "pedestrians_per_hour": round(peds / (covered_s / HOUR_S), 1) if covered_s >= HOUR_S * MIN_COVERAGE else None,
        "share_in": round(total["ped_in"] / peds, 2) if peds else None,
        "coverage_24h": round(min(1.0, covered_s / DAY_S), 3),
        "provisional_share": round(sum(bool(w.get("provisional")) for w in day) / len(day), 2) if day else None,
    }


def _vulnerable(ev):
    a = ev.get("attrs") or {}
    return bool(a.get("child") or a.get("slow") or a.get("aid") not in (None, "normal"))


def safety(events, now):
    """Yield rate, near misses, incidents and vulnerable pedestrians of the last 24 hours."""
    recent = [e for e in events if e.get("ts") is not None and now - DAY_S < e["ts"] <= now + 1]
    crossings = [e for e in recent if e.get("type") == "crossing" and e.get("cls") == "pedestrian"
                 and e.get("line", "ped") == "ped"]
    yields = [bool(e.get("yielded")) for e in recent if e.get("type") == "yield"]
    near = sum(1 for e in recent if e.get("type") == "near_miss")
    kinds = {}
    for e in recent:
        if e.get("type") == "incident":
            kinds[e.get("kind", "unknown")] = kinds.get(e.get("kind", "unknown"), 0) + 1
    vulnerable = sum(1 for e in crossings if _vulnerable(e))
    return {
        "pedestrian_crossings": len(crossings),
        "vulnerable": vulnerable,
        "vulnerable_share": round(vulnerable / len(crossings), 3) if crossings else None,
        "vehicles_met": len(yields),                 # vehicles that arrived while a pedestrian was waiting
        "yield_rate": round(sum(yields) / len(yields), 2) if yields else None,
        "near_miss": near,
        "near_miss_per_1000_crossings": round(1000.0 * near / len(crossings), 1) if crossings else None,
        "incidents": sum(kinds.values()),
        "incidents_by_kind": kinds,
    }


def summary(windows, events, now=None):
    now = time.time() if now is None else now
    return {"now": now, "traffic": traffic(windows, now), "safety": safety(events, now)}
