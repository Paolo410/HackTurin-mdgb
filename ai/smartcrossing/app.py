"""Entry point: python -m smartcrossing.app --source 0|file.mp4|rtsp://... [--emulate-unoq] [--headless]

AI-M1: source + detector + tracker + overlay.
AI-M2: roles (pedestrian, cyclist, ...) and directional counting on the lines of calib.json.
AI-M3: metres and speeds from the calibration, pedestrian attributes, the explicit rule and the actuator.
AI-M4: animals, events from the trajectories and the C3 log for comms/ (metadata only, never frames).
AI-M5: optional thermal camera for the night (--thermal).
"""
from __future__ import annotations

import argparse
import sys
import time
from time import perf_counter

import cv2

from .actuator import make_actuator
from .config import load_config
from .geometry import load_calib
from .logger import C3Logger, flat_counts
from .overlay import draw_hud, draw_lines, draw_state, draw_thermal, draw_tracks, draw_zones
from .pipeline import PHASES, LatencyStats, Pipeline
from .sources import FrameSource, default_source
from .thermal import ThermalFusion, make_thermal_source

_KEY_ESC = 27
_MIN_DT = 1e-6  # avoids a division by zero in the instantaneous FPS
_NO_FRAME_SLEEP_S = 0.05  # pause between two attempts when a live camera gives no frame


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m smartcrossing.app", description=__doc__.splitlines()[0])
    p.add_argument("--source", help="webcam index, video file or rtsp:// URL (default: first video in samples/, else 0)")
    p.add_argument("--profile", choices=["pc", "unoq"], default="pc")
    p.add_argument("--site", choices=["urbano", "lungofiume", "collina"])
    p.add_argument("--headless", action="store_true", help="no window, status lines on the terminal")
    p.add_argument("--emulate-unoq", action="store_true", help="UNO Q limits on the PC (FPS cap, threads, input size)")
    p.add_argument("--actuator", choices=["sim", "serial", "bridge"], default="sim")
    p.add_argument("--port", help="serial port of the firmware, with --actuator serial")
    p.add_argument("--thermal", choices=["none", "sim", "mlx90621", "mlx90640", "uvc"], default="none",
                   help="thermal camera: mlx90621 = the Grove 16x4 read by the MCU, sim = simulated")
    p.add_argument("--night", action="store_true", help="force night mode (to try the thermal fusion in daylight)")
    p.add_argument("--max-fps", type=float, help="override source.max_fps")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = until the source ends)")
    p.add_argument("--config", help="path to a config.yaml (default: ai/config.yaml)")
    p.add_argument("--calib", help="path to a calib.json (default: ai/calib.json, else ai/calib.example.json)")
    p.add_argument("--c3-dir", help="folder of the C3 event files (default: $MDGB_C3_DIR, else logs/c3 in the repo)")
    p.add_argument("--no-c3", action="store_true", help="do not write the C3 event files")
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
        calib, calib_path = load_calib(cfg, args.calib)
        actuator = make_actuator(args.actuator, cfg, **({"port": args.port} if args.port else {}))
        thermal_source = make_thermal_source(args.thermal, cfg, actuator)
        thermal = ThermalFusion(cfg, thermal_source, force_night=args.night) if thermal_source else None
        source = FrameSource(args.source or default_source(cfg), cfg)
        pipeline = Pipeline(cfg, source.fps, calib, actuator, site=args.site, thermal=thermal)
    except (FileNotFoundError, RuntimeError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    stats = LatencyStats()
    log = C3Logger(cfg, args.c3_dir) if cfg["logger"]["enabled"] and not args.no_c3 else None

    threads = int(cfg["model"]["intra_op_num_threads"])
    setup = (f"source={source.name} profile={cfg['profile']} emulate_unoq={cfg['emulate_unoq']} "
             f"input={pipeline.detector.input_size}px threads={threads or 'auto'} "
             f"max_fps={cfg['source']['max_fps'] or 'unlimited'} actuator={args.actuator} "
             f"site={pipeline.animals.site_name}")
    print(setup)
    print(f"c3={log.dir if log else 'off'}")
    metric = pipeline.geometry is not None and pipeline.geometry.metric
    print(f"calib={calib_path}" + ("" if metric else
                                  "  (no metric calibration: no speeds and no rule; run scripts/calibrate.py)"))
    if thermal is not None:
        print(f"thermal={args.thermal} zones={ {name: len(cols) for name, cols in thermal.zones.items()} }"
              + (" night forced" if args.night else ""))

    quit_keys = {ord(k) for k in o["quit_keys"]} | {_KEY_ESC}
    alpha = float(o["fps_ema_alpha"])
    fps = 0.0
    frames = 0
    last_state = None
    last_frame = None
    # The clock starts at the first frame: opening the camera is not part of the frame rate.
    first = last = last_status = perf_counter()
    pipeline.commander.start()   # heartbeat every 100 ms, only while this loop is alive
    try:
        while True:
            item = source.read()
            if item is None:
                if not source.is_live or frames == 0:
                    break
                # A live camera stopped giving frames: keep deciding (DEGRADED after the timeout) and retry.
                command = pipeline.no_frame(time.monotonic())
                result = None
                time.sleep(_NO_FRAME_SLEEP_S)
            else:
                frame, t = item
                result = pipeline.step(frame, t)
                command = result.command
                stats.add(result.lat_ms)
                frames += 1
                last_frame = frame

            now = perf_counter()
            if result is not None:
                if frames == 1:
                    first = last_status = now
                else:
                    instant = 1.0 / max(now - last, _MIN_DT)
                    fps = instant if frames == 2 else (1 - alpha) * fps + alpha * instant
                last = now
                for event in result.events:
                    if event["type"] == "crossing":
                        print(f"t={now - first:6.1f}s crossing line={event['line']} dir={event['dir']} "
                              f"cls={event['cls']} track=#{event['track_id']}")
                    else:
                        details = " ".join(f"{k}={v}" for k, v in event.items() if k != "type")
                        print(f"t={now - first:6.1f}s {event['type']} {details}")
                    if log:
                        log.write(event)
                for animal in pipeline.animals.new_sightings(pipeline.scene.animals):
                    print(f"t={now - first:6.1f}s animal track=#{animal.track_id} coco={animal.coco} size={animal.size} "
                          f"free={animal.free} on_road={animal.on_road}")
                if log and log.status_due():
                    log.write_status(command["state"], fps, result.lat_ms,
                                     flat_counts(pipeline.counter.counts) if pipeline.counter else {})
            if command["state"] != last_state:
                last_state = command["state"]
                print(f"t={now - first:6.1f}s state={command['state']} led={command['led']} | {command['reason']}")

            counts = pipeline.counter.summary() if pipeline.counter else "no counting lines"
            if result is not None:
                n_tracks, n_valid = len(result.tracked), int(result.valid.sum())
                lat = " ".join(f"{phase}={_fmt_ms(result.lat_ms[phase])}" for phase in PHASES)
            if args.headless:
                if result is not None and now - last_status >= float(o["status_every_s"]):
                    print(f"t={now - first:6.1f}s frame={frames} fps={fps:.1f} ms[{lat}] "
                          f"tracks={n_tracks} valid={n_valid} state={command['state']} | {counts}")
                    last_status = now
            else:
                view = last_frame if result is not None else last_frame.copy()
                if result is not None:
                    draw_zones(view, pipeline.geometry, cfg)
                    draw_lines(view, pipeline.counter, cfg)
                    draw_tracks(view, result, pipeline.tracker, cfg)
                    draw_hud(view, [f"FPS {fps:.1f}   tracks {n_valid}/{n_tracks}", f"ms  {lat}", counts,
                                    pipeline.events.summary(), setup], cfg)
                    draw_thermal(view, pipeline.thermal, cfg)
                draw_state(view, command, cfg, failsafe=bool(getattr(actuator, "failsafe", False)))
                cv2.imshow(o["window_name"], view)
                if cv2.waitKey(1) & 0xFF in quit_keys:
                    break
                if cv2.getWindowProperty(o["window_name"], cv2.WND_PROP_VISIBLE) < 1:
                    break
            if args.max_frames and frames >= args.max_frames:
                break
    except KeyboardInterrupt:
        pass
    finally:
        pipeline.commander.close()
        source.release()
        if log:
            log.close()
        if not args.headless:
            cv2.destroyAllWindows()

    # Frame intervals between the first and the last frame.
    elapsed = last - first
    end_to_end = (frames - 1) / elapsed if frames > 1 and elapsed > 0 else 0.0
    print(f"\nframes={frames} elapsed={elapsed:.1f}s end-to-end FPS={end_to_end:.1f}")
    print(stats.table(float(cfg["bench"]["percentile"])))
    print("counts  " + (pipeline.counter.summary() if pipeline.counter else "no counting lines"))
    print("events  " + pipeline.events.summary())
    if thermal is not None:
        print(thermal.summary())
        thermal_source.close()
    if log and log.written:
        print(f"c3  {log.written} lines, last file {log.path}")
    sent = len(getattr(actuator, "sent", []))
    if sent:
        print(f"actuator  C1 sent={sent} heartbeats={actuator.heartbeats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
