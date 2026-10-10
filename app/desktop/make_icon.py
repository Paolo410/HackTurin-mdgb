"""Draws the app icon (a traffic light on a dark rounded square) as a 1024x1024 PNG, standard library only.

    python app/desktop/make_icon.py out.png
build_mac.sh turns it into icon.icns with sips + iconutil, so no binary file lives in the repo.
"""
import struct
import sys
import zlib

N = 1024


def rounded(x, y, x0, y0, x1, y1, r):
    """True if (x, y) is inside the rounded rectangle."""
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(x, y):
    if not rounded(x, y, 40, 40, N - 40, N - 40, 200):
        return (0, 0, 0, 0)                                  # transparent corners
    if rounded(x, y, 352, 150, 672, 874, 120):               # traffic light body
        for cy, color in ((290, (226, 75, 74)), (512, (239, 159, 39)), (734, (99, 153, 34))):
            if (x - 512) ** 2 + (y - cy) ** 2 <= 92 ** 2:
                return color + (255,)
        return (28, 30, 34, 255)
    if (y - 650) ** 2 + (x - 512) ** 2 <= 470 ** 2 and abs(y - 650) < 6:   # thin road line behind the pole
        return (90, 104, 120, 255)
    return (31, 42, 55, 255)                                 # background


def write_png(path):
    rows = bytearray()
    for y in range(N):
        rows.append(0)                                       # filter: none
        for x in range(N):
            rows.extend(pixel(x, y))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", N, N, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    write_png(sys.argv[1] if len(sys.argv) > 1 else "icon.png")
