import React, { useEffect, useState } from "react";
import { AbsoluteFill, continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C, F, prog, rgba, SAFE_X, SAFE_Y } from "../theme";

/** current scene time in seconds */
export const useT = () => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  return f / fps;
};

/** Blocks rendering until the web fonts are loaded (otherwise the first frames use fallbacks). */
export const FontsReady: React.FC = () => {
  const [h] = useState(() => delayRender("fonts"));
  useEffect(() => {
    const specs = ['800 100px "Barlow Condensed"', '700 100px "Barlow Condensed"', '600 100px "Barlow Condensed"',
      '500 100px "Barlow Condensed"', "400 40px Barlow", "500 40px Barlow", "600 40px Barlow",
      '400 40px "JetBrains Mono"', '500 40px "JetBrains Mono"', '700 40px "JetBrains Mono"'];
    Promise.all(specs.map((s) => document.fonts.load(s))).finally(() => continueRender(h));
  }, [h]);
  return null;
};

/** small rounded label, mono uppercase */
export const Chip: React.FC<{ children: React.ReactNode; color?: string; t: number; t0: number; style?: React.CSSProperties; dot?: string }> =
  ({ children, color = C.ink, t, t0, style, dot }) => {
    const k = prog(t, t0, t0 + 0.35);
    return (
      <div style={{ display: "inline-flex", alignItems: "center", gap: 10, padding: "9px 16px 9px 14px", borderRadius: 999,
        background: "rgba(8,10,13,0.72)", border: `1px solid ${rgba(color, 0.45)}`, color, fontFamily: F.mono, fontWeight: 500,
        fontSize: 21, letterSpacing: "0.08em", textTransform: "uppercase", opacity: k, transform: `translateY(${(1 - k) * 12}px)`,
        ...style }}>
        {dot ? <span style={{ width: 10, height: 10, borderRadius: 10, background: dot, boxShadow: `0 0 12px ${dot}` }} /> : null}
        {children}
      </div>
    );
  };

/** "MDGB — SEES": the proof-act stamp, same place in every proof scene */
export const VerbStamp: React.FC<{ verb: string; t: number; dur: number; color?: string }> = ({ verb, t, dur, color = C.amber }) => {
  const k = prog(t, 0.15, 0.75);
  const out = 1 - prog(t, dur - 0.45, dur - 0.05);
  return (
    <div style={{ position: "absolute", left: SAFE_X, top: SAFE_Y + 8, opacity: out }}>
      <div style={{ fontFamily: F.mono, fontSize: 20, letterSpacing: "0.22em", color: C.dim, opacity: k }}>MDGB</div>
      <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 92, lineHeight: 0.95, color, letterSpacing: "0.01em",
        clipPath: `inset(0 ${100 - k * 100}% 0 0)`, textShadow: "0 4px 30px rgba(0,0,0,0.6)" }}>{verb}</div>
    </div>
  );
};

/** type-on text */
export const Typed: React.FC<{ text: string; t: number; t0: number; cps?: number; caret?: boolean; style?: React.CSSProperties }> =
  ({ text, t, t0, cps = 38, caret = true, style }) => {
    const n = Math.max(0, Math.min(text.length, Math.floor((t - t0) * cps)));
    const blink = Math.floor(t * 2.5) % 2 === 0;
    return <span style={style}>{text.slice(0, n)}{caret && n < text.length && t >= t0 ? <span style={{ opacity: blink ? 1 : 0 }}>▌</span> : null}</span>;
  };

/** corner brackets around a box (pixels) */
export const Bracket: React.FC<{ box: [number, number, number, number]; color: string; lw?: number; alpha?: number; glow?: boolean }> =
  ({ box, color, lw = 3, alpha = 1, glow = false }) => {
    const [x1, y1, x2, y2] = box;
    const w = x2 - x1, h = y2 - y1;
    const l = Math.max(10, Math.min(w, h) * 0.24);
    const d = [
      `M${x1},${y1 + l}V${y1}H${x1 + l}`, `M${x2 - l},${y1}H${x2}V${y1 + l}`,
      `M${x2},${y2 - l}V${y2}H${x2 - l}`, `M${x1 + l},${y2}H${x1}V${y2 - l}`,
    ].join("");
    return <path d={d} fill="none" stroke={color} strokeWidth={lw} opacity={alpha} strokeLinecap="square"
      style={glow ? { filter: `drop-shadow(0 0 6px ${rgba(color, 0.7)})` } : undefined} />;
  };

/** full-frame SVG layer in 1920x1080 coordinates */
export const Svg: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <svg viewBox="0 0 1920 1080" width={1920} height={1080} style={{ position: "absolute", inset: 0, overflow: "visible", ...style }}>{children}</svg>
);

/** readable dark scrim behind text blocks */
export const Scrim: React.FC<{ side?: "left" | "bottom" | "right"; strength?: number }> = ({ side = "left", strength = 0.75 }) => {
  const g = side === "left" ? `linear-gradient(90deg, rgba(6,8,11,${strength}) 0%, rgba(6,8,11,${strength * 0.6}) 38%, rgba(6,8,11,0) 70%)`
    : side === "right" ? `linear-gradient(270deg, rgba(6,8,11,${strength}) 0%, rgba(6,8,11,${strength * 0.6}) 38%, rgba(6,8,11,0) 70%)`
    : `linear-gradient(0deg, rgba(6,8,11,${strength}) 0%, rgba(6,8,11,0) 55%)`;
  return <AbsoluteFill style={{ background: g }} />;
};

export const grainUrl = (i: number) => staticFile(`fx/grain_${i % 8}.png`);
