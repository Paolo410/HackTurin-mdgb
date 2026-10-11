"""Records a clip from the camera, for the benchmark and for checking the camera itself.

Development tool. The vision never saves frames; this script does, and only in ai/samples/clips/ (ignored by
git). The camera has one reader at a time: the vision must be on a recorded video, or stopped.

Usage, on the board, from ~/HackTurin-mdgb/ai:
    deploy/run_vision.sh video samples/Torino_1.mp4          # frees the camera
    libcamerify ~/venv/bin/python scripts/record_clip.py --seconds 60 --name incrocio_1
    deploy/run_vision.sh camera                              # back to the camera
On a PC: python scripts/record_clip.py --source 0 --seconds 20

What it does:
- reads the camera at a steady rate (reading as fast as possible makes libcamera's V4L2 layer fail);
- waits for the exposure to settle before recording (after opening, the first frames are black);
- writes <name>.mp4 and <name>.json with: frames, real rate, failed reads, and the frames that are black or
  much darker than the others, with the moment they happen. A clip with dark frames tells a problem of the
  camera or of the light from a problem of the page that shows it.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

AI_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUT = AI_DIR / "samples" / "clips"      # ai/samples/ is ignored by git
BLACK_LEVEL = 3.0                               # mean brightness (0-255) below which a frame is black
SAMPLE_STEP = 8                                 # brightness measured on one pixel out of 8 per side: fast
SETTLE_FRAMES = 5                               # the exposure is settled when this many frames in a row agree
SETTLE_TOLERANCE = 0.10                         # ... within this share of their mean
USUAL_PERCENTILE = 75                           # brightness taken as that of a good frame


def brightness(frame: np.ndarray) -> float:
    return float(frame[::SAMPLE_STEP, ::SAMPLE_STEP].mean())


def read_frame(cap) -> np.ndarray | None:
    """One frame, or None: a failed read and a malformed buffer are the same thing for who records."""
    try:
        ok, frame = cap.read()
    except cv2.error:
        return None
    return frame if ok and frame is not None and frame.size else None


def wait_for_exposure(cap, period: float, max_s: float) -> int:
    """Reads and discards frames until the brightness stops changing. Returns how many were discarded."""
    recent: list[float] = []
    discarded = 0
    start = time.monotonic()
    while time.monotonic() - start < max_s:
        frame = read_frame(cap)
        time.sleep(period)
        if frame is None:
            continue
        discarded += 1
        recent = (recent + [brightness(frame)])[-SETTLE_FRAMES:]
        mean = sum(recent) / len(recent)
        if len(recent) == SETTLE_FRAMES and mean > BLACK_LEVEL and max(recent) - min(recent) <= SETTLE_TOLERANCE * mean:
            break
    return discarded


def dark_runs(levels: list[float], times: list[float], dark_ratio: float) -> tuple[list[dict], float]:
    """Groups of consecutive frames that are black or much darker than the usual frame, and that usual level."""
    if not levels:
        return [], 0.0
    # The level of the good frames: the upper quartile, so that it holds even if half of the frames are black.
    usual = float(np.percentile(levels, USUAL_PERCENTILE))
    limit = max(BLACK_LEVEL, dark_ratio * usual)
    runs: list[dict] = []
    for i, level in enumerate(levels):
        if level >= limit:
            continue
        if runs and runs[-1]["last_frame"] == i - 1:
            runs[-1]["last_frame"] = i
            runs[-1]["frames"] += 1
            runs[-1]["darkest"] = round(min(runs[-1]["darkest"], level), 1)
        else:
            runs.append({"t_s": round(times[i], 2), "first_frame": i, "last_frame": i, "frames": 1,
                         "darkest": round(level, 1)})
    return runs, usual


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", default="0", help="camera index (default 0), or a video file to try the tool")
    p.add_argument("--seconds", type=float, default=30.0, help="length of the clip")
    p.add_argument("--fps", type=float, default=10.0, help="frames read and written per second")
    p.add_argument("--name", help="name of the clip (default: camera_<date>_<time>)")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="folder of the clips (default: ai/samples/clips)")
    p.add_argument("--settle-s", type=float, default=4.0, help="longest wait for the exposure before recording")
    p.add_argument("--dark-ratio", type=float, default=0.35,
                   help="a frame is dark when its brightness is below this share of the usual one")
    args = p.parse_args(argv)

    cap = cv2.VideoCapture(int(args.source) if args.source.isdigit() else args.source)
    if not cap.isOpened():
        print("Camera non aperta: è occupata dalla visione? (deploy/run_vision.sh video ... la libera). "
              "Sulla scheda serve libcamerify davanti al comando.", file=sys.stderr)
        return 2
    period = 1.0 / args.fps
    discarded = wait_for_exposure(cap, period, args.settle_s)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or time.strftime("camera_%Y%m%d_%H%M%S")
    video_path = out_dir / f"{name}.mp4"
    writer = None
    levels: list[float] = []
    times: list[float] = []
    failed = 0
    start = next_read = time.monotonic()
    while (now := time.monotonic()) - start < args.seconds:
        if now < next_read:
            time.sleep(next_read - now)
        next_read += period
        frame = read_frame(cap)
        if frame is None:
            failed += 1
            continue
        if writer is None:
            height, width = frame.shape[:2]
            writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (width, height))
        writer.write(frame)
        levels.append(brightness(frame))
        times.append(time.monotonic() - start)
    elapsed = time.monotonic() - start
    cap.release()
    if writer is None:
        print("Nessun fotogramma dalla camera.", file=sys.stderr)
        return 1
    writer.release()

    runs, usual = dark_runs(levels, times, args.dark_ratio)
    report = {
        "clip": video_path.name, "size": [width, height], "seconds": round(elapsed, 1), "frames": len(levels),
        "fps_asked": args.fps, "fps_real": round(len(levels) / elapsed, 2), "failed_reads": failed,
        "discarded_before_recording": discarded,
        "brightness": {"usual": round(usual, 1), "min": round(min(levels), 1), "max": round(max(levels), 1),
                       "p5": round(float(np.percentile(levels, 5)), 1), "p95": round(float(np.percentile(levels, 95)), 1)},
        "dark_frames": sum(r["frames"] for r in runs), "dark_runs": runs,
    }
    (out_dir / f"{name}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    b = report["brightness"]
    print(f"{video_path}: {report['frames']} fotogrammi in {report['seconds']} s ({report['fps_real']}/s, chiesti "
          f"{args.fps:g}), letture fallite {failed}, scartati prima di registrare {discarded}")
    print(f"  luminosità: solita {b['usual']}, da {b['min']} a {b['max']} (5%-95%: {b['p5']}-{b['p95']})")
    if runs:
        print(f"  fotogrammi scuri: {report['dark_frames']} in {len(runs)} gruppi; i primi: "
              + ", ".join(f"{r['frames']} a {r['t_s']} s" for r in runs[:8]))
    else:
        print("  nessun fotogramma nero o molto più scuro degli altri")
    return 0


if __name__ == "__main__":
    sys.exit(main())
