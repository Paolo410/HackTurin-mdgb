// Act I — the problem. B01 duel · B02 the math · B03 the data · B04 darkness
import React from "react";
import { AbsoluteFill, interpolate } from "remotion";
import { Bracket, Scrim, Svg, useT } from "../components/ui";
import { detsAt, useJson, type Detections } from "../lib/data";
import { C, F, life, prog, rgba, SAFE_X, SAFE_Y } from "../theme";
import type { Scene } from "../types";

const Num: React.FC<{ value: string; label: string; color: string; k: number; size?: number; align?: "left" | "right" | "center" }> =
  ({ value, label, color, k, size = 120, align = "left" }) => (
    <div style={{ opacity: k, transform: `translateY(${(1 - k) * 18}px)`, textAlign: align }}>
      <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: size * 1.15, lineHeight: 0.92, color, letterSpacing: "0.01em",
        textShadow: `0 0 34px ${rgba(color, 0.45)}, 0 4px 18px rgba(0,0,0,0.8)` }}>{value}</div>
      <div style={{ fontFamily: F.display, fontWeight: 600, fontSize: size * 0.27, letterSpacing: "0.14em", color: C.ink,
        marginTop: 8, textShadow: "0 2px 12px rgba(0,0,0,0.9)" }}>{label}</div>
    </div>
  );

/** counts 0 -> target while appearing (stopwatch feel) */
const counting = (t: number, t0: number, target: number, dur = 0.9) => (target * prog(t, t0, t0 + dur)).toFixed(1);

// ------------------------------------------------------------------ B01 — the duel
export const B01: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const shot = scene.shots[0];
  const det = useJson<Detections>(shot.detections ? `data/detections_${shot.detections}.json` : null);
  // pin the 9.8 s label above the walking pedestrian (real detection), fallback: fixed point
  const clipT = (shot.in ?? 0) + t;
  const mains = det?.main ?? [];
  const i = Math.max(0, Math.min(mains.length - 1, Math.round(clipT * 30)));
  const mb = mains[i]?.box;
  const zoom = (shot.zoom?.[0] ?? 1) + ((shot.zoom?.[1] ?? 1) - (shot.zoom?.[0] ?? 1)) * (t / shot.dur);
  const px = mb ? 960 + ((mb[0] + mb[2]) / 2 - 960) * zoom : 1100;
  const py = mb ? 540 + (mb[1] - 540) * zoom : 420;
  const kp = prog(t, 0.9, 1.4), kc = prog(t, 2.8, 3.3);
  const out = 1 - prog(t, 5.6, 6.0);
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <Svg>
        {mb ? <Bracket box={[960 + (mb[0] - 960) * zoom, py, 960 + (mb[2] - 960) * zoom, 540 + (mb[3] - 540) * zoom]} color={C.amber} lw={3} alpha={kp} /> : null}
        <line x1={px} y1={py - 14} x2={px} y2={py - 96} stroke={C.amber} strokeWidth={2} opacity={kp} />
      </Svg>
      {/* headlights entering from the right edge */}
      {[0, 1].map((k) => (
        <div key={k} style={{ position: "absolute", left: 1990 - 150 * kc - k * 10, top: 250 + k * 110, width: 260, height: 160, borderRadius: "50%",
          background: "radial-gradient(closest-side, rgba(255,246,220,0.95), rgba(255,226,160,0.35) 45%, rgba(255,200,120,0) 100%)",
          mixBlendMode: "screen", opacity: kc * (0.85 + 0.15 * Math.sin(t * 11 + k)) }} />
      ))}
      <div style={{ position: "absolute", left: Math.min(1920 - SAFE_X - 360, Math.max(SAFE_X, px - 110)), top: Math.max(SAFE_Y + 10, py - 300) }}>
        <Num value={`${counting(t, 0.9, 9.8)} s`} label={o.pedLabel} color={C.amber} k={kp} size={104} />
      </div>
      <div style={{ position: "absolute", right: SAFE_X, top: 330 }}>
        <Num value={`${counting(t, 2.8, 4.3, 0.6)} s`} label={o.carLabel} color={C.red} k={kc} size={104} align="right" />
      </div>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B02 — the math, on the freeze-frame
