"""Writes every file of the main MDGB placeholder logo from one drawing, so they always match.

    python docs/brand/genera_logo.py

The drawing ("strisce e faro"): a geometric M cut by horizontal bands, like the stripes of a crossing seen from a
car; the amber beacon sits in the notch of the M and watches over it. Change MARK or the colours here, run the
script, commit the SVG files. The alternatives in alternative/ are drawn by hand and are not touched.
Standard library only.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT = "Inter, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
ASPHALT, WHITE, AMBER, MUTED, MUTED_DARK = "#1d2226", "#f3f4f1", "#f2a900", "#59636b", "#a2abb2"

# The M, in a 64x64 box: outer legs, and the two diagonals that meet in the middle.
M_POINTS = "10,52 10,13 19.5,13 32,31 44.5,13 54,13 54,52 45,52 45,29 32,47.5 19,29 19,52"
BANDS = [(13 + i * 8.25, 6) for i in range(5)]          # (top, height) of the five stripes: 13 .. 52
BEACON = (32, 20.5, 4.4)                                 # centre x, centre y, radius of the amber lamp


def mark(uid: str, edge: bool = False) -> str:
    """The symbol (64x64) as SVG elements. uid keeps the ids unique when several symbols share one page."""
    bands = "".join(f'<rect x="0" y="{top}" width="64" height="{h}"/>' for top, h in BANDS)
    x, y, r = BEACON
    border = (f'<rect x=".5" y=".5" width="63" height="63" rx="14.5" fill="{ASPHALT}" stroke="{WHITE}" '
              f'stroke-opacity=".25"/>' if edge else f'<rect width="64" height="64" rx="15" fill="{ASPHALT}"/>')
    return (f'<defs><clipPath id="{uid}-bands">{bands}</clipPath>'
            f'<radialGradient id="{uid}-glow" cx="{x}" cy="{y}" r="15" gradientUnits="userSpaceOnUse">'
            f'<stop offset="0" stop-color="{AMBER}" stop-opacity=".55"/>'
            f'<stop offset="1" stop-color="{AMBER}" stop-opacity="0"/></radialGradient></defs>'
            f'{border}'
            f'<circle cx="{x}" cy="{y}" r="15" fill="url(#{uid}-glow)"/>'
            f'<polygon points="{M_POINTS}" fill="{WHITE}" clip-path="url(#{uid}-bands)"/>'
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="{AMBER}"/>')


def svg(view: str, width: int, height: int, title: str, body: str, note: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{width}" height="{height}" '
            f'role="img" aria-label="{title}">\n  <!-- {note} -->\n  {body}\n</svg>\n')


def lockup(dark: bool) -> str:
    """Symbol and name side by side."""
    name, tag = (WHITE, MUTED_DARK) if dark else (ASPHALT, MUTED)
    body = (f'<g transform="translate(4 8) scale(1.25)">{mark("lk", edge=dark)}</g>'
            f'<text x="104" y="56" fill="{name}" font-family="{FONT}" font-size="46" font-weight="800" '
            f'letter-spacing="5">MDGB</text>'
            f'<text x="106" y="80" fill="{tag}" font-family="{FONT}" font-size="14.5" font-weight="500" '
            f'letter-spacing=".4">Mobility Data &amp; Guardian Beacon</text>')
    note = ("Logo for dark backgrounds (video, dark map)." if dark else "Logo for light backgrounds.") + \
        " Placeholder: the name uses system fonts; for print or video retype it in the chosen typeface."
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
    """16:9 title card for the trailer: the crossing in perspective at the bottom, the beacon lighting the logo."""
    vx, k = 960, 0.42
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
            f'<text x="960" y="650" text-anchor="middle" fill="{WHITE}" font-family="{FONT}" font-size="150" '
            f'font-weight="800" letter-spacing="18">MDGB</text>'
            f'<text x="960" y="730" text-anchor="middle" fill="{MUTED_DARK}" font-family="{FONT}" font-size="40" '
            f'font-weight="500" letter-spacing="2">Mobility Data &amp; Guardian Beacon</text>'
            f'<text x="960" y="800" text-anchor="middle" fill="{AMBER}" font-family="{FONT}" font-size="30" '
            f'font-weight="600" letter-spacing="1">Ogni attraversamento ha un guardiano.</text>')
    return svg("0 0 1920 1080", 1920, 1080, "MDGB: cartello del trailer", body,
               "Title card for the trailer, 1920x1080. Placeholder: retype the texts in the chosen typeface.")


def main() -> None:
    files = {
        "mdgb-simbolo.svg": svg("0 0 64 64", 64, 64, "MDGB", mark("sym"),
                                "Placeholder logo of MDGB: the M made of crossing stripes, the beacon watching it."),
        "mdgb-logo.svg": lockup(dark=False),
        "mdgb-logo-scuro.svg": lockup(dark=True),
        "trailer/mdgb-cartello-16x9.svg": title_card(),
    }
    for name, (color, meaning) in PINS.items():
        files[f"mappa/pin-{name}.svg"] = pin(color, meaning, f"pin-{name}")
    # Copy used by the panel of the App Lab app (firmware/unoq_mcu/assets, packed in both zips).
    files["../../firmware/unoq_mcu/assets/logo.svg"] = files["mdgb-simbolo.svg"]
    for rel, text in files.items():
        path = (HERE / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        print(rel)


if __name__ == "__main__":
    main()
