import { Easing, interpolate } from "remotion";

// Same tokens as the animatic (Trailer MDGB.html): night stage, amber beacon, traffic-light accents.
export const C = {
  bg: "#0A0C0F",
  bg2: "#121519",
  ink: "#EEEEE8",
  dim: "#8C9197",
  faint: "#2A2F35",
  amber: "#F2A516",
  red: "#E5484D",
  green: "#5CC35A",
  blue: "#4C8DF6",
  teal: "#3FB8AF",
};

export const F = {
  display: '"Barlow Condensed", "Arial Narrow", Arial, sans-serif',
  body: 'Barlow, system-ui, sans-serif',
  mono: '"JetBrains Mono", ui-monospace, Menlo, monospace',
};

export const W = 1920;
export const H = 1080;
export const SAFE_X = 96;  // 5 % safe margins
export const SAFE_Y = 64;

export const ease = Easing.bezier(0.22, 1, 0.36, 1);       // easeOutQuint-like
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

/** 0→1 between t0 and t1 (seconds), clamped and eased. */
export const prog = (t: number, t0: number, t1: number, e = ease) =>
  interpolate(t, [t0, t1], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: e });

/** fade in at t0 over d, fade out at t1 over d. */
export const life = (t: number, t0: number, t1: number, d = 0.35) =>
  Math.min(prog(t, t0, t0 + d), 1 - prog(t, t1 - d, t1));

export const rgba = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};

/** deterministic PRNG (same as the animatic) */
export const mulberry = (a: number) => () => {
  a |= 0; a = (a + 0x6d2b79f5) | 0;
  let t = Math.imul(a ^ (a >>> 15), 1 | a);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
