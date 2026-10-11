// Act III — the proofs. B07 sees · B08 measures · B09 understands · B10 decides · B11 fails safe ·
// B12 loses nothing · B13 sees no faces.  Every number on screen comes from timeline.json (ost).
import React from "react";
import { AbsoluteFill } from "remotion";
import { shotAt } from "../components/Shots";
import { Bracket, Chip, Scrim, Svg, Typed, useT, VerbStamp } from "../components/ui";
import { detsAt, useJson, type Det, type Detections } from "../lib/data";
import { C, F, life, mulberry, prog, rgba, SAFE_X, SAFE_Y } from "../theme";
import type { Scene, Shot } from "../types";

const CLS_COLOR: Record<string, string> = {
  pedestrian: C.amber, cyclist: C.blue, motorcyclist: C.blue, car: C.ink, bus: C.ink, truck: C.ink, dog: C.green, cat: C.green,
};

/** clip pixel -> screen pixel, following the shot's slow zoom */
const toScreen = (shot: Shot, t: number) => {
  const [z0, z1] = shot.zoom ?? [1.0, 1.0];
  const z = z0 + (z1 - z0) * Math.min(1, t / shot.dur);
  return (b: [number, number, number, number]): [number, number, number, number] =>
    [960 + (b[0] - 960) * z, 540 + (b[1] - 540) * z, 960 + (b[2] - 960) * z, 540 + (b[3] - 540) * z];
};

const ChipRow: React.FC<{ chips: string[]; t: number; top?: number }> = ({ chips, t, top = 210 }) => (
  <div style={{ position: "absolute", left: SAFE_X, top, display: "flex", gap: 12 }}>
    {chips.map((c, i) => (
      <Chip key={c} t={t} t0={0.5 + i * 0.18} color={i === 2 ? C.red : C.ink} dot={i === 0 ? C.red : undefined}>{c}</Chip>
    ))}
  </div>
);

