"""Shared by the tests of the expected-flow model (ai/forecast): canned surroundings, a clock, a small GeoTIFF
laid out like ESA WorldCover, a forecaster that never touches the network and the windows a node would send."""
import struct
import time
import zlib

from forecast.context import Context
from forecast.service import Forecaster

CENTRE = {"poi": {"food": 60, "shop": 140, "transit": 10, "edu": 2, "leisure": 60, "road": 0},
          "esa": {"built": 0.95, "green": 0.03, "water": 0.0}}
SUBURB = {"poi": {"food": 2, "shop": 8, "transit": 2, "edu": 1, "leisure": 3, "road": 4},
          "esa": {"built": 0.6, "green": 0.35, "water": 0.0}}
NODE = {"id": "nodo01", "name": "Corso Castelfidardo", "lat": 45.0614, "lon": 7.6581}


def local(day, hour, minute=0, month=10, year=2026):
    """Epoch seconds of a local date and time (the model works on the local time of the control room)."""
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


MONDAY_18 = local(12, 18)           # 12 October 2026 is a Monday


def tiled_tiff(pixels, tile=32, lon0=6.0, lat0=48.0, scale=1 / 12000.0, compression=8, byte_order=b"II"):
    """A small GeoTIFF laid out like ESA WorldCover: little-endian, 8 bit, deflate, square tiles."""
    h, w = len(pixels), len(pixels[0])
    tiles = [zlib.compress(bytes(pixels[r][c] for r in range(tr, tr + tile) for c in range(tc, tc + tile)))
             for tr in range(0, h, tile) for tc in range(0, w, tile)]
    n = len(tiles)
    entries = [(256, 3, 1, w), (257, 3, 1, h), (258, 3, 1, 8), (259, 3, 1, compression), (317, 3, 1, 1),
               (322, 3, 1, tile), (323, 3, 1, tile), (324, 4, n, None), (325, 4, n, None), (33550, 12, 3, None),
               (33922, 12, 6, None)]
    at = 8 + 2 + 12 * len(entries) + 4
    extra = {324: at, 325: at + 4 * n, 33550: at + 8 * n, 33922: at + 8 * n + 24}
    data_at = at + 8 * n + 24 + 48
    offsets, at_byte = [], data_at
    for t in tiles:
        offsets.append(at_byte)
        at_byte += len(t)
    out = byte_order + b"*\x00" + struct.pack("<I", 8) + struct.pack("<H", len(entries))
    for tag, typ, count, value in entries:
        out += struct.pack("<HHII", tag, typ, count, extra.get(tag, value))
    out += struct.pack("<I", 0) + struct.pack("<%dI" % n, *offsets) + struct.pack("<%dI" % n, *map(len, tiles))
    out += struct.pack("<3d", scale, scale, 0.0) + struct.pack("<6d", 0.0, 0.0, 0.0, lon0, lat0, 0.0)
    return out + b"".join(tiles)


def ranged(blob, asked=None):
    """An `http` stand-in that serves `blob` to range requests, as the public WorldCover bucket does."""
    def http(url, data=None, headers=None, timeout=None):
        a, b = map(int, headers["Range"].split("=")[1].split("-"))
        if asked is not None:
            asked.append((url, a, b))
        return blob[a:b + 1]
    return http


def forecaster(model, parts=CENTRE, now=MONDAY_18):
    """A Forecaster whose surroundings are `parts` ({part: data}); no thread, no network."""
    ctx = Context(None, {k: (lambda lat, lon, v=v: dict(v)) for k, v in parts.items()}, clock=lambda: now,
                  background=False)
    ctx.refresh(NODE["lat"], NODE["lon"])
    return Forecaster(model, ctx, clock=lambda: now)


def windows(now, n, length, ped_in, ped_out=0, vehicles=0, cyclist=0, end=None):
    """What a node measured: n windows of `length` seconds ending at `end` (default: the last one closed before now)."""
    t1 = int((now if end is None else end) // length) * length
    return [{"t0": t1 - (i + 1) * length, "t1": t1 - i * length, "ped_in": ped_in, "ped_out": ped_out,
             "cyclist": cyclist, "vehicles": vehicles, "animals": 0, "provisional": False, "env": {"t_c": 14.0}}
            for i in reversed(range(n))]
