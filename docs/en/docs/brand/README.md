# MDGB logo (placeholder)

> English translation of [`docs/brand/README.md`](../../../brand/README.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

Temporary logo of MDGB (Mobility Data & Guardian Beacon), to use until there is a final one.
To compare the proposals open [`proposte.html`](../../../brand/proposte.html) in a browser (works without a network).

**Main proposal, "stripes and beacon":** the M of MDGB cut by five horizontal bands, like the stripes of a crossing seen
from a car; the amber beacon in the notch of the M watches over the crossing.

## Files

| File | For |
|---|---|
| `mdgb-simbolo.svg` | the symbol alone (icon, favicon, avatar); already inside the technician page |
| `../../firmware/unoq_mcu/assets/logo.svg` | copy of the symbol for the panel of the App Lab app (bar and icon), written by `genera_logo.py` |
| `mdgb-logo.svg` | symbol and name, for light backgrounds |
| `mdgb-logo-scuro.svg` | symbol and name, for dark backgrounds (video, dark map) |
| `mappa/pin-ok.svg`, `pin-rete-giu.svg`, `pin-guasto.svg`, `pin-senza-dati.svg` | map pins for the central office, with the status colours of `app/` (tip at x 24, y 62 of the 48×64 drawing) |
| `trailer/mdgb-cartello-16x9.svg` | title card for the trailer, 1920×1080 |
| `alternative/` | three alternative proposals: shield, eye, lantern (drawn by hand) |
| `genera_logo.py` | regenerates every file of the main proposal from a single drawing |

To change a colour or the drawing: edit `genera_logo.py`, then run `python docs/brand/genera_logo.py`, and commit the
SVG files. Remember to update the logo inside `ai/smartcrossing/operator_ui.py` too (same drawing).

## Colours

| Name | Code | Use |
|---|---|---|
| Asphalt | `#1d2226` | background of the symbol, texts |
| Sign white | `#f3f4f1` | stripes, light backgrounds |
| Beacon amber | `#f2a900` | the beacon, accents |
| Green / red | `#3fbf6a` / `#e5483f` | statuses (OK / fault) |
| Sign blue | `#1f5fae` | links and information |

## Minimum rules

- Free space around the symbol: at least a quarter of its width.
- Below 16 px use the symbol alone, without the name.
- The name uses system fonts: for print and video retype it in the typeface chosen for the trailer.
- Do not stretch, rotate, or change the colours of the beacon and the stripes.
