"""Drawing of boxes, IDs and the on-screen status. Display only: nothing is saved."""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import in_direction
from .pipeline import FrameResult
from .tracking import Tracker

# Colour group of each role (colours are in config.yaml).
ROLE_GROUP = {
    "pedestrian": "person",
    "cyclist": "two_wheeler",
    "motorcyclist": "two_wheeler",
    "bicycle": "two_wheeler",
    "motorcycle": "two_wheeler",
    "car": "vehicle",
    "bus": "vehicle",
    "truck": "vehicle",
    "ridden": "pending",   # two-wheeler represented by its rider
}
_DEFAULT_GROUP = "animal"
_FONT = cv2.FONT_HERSHEY_SIMPLEX
KMH = 3.6


def draw_tracks(frame: np.ndarray, result: FrameResult, tracker: Tracker, cfg: dict) -> None:
    """Draws one box per track: '#id role score'. Tracks not yet valid are grey."""
    o = cfg["overlay"]
    colors, scale, thickness = o["colors"], float(o["font_scale"]), int(o["thickness"])
    tracked = result.tracked
    if tracked.tracker_id is None:
        return
    for i, (xyxy, score, track_id, valid) in enumerate(
            zip(tracked.xyxy, tracked.confidence, tracked.tracker_id, result.valid)):
        state = tracker.tracks.get(int(track_id))
        name = result.roles[i] if i < len(result.roles) else (state.class_name if state else "?")
        group = ROLE_GROUP.get(name, _DEFAULT_GROUP) if valid else "pending"
        color = tuple(int(c) for c in colors[group])
        x1, y1, x2, y2 = (int(v) for v in xyxy)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        label = f"#{int(track_id)} {name} {score:.2f}"
        if state is not None and state.speed_samples > 0:
            label += f" {state.speed * KMH:.0f}km/h"
            flags = [flag for flag in ("child", "slow") if state.attrs.get(flag)]
            if state.attrs.get("aid") not in (None, "normal"):
                flags.append(state.attrs["aid"])
            if flags:
                label += " " + "+".join(flags)
        (tw, th), baseline = cv2.getTextSize(label, _FONT, scale, 1)
        top = max(y1 - th - baseline, 0)
        cv2.rectangle(frame, (x1, top), (x1 + tw, top + th + baseline), color, cv2.FILLED)
        cv2.putText(frame, label, (x1, top + th), _FONT, scale, tuple(colors["hud_bg"]), 1, cv2.LINE_AA)


def draw_lines(frame: np.ndarray, counter, cfg: dict) -> None:
    """Counting lines with their name and an arrow pointing to the IN direction."""
    if counter is None:
        return
    o = cfg["overlay"]
    color, scale, thickness = tuple(o["colors"]["line"]), float(o["font_scale"]), int(o["thickness"])
    arrow = int(o["line_arrow_px"])
    for name, line in counter.lines.items():
        start, end = line["start"], line["end"]
        cv2.line(frame, start, end, color, thickness)
        mid = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
        dx, dy = in_direction(start, end)
        tip = (int(mid[0] + dx * arrow), int(mid[1] + dy * arrow))
        cv2.arrowedLine(frame, mid, tip, color, thickness, tipLength=float(o["line_arrow_tip"]))
        cv2.putText(frame, f"{name} IN", (tip[0] + thickness, tip[1]), _FONT, scale, color, 1, cv2.LINE_AA)


def draw_zones(frame: np.ndarray, geometry, cfg: dict) -> None:
    """Outline of the zones of the metric calibration (stripes and waiting zones)."""
    if geometry is None or not geometry.metric:
        return
    o = cfg["overlay"]
    color = tuple(o["colors"]["zone"])
    for name in o["zones"]:
        polygon = geometry.zones.get(name)
        if polygon:
            points = np.array([geometry.to_image(x, y) for x, y in polygon], dtype=np.int32)
            cv2.polylines(frame, [points], isClosed=True, color=color, thickness=1, lineType=cv2.LINE_AA)


def draw_state(frame: np.ndarray, command: dict | None, cfg: dict, failsafe: bool = False) -> None:
    """Banner at the bottom: state and lamp, the reason, the texts of the two displays and the requests."""
    if command is None:
        return
    o = cfg["overlay"]
    colors, scale = o["colors"], float(o["font_scale"])
    req = command["req"]
    lines = [
        f"{command['state']}   LED {command['led']}" + ("   [FAIL-SAFE: no heartbeat]" if failsafe else ""),
        command["reason"][:int(o["reason_max_chars"])],
        f"LCD [{command['lcd']}]  OLED [{command['oled']}]  green {command['green_s']}s "
        f"+{req['ped_green_extend_s']}s  red_hold={int(req['veh_red_hold'])} flash={int(req['flash'])}",
    ]
    (_, text_h), baseline = cv2.getTextSize("Ag", _FONT, scale, 1)
    line_h = text_h + baseline + int(o["thickness"])
    height, width = frame.shape[:2]
    top = height - line_h * len(lines) - line_h // 2
    cv2.rectangle(frame, (0, top), (width, height), tuple(colors["hud_bg"]), cv2.FILLED)
    cv2.rectangle(frame, (0, top), (line_h // 2, height), tuple(colors["state"][command["state"]]), cv2.FILLED)
    for i, line in enumerate(lines):
        color = tuple(colors["state"][command["state"]]) if i == 0 else tuple(colors["text"])
        cv2.putText(frame, line, (line_h, top + line_h * (i + 1)), _FONT, scale, color, 1, cv2.LINE_AA)


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
