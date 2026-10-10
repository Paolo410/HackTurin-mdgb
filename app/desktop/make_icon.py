"""Draws the app icon (a traffic light on a dark rounded square), standard library only.

    python app/desktop/make_icon.py out.png            1024x1024 PNG (build_mac.sh turns it into .icns)
    python app/desktop/make_icon.py --ico out.ico      Windows icon with 256/64/48/32/16 px images
No binary file lives in the repo: the build scripts generate the icons.
"""
import struct
import sys
import zlib

REF = 1024   # the drawing is defined on a 1024x1024 canvas and sampled at any size


def rounded(x, y, x0, y0, x1, y1, r):
    """True if (x, y) is inside the rounded rectangle."""
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def pixel(x, y):
    if not rounded(x, y, 40, 40, REF - 40, REF - 40, 200):
        return (0, 0, 0, 0)                                  # transparent corners
    if rounded(x, y, 352, 150, 672, 874, 120):               # traffic light body
        for cy, color in ((290, (226, 75, 74)), (512, (239, 159, 39)), (734, (99, 153, 34))):
            if (x - 512) ** 2 + (y - cy) ** 2 <= 92 ** 2:
                return color + (255,)
        return (28, 30, 34, 255)
    if (y - 650) ** 2 + (x - 512) ** 2 <= 470 ** 2 and abs(y - 650) < 6:   # thin road line behind the pole
        return (90, 104, 120, 255)
    return (31, 42, 55, 255)                                 # background


def png_bytes(n):
    """n x n RGBA PNG; each pixel samples the centre of its cell on the reference canvas."""
    k = REF / n
    rows = bytearray()
    for y in range(n):
        rows.append(0)                                       # filter: none
        for x in range(n):
            rows.extend(pixel((x + 0.5) * k, (y + 0.5) * k))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


def write_ico(path, sizes=(256, 64, 48, 32, 16)):
    """ICO with PNG-compressed images (supported since Windows Vista)."""
    images = [png_bytes(n) for n in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for n, data in zip(sizes, images):
        out += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)   # 256 is written as 0
        offset += len(data)
    with open(path, "wb") as f:
        f.write(out + b"".join(images))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--ico":
        write_ico(sys.argv[2])
    else:
        with open(sys.argv[1] if len(sys.argv) > 1 else "icon.png", "wb") as f:
            f.write(png_bytes(REF))
