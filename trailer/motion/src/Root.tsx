import React from "react";
import { CalculateMetadataFunction, Composition, staticFile } from "remotion";
import { Trailer } from "./Trailer";
import type { Timeline } from "./types";

type Props = { timeline: Timeline | null; only?: string | null };

// The timeline is read from the public dir (build/public/data/timeline.json) unless passed via --props.
const calc: CalculateMetadataFunction<Props> = async ({ props }) => {
  const tl: Timeline = props.timeline ?? (await (await fetch(staticFile("data/timeline.json"))).json());
  let duration = tl.meta.duration;
  if (props.only) {
    const sc = tl.scenes.find((s) => s.id === props.only);
    if (sc) duration = sc.dur;
  }
  return {
    durationInFrames: Math.round(duration * tl.meta.fps),
    fps: tl.meta.fps,
    width: tl.meta.width,
    height: tl.meta.height,
    props: { ...props, timeline: tl },
  };
};

export const RemotionRoot: React.FC = () => (
  <>
    {/* Full trailer. Render: npx remotion render src/index.ts Trailer ../build/video.mp4 */}
    <Composition id="Trailer" component={Trailer} durationInFrames={3600} fps={30} width={1920} height={1080}
      defaultProps={{ timeline: null, only: null } as Props} calculateMetadata={calc} />
    {/* One scene in isolation, for quick previews: --props='{"only":"B07"}' */}
    <Composition id="Scene" component={Trailer} durationInFrames={240} fps={30} width={1920} height={1080}
      defaultProps={{ timeline: null, only: "B01" } as Props} calculateMetadata={calc} />
  </>
);
