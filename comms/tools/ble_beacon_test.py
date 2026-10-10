"""First real-radio check of the BLE backup: run it ON THE UNO Q, watch it from the laptop.

    UNO Q:   python -m comms.tools.ble_beacon_test --seconds 60          (add --sudo if not root)
    laptop:  python app/ble_receiver.py --node nodo01 --dry-run

Every 5 s it advertises a C4-B HB frame (plus, on instance 3, a "technician badge" notice: TAMPER code 3, shown as
information, not as an alarm) with the real btmgmt commands used by the node, then switches the beacons off.
The laptop (or the app, channel BLE of nodo01) must show the HB with an increasing ts.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "node"))
from backup_link import BleBackup  # noqa: E402  (flat modules of comms/node)
from payload import TYPE_HB, TYPE_TAMPER, pack_alarm, pack_hb  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--sudo", action="store_true", help="prefix btmgmt with sudo")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ble = BleBackup(sudo=a.sudo)
    t_end, n = time.time() + a.seconds, 0
    try:
        if not ble.send(pack_alarm(time.time(), 3), TYPE_TAMPER):
            print("btmgmt add-adv fallito: controlla `which btmgmt`, `sudo btmgmt info` e i permessi (--sudo)")
            return 1
        while time.time() < t_end:
            n += 1
            ble.send(pack_hb(time.time(), "normal", "IDLE", backlog=0), TYPE_HB)
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        ble.idle()
    print(f"{n} HB trasmessi; beacon spenti")
    return 0


if __name__ == "__main__":
    sys.exit(main())