// ------------------------------------------------------------------ B07 — it sees (real detections)
export const B07: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const shot = scene.shots[0];
  const det = useJson<Detections>(`data/detections_${shot.detections}.json`);
  const clipT = (shot.in ?? 0) + t;
  const map = toScreen(shot, t);
  const on = prog(t, 0.6, 1.0) * (1 - prog(t, 7.6, 8.0));
  const items = detsAt(det, clipT).filter((d) => (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]) > 900);
  const f = Math.round(clipT * 30);
  const ev = (det?.events ?? []).filter((e) => e.f <= f);
  const nIn = ev.filter((e) => e.dir === "in").length, nOut = ev.length - nIn;
  const line = det?.line ? map(det.line as any) : null;
  return (
    <AbsoluteFill>
      <Svg style={{ opacity: on }}>
        {line ? <line x1={line[0]} y1={line[1]} x2={line[2]} y2={line[3]} stroke={C.amber} strokeWidth={3} strokeDasharray="18 12" opacity={0.75} /> : null}
        {items.map((d) => {
          const b = map(d.box);
          const col = CLS_COLOR[d.cls] ?? C.ink;
          const label = `#${d.id} ${d.cls.toUpperCase()} ${d.conf.toFixed(2)}`;
          return (
            <g key={d.id}>
              <Bracket box={b} color={col} lw={3} />
              <rect x={b[0]} y={b[1] - 34} width={label.length * 12.2 + 16} height={28} fill="rgba(8,10,13,0.78)" stroke={rgba(col, 0.7)} />
              <text x={b[0] + 8} y={b[1] - 14} fill={col} fontFamily={F.mono} fontSize={19} fontWeight={600}>{label}</text>
            </g>
          );
        })}
      </Svg>
      <VerbStamp verb={scene.ost.verb} t={t} dur={scene.dur} />
      <ChipRow chips={scene.ost.chips} t={t} />
      <div style={{ position: "absolute", right: SAFE_X, bottom: SAFE_Y, display: "flex", gap: 18, opacity: on }}>
        {[["IN", nIn, C.green], ["OUT", nOut, C.amber]].map(([k, v, c]) => (
          <div key={k as string} style={{ background: "rgba(8,10,13,0.78)", border: `1px solid ${rgba(c as string, 0.6)}`, padding: "10px 22px", textAlign: "center" }}>
            <div style={{ fontFamily: F.mono, fontSize: 18, color: C.dim, letterSpacing: "0.2em" }}>{k}</div>
            <div style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 54, color: c as string }}>{v as number}</div>
          </div>
        ))}
      </div>
      <div style={{ position: "absolute", left: SAFE_X, bottom: SAFE_Y, display: "flex", gap: 24, opacity: on, fontFamily: F.mono, fontSize: 19, color: C.ink }}>
        {[["PEDESTRIAN", C.amber], ["CYCLIST", C.blue], ["VEHICLE", C.ink], ["ANIMAL", C.green]].map(([n, c]) => (
          <span key={n}><span style={{ display: "inline-block", width: 12, height: 12, background: c, marginRight: 8 }} />{n}</span>
        ))}
      </div>
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B08 — it measures: the stripes are the ruler
export const B08: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const W = 1260, X0 = 330, Y0 = 740, Hs = 190, px = W / 7;       // 7 m crossing, 1 m = stripe 50 cm + gap 50 cm
  const BEAT = 0.5457;                                           // stripes light on the music's beats
  const lit = (i: number) => prog(t, 2 * BEAT + i * BEAT, 2 * BEAT + i * BEAT + 0.2);
  const kp = prog(t, 0.5, 1.0), keq = prog(t, 1.4, 1.9), kw = prog(t, 5.0, 5.5);
  const beam = ((t * 0.55) % 1.2) - 0.1;
  const out = 1 - prog(t, 7.6, 8.0);
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <AbsoluteFill style={{ background: `linear-gradient(105deg, transparent ${beam * 100 - 6}%, ${rgba(C.amber, 0.16)} ${beam * 100}%, transparent ${beam * 100 + 6}%)` }} />
      <Scrim side="bottom" strength={0.85} />
      <Svg>
        <g opacity={kp}>
          <rect x={X0 - 30} y={Y0 - 70} width={W + 60} height={Hs + 150} fill="rgba(8,10,13,0.55)" stroke={rgba(C.ink, 0.15)} />
          {Array.from({ length: 7 }).map((_, i) => (
            <g key={i}>
              <rect x={X0 + i * px} y={Y0} width={px / 2} height={Hs} fill={C.amber} opacity={0.18 + 0.82 * lit(i)}
                style={{ filter: lit(i) > 0.5 ? `drop-shadow(0 0 12px ${rgba(C.amber, 0.8)})` : undefined }} />
              <rect x={X0 + i * px + px / 2} y={Y0} width={px / 2} height={Hs} fill="none" stroke={rgba(C.ink, 0.25)} strokeDasharray="6 6" />
              <line x1={X0 + (i + 1) * px} y1={Y0 - 22} x2={X0 + (i + 1) * px} y2={Y0 + Hs + 10} stroke={C.ink} strokeWidth={2} opacity={lit(i)} />
              <text x={X0 + (i + 1) * px} y={Y0 - 30} fill={C.ink} fontFamily={F.mono} fontWeight={700} fontSize={30} textAnchor="middle" opacity={lit(i)}>{i + 1} m</text>
            </g>
          ))}
          <text x={X0 + px / 4} y={Y0 + Hs + 44} fill={C.amber} fontFamily={F.mono} fontSize={24} textAnchor="middle" opacity={keq}>50 cm</text>
          <text x={X0 + (3 * px) / 4} y={Y0 + Hs + 44} fill={C.dim} fontFamily={F.mono} fontSize={24} textAnchor="middle" opacity={keq}>50 cm</text>
        </g>
      </Svg>
      <div style={{ position: "absolute", left: X0 - 30, top: Y0 - 170, opacity: keq }}>
        <Chip t={t} t0={1.4} color={C.amber}>{o.eq}</Chip>
      </div>
      <div style={{ position: "absolute", right: SAFE_X + 20, top: Y0 - 205, fontFamily: F.display, fontWeight: 800, fontSize: 96, color: C.amber,
        opacity: kw, transform: `scale(${0.9 + 0.1 * kw})`, textShadow: `0 0 30px ${rgba(C.amber, 0.4)}` }}>{o.width}</div>
      <VerbStamp verb={o.verb} t={t} dur={scene.dur} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B09 — it understands (attributes)
