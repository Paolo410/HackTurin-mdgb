// Act IV — vision and close. B14 the city · B15 the time you need
import React, { useMemo } from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { Chip, Svg, useT } from "../components/ui";
import { SAN_CARLO, TO_H, TO_RING, TO_W } from "../lib/turin";
import { C, F, mulberry, prog, rgba, SAFE_X, SAFE_Y } from "../theme";
import type { Scene } from "../types";
import { Beacon } from "./reveal";

const inPoly = (x: number, y: number, ring: [number, number][]) => {
  let ins = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
};

// ------------------------------------------------------------------ B14 — a hundred crossings tell the city
export const B14: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const MAP_IN = scene.shots[0].dur - 0.9;                // map takes over at the end of the aerial
  const km = prog(t, MAP_IN, MAP_IN + 1.0);
  const S = 860 / TO_H, ox = 960 - (TO_W * S) / 2 + 120, oy = 110;
  const P = (x: number, y: number): [number, number] => [ox + x * S, oy + y * S];
  const ringPath = useMemo(() => TO_RING.map(([x, y], i) => `${i ? "L" : "M"}${P(x, y).join(",")}`).join("") + "Z", []);
  const nodes = useMemo(() => {
    const r = mulberry(17), out: { x: number; y: number; d: number; hot: boolean }[] = [];
    let tries = 0;
    while (out.length < 100 && tries++ < 5000) {
      const x = r() * TO_W, y = r() * TO_H;
      if (!inPoly(x, y, TO_RING)) continue;
      const d = Math.hypot(x - SAN_CARLO[0], y - SAN_CARLO[1]);
      out.push({ x, y, d, hot: false });
    }
    out.sort((a, b) => a.d - b.d);
    out.slice(0, 40).filter((_, i) => i % 3 === 0).slice(0, 12).forEach((n) => (n.hot = true));
    return out;
  }, []);
  const maxD = nodes[nodes.length - 1]?.d ?? 1;
  const grow = prog(t, MAP_IN + 0.3, MAP_IN + 2.6);
  const flows = useMemo(() => {
    const r = mulberry(5);
    return Array.from({ length: 26 }).map(() => [Math.floor(r() * 60), Math.floor(r() * 100)] as [number, number]);
  }, []);
  const kc = prog(t, MAP_IN + 2.4, MAP_IN + 3.0);
  // on the aerial: a few nodes already glowing over the rooftops
  const pre = prog(t, 0.8, 2.0) * (1 - km);
  return (
    <AbsoluteFill>
      <Svg style={{ opacity: pre }}>
        {[[520, 640], [760, 700], [1010, 620], [1240, 690], [1460, 640], [880, 820], [1130, 860]].map(([x, y], i) => (
          <g key={i}>
            <circle cx={x} cy={y} r={7} fill={C.amber} style={{ filter: `drop-shadow(0 0 12px ${C.amber})` }} opacity={prog(t, 0.8 + i * 0.15, 1.1 + i * 0.15)} />
            <circle cx={x} cy={y} r={7 + ((t + i * 0.3) % 1.2) * 30} fill="none" stroke={C.amber} strokeWidth={2} opacity={(1 - ((t + i * 0.3) % 1.2) / 1.2) * 0.6} />
          </g>
        ))}
      </Svg>
      <AbsoluteFill style={{ background: C.bg, opacity: km }}>
        <Svg>
          <path d={ringPath} fill={rgba(C.blue, 0.05)} stroke={rgba(C.ink, 0.55)} strokeWidth={2} strokeDasharray={4000} strokeDashoffset={4000 * (1 - prog(t, MAP_IN, MAP_IN + 1.6))} />
          {flows.map(([a, b], i) => {
            const na = nodes[a], nb = nodes[b];
            if (!na || !nb) return null;
            const [x1, y1] = P(na.x, na.y), [x2, y2] = P(nb.x, nb.y);
            const mx = (x1 + x2) / 2, my = (y1 + y2) / 2 - 40;
            return <path key={i} d={`M${x1},${y1} Q${mx},${my} ${x2},${y2}`} fill="none" stroke={rgba(C.blue, 0.5)} strokeWidth={1.6}
              strokeDasharray="6 10" strokeDashoffset={-t * 40} opacity={prog(t, MAP_IN + 1.4, MAP_IN + 2.2)} />;
          })}
          {nodes.map((n, i) => {
            const [x, y] = P(n.x, n.y);
            const on = grow >= n.d / maxD ? 1 : 0;
            const hot = n.hot && t > MAP_IN + 2.4;
            const pulse = hot ? 1 + 0.6 * Math.abs(Math.sin(t * 4 + i)) : 1;
            return <circle key={i} cx={x} cy={y} r={(hot ? 7 : 4.5) * pulse} fill={hot ? C.amber : C.green} opacity={on * (hot ? 1 : 0.85)}
              style={hot ? { filter: `drop-shadow(0 0 10px ${C.amber})` } : undefined} />;
          })}
        </Svg>
        <div style={{ position: "absolute", left: SAFE_X, top: SAFE_Y + 30 }}>
          <div style={{ fontFamily: F.mono, fontSize: 22, letterSpacing: "0.3em", color: C.dim }}>TURIN · 100 CROSSINGS</div>
          <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 96, color: C.ink, lineHeight: 0.95 }}>THE CITY,<br />IN REAL TIME</div>
        </div>
        <div style={{ position: "absolute", left: SAFE_X, bottom: SAFE_Y + 40, padding: "20px 26px", background: "rgba(14,17,21,0.92)",
          borderLeft: `6px solid ${C.amber}`, opacity: kc, transform: `translateY(${(1 - kc) * 20}px)` }}>
          {(o.forecast as string[]).map((l, i) => (
            <div key={i} style={{ fontFamily: i === 0 ? F.mono : F.display, fontWeight: i === 0 ? 500 : 700, fontSize: i === 0 ? 22 : 44,
              letterSpacing: i === 0 ? "0.24em" : "0.02em", color: i === 2 ? C.amber : C.ink, marginTop: i ? 4 : 0 }}>{l}</div>
          ))}
        </div>
        <div style={{ position: "absolute", right: SAFE_X, bottom: SAFE_Y }}>
          <Chip t={t} t0={MAP_IN + 1.0} color={C.dim}>{o.label}</Chip>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B15 — MDGB. The time you need.
