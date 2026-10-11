"""Formati dati del nodo (docs/CONTRACTS.md v1): evento e aggregato JSON (C4), messaggi binari di backup (C4-B).

C4-B, little-endian. BLE: frame = type(1) | corpo (zeri in coda fino a 27 byte). LoRaWAN: fPort = type, payload = corpo.
  AGG  (type 1), 26 byte: ver|ts_q|degraded | t0 u32 | min u8 | ped_in u16 | ped_out u16 | bici u16 | veicoli u16 |
                          animali u8 | vulnerabili u8 | near_miss u8 | incidenti u8 | yield % u8 | t_c i8 | rh u8 |
                          lux u16 | backlog/10 u16 | batt % u8
  HB   (type 2), 12 byte: ver|mode|ts_q | ts u32 | state u8 | backlog/10 u16 | batt % u8 | disco % u8 | min senza ACK u16
  DEAD (type 9): 0xDE 0xAD (lo manda l'MCU)      TAMPER/INCIDENT/FAULT (type 10/11/12): ts u32 | code u8
Il decoder della centrale (app/decoder.py) è scritto a parte: i test verificano che coincidano.
"""
import struct

C4_VERSION = 1
B_VERSION = 1

# righe C3/C5 che NON diventano eventi: alimentano `hb` e `agg` (C4)
INFO_TYPES = {"status", "env", "thermal"}

TYPE_AGG, TYPE_HB, TYPE_DEAD, TYPE_TAMPER, TYPE_INCIDENT, TYPE_FAULT = 1, 2, 9, 10, 11, 12
AGG_FMT, HB_FMT, ALARM_FMT = "<BIBHHHHBBBBBbBHHB", "<BIBHBBH", "<IB"
assert (struct.calcsize(AGG_FMT), struct.calcsize(HB_FMT), struct.calcsize(ALARM_FMT)) == (26, 12, 5)

STATES = ["IDLE", "PRESENCE", "WARN_DRIVER", "WARN_PEDESTRIAN", "ANIMAL_WARN", "ANIMAL_ALERT", "DEGRADED"]
MODES = {"normal": 0, "degraded": 1, "failsafe": 2}
INCIDENT_CODES = {"person_down": 1, "collision": 2, "hard_brake": 3, "vehicle_on_crosswalk": 4}
FAULT_CODES = {"lamp_fault": 1, "video_lost": 2, "lens_covered": 3, "glare": 4, "firmware_failsafe": 5}
TSQ_NTP, TSQ_RTC = 0, 1

VEHICLES = {"car", "motorcyclist", "bus", "truck"}
ANIMALS = {"animal", "bird"}
NA8, NA16, NA_I8 = 255, 0xFFFF, -128


def event_id(node_id: str, seq: int) -> str:
    return f"{node_id}-{seq:06d}"


def is_vulnerable(ev: dict) -> bool:
    a = ev.get("attrs") or {}
    return bool(a.get("child") or a.get("slow") or a.get("aid") not in (None, "normal"))


def summarize(events, t0, t1, node_id, env=None, queue=0):
    """Aggregato C4 `agg` della finestra [t0, t1) calcolato dagli eventi su disco (quindi esatto)."""
    counts, vulnerable, near_miss, incident, yields = {}, 0, 0, 0, []
    for ev in events:
        t = ev.get("type")
        if t == "crossing":
            # "Pedoni in/out" are the crossings of the pedestrian line: a pedestrian over the vehicle line (walking
            # along the road) is not a crossing of the stripes and must not move those numbers.
            if ev.get("cls") == "pedestrian" and ev.get("line", "ped") != "ped":
                continue
            c = counts.setdefault(ev.get("cls", "unknown"), {"in": 0, "out": 0})
            if ev.get("dir") in c:
                c[ev["dir"]] += 1
            vulnerable += ev.get("cls") == "pedestrian" and is_vulnerable(ev)
        elif t == "near_miss":
            near_miss += 1
        elif t == "incident":
            incident += 1
        elif t == "yield":
            yields.append(bool(ev.get("yielded")))
    return {"v": C4_VERSION, "node_id": node_id, "type": "agg", "t0": int(t0), "t1": int(t1), "counts": counts,
            "vulnerable": vulnerable, "near_miss": near_miss, "incident": incident,
            "yield_rate": round(sum(yields) / len(yields), 2) if yields else None,
            "env": env or {}, "queue": queue}


def _u8(x):
    """Valore opzionale: 255 = non disponibile, quindi si satura a 254."""
    return NA8 if x is None else max(0, min(int(round(x)), 254))


def _cnt8(x):
    return max(0, min(int(x), 255))


def _u16(x):
    return max(0, min(int(x), 0xFFFE))


def pack_agg(agg: dict, backlog: int, batt=None, degraded=False, ts_quality=TSQ_NTP) -> bytes:
    """Aggregato JSON (summarize) -> corpo AGG da 26 byte."""
    c = agg["counts"]
    tot = lambda classes: sum(v["in"] + v["out"] for k, v in c.items() if k in classes)
    env = agg.get("env") or {}
    yr = agg.get("yield_rate")
    t_c = env.get("t_c")
    flags = (B_VERSION << 4) | ((ts_quality & 3) << 2) | (int(bool(degraded)) << 1)
    return struct.pack(
        AGG_FMT, flags, int(agg["t0"]), max(1, min(255, (agg["t1"] - agg["t0"]) // 60)),
        _u16(c.get("pedestrian", {}).get("in", 0)), _u16(c.get("pedestrian", {}).get("out", 0)),
        _u16(tot({"cyclist"})), _u16(tot(VEHICLES)),
        _cnt8(tot(ANIMALS)), _cnt8(agg["vulnerable"]), _cnt8(agg["near_miss"]), _cnt8(agg["incident"]),
        _u8(None if yr is None else 100 * yr),
        NA_I8 if t_c is None else max(-127, min(127, int(round(t_c)))),
        _u8(env.get("rh")), NA16 if env.get("lux") is None else _u16(env["lux"]),
        _u16(backlog // 10), _u8(batt))


def pack_hb(ts, mode="normal", state=None, backlog=0, batt=None, disk_free_pct=None, offline_min=0,
            ts_quality=TSQ_NTP) -> bytes:
    flags = (B_VERSION << 4) | (MODES.get(mode, 1) << 2) | (ts_quality & 3)
    st = STATES.index(state) if state in STATES else NA8
    return struct.pack(HB_FMT, flags, int(ts), st, _u16(backlog // 10), _u8(batt), _u8(disk_free_pct),
                       _u16(offline_min))


def pack_alarm(ts, code) -> bytes:
    return struct.pack(ALARM_FMT, int(ts), int(code) & 0xFF)


ALARM_TYPES = ("incident", "tamper", "lamp_fault", "failsafe")   # eventi che sul backup partono subito


def alarm_to_c4b(ev: dict):
    """Evento C3/C5 di allarme -> (type C4-B, corpo da 5 byte); None se non è un allarme."""
    t, ts = ev.get("type"), ev.get("ts") or 0
    if t == "incident":
        return TYPE_INCIDENT, pack_alarm(ts, INCIDENT_CODES.get(ev.get("kind"), 0))
    if t == "tamper":
        return TYPE_TAMPER, pack_alarm(ts, ev.get("code", 0))
    if t == "lamp_fault":
        return TYPE_FAULT, pack_alarm(ts, FAULT_CODES["lamp_fault"])
    if t == "failsafe":
        return TYPE_FAULT, pack_alarm(ts, FAULT_CODES["firmware_failsafe"])
    return None
