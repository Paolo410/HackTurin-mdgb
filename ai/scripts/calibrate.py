"""Calibration tool. AI-M2: draws the two counting lines and saves them in calib.json.

Usage (from ai/):
    python scripts/calibrate.py [--source 0|video.mp4] [--out calib.json]

Click four points on the frame, in this order:
    1-2  pedestrian line ("ped"): along the stripes, in the middle of the road
    3-4  vehicle line ("veh"): across the lane, before the crossing
The arrow shows the direction counted as IN. Keys: i = invert the last line, r = restart, s = save, q = quit.
A line only counts between its two ends: draw it longer than needed.
The homography and the zones are added to the same file by AI-M3.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartcrossing.config import load_config, resolve_path  # noqa: E402
from smartcrossing.geometry import in_direction, save_calib, to_normalized  # noqa: E402
from smartcrossing.sources import FrameSource, default_source  # noqa: E402

LINE_NAMES = ("ped", "veh")
POINTS_PER_LINE = 2
WINDOW = "MDGB calibration"
HELP = "click: ped start/end, veh start/end | i invert  r restart  s save  q quit"


def build_lines(points: list[tuple[int, int]], width: int, height: int) -> dict:
    """Clicked pixel points (2 per line, in LINE_NAMES order) -> the "lines" section of calib.json."""
    lines = {}
    for i, name in enumerate(LINE_NAMES):
        pair = points[i * POINTS_PER_LINE:(i + 1) * POINTS_PER_LINE]
        if len(pair) == POINTS_PER_LINE:
            lines[name] = {"start": to_normalized(pair[0], width, height),
                           "end": to_normalized(pair[1], width, height)}
    return lines


def invert_last_line(points: list[tuple[int, int]]) -> None:
    """Swaps start and end of the last complete line: IN and OUT are exchanged."""
    complete = len(points) // POINTS_PER_LINE * POINTS_PER_LINE
    if complete:
        points[complete - 2], points[complete - 1] = points[complete - 1], points[complete - 2]


def draw(frame, points: list[tuple[int, int]], cfg: dict):
    o = cfg["overlay"]
    color, thickness, scale = tuple(o["colors"]["line"]), int(o["thickness"]), float(o["font_scale"])
    arrow = int(o["line_arrow_px"])
    view = frame.copy()
    for point in points:
        cv2.circle(view, point, thickness * 2, color, cv2.FILLED)
    for i, name in enumerate(LINE_NAMES):
        pair = points[i * POINTS_PER_LINE:(i + 1) * POINTS_PER_LINE]
        if len(pair) < POINTS_PER_LINE or pair[0] == pair[1]:
            continue
        cv2.line(view, pair[0], pair[1], color, thickness)
        mid = ((pair[0][0] + pair[1][0]) // 2, (pair[0][1] + pair[1][1]) // 2)
        dx, dy = in_direction(pair[0], pair[1])
        tip = (int(mid[0] + dx * arrow), int(mid[1] + dy * arrow))
        cv2.arrowedLine(view, mid, tip, color, thickness, tipLength=float(o["line_arrow_tip"]))
        cv2.putText(view, f"{name} IN", (tip[0] + thickness, tip[1]), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1,
                    cv2.LINE_AA)
    cv2.putText(view, HELP, (thickness * 4, view.shape[0] - thickness * 4), cv2.FONT_HERSHEY_SIMPLEX, scale,
                tuple(o["colors"]["text"]), 1, cv2.LINE_AA)
    return view


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", help="webcam index or video file (default: first video in samples/, else 0)")
    p.add_argument("--out", help="calibration file to write (default: calib_path in config.yaml)")
    p.add_argument("--warmup-frames", type=int, default=10, help="frames skipped before the one shown")
    args = p.parse_args()

    cfg = load_config()
    out = Path(args.out) if args.out else resolve_path(cfg["counting"]["calib_path"])
    try:
        source = FrameSource(args.source or default_source(cfg), cfg, realtime=False)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    frame = None
    for _ in range(max(1, args.warmup_frames)):
        item = source.read()
        if item is None:
            break
        frame = item[0]
    source.release()
    if frame is None:
        print("Error: no frame from the source", file=sys.stderr)
        return 2
    height, width = frame.shape[:2]

    points: list[tuple[int, int]] = []
    max_points = len(LINE_NAMES) * POINTS_PER_LINE

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < max_points:
            points.append((x, y))

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)
    saved = False
    while True:
        cv2.imshow(WINDOW, draw(frame, points, cfg))
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("r"):
            points.clear()
        elif key == ord("i"):
            invert_last_line(points)
        elif key == ord("s"):
            lines = build_lines(points, width, height)
            if not lines:
                print("Nothing to save: click at least the two points of the pedestrian line.")
                continue
            calib = {}
            if out.is_file():   # keep what other steps wrote (homography, zones)
                with open(out, "r", encoding="utf-8") as fh:
                    calib = json.load(fh)
            calib["lines"] = lines
            save_calib(calib, out)
            print(f"Saved {out}: {', '.join(lines)}")
            saved = True
            break
    cv2.destroyAllWindows()
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
