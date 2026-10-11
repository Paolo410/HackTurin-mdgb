import { useEffect, useState } from "react";
import { continueRender, delayRender, staticFile } from "remotion";

/** Load a JSON file from the public dir (build/public) before the frame renders. */
export function useJson<T>(path: string | undefined | null): T | null {
  const [data, setData] = useState<T | null>(null);
  const [handle] = useState(() => (path ? delayRender(`load ${path}`) : null));
  useEffect(() => {
    if (!path) return;
    fetch(staticFile(path))
      .then((r) => r.json())
      .then((d) => setData(d))
      .catch((e) => console.error("could not load", path, e))
      .finally(() => handle !== null && continueRender(handle));
  }, [path, handle]);
  return data;
}

/** Detections written by tools/detect.py: per-frame boxes in 1920x1080 pixels of the conformed clip. */
export interface Det { id: number; cls: string; conf: number; box: [number, number, number, number] }
export interface Detections {
  fps: number;
  frames: Det[][];                 // index = frame of the conformed clip (30 fps)
  line?: [number, number, number, number];
  events?: { f: number; id: number; dir: "in" | "out"; cls: string }[];
  main?: { f: number; box: [number, number, number, number] }[];  // largest person per frame
}

export function detsAt(d: Detections | null, clipTime: number): Det[] {
  if (!d) return [];
  const i = Math.max(0, Math.min(d.frames.length - 1, Math.round(clipTime * d.fps)));
  return d.frames[i] ?? [];
}
