import React from "react";
import { AbsoluteFill, Img, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { C } from "../theme";
import type { Shot } from "../types";

const mix = (a: number, b: number, k: number) => a + (b - a) * k;
const fill: React.CSSProperties = { position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "cover" };

// ---------------------------------------------------------------- one shot
// The footage arrives as a graded "plate" rendered by ffmpeg (tools/prep_media.py): exact in/out, speed,
// colour grade, tilt-shift and privacy blur are already baked in, so the browser only composites.
export const ShotView: React.FC<{ shot: Shot }> = ({ shot }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  const p = Math.min(1, t / shot.dur);
  const [z0, z1] = shot.zoom ?? [1.0, 1.0];
  const scale = mix(z0, z1, p);
  const src = shot.src ? staticFile(shot.src) : "";
  return (
    <AbsoluteFill style={{ overflow: "hidden", backgroundColor: C.bg }}>
      <AbsoluteFill style={scale !== 1 ? { transform: `scale(${scale})` } : undefined}>
        {shot.src?.endsWith(".jpg") ? <Img src={src} style={fill} /> : <OffthreadVideo src={src} muted style={fill} />}
      </AbsoluteFill>
      <AbsoluteFill style={{ background: "linear-gradient(180deg, rgba(5,7,10,0.35) 0%, rgba(5,7,10,0) 22%, rgba(5,7,10,0) 70%, rgba(5,7,10,0.45) 100%)" }} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------- a scene's shot list, back to back
export function shotStarts(shots: Shot[]): number[] {
  const out: number[] = [];
  let acc = 0;
  for (const s of shots) { out.push(acc); acc += s.dur; }
  return out;
}

export const Shots: React.FC<{ shots: Shot[] }> = ({ shots }) => {
  const { fps } = useVideoConfig();
  const starts = shotStarts(shots);
  return (
    <>
      {shots.map((sh, i) => {
        const from = Math.round(starts[i] * fps);
        const to = Math.round((starts[i] + sh.dur) * fps);
        return (
          <Sequence key={i} from={from} durationInFrames={Math.max(1, to - from)} name={`${sh.media}`}>
            <ShotView shot={sh} />
          </Sequence>
        );
      })}
    </>
  );
};

/** index of the shot playing at scene time t, and the time inside it */
export function shotAt(shots: Shot[], t: number): { i: number; local: number; shot: Shot } {
  const st = shotStarts(shots);
  let i = 0;
  for (let k = 0; k < shots.length; k++) if (t >= st[k]) i = k;
  return { i, local: t - st[i], shot: shots[i] };
}
