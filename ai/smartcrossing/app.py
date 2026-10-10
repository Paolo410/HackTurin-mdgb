"""Entry point: python -m smartcrossing.app --source 0|file.mp4|rtsp://... [--emulate-unoq] [--headless]

AI-M1: source + detector + tracker + overlay. Counting, rules, events and thermal arrive with the next milestones.
"""
from __future__ import annotations

import argparse
import sys
from time import perf_counter

import cv2

from .config import load_config
from .overlay import draw_hud, draw_tracks
from .pipeline import PHASES, LatencyStats, Pipeline
from .sources import FrameSource, default_source

_KEY_ESC = 27
_MIN_DT = 1e-6  # avoids a division by zero in the instantaneous FPS
# Options of the full CLI that are accepted but have no effect before their milestone.
_NOT_ACTIVE_YET = {"site": "AI-M4", "actuator": "AI-M3", "thermal": "AI-M5"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m smartcrossing.app", description=__doc__.splitlines()[0])
    p.add_argument("--source", help="webcam index, video file or rtsp:// URL (default: first video in samples/, else 0)")
    p.add_argument("--profile", choices=["pc", "unoq"], default="pc")
    p.add_argument("--site", choices=["urbano", "lungofiume", "collina"])
    p.add_argument("--headless", action="store_true", help="no window, status lines on the terminal")
    p.add_argument("--emulate-unoq", action="store_true", help="UNO Q limits on the PC (FPS cap, threads, input size)")
    p.add_argument("--actuator", choices=["sim", "serial", "bridge"])
    p.add_argument("--thermal", choices=["none", "uvc", "mlx90640"])
    p.add_argument("--max-fps", type=float, help="override source.max_fps")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = until the source ends)")
    p.add_argument("--config", help="path to a config.yaml (default: ai/config.yaml)")
    return p.parse_args(argv)


def _fmt_ms(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config, args.profile, args.emulate_unoq)
    if args.max_fps is not None:
        cfg["source"]["max_fps"] = args.max_fps
    o = cfg["overlay"]

    try:
        source = FrameSource(args.source or default_source(cfg), cfg)
        pipeline = Pipeline(cfg, source.fps)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    stats = LatencyStats()

    threads = int(cfg["model"]["intra_op_num_threads"])
    setup = (f"source={source.name} profile={cfg['profile']} emulate_unoq={cfg['emulate_unoq']} "
             f"input={pipeline.detector.input_size}px threads={threads or 'auto'} "
             f"max_fps={cfg['source']['max_fps'] or 'unlimited'}")
    print(setup)
    ignored = [f"--{name} ({milestone})" for name, milestone in _NOT_ACTIVE_YET.items() if getattr(args, name)]
    if ignored:
        print("Not active yet: " + ", ".join(ignored))

    quit_keys = {ord(k) for k in o["quit_keys"]} | {_KEY_ESC}
    alpha = float(o["fps_ema_alpha"])
    fps = 0.0
    frames = 0
    start = last = last_status = perf_counter()
    try:
        while True:
            item = source.read()
            if item is None:
                break
            frame, t = item
            result = pipeline.step(frame, t)
            stats.add(result.lat_ms)
            frames += 1

            now = perf_counter()
            instant = 1.0 / max(now - last, _MIN_DT)
            fps = instant if frames == 1 else (1 - alpha) * fps + alpha * instant
            last = now
            n_tracks = len(result.tracked)
            n_valid = int(result.valid.sum())
            lat = " ".join(f"{phase}={_fmt_ms(result.lat_ms[phase])}" for phase in PHASES)

            if args.headless:
                if now - last_status >= float(o["status_every_s"]):
                    print(f"t={now - start:6.1f}s frame={frames} fps={fps:.1f} ms[{lat}] tracks={n_tracks} valid={n_valid}")
                    last_status = now
            else:
                draw_tracks(frame, result, pipeline.tracker, cfg)
                draw_hud(frame, [f"FPS {fps:.1f}   tracks {n_valid}/{n_tracks}", f"ms  {lat}", setup], cfg)
                cv2.imshow(o["window_name"], frame)
                if cv2.waitKey(1) & 0xFF in quit_keys:
                    break
                if cv2.getWindowProperty(o["window_name"], cv2.WND_PROP_VISIBLE) < 1:
                    break
            if args.max_frames and frames >= args.max_frames:
                break
    except KeyboardInterrupt:
        pass
    finally:
        source.release()
        if not args.headless:
            cv2.destroyAllWindows()

    elapsed = perf_counter() - start
    print(f"\nframes={frames} elapsed={elapsed:.1f}s end-to-end FPS={frames / elapsed if elapsed > 0 else 0:.1f}")
    print(stats.table(float(cfg["bench"]["percentile"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