const TagCard: React.FC<{ title: string; value: string; note?: string; x: number; y: number; k: number }> = ({ title, value, note, x, y, k }) => (
  <div style={{ position: "absolute", left: x, top: y, padding: "16px 22px 18px", background: "rgba(8,10,13,0.8)", borderLeft: `6px solid ${C.amber}`,
    opacity: k, transform: `translateX(${(1 - k) * 24}px)`, minWidth: 300 }}>
    <div style={{ fontFamily: F.mono, fontSize: 20, letterSpacing: "0.22em", color: C.amber }}>{title}</div>
    <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 84, lineHeight: 1, color: C.ink }}>{value}</div>
    {note ? <div style={{ fontFamily: F.body, fontSize: 26, color: C.dim, marginTop: 6 }}>{note}</div> : null}
  </div>
);

const MainBox: React.FC<{ shot: Shot; local: number; prefer?: string }> = ({ shot, local, prefer }) => {
  const det = useJson<Detections>(shot.detections ? `data/detections_${shot.detections}.json` : null);
  const tag = shot.tag!;
  const clipT = (shot.in ?? 0) + local;
  const items = detsAt(det, clipT);
  const map = toScreen(shot, local);
  const walkers = items.filter((d) => d.cls === "pedestrian" && d.box[3] - d.box[1] > 90);
  let target: Det | undefined = prefer === "small" ? walkers.sort((a, b) => (a.box[3] - a.box[1]) - (b.box[3] - b.box[1]))[0]
    : prefer ? items.filter((d) => d.cls === prefer).sort((a, b) => area(b) - area(a))[0] : undefined;
  if (!target) target = items.filter((d) => d.cls === "pedestrian").sort((a, b) => area(b) - area(a))[0];
  const k = prog(local, 0.25, 0.65);
  if (!target) return <TagCard {...tag} x={tag.x * 1920} y={tag.y * 1080} k={k} />;
  const b = map(target.box);
  const right = b[2] + 30 + 340 < 1920 - SAFE_X;
  const cx = right ? b[2] + 30 : b[0] - 30 - 380;
  const cy = Math.max(SAFE_Y + 150, Math.min(1080 - 300, b[1] + 20));
  return (
    <>
      <Svg><Bracket box={b} color={C.amber} lw={4} alpha={k} /></Svg>
      <TagCard {...tag} x={cx} y={cy} k={k} />
    </>
  );
};
const area = (d: Det) => (d.box[2] - d.box[0]) * (d.box[3] - d.box[1]);

export const B09: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const { i, local, shot } = shotAt(scene.shots, t);
  const prefer = shot.tag?.title.startsWith("DOG") ? "dog" : shot.tag?.title.startsWith("CHILD") ? "small" : undefined;
  return (
    <AbsoluteFill>
      <MainBox key={i} shot={shot} local={local} prefer={prefer} />
      <VerbStamp verb={scene.ost.verb} t={t} dur={scene.dur} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B10 — it decides and acts
export const B10: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const formula = o.formula as string[];
  const t1 = scene.shots[0].dur;
  const blink = Math.floor(t * 4) % 2 === 0;                     // 2 Hz amber, one flash per beat at 120 BPM
  const kf = life(t, 0.3, t1 + 0.4, 0.3);
  const kl = prog(t, t1 + 0.1, t1 + 0.5), ko = prog(t, t1 + 0.5, t1 + 0.9);
  const kb = prog(t, 6.7, 6.9) * (1 - prog(t, 7.7, 8.0));
  return (
    <AbsoluteFill>
      {t < t1 + 0.4 ? <Scrim side="left" strength={0.85 * kf} /> : null}
      <div style={{ position: "absolute", left: SAFE_X, top: 330, opacity: kf, fontFamily: F.mono, fontSize: 44, lineHeight: 1.6, color: C.ink }}>
        {formula.map((l, k) => (
          <div key={k} style={{ color: k === 2 ? C.amber : C.ink, fontWeight: k === 2 ? 700 : 500 }}>
            <Typed text={l} t={t} t0={0.5 + k * 0.9} cps={34} caret={k < 2} />
          </div>
        ))}
      </div>
      {/* LCD for the driver and OLED for the pedestrian, as on the real hardware */}
      <div style={{ position: "absolute", right: SAFE_X, top: 200, opacity: kl, transform: `translateY(${(1 - kl) * 20}px)` }}>
        <div style={{ fontFamily: F.mono, fontSize: 18, color: C.dim, letterSpacing: "0.2em", marginBottom: 8 }}>LCD · FOR DRIVERS</div>
        <div style={{ width: 720, padding: "22px 30px", borderRadius: 12, background: blink ? C.amber : "#5A3A06",
          boxShadow: blink ? `0 0 60px ${rgba(C.amber, 0.55)}` : "none", border: "6px solid #1B1E22" }}>
          {(o.lcd as string[]).map((l, k) => (
            <div key={k} style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 52, color: "#1A1205", letterSpacing: "0.06em", whiteSpace: "pre" }}>{l}</div>
          ))}
        </div>
      </div>
      <div style={{ position: "absolute", right: SAFE_X, top: 520, opacity: ko, transform: `translateY(${(1 - ko) * 20}px)` }}>
        <div style={{ fontFamily: F.mono, fontSize: 18, color: C.dim, letterSpacing: "0.2em", marginBottom: 8, textAlign: "right" }}>OLED · FOR PEDESTRIANS</div>
        <div style={{ width: 380, marginLeft: 340, padding: "18px 26px", borderRadius: 10, background: "#05070A", border: "6px solid #1B1E22" }}>
          {(o.oled as string[]).map((l, k) => (
            <div key={k} style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 64, color: "#E8F4FF", textAlign: "center" }}>{l}</div>
          ))}
        </div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 120, textAlign: "center", opacity: kb, fontFamily: F.display, fontWeight: 800,
        fontSize: 170, color: C.red, transform: `scale(${1.15 - 0.15 * prog(t, 6.7, 6.95)})`, textShadow: `0 0 60px ${rgba(C.red, 0.7)}` }}>{o.alarm}</div>
      <VerbStamp verb={o.verb} t={t} dur={scene.dur} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B11 — fail-safe
