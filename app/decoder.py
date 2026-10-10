"""Decoder lato centrale dei messaggi di backup C4-B (docs/CONTRACTS.md v1), stesso layout di
comms/node/payload.py. È volutamente indipendente dal codice del nodo: i test verificano
che coincidano. I frame BLE hanno zeri in coda: per ogni tipo si leggono solo i byte che servono."""
import struct

STATES = ["IDLE", "PRESENCE", "WARN_DRIVER", "WARN_PEDESTRIAN", "ANIMAL_WARN", "ANIMAL_ALERT", "DEGRADED"]
MODES = ["normal", "degraded", "failsafe"]
TAMPER = {1: "shock_or_tilt", 2: "door_open", 3: "authorized_badge"}
INCIDENT = {1: "person_down", 2: "collision", 3: "hard_brake", 4: "vehicle_on_crosswalk"}
FAULT = {1: "lamp_fault", 2: "video_lost", 3: "lens_covered", 4: "glare", 5: "firmware_failsafe"}
ALARMS = {10: ("tamper", TAMPER), 11: ("incident", INCIDENT), 12: ("fault", FAULT)}


def _na(v, na):
    return None if v == na else v


def _need(data, n, what):
    if len(data) < n:
        raise ValueError(f"{what}: {len(data)} byte, attesi {n}")


def decode(type_: int, data: bytes) -> dict:
    if type_ == 1:
        _need(data, 26, "AGG")
        (f, t0, mins, p_in, p_out, bike, veh, animals, vuln, nm, inc, yr, t_c, rh, lux, backlog,
         batt) = struct.unpack_from("<BIBHHHHBBBBBbBHHB", data)
        return {"kind": "agg", "version": f >> 4, "ts_quality": (f >> 2) & 3, "degraded": bool(f & 2),
                "t0": t0, "t1": t0 + 60 * mins, "pedestrian": {"in": p_in, "out": p_out}, "cyclist": bike,
                "vehicles": veh, "animals": animals, "vulnerable": vuln, "near_miss": nm, "incident": inc,
                "yield_rate": None if yr == 255 else yr / 100,
                "env": {"t_c": _na(t_c, -128), "rh": _na(rh, 255), "lux": _na(lux, 0xFFFF)},
                "backlog": backlog * 10, "batt": _na(batt, 255)}
    if type_ == 2:
        _need(data, 12, "HB")
        f, ts, st, backlog, batt, disk, off_min = struct.unpack_from("<BIBHBBH", data)
        mode = (f >> 2) & 3
        return {"kind": "hb", "version": f >> 4, "mode": MODES[mode] if mode < len(MODES) else "unknown",
                "ts_quality": f & 3, "ts": ts, "state": STATES[st] if st < len(STATES) else None,
                "backlog": backlog * 10, "batt": _na(batt, 255), "disk_free_pct": _na(disk, 255),
                "offline_min": off_min}
    if type_ == 9:
        return {"kind": "alarm", "alarm": "dead"}           # watchdog dell'MCU: Linux bloccato
    if type_ in ALARMS:
        _need(data, 5, "allarme")
        ts, code = struct.unpack_from("<IB", data)
        name, codes = ALARMS[type_]
        return {"kind": "alarm", "alarm": name, "ts": ts, "code": code, "detail": codes.get(code, "unknown")}
    raise ValueError(f"type C4-B sconosciuto: {type_}")
