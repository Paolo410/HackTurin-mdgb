"""Writes every file of the MDGB logo from one drawing, so they always match.

    python docs/brand/genera_logo.py

The drawing ("telecamera intelligente"): a street camera on its bracket, looking down at the crossing. Its lens is
the amber beacon, the arcs in front of it say that it sees and reports. The name MDGB is drawn here as shapes, not
typed in a font, so it looks the same on every system.

The drawing is a list of shapes (polygons, circles, one glow) in the 64x64 box of the symbol. The SVG files are
written from that list, and app/desktop/make_icon.py paints the same list for the icon of the app. The script also
rewrites the copies of the symbol that live inside other files (COPIES below): change the drawing or the colours
here, run the script, commit what it wrote. The alternatives in alternative/ are drawn by hand and are not touched.
Standard library only.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FONT = "Inter, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
ASPHALT, WHITE, AMBER, MUTED, MUTED_DARK = "#1d2226", "#f3f4f1", "#f2a900", "#59636b", "#a2abb2"
BOX = 64            # side of the box the symbol is drawn in
CORNER = 15         # radius of its rounded square
ARC_STEPS = 16      # points per quarter of a circle, where a curve becomes a polygon

# The camera, in the 64x64 box. Lengths along its axis (x) and across it (y), from the centre of the body.
TILT = 18.0                     # degrees it looks down
BODY = (30.0, 16.0, 5.0)        # length, height, corner radius
SHIELD = (3.5, -11.6, 34.0, 4.4)   # sun shield, detached from the body: centre x, centre y, length, height
LENS = (7.5, 5.4, 3.1)          # x on the body, radius of the dark ring, radius of the amber lens
ARCS = (16.5, (5.2, 10.2), 2.8, 40.0)   # centre x, radii, thickness, half opening in degrees
PLATE = (9.6, 4.6, 24.0)        # the plate on the pole: x in the box, width, height
ARM_H = 6.0                     # thickness of the arm between plate and body
GLOW = (18.0, 0.5)              # radius and strength of the light around the lens
CAMERA_AT = (30.0, 33.5)        # centre of the body, symbol without the name
NAMED_CAMERA = (0.9, 2.3, -3.6)    # with the name under it: scale, shift x, shift y of the camera
NAMED_CAP = 10.4                # ... and height of the letters; the name is centred, its base at NAMED_BASE
NAMED_BASE = 55.0

# The letters of the name, in units of their height.
STROKE = 0.2                    # thickness of the strokes
GAPS = (0.17, 0.11, 0.15)       # space after M, D, G (less next to the round G)


def arc(cx: float, cy: float, r: float, a0: float, a1: float) -> list[tuple[float, float]]:
    """Points along an arc from angle a0 to a1, in degrees: 0 points right, 90 down (clockwise on screen)."""
    n = max(2, round(abs(a1 - a0) / 90 * ARC_STEPS))
    angles = (math.radians(a0 + (a1 - a0) * i / n) for i in range(n + 1))
    return [(cx + r * math.cos(a), cy + r * math.sin(a)) for a in angles]


def rounded_box(cx: float, cy: float, w: float, h: float, r: float, angle: float = 0.0) -> list[tuple[float, float]]:
    """Outline of a rectangle with round corners, centred in (cx, cy) and turned by angle degrees."""
    corners = ((w / 2 - r, -h / 2 + r, -90), (w / 2 - r, h / 2 - r, 0), (-w / 2 + r, h / 2 - r, 90),
               (-w / 2 + r, -h / 2 + r, 180))
    cos, sin = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    points = [p for x, y, a in corners for p in arc(x, y, r, a, a + 90)]
    return [(cx + x * cos - y * sin, cy + x * sin + y * cos) for x, y in points]


def band(cx: float, cy: float, r: float, width: float, a0: float, a1: float) -> list[tuple[float, float]]:
    """Outline of a stroke with round ends that follows an arc of radius r from a0 to a1."""
    def end(a: float, first: float) -> list[tuple[float, float]]:
        rad = math.radians(a)
        return arc(cx + r * math.cos(rad), cy + r * math.sin(rad), width / 2, first, first + 180)[1:-1]
    return (arc(cx, cy, r + width / 2, a0, a1) + end(a1, a1)
            + arc(cx, cy, r - width / 2, a1, a0) + end(a0, a0 + 180))


def poly(colour: str, outline: list, *holes: list) -> tuple:
    return ("poly", colour, outline, list(holes))


def moved(shapes: list, k: float, dx: float, dy: float) -> list:
    """The shapes scaled by k around the origin, then shifted."""
    def pts(points: list) -> list:
        return [(x * k + dx, y * k + dy) for x, y in points]
    out = []
    for kind, colour, *rest in shapes:
        if kind == "poly":
            out.append((kind, colour, pts(rest[0]), [pts(hole) for hole in rest[1]]))
        else:   # circle: cx, cy, r; glow: cx, cy, r, alpha
            out.append((kind, colour, rest[0] * k + dx, rest[1] * k + dy, rest[2] * k, *rest[3:]))
    return out


def camera() -> list:
    """The camera: plate and arm on the left, body looking down to the right, amber lens, arcs in front."""
    cx, cy = CAMERA_AT
    cos, sin = math.cos(math.radians(TILT)), math.sin(math.radians(TILT))

    def at(x: float, y: float) -> tuple[float, float]:
        return cx + x * cos - y * sin, cy + x * sin + y * cos

    length, height, radius = BODY
    back, lens, front = at(-length / 2, 0), at(LENS[0], 0), at(ARCS[0], 0)
    plate_x, plate_w, plate_h = PLATE
    shapes = [
        ("glow", AMBER, *lens, *GLOW),
        poly(WHITE, rounded_box(plate_x, back[1], plate_w, plate_h, plate_w / 2)),
        poly(WHITE, rounded_box((plate_x + back[0]) / 2 + 1, back[1], back[0] - plate_x + 4, ARM_H, ARM_H / 2)),
        poly(WHITE, rounded_box(*at(SHIELD[0], SHIELD[1]), SHIELD[2], SHIELD[3], SHIELD[3] / 2, TILT)),
        poly(WHITE, rounded_box(cx, cy, length, height, radius, TILT)),
        ("circle", ASPHALT, *lens, LENS[1]),
        ("circle", AMBER, *lens, LENS[2]),
    ]
    for r in ARCS[1]:
        shapes.append(poly(AMBER, band(*front, r, ARCS[2], TILT - ARCS[3], TILT + ARCS[3])))
    return shapes


def letters() -> list[tuple[float, list]]:
    """M, D, G, B as (width, [(outline, holes), ...]) with the letter 1 high and its top left corner in (0, 0)."""
    t = STROKE
    w, a, dip, low = 1.06, 0.21, 0.5, 0.86          # M: width, top of the legs, the two points of the V
    k = low - dip / (w / 2 - a) * (w / 2 - t)       # where the inner side of the V leaves the leg
    m = [([(0, 1), (0, 0), (a, 0), (w / 2, dip), (w - a, 0), (w, 0), (w, 1), (w - t, 1), (w - t, k), (w / 2, low),
           (t, k), (t, 1)], [])]
    dw = 0.9
    d = [([(0, 0)] + arc(dw - 0.5, 0.5, 0.5, -90, 90) + [(0, 1)],
          [[(t, t)] + arc(dw - 0.5, 0.5, 0.5 - t, -90, 90) + [(t, 1 - t)]])]
    g = [(arc(0.5, 0.5, 0.5, -7, 318) + arc(0.5, 0.5, 0.5 - t, 318, -7), []),
         ([(0.5, 0.44), (0.98, 0.44), (0.98, 0.64), (0.5, 0.64)], [])]
    up, down = 0.47, 0.495                          # B: where the two bowls start to turn
    b = [([(0, 0)] + arc(up, 0.285, 0.285, -90, 90) + [(0, 0.57)],
          [[(t, 0.19)] + arc(up, 0.29, 0.10, -90, 90) + [(t, 0.39)]]),
         ([(0, 0.39)] + arc(down, 0.695, 0.305, -90, 90) + [(0, 1)],
          [[(t, 0.57)] + arc(down, 0.69, 0.12, -90, 90) + [(t, 0.81)]])]
    return [(w, m), (dw, d), (1.0, g), (0.8, b)]


def wordmark_width(cap: float) -> float:
    return (sum(width for width, _ in letters()) + sum(GAPS)) * cap


def wordmark(colour: str, x: float, y: float, cap: float) -> list:
    """The name MDGB as shapes: top left corner in (x, y), letters cap high."""
    shapes = []
    for (width, parts), gap in zip(letters(), GAPS + (0,)):
        shapes += moved([poly(colour, outline, *holes) for outline, holes in parts], cap, x, y)
        x += (width + gap) * cap
    return shapes


def symbol(name: bool = False) -> list:
    """The shapes on the rounded square: the camera alone, or (name=True) smaller with MDGB under it.
    With the name it needs about 48 px to be read: below that use the camera alone."""
    if not name:
        return camera()
    width = wordmark_width(NAMED_CAP)
    return moved(camera(), *NAMED_CAMERA) + wordmark(WHITE, (BOX - width) / 2, NAMED_BASE - NAMED_CAP, NAMED_CAP)


def num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def draw(shapes: list, uid: str) -> str:
    """The shapes as SVG elements. uid keeps the ids unique when several drawings share one page."""
    out = []
    for kind, colour, *rest in shapes:
        if kind == "poly":
            d = "".join("M" + " ".join(f"{num(x)},{num(y)}" for x, y in ring) + "Z" for ring in [rest[0], *rest[1]])
            out.append(f'<path d="{d}" fill="{colour}"' + (' fill-rule="evenodd"/>' if rest[1] else "/>"))
        elif kind == "circle":
            out.append(f'<circle cx="{num(rest[0])}" cy="{num(rest[1])}" r="{num(rest[2])}" fill="{colour}"/>')
        else:
            x, y, r, alpha = (num(v) for v in rest)
            out.append(f'<defs><radialGradient id="{uid}-glow" cx="{x}" cy="{y}" r="{r}" '
                       f'gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{colour}" '
                       f'stop-opacity="{alpha}"/><stop offset="1" stop-color="{colour}" stop-opacity="0"/>'
                       f'</radialGradient></defs><circle cx="{x}" cy="{y}" r="{r}" fill="url(#{uid}-glow)"/>')
    return "".join(out)


def mark(uid: str, edge: bool = False, name: bool = False, light: bool = True) -> str:
    """The symbol (64x64) as SVG elements: rounded square and camera. edge adds a thin border for dark
    backgrounds, name puts MDGB under the camera, light=False leaves out the glow (for very small sizes)."""
    square = (f'<rect x=".5" y=".5" width="{BOX - 1}" height="{BOX - 1}" rx="{CORNER - .5}" fill="{ASPHALT}" '
              f'stroke="{WHITE}" stroke-opacity=".25"/>' if edge
              else f'<rect width="{BOX}" height="{BOX}" rx="{CORNER}" fill="{ASPHALT}"/>')
    return square + draw([s for s in symbol(name) if light or s[0] != "glow"], uid)


def svg(view: str, width: int, height: int, title: str, body: str, note: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{width}" height="{height}" '
            f'role="img" aria-label="{title}">\n  <!-- {note} -->\n  {body}\n</svg>\n')


def lockup(dark: bool) -> str:
    """Symbol and name side by side."""
    name, tag = (WHITE, MUTED_DARK) if dark else (ASPHALT, MUTED)
    body = (f'<g transform="translate(4 8) scale(1.25)">{mark("lk", edge=dark)}</g>'
            + draw(wordmark(name, 105, 20, 36), "lk-name") +
            f'<text x="106" y="80" fill="{tag}" font-family="{FONT}" font-size="14.5" font-weight="500" '
            f'letter-spacing=".4">Mobility Data &amp; Guardian Beacon</text>')
    note = ("Logo for dark backgrounds (video, dark map)." if dark else "Logo for light backgrounds.") + \
        " The name is drawn; the line under it uses system fonts: for print or video retype it in the chosen typeface."
    return svg("0 0 400 96", 400, 96, "MDGB, Mobility Data &amp; Guardian Beacon", body, note)


PINS = {   # file name: (ring colour, meaning on the map of app/)
    "ok": ("#3fbf6a", "nodo OK"),
    "rete-giu": (AMBER, "rete giù, nodo sano (backup Bluetooth)"),
    "guasto": ("#e5483f", "guasto, manomissione o spento"),
    "senza-dati": ("#8a9399", "camera senza dati"),
}


def pin(color: str, meaning: str, uid: str) -> str:
    """Map pin of a node: the tip is the point on the map (x 24, y 62); the ring says the status."""
    body = (f'<path d="M24 62C24 62 4 38.5 4 23a20 20 0 0 1 40 0C44 38.5 24 62 24 62Z" fill="{ASPHALT}" '
            f'stroke="#ffffff" stroke-width="2"/>'
            f'<circle cx="24" cy="23" r="16.5" fill="none" stroke="{color}" stroke-width="3"/>'
            f'<g transform="translate(24 23.5) scale(.44) translate(-32 -32)">{mark(uid)}</g>')
    return svg("0 0 48 64", 48, 64, f"MDGB: {meaning}", body,
               "Map pin of a crossing node (central, app/). Tip at x 24, y 62.")


def title_card() -> str:
    """16:9 title card for the trailer: the crossing in perspective at the bottom, the camera watching over it."""
    vx, k, cap = 960, 0.42, 112
    stripes = "".join(
        f'<path d="M{x0} 1080H{x0 + 110}L{vx + (x0 + 110 - vx) * k:.0f} 860H{vx + (x0 - vx) * k:.0f}Z"/>'
        for x0 in (120 + i * 200 for i in range(9)))
    body = (f'<defs><radialGradient id="card-glow" cx="960" cy="330" r="430" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{AMBER}" stop-opacity=".22"/>'
            f'<stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="card-road" x1="0" y1="860" x2="0" y2="1080" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{WHITE}" stop-opacity="0"/>'
            f'<stop offset="1" stop-color="{WHITE}" stop-opacity=".16"/></linearGradient></defs>'
            f'<rect width="1920" height="1080" fill="#101316"/><rect width="1920" height="1080" fill="url(#card-glow)"/>'
            f'<g fill="url(#card-road)">{stripes}</g>'
            f'<g transform="translate(800 170) scale(5)">{mark("card", edge=True)}</g>'
            + draw(wordmark(WHITE, vx - wordmark_width(cap) / 2, 650 - cap, cap), "card-name") +
            f'<text x="960" y="730" text-anchor="middle" fill="{MUTED_DARK}" font-family="{FONT}" font-size="40" '
            f'font-weight="500" letter-spacing="2">Mobility Data &amp; Guardian Beacon</text>'
            f'<text x="960" y="800" text-anchor="middle" fill="{AMBER}" font-family="{FONT}" font-size="30" '
            f'font-weight="600" letter-spacing="1">Ogni attraversamento ha un guardiano.</text>')
    return svg("0 0 1920 1080", 1920, 1080, "MDGB: cartello del trailer", body,
               "Title card for the trailer, 1920x1080. The two lines of text use system fonts: retype them in the "
               "chosen typeface.")


def python_text(name: str, text: str, width: int = 100) -> str:
    """A long string as a Python constant, split over lines that fit the page."""
    pieces = [text[i:i + width] for i in range(0, len(text), width)]
    return f"{name} = (\n" + "".join(f"    {piece!r}\n" for piece in pieces) + ")\n"


def page_module() -> str:
    """ai/smartcrossing/brand.py: the symbol inside the technician's page (the board has no docs/ folder)."""
    logo = f'<svg class="logo" viewBox="0 0 {BOX} {BOX}" aria-hidden="true">{mark("lg")}</svg>'
    icon = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BOX} {BOX}">{mark("fav", light=False)}</svg>')
    favicon = "data:image/svg+xml," + quote(icon.replace('"', "'"), safe=" ='/:,.-")
    return ('"""The MDGB symbol for the technician\'s page: the same drawing as docs/brand/mdgb-simbolo.svg.\n\n'
            "Written by docs/brand/genera_logo.py: do not edit it by hand, change the drawing there and run it again.\n"
            'The ids start with "lg-": operator_ui.py renames them for each copy of the logo in the page.\n"""\n\n'
            + python_text("LOGO", logo) + "\n" + python_text("FAVICON", favicon))


