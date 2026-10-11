---
name: motion-graphics-generator
description: Code-driven motion graphics with Remotion (React) for the trailer — titles, lower-thirds, stat cards, HUD detection overlays, formula/LCD/OLED panels, heartbeat, network diagram, Turin map, end title. Use to change on-screen text, animations or the edit, then render.
---

# Motion graphics generator (Remotion)

Project: `trailer/motion/` (Remotion 4, React 19, fonts Barlow Condensed / Barlow / JetBrains Mono from
@fontsource, so rendering works offline). Data in, video out:
`build/public/data/timeline.json` (made by `tools/build.py data`) -> `src/Trailer.tsx`.

## Structure
- `src/Trailer.tsx` — one `<Sequence>` per scene: footage (`components/Shots.tsx`) + overlay (`scenes/*`) + finishing (vignette, grain, flashes).
- `src/components/Shots.tsx` — plays the shots of a scene, CSS grades (`night`, `dusk`, `dusk2night`, `dawn`, `neutral`, `neutralDark`), slow zoom, tilt-shift, freeze frames.
- `src/scenes/open.tsx` (B01–B04), `reveal.tsx` (B05–B06), `proof.tsx` (B07–B13), `close.tsx` (B14–B15); `scenes/index.ts` maps scene ids to overlays.
- `src/theme.ts` — colours of the animatic (night stage, amber beacon, traffic-light accents), fonts, easing.
- All on-screen text comes from `timeline.json` -> `scenes[].ost`: edit text there, not in the components.

## Commands (from `trailer/motion`)
- Preview in the browser: `npm run studio` (public dir is `../build/public`).
- QC stills: `node scripts/stills.mjs 90 480 1500` -> `build/stills/`.
- One scene only: `npx remotion render src/index.ts Scene out.mp4 --props='{"only":"B07"}'`.
- Full render: `python tools/build.py render` (uses `REMOTION_BROWSER` if set, otherwise Remotion's own Chrome).

## Rules
- Safe margins 5 % (`SAFE_X`, `SAFE_Y`); text in Barlow Condensed, data in JetBrains Mono.
- Overlays that follow people use real detections (`tools/detect.py`, team's YOLOX): re-run it when the footage changes.
- Label simulations as such ("CONCEPT · SIMULATED DATA"); never show a feature that does not run.
- Remotion licence: free for individuals and small teams; check remotion.dev/license before commercial use.
