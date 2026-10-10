"""Drawing of boxes, IDs and the on-screen status. Display only: nothing is saved."""
from __future__ import annotations

import cv2
import numpy as np

from .pipeline import FrameResult
from .tracking import Tracker

# Colour group of each kept class (colours are in config.yaml).
CLASS_GROUP = {
    "person": "person",
    "bicycle": "two_wheeler",
    "motorcycle": "two_wheeler",
    "car": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
}
_DEFAULT_GROUP = "animal"
_FONT = cv2.FONT_HERSHEY_SIMPLEX


def draw_tracks(frame: np.ndarray, result: FrameResult, tracker: Tracker, cfg: dict) -> None:
    """Draws one box per track: '#id class score'. Tracks not yet valid are grey."""
    o = cfg["overlay"]
    colors, scale, thickness = o["colors"], float(o["font_scale"]), int(o["thickness"])
    tracked = result.tracked
    if tracked.tracker_id is None:
        return
    for xyxy, score, track_id, valid in zip(tracked.xyxy, tracked.confidence, tracked.tracker_id, result.valid):
        state = tracker.tracks.get(int(track_id))
        name = state.class_name if state else "?"
        group = CLASS_GROUP.get(name, _DEFAULT_GROUP) if valid else "pending"
        color = tuple(int(c) for c in colors[group])
        x1, y1, x2, y2 = (int(v) for v in xyxy)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        label = f"#{int(track_id)} {name} {score:.2f}"
        (tw, th), baseline = cv2.getTextSize(label, _FONT, scale, 1)
        top = max(y1 - th - baseline, 0)
        cv2.rectangle(frame, (x1, top), (x1 + tw, top + th + baseline), color, cv2.FILLED)
        cv2.putText(frame, label, (x1, top + th), _FONT, scale, tuple(colors["hud_bg"]), 1, cv2.LINE_AA)


def draw_hud(frame: np.ndarray, lines: list[str], cfg: dict) -> None:
    """Status lines in the top-left corner, on a filled background."""
    o = cfg["overlay"]
    colors, scale = o["colors"], float(o["font_scale"])
    sizes = [cv2.getTextSize(line, _FONT, scale, 1) for line in lines]
    line_h = max(size[1] + baseline for size, baseline in sizes) + int(o["thickness"])
    width = max(size[0] for size, _ in sizes)
    cv2.rectangle(frame, (0, 0), (width + line_h, line_h * len(lines) + line_h // 2),
                  tuple(colors["hud_bg"]), cv2.FILLED)
    for i, line in enumerate(lines):
        cv2.putText(frame, line, (line_h // 2, line_h * (i + 1)), _FONT, scale,
                    tuple(colors["text"]), 1, cv2.LINE_AA)
