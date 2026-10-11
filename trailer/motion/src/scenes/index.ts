// Scene id (timeline.json) -> overlay component. Footage comes from the shots, overlays from here.
import type React from "react";
import type { Scene } from "../types";
import { B14, B15 } from "./close";
import { B01, B02, B03, B04 } from "./open";
import { B07, B08, B09, B10, B11, B12, B13 } from "./proof";
import { B05, B06 } from "./reveal";

export const SCENES: Record<string, React.FC<{ scene: Scene }>> = {
  B01, B02, B03, B04, B05, B06, B07, B08, B09, B10, B11, B12, B13, B14, B15,
};
