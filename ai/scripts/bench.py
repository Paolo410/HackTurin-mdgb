"""Benchmark: mean and p95 milliseconds per phase on a video (or the webcam). Prints a table.

Usage (from ai/):
    python scripts/bench.py [source] [--frames N] [--profile pc|unoq] [--emulate-unoq]
Video files are read as fast as possible: the numbers are processing times, not playback speed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartcrossing.config import load_config  # noqa: E402
from smartcrossing.pipeline import LatencyStats, Pipeline  # noqa: E402
from smartcrossing.sources import FrameSource, default_source  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("source", nargs="?", help="video file, webcam index or rtsp:// URL")
    p.add_argument("--frames", type=int, help="frames to measure (default: bench.frames in config.yaml)")
    p.add_argument("--profile", choices=["pc", "unoq"], default="pc")
    p.add_argument("--emulate-unoq", action="store_true")
    p.add_argument("--config")
    args = p.parse_args()

    cfg = load_config(args.config, args.profile, args.emulate_unoq)
    n_frames = args.frames or int(cfg["bench"]["frames"])
    warmup = int(cfg["bench"]["warmup_frames"])

    try:
        source = FrameSource(args.source or default_source(cfg), cfg, realtime=False)
        pipeline = Pipeline(cfg, source.fps)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    stats = LatencyStats()
    seen = measured = 0
    try:
        while measured < n_frames:
            item = source.read()
            if item is None:
                break
            result = pipeline.step(*item)
            seen += 1
            if seen > warmup:
                stats.add(result.lat_ms)
                measured += 1
    finally:
        source.release()

    if measured == 0:
        print("No frames measured: the source ended during the warm-up.")
        return 1
    threads = int(cfg["model"]["intra_op_num_threads"])
    total = stats.total_mean()
    print(f"source={source.name} profile={cfg['profile']} emulate_unoq={cfg['emulate_unoq']}")
    print(stats.table(float(cfg["bench"]["percentile"])))
    print(f"frames={measured} input={pipeline.detector.input_label} threads={threads or 'auto'} "
          f"pipeline FPS={1000.0 / total:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
