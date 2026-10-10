"""Calibration tool: tells the system where the crossing is in this camera view. Writes calib.json.

Usage (from ai/):
    python scripts/calibrate.py [--source 0|video.mp4] [--along 4.0 --width 7.0]
    python scripts/calibrate.py --lines-only [--source ...]

Default (metric): click the four corners of the stripes, in this order:
    1-2  the two corners on the near kerb
    3-4  the two corners on the far kerb, going around (3 is opposite to 2, 4 is opposite to 1)
then give two sizes in metres: --along = distance 1-2 (the crossing measured along the road) and
--width = distance 2-3 (the road, kerb to kerb). Without the options the tool asks for them.
From these it derives metres and speeds, the waiting zones and the two counting lines.

--lines-only: no measures, click only the two counting lines (pedestrians: 1-2, vehicles: 3-4).

Keys: i = invert the last counting line (lines-only), r = restart, s = save, q = quit.
A counting line only counts between its two ends: draw it longer than needed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartcrossing.config import load_config, resolve_path  # noqa: E402
from smartcrossing.geometry import (  # noqa: E402
    Geometry, build_metric_calib, in_direction, save_calib, to_normalized, to_pixels,
)
from smartcrossing.sources import FrameSource, default_source  # noqa: E402

LINE_NAMES = ("ped", "veh")
POINTS_PER_LINE = 2
N_POINTS = 4
WINDOW = "MDGB calibration"
HELP_METRIC = "click the 4 corners of the stripes: near kerb (1, 2), far kerb (3, 4) | r restart  s save  q quit"
HELP_LINES = "click: ped start/end, veh start/end | i invert  r restart  s save  q quit"
_FONT = cv2.FONT_HERSHEY_SIMPLEX


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


def metric_from_points(points: list[tuple[int, int]], width: int, height: int, along: float, road: float,
                       cfg: dict) -> dict:
    """The four clicked corners (pixels) and the two sizes in metres -> a full calibration."""
    corners = [to_normalized(p, width, height) for p in points]
    return build_metric_calib(corners, along, road, cfg)


def _draw_line(view, start, end, name: str, cfg: dict) -> None:
    o = cfg["overlay"]
    color, thickness, scale = tuple(o["colors"]["line"]), int(o["thickness"]), float(o["font_scale"])
    if start == end:
        return
    cv2.line(view, start, end, color, thickness)
    mid = ((start[0] + end[0]) // 2, (start[1] + end[1]) // 2)
    dx, dy = in_direction(start, end)
    arrow = int(o["line_arrow_px"])
    tip = (int(mid[0] + dx * arrow), int(mid[1] + dy * arrow))
    cv2.arrowedLine(view, mid, tip, color, thickness, tipLength=float(o["line_arrow_tip"]))
    cv2.putText(view, f"{name} IN", (tip[0] + thickness, tip[1]), _FONT, scale, color, 1, cv2.LINE_AA)


def draw(frame, points: list[tuple[int, int]], cfg: dict, calib: dict | None = None, lines_only: bool = True):
    """The frame with the clicked points and, when available, the lines and zones they produce."""
    o = cfg["overlay"]
    color, thickness, scale = tuple(o["colors"]["line"]), int(o["thickness"]), float(o["font_scale"])
    view = frame.copy()
    height, width = view.shape[:2]
    for i, point in enumerate(points):
        cv2.circle(view, point, thickness * 2, color, cv2.FILLED)
        cv2.putText(view, str(i + 1), (point[0] + thickness * 3, point[1]), _FONT, scale, color, 1, cv2.LINE_AA)
    if lines_only:
        for i, name in enumerate(LINE_NAMES):
            pair = points[i * POINTS_PER_LINE:(i + 1) * POINTS_PER_LINE]
            if len(pair) == POINTS_PER_LINE:
                _draw_line(view, pair[0], pair[1], name, cfg)
    elif calib is not None:
        geometry = Geometry(calib, cfg)
        geometry.set_frame_size(width, height)
        for name in o["zones"]:
            polygon = np.array([geometry.to_image(x, y) for x, y in calib["zones"][name]], dtype=np.int32)
            cv2.polylines(view, [polygon], True, tuple(o["colors"]["zone"]), thickness, cv2.LINE_AA)
        for name, line in calib["lines"].items():
            _draw_line(view, to_pixels(line["start"], width, height), to_pixels(line["end"], width, height), name, cfg)
    elif len(points) > 1:
        cv2.polylines(view, [np.array(points, dtype=np.int32)], len(points) == N_POINTS, color, 1, cv2.LINE_AA)
    cv2.putText(view, HELP_LINES if lines_only else HELP_METRIC, (thickness * 4, height - thickness * 4), _FONT,
                scale, tuple(o["colors"]["text"]), 1, cv2.LINE_AA)
    return view


def write_calib(out: Path, new: dict, replace_all: bool) -> None:
    calib = {}
    if not replace_all and out.is_file():   # lines-only: keep the metric part already there
        with open(out, "r", encoding="utf-8") as fh:
            calib = json.load(fh)
    calib.update(new)
    save_calib(calib, out)


def _ask_metres(label: str) -> float:
    while True:
        try:
            value = float(input(f"{label} in metres: ").replace(",", "."))
            if value > 0:
                return value
        except ValueError:
            pass
        print("Please type a positive number, e.g. 7.0")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", help="webcam index or video file (default: first video in samples/, else 0)")
    p.add_argument("--out", help="calibration file to write (default: calib_path in config.yaml)")
    p.add_argument("--along", type=float, help="distance between corners 1 and 2, in metres")
    p.add_argument("--width", type=float, help="distance between corners 2 and 3 (road width W), in metres")
    p.add_argument("--corners", help='skip the window: the 4 corners as normalized "x,y x,y x,y x,y"')
    p.add_argument("--lines-only", action="store_true", help="only draw the two counting lines")
    p.add_argument("--warmup-frames", type=int, default=10, help="frames skipped before the one shown")
    args = p.parse_args()

    cfg = load_config()
    out = Path(args.out) if args.out else resolve_path(cfg["counting"]["calib_path"])

    if args.corners:   # no window: everything from the command line
        if args.along is None or args.width is None:
            p.error("--corners needs --along and --width")
        corners = [[float(v) for v in pair.split(",")] for pair in args.corners.split()]
        if len(corners) != N_POINTS:
            p.error("--corners needs exactly 4 points")
        write_calib(out, build_metric_calib(corners, args.along, args.width, cfg), replace_all=True)
        print(f"Saved {out}")
        return 0

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
    state = {"calib": None, "along": args.along, "road": args.width}

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < N_POINTS:
            points.append((x, y))

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)
    saved = False
    while True:
        if not args.lines_only and len(points) == N_POINTS and state["calib"] is None:
            cv2.imshow(WINDOW, draw(frame, points, cfg, None, False))
            cv2.waitKey(1)
            if state["along"] is None:
                state["along"] = _ask_metres("Distance between corners 1 and 2 (along the road)")
            if state["road"] is None:
                state["road"] = _ask_metres("Distance between corners 2 and 3 (road width, kerb to kerb)")
            state["calib"] = metric_from_points(points, width, height, state["along"], state["road"], cfg)
            print("Check the zones and the lines in the window, then press s to save or r to restart.")
        cv2.imshow(WINDOW, draw(frame, points, cfg, state["calib"], args.lines_only))
        key = cv2.waitKey(30) & 0xFF
        if key in (ord("q"), 27):
            break
        if key == ord("r"):
            points.clear()
            state["calib"] = None
        elif key == ord("i") and args.lines_only:
            invert_last_line(points)
        elif key == ord("s"):
            if args.lines_only:
                lines = build_lines(points, width, height)
                if not lines:
                    print("Nothing to save: click at least the two points of the pedestrian line.")
                    continue
                write_calib(out, {"lines": lines}, replace_all=False)
            elif state["calib"] is not None:
                write_calib(out, state["calib"], replace_all=True)
            else:
                print("Nothing to save: click the four corners first.")
                continue
            print(f"Saved {out}")
            saved = True
            break
    cv2.destroyAllWindows()
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