export const B11: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const OFF = 3.4;                                        // vision switched off
  const lost = t >= OFF;
  const W = 1728, X0 = 96, Y = 900, H = 90;
  // beats every 100 ms scroll from right to left; after OFF the line is flat
  const pts: string[] = [];
  for (let x = 0; x <= W; x += 4) {
    const tt = t - (W - x) / 600;                       // 600 px per second
    let y = 0;
    if (tt < OFF && tt > 0) { const ph = (tt % 0.1) / 0.1; y = ph < 0.12 ? -Math.sin((ph / 0.12) * Math.PI) * H * 0.8 : 0; }
    pts.push(`${X0 + x},${Y + y}`);
  }
  const timer = Math.min(0.5, Math.max(0, t - OFF));
  const ks = prog(t, OFF + 0.5, OFF + 0.7), kb = prog(t, OFF + 1.0, OFF + 1.3);
  const out = 1 - prog(t, 7.6, 8.0);
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <Scrim side="bottom" strength={0.8} />
      <Svg>
        <polyline points={pts.join(" ")} fill="none" stroke={lost && t > OFF + 0.05 ? C.red : C.green} strokeWidth={4}
          style={{ filter: `drop-shadow(0 0 8px ${lost ? C.red : C.green})` }} />
      </Svg>
      <div style={{ position: "absolute", left: SAFE_X, top: 770, display: "flex", gap: 14 }}>
        <Chip t={t} t0={0.4} color={C.green} dot={C.green}>{o.beat}</Chip>
        {lost ? <Chip t={t} t0={OFF} color={C.red} dot={C.red}>{o.lost}</Chip> : null}
      </div>
      {lost ? (
        <div style={{ position: "absolute", right: SAFE_X, top: 700, textAlign: "right" }}>
          <div style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 96, color: timer >= 0.5 ? C.amber : C.red }}>{timer.toFixed(2)} s</div>
          <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 64, color: C.amber, opacity: ks }}>{o.safe}</div>
        </div>
      ) : null}
      <div style={{ position: "absolute", left: 0, right: 0, top: 420, textAlign: "center", opacity: kb, fontFamily: F.display, fontWeight: 800,
        fontSize: 78, color: C.green, letterSpacing: "0.04em", textShadow: "0 4px 30px rgba(0,0,0,0.85)" }}>{o.back}</div>
      <VerbStamp verb={o.verb} t={t} dur={scene.dur} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B12 — loses nothing (Wi-Fi -> BLE -> Wi-Fi)
