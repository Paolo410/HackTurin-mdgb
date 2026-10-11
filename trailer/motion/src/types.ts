// Shape of build/public/data/timeline.json (written by tools/build.py from trailer/timeline.json
// + media.json + the voice placement). Every scene is data: swap clips in media.json, not here.

export type Grade = "night" | "dusk" | "dusk2night" | "dawn" | "neutral" | "neutralDark";

export interface Shot {
  media: string;          // clip id in media.json
  src?: string;           // resolved by build.py: "media/<id>.mp4" inside the public dir
  in?: number;            // seconds into the clip
  dur: number;            // seconds on screen
  freeze?: number;        // hold this clip time as a still
  speed?: number;         // playback rate
  grade?: Grade;
  zoom?: [number, number];// scale at start/end of the shot
  tiltShift?: boolean;
  blur?: [number, number, number]; // privacy blur: from t0 to t1 (shot time) up to N px
  detections?: string;    // data/detections_<id>.json
  tag?: { title: string; value: string; note?: string; x: number; y: number };
}

export interface VoLine { id: string; text: string; start?: number; end?: number }

export interface Scene {
  id: string;
  act: "open" | "problem" | "reveal" | "proof" | "vision" | "close";
  start: number;
  dur: number;
  name: string;
  shots: Shot[];
  vo: VoLine | null;
  ost: Record<string, any>;
}

export interface Timeline {
  meta: { title: string; subtitle: string; event: string; fps: number; width: number; height: number;
          duration: number; burnSubtitles?: boolean; version?: string };
  scenes: Scene[];
  vo?: VoLine[];
  credits?: string[];
}
