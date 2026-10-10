"""Decoder lato backend dell'aggregato LoRa da 28 byte (stesso layout di crosswalk-node/python/payload.py
e di ttn_formatter.js). È volutamente indipendente dal codice del nodo: i test verificano che coincidano."""
import struct

CATEGORIES = ["person", "wheelchair", "bicycle", "stroller", "other"]


def decode(data: bytes, port: int = 1) -> dict:
    if port == 9:
        return {"alarm": "mpu_silent"}
    if port in (10, 11):                     # manomissione / incidente sospetto: ts u32 | codice u8
        ts = struct.unpack_from("<I", data, 0)[0] if len(data) >= 4 else 0
        return {"alarm": "tamper" if port == 10 else "incident", "ts": ts,
                "code": data[4] if len(data) > 4 else 0}
    if len(data) != 28:
        raise ValueError(f"payload di {len(data)} byte, attesi 28")
    flags, t0 = data[0], struct.unpack_from("<I", data, 1)[0]
    c = struct.unpack_from("<10H", data, 5)
    backlog, disk = struct.unpack_from("<HB", data, 25)
    return {
        "version": flags >> 4,
        "offline": ((flags >> 2) & 3) == 1,
        "ts_quality": flags & 3,
        "window_start": t0,
        "dir0": dict(zip(CATEGORIES, c[0:5])),
        "dir1": dict(zip(CATEGORIES, c[5:10])),
        "backlog": backlog * 10,
        "disk_free_pct": disk,
    }
