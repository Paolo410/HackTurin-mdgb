import React from "react";
import { AbsoluteFill, Sequence, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { Shots } from "./components/Shots";
import { FontsReady } from "./components/ui";
import { SCENES } from "./scenes";
import { C, F } from "./theme";
import type { Timeline } from "./types";

/** Global finishing: flashes, dips and fades placed on the timeline. */
const Finish: React.FC<{ flashes: number[]; dips: [number, number][]; end: number }> = ({ flashes, dips, end }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps;
  let flash = 0;
  for (const f of flashes) flash = Math.max(flash, interpolate(t, [f - 0.02, f, f + 0.22], [0, 0.85, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  let dip = 0;
  for (const [a, b] of dips) dip = Math.max(dip, interpolate(t, [a, (a + b) / 2, b], [0, 1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }));
  const fadeOut = interpolate(t, [end - 0.9, end - 0.05], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fadeIn = interpolate(t, [0, 0.6], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <>
      {/* vignette and film grain are added by ffmpeg in the mux step (cheaper than in the browser) */}
      <AbsoluteFill style={{ background: "#FFF6E6", opacity: flash * 0.7 }} />
      <AbsoluteFill style={{ background: "#000", opacity: Math.max(dip, fadeOut, fadeIn) }} />
    </>
  );
};

/** Optional burned-in subtitles of the narration (meta.burnSubtitles). */
const Subtitles: React.FC<{ tl: Timeline; offset: number }> = ({ tl, offset }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame / fps + offset;
  const line = (tl.vo ?? []).find((l) => t >= (l.start ?? 0) && t <= (l.end ?? 0) + 0.2);
  if (!line) return null;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 54 }}>
      <div style={{ maxWidth: 1400, textAlign: "center", fontFamily: F.body, fontWeight: 500, fontSize: 34, lineHeight: 1.3,
        color: C.ink, background: "rgba(5,6,8,0.62)", padding: "8px 18px", borderRadius: 8 }}>{line.text}</div>
    </AbsoluteFill>
  );
};

export const Trailer: React.FC<{ timeline: Timeline | null; only?: string | null }> = ({ timeline, only }) => {
  const { fps } = useVideoConfig();
  if (!timeline) return null;
  const scenes = only ? timeline.scenes.filter((s) => s.id === only) : timeline.scenes;
  const offset = only && scenes[0] ? scenes[0].start : 0;
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      <FontsReady />
      {scenes.map((sc) => {
        const Overlay = SCENES[sc.id];
        const from = Math.round((sc.start - offset) * fps);
        const to = Math.round((sc.start + sc.dur - offset) * fps);
        return (
          <Sequence key={sc.id} from={from} durationInFrames={to - from} name={`${sc.id} · ${sc.name}`}>
            <Shots shots={sc.shots} />
            {Overlay ? <Overlay scene={sc} /> : null}
          </Sequence>
        );
      })}
      {timeline.meta.burnSubtitles ? <Subtitles tl={timeline} offset={offset} /> : null}
      {only ? null : <Finish flashes={[12.0, 30.0]} dips={[[101.55, 102.25]]} end={timeline.meta.duration} />}
    </AbsoluteFill>
  );
};
