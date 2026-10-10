"""Plays a scripted scene through tracker, geometry, rules and actuator, without a camera.

Usage (from ai/):
    python scripts/scenario.py                      # list of the scenarios
    python scripts/scenario.py elderly_fast_car     # prints every change of state with its reason
    python scripts/scenario.py elderly_fast_car --realtime --actuator serial --port /dev/cu.usbmodem1101

With a real actuator the lamps and the displays of the firmware follow the scene: no video is needed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartcrossing.actuator import make_actuator  # noqa: E402
from smartcrossing.config import load_config  # noqa: E402
from smartcrossing.sim import SCENARIOS, run_scenario  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("name", nargs="?", choices=sorted(SCENARIOS))
    p.add_argument("--fps", type=float, default=10.0, help="frames per second of the virtual camera")
    p.add_argument("--realtime", action="store_true", help="play at real speed (needed with a real actuator)")
    p.add_argument("--actuator", choices=["sim", "serial", "bridge"], default="sim")
    p.add_argument("--port", help="serial port of the firmware, with --actuator serial")
    p.add_argument("--site", choices=["urbano", "lungofiume", "collina"])
    args = p.parse_args()
    if args.name is None:
        for name, make in sorted(SCENARIOS.items()):
            print(f"{name:<22} {make.__doc__.strip()}")
        return 0

    cfg = load_config()
    try:
        actuator = make_actuator(args.actuator, cfg, **({"port": args.port} if args.port else {}))
    except (RuntimeError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    last = {"state": None}

    def show(t: float, command: dict, _pipeline) -> None:
        if command["state"] != last["state"]:
            last["state"] = command["state"]
            req = command["req"]
            print(f"t={t:5.1f}s {command['state']:<16} LED {command['led']:<17} green {command['green_s']}s "
                  f"+{req['ped_green_extend_s']}s red_hold={int(req['veh_red_hold'])} flash={int(req['flash'])}")
            print(f"         LCD [{command['lcd']}]  OLED [{command['oled']}]")
            print(f"         {command['reason']}")

    pipeline = run_scenario(cfg, args.name, fps=args.fps, actuator=actuator, realtime=args.realtime,
                            site=args.site, on_step=show)
    pipeline.commander.close()
    print("counts  " + pipeline.counter.summary())
    print("events  " + pipeline.events.summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