export const B12: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const N = { x: 560, y: 520 }, R = { x: 1360, y: 520 };
  const DOWN = 1.3, UP = 5.0;
  const down = t >= DOWN && t < UP;
  const queued = down ? Math.min(14, Math.floor((t - DOWN) * 4)) : t >= UP ? Math.max(0, 14 - Math.floor((t - UP) * 18)) : 0;
  const dash = -t * 120;
  const kz = prog(t, 6.0, 6.5);
  const rings = down ? [0, 1, 2].map((i) => ((t - DOWN + i * 0.45) % 1.35) / 1.35) : [];
  const out = 1 - prog(t, 7.6, 8.0);
  return (
    <AbsoluteFill style={{ opacity: out }}>
      <AbsoluteFill style={{ background: "rgba(5,7,10,0.55)" }} />
      <Svg>
        <line x1={N.x + 70} y1={N.y} x2={R.x - 90} y2={R.y} stroke={down ? C.red : C.green} strokeWidth={4}
          strokeDasharray={down ? "4 18" : "22 14"} strokeDashoffset={dash} opacity={down ? 0.5 : 1} />
        {down ? <text x={(N.x + R.x) / 2} y={N.y + 26} fill={C.red} fontFamily={F.display} fontWeight={800} fontSize={90} textAnchor="middle">✕</text> : null}
        {t >= UP ? Array.from({ length: 6 }).map((_, i) => {
          const p = ((t - UP) * 1.6 + i / 6) % 1;
          return <circle key={i} cx={N.x + 70 + (R.x - 90 - N.x - 70) * p} cy={N.y} r={9} fill={C.amber} opacity={queued > 0 ? 1 : 0} />;
        }) : null}
        {rings.map((r, i) => <circle key={i} cx={N.x} cy={N.y} r={60 + r * 300} fill="none" stroke={C.blue} strokeWidth={3} opacity={(1 - r) * 0.8} />)}
        <circle cx={N.x} cy={N.y} r={64} fill="#0C0F13" stroke={C.amber} strokeWidth={4} />
        <circle cx={N.x} cy={N.y} r={18} fill={C.amber} style={{ filter: `drop-shadow(0 0 16px ${C.amber})` }} />
        <rect x={R.x - 90} y={R.y - 60} width={180} height={120} rx={10} fill="#0C0F13" stroke={C.ink} strokeWidth={3} />
        <text x={N.x} y={N.y + 110} fill={C.ink} fontFamily={F.mono} fontSize={22} textAnchor="middle">MDGB NODE</text>
        <text x={R.x} y={R.y + 8} fill={C.ink} fontFamily={F.mono} fontSize={20} textAnchor="middle">CONTROL</text>
        <text x={R.x} y={R.y + 34} fill={C.ink} fontFamily={F.mono} fontSize={20} textAnchor="middle">ROOM</text>
        <text x={N.x} y={N.y + 146} fill={queued ? C.amber : C.dim} fontFamily={F.mono} fontSize={22} textAnchor="middle">QUEUED {queued}</text>
      </Svg>
      <div style={{ position: "absolute", left: 0, right: 0, top: 250, display: "flex", justifyContent: "center", gap: 16 }}>
        {t >= DOWN && t < UP ? <Chip t={t} t0={DOWN} color={C.red} dot={C.red}>{o.wifiDown}</Chip> : null}
        {t >= DOWN + 0.5 && t < UP ? <Chip t={t} t0={DOWN + 0.5} color={C.blue} dot={C.blue}>{o.ble}</Chip> : null}
        {t >= UP ? <Chip t={t} t0={UP} color={C.green} dot={C.green}>{o.wifiUp}</Chip> : null}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 110, textAlign: "center", opacity: kz }}>
        <span style={{ fontFamily: F.display, fontWeight: 700, fontSize: 64, color: C.ink, letterSpacing: "0.06em" }}>{o.lost}: </span>
        <span style={{ fontFamily: F.mono, fontWeight: 700, fontSize: 110, color: C.green, textShadow: `0 0 40px ${rgba(C.green, 0.5)}` }}>0</span>
      </div>
      <VerbStamp verb={o.verb} t={t} dur={scene.dur} />
    </AbsoluteFill>
  );
};

