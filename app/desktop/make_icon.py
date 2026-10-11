"""Draws the app icon: the MDGB symbol of docs/brand ("strisce e faro"), standard library only.

    python app/desktop/make_icon.py out.png            1024x1024 PNG (build_mac.sh turns it into .icns)
    python app/desktop/make_icon.py --ico out.ico      Windows icon with 256/64/48/32/16 px images
No binary file lives in the repo: the build scripts generate the icons.

The drawing is not repeated here: shape and colours come from docs/brand/genera_logo.py, the same script that
writes the SVG files of the logo, so the icon follows the brand when that changes. The symbol is the M of MDGB
cut by five bands, like the stripes of a crossing, with the amber beacon in its notch, on a dark rounded square.
"""
import importlib.util
import os
import struct
import sys
import zlib

BRAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "brand", "genera_logo.py")
_spec = importlib.util.spec_from_file_location("genera_logo", BRAND)
brand = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brand)                              # importing it writes nothing: only main() does

BOX = 64.0          # the symbol is drawn in a 64x64 box
CORNER = 15.0       # radius of its rounded square (rx in mdgb-simbolo.svg)
GLOW_RADIUS = 15.0  # the beacon's glow: amber at GLOW_ALPHA in the centre, fading to nothing at this radius
GLOW_ALPHA = 0.55
MARGIN = 40 / 1024  # empty border around the square, as a share of the icon (as in the previous icon)
SAMPLES = {1024: 1} # sub-samples per side for a size; the big PNG is scaled down by the build, the others get 4


def rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


ASPHALT, WHITE, AMBER = rgb(brand.ASPHALT), rgb(brand.WHITE), rgb(brand.AMBER)
M = [tuple(float(v) for v in point.split(",")) for point in brand.M_POINTS.split()]
BANDS = [(float(top), float(top) + float(height)) for top, height in brand.BANDS]
BEACON_X, BEACON_Y, BEACON_R = (float(v) for v in brand.BEACON)


def in_rounded_square(x, y):
    """True if (x, y) is inside the rounded square that fills the 64x64 box."""
    if not (0 <= x <= BOX and 0 <= y <= BOX):
        return False
    cx = min(max(x, CORNER), BOX - CORNER)
    cy = min(max(y, CORNER), BOX - CORNER)
    return (x - cx) ** 2 + (y - cy) ** 2 <= CORNER ** 2


def in_m(x, y):
    """True if (x, y) is inside the M (ray casting) and on one of the bands that cut it."""
    if not any(top <= y <= bottom for top, bottom in BANDS):
        return False
    inside = False
    for (x1, y1), (x2, y2) in zip(M, M[1:] + M[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def color_at(x, y):
    """RGBA of the symbol at a point of its 64x64 box. Same order as the SVG: square, glow, M, beacon."""
    if not in_rounded_square(x, y):
        return (0, 0, 0, 0)                                  # transparent corners
    distance = ((x - BEACON_X) ** 2 + (y - BEACON_Y) ** 2) ** 0.5
    if distance <= BEACON_R:
        return AMBER + (255,)
    if in_m(x, y):
        return WHITE + (255,)
    if distance < GLOW_RADIUS:
        a = GLOW_ALPHA * (1 - distance / GLOW_RADIUS)
        return tuple(round(c * (1 - a) + g * a) for c, g in zip(ASPHALT, AMBER)) + (255,)
    return ASPHALT + (255,)


def pixel(px, py, n, samples):
    """One pixel of an n x n icon: the mean of samples x samples points, for smooth edges at small sizes."""
    scale = BOX / (n * (1 - 2 * MARGIN))                     # icon pixels -> units of the 64x64 box
    offset = n * MARGIN
    total = [0.0, 0.0, 0.0, 0.0]
    for sy in range(samples):
        for sx in range(samples):
            r, g, b, a = color_at((px + (sx + 0.5) / samples - offset) * scale,
                                  (py + (sy + 0.5) / samples - offset) * scale)
            total[0] += r * a
            total[1] += g * a
            total[2] += b * a
            total[3] += a
    if total[3] == 0:
        return (0, 0, 0, 0)
    return (round(total[0] / total[3]), round(total[1] / total[3]), round(total[2] / total[3]),
            round(total[3] / samples ** 2))


def png_bytes(n):
    """n x n RGBA PNG of the icon."""
    samples = SAMPLES.get(n, 4)
    rows = bytearray()
    for y in range(n):
        rows.append(0)                                       # filter: none
        for x in range(n):
            rows.extend(pixel(x, y, n, samples))
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
            f.write(png_bytes(1024))
