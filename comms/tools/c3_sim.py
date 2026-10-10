"""Write simulated C3 lines to $MDGB_C3_DIR as ai/ will do (docs/CONTRACTS.md v1), plus a `status` line every 5 s.
Lets you run the whole network (node with EVENT_SOURCE=c3) before the vision pipeline is ready.

    python -m comms.tools.c3_sim --rate 2 --duration 600
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from comms.jsonl import JsonlWriter, default_c3_dir

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "node"))
from event_source import SimulatedSource  # noqa: E402  (flat module of comms/node)


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
    print(f"{n} eventi C3 scritti in {a.dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
