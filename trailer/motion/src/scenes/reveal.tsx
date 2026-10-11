// Act II — the reveal. B05 the beacon · B06 on the traffic light that's already there
import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { shotAt } from "../components/Shots";
import { Svg, useT } from "../components/ui";
import { C, F, prog, rgba, SAFE_X, SAFE_Y } from "../theme";
import type { Scene } from "../types";

/** The MDGB mark: a traffic light whose three lamps collapse into one amber beacon. */
export const Beacon: React.FC<{ t: number; cx: number; cy: number; scale?: number }> = ({ t, cx, cy, scale = 1 }) => {
  const merge = prog(t, 0.9, 1.7);
  const lamps = [C.red, C.amber, C.green];
  const appear = (i: number) => prog(t, 0.15 + i * 0.18, 0.45 + i * 0.18);
  const rings = [0, 1, 2].map((i) => ((t - 1.7 + i * 0.6) % 1.8 + 1.8) % 1.8);
  return (
    <g transform={`translate(${cx},${cy}) scale(${scale})`}>
      <rect x={-46} y={-150} width={92} height={300} rx={26} fill="none" stroke={C.dim} strokeWidth={3} opacity={(1 - merge) * 0.8} />
      {lamps.map((c, i) => {
        const y0 = -95 + i * 95;
        const y = y0 * (1 - merge);
        const col = merge > 0.6 ? C.amber : c;
        return <circle key={i} cx={0} cy={y} r={30 + merge * 6} fill={col} opacity={appear(i)}
          style={{ filter: `drop-shadow(0 0 ${18 + merge * 30}px ${rgba(col, 0.9)})` }} />;
      })}
      {t > 1.7 ? rings.map((r, i) => (
        <circle key={`r${i}`} cx={0} cy={0} r={40 + r * 220} fill="none" stroke={C.amber} strokeWidth={3} opacity={Math.max(0, 0.7 - r * 0.4)} />
      )) : null}
    </g>
  );
};

// ------------------------------------------------------------------ B05 — "This is MDGB."
export const B05: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const dark = interpolate(t, [0, 0.5, 4.2, 4.6], [0.25, 0.55, 0.6, 0.92], { extrapolateRight: "clamp" });
  const kw = prog(t, 1.8, 2.6);
  const ks = prog(t, 2.7, 3.4);
  const track = interpolate(kw, [0, 1], [0.6, 0.12]);
  const out = 1 - prog(t, 7.5, 8.0);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "#040507", opacity: dark }} />
      <AbsoluteFill style={{ opacity: out }}>
        <Svg><Beacon t={t} cx={960} cy={360} scale={0.9} /></Svg>
        <div style={{ position: "absolute", left: 0, right: 0, top: 560, textAlign: "center" }}>
          <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 230, lineHeight: 0.9, color: C.ink, letterSpacing: `${track}em`,
            opacity: kw, filter: `blur(${(1 - kw) * 10}px)`, textShadow: `0 0 50px ${rgba(C.amber, 0.25)}` }}>{o.wordmark}</div>
          <div style={{ fontFamily: F.mono, fontSize: 28, letterSpacing: "0.32em", color: C.amber, marginTop: 18, opacity: ks,
            textTransform: "uppercase" }}>{o.expansion}</div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B06 — Turin, then the node on the pole
export const B06: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const { i, local } = shotAt(scene.shots, t);
  if (i === 0) {
    const k = prog(local, 0.3, 1.2);
    const out = 1 - prog(local, scene.shots[0].dur - 0.35, scene.shots[0].dur);
    return (
      <AbsoluteFill style={{ opacity: out }}>
        <div style={{ position: "absolute", left: 0, right: 0, top: 130, textAlign: "center" }}>
          <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 200, color: C.ink, letterSpacing: `${0.5 - k * 0.2}em`,
            opacity: k * 0.92, textShadow: "0 6px 40px rgba(0,0,0,0.55)" }}>{o.city}</div>
          <div style={{ fontFamily: F.mono, fontSize: 24, letterSpacing: "0.3em", color: C.ink, opacity: k * 0.8 }}>45.07° N · 7.69° E</div>
        </div>
      </AbsoluteFill>
    );
  }
  // callout pinned to the traffic-light head
  const ax = 1010, ay = 300;                 // anchor on the lamp housing (frame of clip c16)
  const bx = 1250, by = 150;                 // callout box
  const kl = prog(local, 0.2, 0.7), kb = prog(local, 0.55, 1.0);
  const lines = o.lines as string[];
  return (
    <AbsoluteFill>
      <Svg>
        <circle cx={ax} cy={ay} r={14} fill={C.amber} opacity={kl} style={{ filter: `drop-shadow(0 0 14px ${C.amber})` }} />
        <circle cx={ax} cy={ay} r={14 + ((local * 1.4) % 1) * 40} fill="none" stroke={C.amber} strokeWidth={2} opacity={kl * (1 - ((local * 1.4) % 1))} />
        <polyline points={`${ax},${ay} ${ax + (bx - ax) * kl * 0.6},${by + 60} ${ax + (bx - ax) * kl},${by + 60}`} fill="none" stroke={C.amber} strokeWidth={3} opacity={kl} />
      </Svg>
      <div style={{ position: "absolute", left: bx, top: by, width: 560, padding: "22px 28px", background: "rgba(8,10,13,0.78)",
        border: `1px solid ${rgba(C.amber, 0.6)}`, borderLeft: `6px solid ${C.amber}`, opacity: kb, transform: `translateX(${(1 - kb) * 30}px)` }}>
        <div style={{ fontFamily: F.mono, fontSize: 22, letterSpacing: "0.24em", color: C.amber }}>{o.tag}</div>
        {lines.map((l, k) => (
          <div key={k} style={{ fontFamily: F.display, fontWeight: 700, fontSize: k === 0 ? 72 : 40, lineHeight: 1.05, color: C.ink,
            marginTop: k === 0 ? 6 : 4, opacity: prog(local, 0.8 + k * 0.35, 1.2 + k * 0.35) }}>{l}</div>
        ))}
      </div>
      <div style={{ position: "absolute", left: SAFE_X, bottom: SAFE_Y, fontFamily: F.mono, fontSize: 20, color: C.dim, opacity: kb }}>
        ARDUINO UNO Q · CAMERA · LED BEACON · NO CLOUD
      </div>
    </AbsoluteFill>
  );
};
