"""TEST TOOL, launched by hand: writes made-up C3 lines to $MDGB_C3_DIR exactly as ai/ does (docs/CONTRACTS.md v1),
plus a `status` line every 5 s. Lets you try the whole network on the board (the node reads these files like the
real ones) before the vision pipeline runs. The node itself never makes events up.

    python -m comms.tools.c3_sim --rate 2 --duration 600
"""
from __future__ import annotations

import argparse
import random
import sys
import time

from comms.jsonl import JsonlWriter, default_c3_dir

# rough mix of the users of an urban crossing
SIM_MIX = [("pedestrian", 0.55), ("car", 0.25), ("cyclist", 0.10), ("motorcyclist", 0.04), ("bus", 0.02),
           ("truck", 0.02), ("animal", 0.02)]


class SimulatedSource:
    """Plausible C3 lines (crossing, sometimes near_miss or yield); also used by the tests."""

    def __init__(self, rate_hz=0.5, seed=None):
        self.rate = rate_hz
        self.rng = random.Random(seed)
        self._track = 0

    def make_event(self, ts=None):
        r, ts = self.rng, time.time() if ts is None else ts
        self._track += 1
        if r.random() < 0.01:
            return {"v": 1, "ts": ts, "type": "near_miss", "a": self._track, "b": self._track + 1,
                    "ttc_s": round(r.uniform(0.3, 1.0), 2), "pet_s": None}
        cls = r.choices(*zip(*SIM_MIX))[0]
        if cls == "car" and r.random() < 0.3:
            return {"v": 1, "ts": ts, "type": "yield", "track_id": self._track, "yielded": r.random() < 0.5}
        ev = {"v": 1, "ts": ts, "type": "crossing", "track_id": self._track, "cls": cls,
              "dir": r.choice(["in", "out"]), "line": "ped" if cls in ("pedestrian", "cyclist") else "veh"}
        if cls == "pedestrian":
            ev["attrs"] = {"child": r.random() < 0.05, "slow": r.random() < 0.10,
                           "aid": r.choice(["wheelchair", "stroller"]) if r.random() < 0.04 else None}
        if cls == "animal":
            ev["coco"] = "dog"
        return ev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=default_c3_dir())
    ap.add_argument("--rate", type=float, default=1.0, help="events per second (Poisson)")
    ap.add_argument("--duration", type=float, default=60.0, help="seconds")
    ap.add_argument("--state", default="PRESENCE", help="state written in the status lines (e.g. DEGRADED)")
    a = ap.parse_args(argv)
    sim, w = SimulatedSource(a.rate), JsonlWriter(a.dir, "c3")
    t_end, t_status, n = time.time() + a.duration, 0.0, 0
    try:
        while (now := time.time()) < t_end:
            if now - t_status >= 5:
                w.write({"v": 1, "ts": round(now, 3), "type": "status", "state": a.state, "fps": 9.6})
                t_status = now
            w.write(dict(sim.make_event(), ts=round(now, 3)))
            n += 1
            time.sleep(min(sim.rng.expovariate(a.rate), max(0.0, t_end - time.time())))
    except KeyboardInterrupt:
        pass
    finally:
        w.close()
    print(f"{n} eventi C3 di prova scritti in {a.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
