"""Drive the firmware from a PC with C1 commands and C2 heartbeats (docs/CONTRACTS.md v1).

Cycles through a scenario of C1 states (each resent every second, as the contract asks), sends C2 at 10 Hz
and prints every C5 line coming back from the MCU. With --stop-hb-at the heartbeat stops: the firmware
must fail safe within 500 ms.

    python -m comms.tools.c1_send --port /dev/cu.usbmodem1101 --duration 30 --stop-hb-at 20
    python -m comms.tools.c1_send --port sim --duration 3          # no hardware
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from comms.actuators import make_actuator

SCENARIO = [
    {"state": "IDLE", "led": "OFF", "green_s": 0, "req": {"ped_green_extend_s": 0, "veh_red_hold": False, "flash": False},
     "lcd": "", "oled": "", "reason": "nessuno in zona"},
    {"state": "PRESENCE", "led": "WHITE_ON", "green_s": 0, "req": {"ped_green_extend_s": 0, "veh_red_hold": False, "flash": False},
     "lcd": "PEDONE", "oled": "", "reason": "pedone in zona d'attesa"},
    {"state": "WARN_DRIVER", "led": "AMBER_BLINK_2HZ", "green_s": 19,
     "req": {"ped_green_extend_s": 7, "veh_red_hold": True, "flash": False},
     "lcd": "PEDONE  47 km/h", "oled": "ATTENDI auto 45km/h",
     "reason": "anziano 0.8 m/s; auto 50 km/h a 60 m; TTC 4.3 s < T_need 9.8 s"},
    {"state": "WARN_PEDESTRIAN", "led": "RED_GROUND_BLINK", "green_s": 19,
     "req": {"ped_green_extend_s": 7, "veh_red_hold": True, "flash": False},
     "lcd": "PEDONE!", "oled": "STOP auto vicina", "reason": "auto a 25 m senza decelerare"},
    {"state": "ANIMAL_ALERT", "led": "AMBER_BLINK_4HZ", "green_s": 0,
     "req": {"ped_green_extend_s": 0, "veh_red_hold": False, "flash": True},
     "lcd": "ANIMALE IN STRADA", "oled": "", "reason": "animale large in carreggiata"},
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="serial port, or 'sim' to run without hardware")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--duration", type=float, default=30.0, help="seconds")
    ap.add_argument("--period", type=float, default=3.0, help="seconds per scenario state")
    ap.add_argument("--stop-hb-at", type=float, default=None, help="stop C2 after this many seconds")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    def on_c5(obj):
        if obj.get("type") != "thermal":
            print("C5 <-", obj, flush=True)

    if a.port == "sim":
        act = make_actuator("sim", verbose=True, listener=on_c5)
    else:
        act = make_actuator("serial", port=a.port, baud=a.baud, listener=on_c5)

    t0 = time.monotonic()
    seq = hb = 0
    t_cmd = t_hb = -1.0
    last_state = None
    try:
        while (now := time.monotonic() - t0) < a.duration:
            cmd = dict(SCENARIO[int(now // a.period) % len(SCENARIO)])
            if cmd["state"] != last_state or now - t_cmd >= 1.0:          # on change, and at least every 1 s
                seq += 1
                cmd.update({"v": 1, "seq": seq, "t_ms": int(time.time() * 1000)})
                act.send(cmd)
                if cmd["state"] != last_state:
                    print(f"{now:6.1f} s  C1 -> {cmd['state']} ({cmd['led']})", flush=True)
                last_state, t_cmd = cmd["state"], now
            hb_on = a.stop_hb_at is None or now < a.stop_hb_at
            if hb_on and now - t_hb >= 0.1:
                hb += 1
                act.heartbeat(hb)
                t_hb = now
            if not hb_on and t_hb >= 0:
                print(f"{now:6.1f} s  C2 fermato: il firmware deve andare in fail-safe entro 500 ms", flush=True)
                t_hb = -1e9                                                # print once
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        act.close()
    print(f"fine: {seq} C1 e {hb} C2 inviati")
    return 0


if __name__ == "__main__":
    sys.exit(main())
