"""Formati dati condivisi: categorie, evento JSON (MQTT) e aggregato binario da 28 byte (LoRa).

Layout aggregato (little-endian, 28 byte):
  byte 0      : ver(4 bit) | net_state(2 bit) | ts_quality(2 bit)
  byte 1-4    : window_start  uint32  (Unix epoch, secondi)
  byte 5-14   : direzione 0 -> 5 x uint16 (person, wheelchair, bicycle, stroller, other)
  byte 15-24  : direzione 1 -> 5 x uint16
  byte 25-26  : backlog eventi non ancora inviati / 10  (uint16)
  byte 27     : spazio disco libero %  (uint8)
"""
import struct

CATEGORIES = ["person", "wheelchair", "bicycle", "stroller", "other"]
CAT_ID = {name: i for i, name in enumerate(CATEGORIES)}
SLOW_USERS = {"wheelchair", "stroller"}          # attivano l'estensione del verde

AGG_VERSION = 1
NET_ONLINE, NET_OFFLINE = 0, 1
TSQ_NTP, TSQ_RTC = 0, 1
AGG_FMT = "<BI10HHB"
AGG_SIZE = struct.calcsize(AGG_FMT)              # = 28
assert AGG_SIZE == 28


def cat_id(label: str) -> int:
    return CAT_ID.get(label, CAT_ID["other"])


def event_to_json(seq, ts, cat, direction, conf):
    """Rappresentazione compatta di un evento nel messaggio MQTT."""
    return {"seq": seq, "ts": round(ts, 3), "cat": CATEGORIES[cat], "dir": direction, "conf": round(conf, 2)}


def pack_aggregate(window_start, counts, backlog, disk_free_pct, online, ts_quality=TSQ_NTP):
    """counts: matrice 2x5 [direzione][categoria]."""
    flags = (AGG_VERSION << 4) | ((NET_ONLINE if online else NET_OFFLINE) << 2) | (ts_quality & 3)
    flat = [min(int(n), 0xFFFF) for d in range(2) for n in counts[d]]
    return struct.pack(AGG_FMT, flags, int(window_start), *flat,
                       min(int(backlog) // 10, 0xFFFF), max(0, min(int(disk_free_pct), 100)))


def unpack_aggregate(data: bytes) -> dict:
    v = struct.unpack(AGG_FMT, data)
    flags, t0, c = v[0], v[1], v[2:12]
    return {
        "version": flags >> 4,
        "offline": ((flags >> 2) & 3) == NET_OFFLINE,
        "ts_quality": flags & 3,
        "window_start": t0,
        "dir0": dict(zip(CATEGORIES, c[0:5])),
        "dir1": dict(zip(CATEGORIES, c[5:10])),
        "backlog": v[12] * 10,
        "disk_free_pct": v[13],
    }
