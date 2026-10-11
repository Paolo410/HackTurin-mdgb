"""Draws the app icon: the MDGB symbol of docs/brand (the smart camera, with the name under it), standard library only.

    python app/desktop/make_icon.py out.png            1024x1024 PNG
    python app/desktop/make_icon.py --ico out.ico      Windows icon with 256/64/48/32/16 px images
    python app/desktop/make_icon.py --iconset folder   the PNG files of a macOS .iconset (build_mac.sh, iconutil)
No binary file lives in the repo: the build scripts generate the icons.

The drawing is not repeated here: the shapes and the colours come from docs/brand/genera_logo.py, the same script
that writes the SVG files of the logo, so the icon follows the brand when that changes. Each size is drawn on its
own, not scaled from a bigger one: from NAME_FROM pixels up the icon has the name MDGB under the camera, below
that the camera alone, because the letters would be a smudge.
"""
import importlib.util
import math
import os
import struct
import sys
import zlib

BRAND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "docs", "brand", "genera_logo.py")
_spec = importlib.util.spec_from_file_location("genera_logo", BRAND)
brand = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brand)                              # importing it writes nothing: only main() does

MARGIN = 40 / 1024      # empty border around the square, as a share of the icon
NAME_FROM = 48          # smallest icon, in pixels, that carries the name under the camera
ICO_SIZES = (256, 64, 48, 32, 16)
ICONSET = {16: ("16x16",), 32: ("16x16@2x", "32x32"), 64: ("32x32@2x",), 128: ("128x128",),
           256: ("128x128@2x", "256x256"), 512: ("256x256@2x", "512x512"), 1024: ("512x512@2x",)}
EMPTY, SQUARE = 0, 1    # what a sample holds: nothing, the rounded square, or 2.. = the colour of a shape


def samples_per_side(n):
    """Sub-samples per pixel side, for smooth edges: more where the icon is small."""
    return 4 if n <= 128 else 3 if n <= 512 else 2


def rgb(hex_color):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def square_span(y):
    """Where the horizontal line y crosses the rounded square that fills the box, or None."""
    box, corner = brand.BOX, brand.CORNER
    if not 0 <= y <= box:
        return None
    d = max(corner - y, y - (box - corner), 0)               # how far into the band of the round corners
    inset = corner - math.sqrt(corner ** 2 - d ** 2)
    return inset, box - inset


def polygon_spans(rings, y):
    """Where the line y is inside a polygon with holes (even-odd rule over all its rings)."""
    xs = sorted(x1 + (x2 - x1) * (y - y1) / (y2 - y1)
                for ring in rings for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])
                if (y1 > y) != (y2 > y))
    return zip(xs[::2], xs[1::2])


def layers_of(shapes):
    """The shapes as (top, bottom, colour number, function y -> spans), the glows, and the colours by number."""
    colours, layers, glows = [None, rgb(brand.ASPHALT)], [], []
    for kind, colour, *rest in shapes:
        if kind == "glow":
            glows.append((rgb(colour), *rest))
            continue
        if rgb(colour) not in colours[2:]:
            colours.append(rgb(colour))
        index = colours.index(rgb(colour), 2)
        if kind == "circle":
            cx, cy, r = rest
            layers.append((cy - r, cy + r, index,
                           lambda y, cx=cx, cy=cy, r=r: [(cx - math.sqrt(r * r - (y - cy) ** 2),
                                                          cx + math.sqrt(r * r - (y - cy) ** 2))]))
        else:
            rings = [rest[0], *rest[1]]
            ys = [y for _, y in rest[0]]
            layers.append((min(ys), max(ys), index, lambda y, rings=rings: polygon_spans(rings, y)))
    return layers, glows, colours


def png_bytes(n, name=None):
    """n x n RGBA PNG of the icon. name: with MDGB under the camera (default: from NAME_FROM pixels up)."""
    layers, glows, colours = layers_of(brand.symbol(n >= NAME_FROM if name is None else name))
    s = samples_per_side(n)
    width = n * s
    scale = brand.BOX / (n * (1 - 2 * MARGIN))               # icon pixels -> units of the box
    offset = n * MARGIN

    def column(x):                                           # first sample whose centre is at x or beyond
        return min(max(math.ceil((x / scale + offset) * s - 0.5), 0), width)

    def fill(row, span, index):
        first, last = column(span[0]), column(span[1])
        if last > first:
            row[first:last] = bytes([index]) * (last - first)

    out = bytearray()
    for py in range(n):
        rows = []
        for sub in range(s):
            y = (py + (sub + 0.5) / s - offset) * scale
            row = bytearray(width)
            span = square_span(y)
            if span:
                fill(row, span, SQUARE)
                for top, bottom, index, spans in layers:
                    if top < y < bottom:
                        for one in spans(y):
                            fill(row, one, index)
            rows.append(row)
        out.append(0)                                        # PNG filter of the row: none
        cy = (py + 0.5 - offset) * scale
        for px in range(n):
            cell = b"".join(row[px * s:(px + 1) * s] for row in rows)
            if cell.count(EMPTY) == len(cell):
                out += b"\0\0\0\0"
                continue
            back = colours[SQUARE]
            if SQUARE in cell:                               # the glow lights the square, not the shapes on it
                cx = (px + 0.5 - offset) * scale
                for colour, gx, gy, radius, alpha in glows:
                    a = alpha * (1 - math.hypot(cx - gx, cy - gy) / radius)
                    if a > 0:
                        back = tuple(b * (1 - a) + g * a for b, g in zip(back, colour))
            seen = len(cell) - cell.count(EMPTY)
            mix = [0.0, 0.0, 0.0]
            for index in set(cell) - {EMPTY}:
                share = cell.count(index) / seen
                colour = back if index == SQUARE else colours[index]
                mix = [m + c * share for m, c in zip(mix, colour)]
            out += bytes((round(mix[0]), round(mix[1]), round(mix[2]), round(255 * seen / len(cell))))
    chunk = lambda tag, data: struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(out), 9)) + chunk(b"IEND", b""))


def write_ico(path, sizes=ICO_SIZES):
    """ICO with PNG-compressed images (supported since Windows Vista)."""
    images = [png_bytes(n) for n in sizes]
    out = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    for n, data in zip(sizes, images):
        out += struct.pack("<BBBBHHII", n % 256, n % 256, 0, 0, 1, 32, len(data), offset)   # 256 is written as 0
        offset += len(data)
    with open(path, "wb") as f:
        f.write(out + b"".join(images))


def write_iconset(folder):
    """The files iconutil turns into an .icns: icon_16x16.png, icon_16x16@2x.png, ... each drawn at its size."""
    os.makedirs(folder, exist_ok=True)
    for n, names in ICONSET.items():
        data = png_bytes(n)
        for name in names:
            with open(os.path.join(folder, f"icon_{name}.png"), "wb") as f:
                f.write(data)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--ico":
        write_ico(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--iconset":
        write_iconset(sys.argv[2])
    else:
        with open(sys.argv[1] if len(sys.argv) > 1 else "icon.png", "wb") as f:
            f.write(png_bytes(1024))