// ------------------------------------------------------------------ B13 — no faces: people become anonymous points
export const B13: React.FC<{ scene: Scene }> = ({ scene }) => {
  const t = useT();
  const o = scene.ost;
  const shot = scene.shots[0];
  const det = useJson<Detections>(`data/detections_${shot.detections}.json`);
  const clipT = (shot.in ?? 0) + t;
  const map = toScreen(shot, t);
  const f = Math.round(clipT * 30);
  const dark = prog(t, 2.2, 3.4) * 0.8;                // the image blurs (shot.blur) then fades to the dark
  const kb = prog(t, 0.4, 0.8) * (1 - prog(t, 2.2, 2.8));
  const kd = prog(t, 2.2, 2.9);
  // trails: last 24 frames of each track
  const trails: Record<number, [number, number][]> = {};
  if (det) for (let k = Math.max(0, f - 24); k <= Math.min(det.frames.length - 1, f); k++) {
    for (const d of det.frames[k]) {
      if (d.cls !== "pedestrian" && d.cls !== "cyclist") continue;
      const b = map(d.box);
      (trails[d.id] ??= []).push([(b[0] + b[2]) / 2, (b[1] + b[3]) / 2]);
    }
  }
  const now = detsAt(det, clipT).filter((d) => d.cls === "pedestrian" || d.cls === "cyclist");
  const rnd = mulberry(7);
  const jsonl = Array.from({ length: 9 }).map((_, i) => {
    const sec = 31 + Math.floor((t * 3 + i) / 3);
    return `{"t":"18:02:${String(sec % 60).padStart(2, "0")}.${Math.floor(rnd() * 9)}","cls":"pedestrian","dir":"${rnd() > 0.5 ? "in" : "out"}","v":${(0.8 + rnd() * 0.8).toFixed(1)}}`;
  });
  const scroll = (t * 46) % 46;
  const kt = prog(t, 5.0, 5.5);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ background: "#04060A", opacity: dark }} />
      <Svg>
        {now.map((d) => <Bracket key={`b${d.id}`} box={map(d.box)} color={C.blue} lw={2} alpha={kb} glow={false} />)}
        {Object.entries(trails).map(([id, pts]) => (
          <g key={id} opacity={kd}>
            <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke={rgba(C.amber, 0.55)} strokeWidth={3} />
            <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r={9} fill={C.amber} style={{ filter: `drop-shadow(0 0 10px ${C.amber})` }} />
          </g>
        ))}
      </Svg>
      <div style={{ position: "absolute", right: SAFE_X, top: 210, width: 640, height: 420, overflow: "hidden", opacity: kd,
        fontFamily: F.mono, fontSize: 16, lineHeight: "46px", color: rgba(C.ink, 0.85), background: "rgba(5,7,10,0.6)", padding: "0 18px",
        borderLeft: `3px solid ${C.blue}` }}>
        <div style={{ transform: `translateY(${-scroll}px)` }}>{jsonl.map((l, i) => <div key={i} style={{ whiteSpace: "nowrap" }}>{l}</div>)}</div>
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, bottom: 150, textAlign: "center", opacity: kd }}>
        <Chip t={t} t0={2.6} color={C.green} dot={C.green} style={{ fontSize: 30, padding: "14px 26px" }}>{o.badge}</Chip>
      </div>
      {/* thermal strip, 16 x 4, warms where people pass */}
      <div style={{ position: "absolute", left: SAFE_X, bottom: SAFE_Y, opacity: kt }}>
        <div style={{ fontFamily: F.mono, fontSize: 18, color: C.dim, letterSpacing: "0.2em", marginBottom: 8 }}>NIGHT · THERMAL 16×4</div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(16, 26px)", gap: 3 }}>
          {Array.from({ length: 64 }).map((_, i) => {
            const col = i % 16, row = Math.floor(i / 16);
            const heat = Math.max(0, 1 - Math.abs(col - ((t * 3.1) % 16)) / 2.2) * (row === 1 || row === 2 ? 1 : 0.55);
            return <div key={i} style={{ width: 26, height: 26, background: `rgba(${110 + heat * 145},${50 + heat * 110},${70 - heat * 50},${0.55 + heat * 0.45})` }} />;
          })}
        </div>
      </div>
      <VerbStamp verb={o.verb} t={t} dur={scene.dur} />
    </AbsoluteFill>
  );
};