export const B02: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const k = prog(t, 0.05, 0.7);
  const kop = prog(t, 0.8, 1.2);
  const pulse = 1 + 0.06 * Math.max(0, Math.sin(t * 7)) * prog(t, 1.2, 1.6);
  const dim = interpolate(t, [0, 0.6], [0, 0.55], { extrapolateRight: "clamp" });
  const out = 1 - prog(t, 5.65, 6.0);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "#05070A", opacity: dim }} />
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: out }}>
        <div style={{ display: "flex", alignItems: "center", gap: 110 }}>
          <div style={{ transform: `translateX(${(1 - k) * 380}px)` }}><Num value={o.left} label={o.leftLabel} color={C.red} k={k} size={190} align="center" /></div>
          <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 210, color: C.red, opacity: kop, transform: `scale(${pulse})`,
            textShadow: `0 0 40px ${rgba(C.red, 0.6)}`, marginTop: -70, lineHeight: 1 }}>{o.op}</div>
          <div style={{ transform: `translateX(${-(1 - k) * 380}px)` }}><Num value={o.right} label={o.rightLabel} color={C.amber} k={k} size={190} align="center" /></div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B03 — the data (montage underneath)
export const B03: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const k = prog(t, 1.6, 2.4);
  const n = Math.round(o.number * prog(t, 1.6, 3.0));
  const k1 = prog(t, 2.6, 3.2), k2 = prog(t, 4.6, 5.2), ks = prog(t, 5.4, 6.0);
  const out = 1 - prog(t, 7.6, 8.0);
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <Scrim side="left" strength={0.8 * k} />
      <div style={{ position: "absolute", left: SAFE_X, top: 250 }}>
        <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 330, lineHeight: 0.82, color: C.red, opacity: k,
          letterSpacing: "-0.01em", textShadow: `0 0 60px ${rgba(C.red, 0.35)}` }}>{n}</div>
        <div style={{ fontFamily: F.display, fontWeight: 600, fontSize: 58, color: C.ink, opacity: k1, maxWidth: 900, lineHeight: 1.05,
          transform: `translateY(${(1 - k1) * 14}px)`, marginTop: 18, textTransform: "uppercase", letterSpacing: "0.02em" }}>{o.line1}</div>
        <div style={{ fontFamily: F.body, fontWeight: 500, fontSize: 40, color: C.amber, opacity: k2, marginTop: 22 }}>{o.line2}</div>
      </div>
      <div style={{ position: "absolute", left: SAFE_X, bottom: SAFE_Y, fontFamily: F.mono, fontSize: 20, color: C.dim, opacity: ks,
        letterSpacing: "0.06em" }}>{o.source}</div>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B04 — darkness at rush hour
export const B04: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const k = prog(t, 0.4, 1.1), kl = prog(t, 1.2, 1.8);
  // clock runs 16:30 -> 17:30 during the dusk-to-night grade, then holds with a blinking colon
  const mins = Math.round(interpolate(t, [0.6, 4.6], [16 * 60 + 30, 17 * 60 + 30], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const hh = String(Math.floor(mins / 60)).padStart(2, "0"), mm = String(mins % 60).padStart(2, "0");
  const colon = t < 4.6 || Math.floor(t * 2) % 2 === 0;
  const sun = prog(t, 0.6, 4.6);
  const out = life(t, 0, 9.7, 0.3);
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <Scrim side="left" strength={0.55} />
      <div style={{ position: "absolute", left: SAFE_X, top: SAFE_Y + 40 }}>
        <div style={{ fontFamily: F.mono, fontSize: 24, letterSpacing: "0.3em", color: C.amber, opacity: k }}>DAYLIGHT SAVING ENDS</div>
        <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 150, lineHeight: 0.9, color: C.ink, opacity: k,
          clipPath: `inset(0 ${100 - 100 * k}% 0 0)` }}>{o.date}</div>
        <div style={{ fontFamily: F.body, fontWeight: 500, fontSize: 40, color: C.ink, opacity: kl, marginTop: 14 }}>{o.line}</div>
      </div>
      <div style={{ position: "absolute", right: SAFE_X, top: SAFE_Y + 40, textAlign: "right", opacity: k }}>
        <div style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 132, color: C.ink, letterSpacing: "-0.02em",
          textShadow: "0 4px 24px rgba(0,0,0,0.8)" }}>{hh}<span style={{ opacity: colon ? 1 : 0.15 }}>:</span>{mm}</div>
        {/* the sun sets under the horizon line */}
        <svg width={320} height={70} style={{ marginTop: 8 }}>
          <line x1={0} y1={46} x2={320} y2={46} stroke={C.dim} strokeWidth={2} />
          <circle cx={250} cy={22 + sun * 44} r={16} fill={C.amber} opacity={1 - sun * 0.85} />
          <rect x={0} y={47} width={320} height={30} fill="#000" opacity={0} />
        </svg>
      </div>
    </AbsoluteFill>
  );
};