def dashboard_page(text: str) -> str:
    """app/dashboard.html with the symbol of its header replaced by the current one."""
    new = f'<svg width="40" height="40" viewBox="0 0 {BOX} {BOX}">{mark("hd")}</svg>'
    out, found = re.subn(r'(<div class="logo" aria-hidden="true">)<svg.*?</svg>(</div>)',
                         lambda m: m.group(1) + new + m.group(2), text, flags=re.S)
    if found != 1:
        raise SystemExit("app/dashboard.html: non trovo il simbolo nell'intestazione (<div class=\"logo\" ...>)")
    return out


def main() -> None:
    files = {
        "mdgb-simbolo.svg": svg(f"0 0 {BOX} {BOX}", BOX, BOX, "MDGB", mark("sym"),
                                "Symbol of MDGB: the smart camera watching the crossing, its lens is the beacon."),
        "mdgb-icona.svg": svg(f"0 0 {BOX} {BOX}", BOX, BOX, "MDGB", mark("ico", name=True),
                              "Symbol with the name under the camera: app icon, avatar. From about 48 px up."),
        "mdgb-logo.svg": lockup(dark=False),
        "mdgb-logo-scuro.svg": lockup(dark=True),
        "trailer/mdgb-cartello-16x9.svg": title_card(),
    }
    for name, (color, meaning) in PINS.items():
        files[f"mappa/pin-{name}.svg"] = pin(color, meaning, f"pin-{name}")
    # COPIES: the symbol inside other files, which cannot read this folder when they run.
    # Panel of the App Lab app (firmware/unoq_mcu/assets, packed in both zips).
    files["../../firmware/unoq_mcu/assets/logo.svg"] = files["mdgb-simbolo.svg"]
    # Technician's page of the vision.
    files["../../ai/smartcrossing/brand.py"] = page_module()
    # Header of the dashboard of the central.
    dashboard = REPO / "app" / "dashboard.html"
    files["../../app/dashboard.html"] = dashboard_page(dashboard.read_text(encoding="utf-8"))
    for rel, text in files.items():
        path = (HERE / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        print(rel)


if __name__ == "__main__":
    main()