export const B15: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const HIT = 1.07;                                       // the music's final hit (timeline 113.07 s)
  const count = t < 0.6 ? 1247 : 1248;
  const kc = prog(t, 0.1, 0.4) * (1 - prog(t, HIT - 0.1, HIT + 0.2));
  const plus = prog(t, 0.6, 0.8) * (1 - prog(t, 1.0, 1.2));
  const dim = interpolate(t, [HIT - 0.05, HIT + 0.3], [0, 0.72], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const kt = prog(t, HIT, HIT + 0.45);
  const scale = interpolate(kt, [0, 1], [1.22, 1]);
  const kg = prog(t, HIT + 0.9, HIT + 1.6), ke = prog(t, HIT + 2.4, HIT + 2.9), kteam = prog(t, HIT + 3.2, HIT + 3.8);
  const kcr = prog(t, 6.1, 6.6);
  const team = o.team as [string, string][];
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", right: SAFE_X, top: SAFE_Y + 20, textAlign: "right", opacity: kc }}>
        <div style={{ fontFamily: F.mono, fontSize: 20, letterSpacing: "0.24em", color: C.dim }}>{o.counter}</div>
        <div style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 84, color: C.ink }}>{count.toLocaleString("en-US")}</div>
        <div style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 44, color: C.green, opacity: plus }}>+1</div>
      </div>
      <AbsoluteFill style={{ background: "#05070A", opacity: dim }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center", marginTop: -60 }}>
          <svg width={120} height={120} style={{ opacity: kt, display: "block", margin: "0 auto 10px" }}>
            <g transform="translate(60,60) scale(0.32)"><Beacon t={2.2 + t} cx={0} cy={0} /></g>
          </svg>
          <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 260, lineHeight: 0.88, color: C.ink, letterSpacing: "0.06em",
            opacity: kt, transform: `scale(${scale})`, filter: `blur(${(1 - kt) * 12}px)`, textShadow: `0 0 60px ${rgba(C.amber, 0.25)}` }}>{o.title}</div>
          <div style={{ fontFamily: F.display, fontWeight: 600, fontSize: 76, color: C.amber, marginTop: 14, opacity: kg,
            clipPath: `inset(0 ${100 - kg * 100}% 0 0)` }}>{o.tagline}</div>
          <div style={{ fontFamily: F.mono, fontSize: 24, letterSpacing: "0.18em", color: C.ink, marginTop: 30, opacity: ke }}>{o.event.toUpperCase()}</div>
          <div style={{ display: "flex", gap: 46, justifyContent: "center", marginTop: 34, opacity: kteam }}>
            {team.map(([n, r]) => (
              <div key={n} style={{ textAlign: "center" }}>
                <div style={{ fontFamily: F.display, fontWeight: 700, fontSize: 34, color: C.ink }}>{n}</div>
                <div style={{ fontFamily: F.mono, fontSize: 17, color: C.dim, letterSpacing: "0.1em" }}>{r.toUpperCase()}</div>
              </div>
            ))}
          </div>
        </div>
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 34, textAlign: "center", fontFamily: F.mono, fontSize: 15, color: C.dim,
        opacity: kcr, letterSpacing: "0.04em" }}>
        PROOF OF CONCEPT · STOCK FOOTAGE: PEXELS · MUSIC: “EPIC TRAILER” BY THE_MOUNTAIN (PIXABAY) · SYNTHETIC VOICE (KOKORO TTS) · DETECTIONS: MDGB SMARTCROSSING (YOLOX)
      </div>
    </AbsoluteFill>
  );
};
