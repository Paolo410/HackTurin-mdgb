"""Runs the whole chain on a test video and writes what happened: numbers (JSON) and annotated frames.

Usage (from ai/):
    python scripts/evaluate.py samples/video.mp4 [--calib calib.json] [--out samples/report] [--emulate-unoq]

Development tool for recorded test videos only: it saves frames to disk, which the product never does.
Keep its output out of git (samples/ is ignored).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartcrossing.actuator import SimActuator  # noqa: E402
from smartcrossing.config import load_config  # noqa: E402
from smartcrossing.geometry import load_calib  # noqa: E402
from smartcrossing.overlay import draw_hud, draw_lines, draw_state, draw_tracks, draw_zones  # noqa: E402
from smartcrossing.pipeline import PHASES, Pipeline  # noqa: E402
from smartcrossing.sources import FrameSource  # noqa: E402

KMH = 3.6
SNAPSHOT_WIDTH = 960
JPEG_QUALITY = 82


class Stabilizer:
    """Brings every frame of a hand-held video back onto the first one (shift, rotation, zoom).

    The product has a fixed camera and one calibration; a test video shot by hand needs this first.
    """

    def __init__(self, reference: np.ndarray):
        self.gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        self.points = cv2.goodFeaturesToTrack(self.gray, 500, 0.01, 8)
        self.last = np.eye(2, 3, dtype=np.float64)
        self.max_shift = 0.0

    def apply(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        moved, status, _ = cv2.calcOpticalFlowPyrLK(self.gray, gray, self.points, None, winSize=(31, 31), maxLevel=4)
        good = status.ravel() == 1
        if good.sum() >= 20:
            matrix, _ = cv2.estimateAffinePartial2D(moved[good], self.points[good], method=cv2.RANSAC,
                                                    ransacReprojThreshold=3.0)
            if matrix is not None:
                self.last = matrix
        self.max_shift = max(self.max_shift, float(np.hypot(self.last[0, 2], self.last[1, 2])))
        height, width = frame.shape[:2]
        return cv2.warpAffine(frame, self.last, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def crossing_point(history, start, end) -> dict:
    """Where and when the track went over the line: the last change of side in its history, interpolated on the
    line. The count comes minimum_crossing_threshold detector frames later (at 4 per second, 0.7 s and metres
    further): the benchmark compares this point and time, not those of the count."""
    def side(x, y):
        return (end[0] - start[0]) * (y - start[1]) - (end[1] - start[1]) * (x - start[0])
    samples = list(history)
    for (t0, x0, y0), (t1, x1, y1) in zip(reversed(samples[:-1]), reversed(samples[1:])):
        s0, s1 = side(x0, y0), side(x1, y1)
        if (s0 < 0) != (s1 < 0):
            k = s0 / (s0 - s1) if s0 != s1 else 0.0
            return {"t_line": t0 + k * (t1 - t0), "x_line": round(x0 + k * (x1 - x0), 1),
                    "y_line": round(y0 + k * (y1 - y0), 1)}
    return {}


def percentile(values: list[float], q: float) -> float | None:
    return float(np.percentile(values, q)) if values else None


def annotate(frame: np.ndarray, result, pipeline: Pipeline, cfg: dict, title: str) -> np.ndarray:
    view = frame.copy()
    draw_zones(view, pipeline.geometry, cfg)
    draw_lines(view, pipeline.counter, cfg)
    draw_tracks(view, result, pipeline.tracker, cfg)
    counts = pipeline.counter.summary() if pipeline.counter else "no counting lines"
    draw_hud(view, [title, counts, pipeline.events.summary()], cfg)
    if pipeline.geometry is not None and pipeline.geometry.metric:
        draw_state(view, result.command, cfg)
    if view.shape[1] > SNAPSHOT_WIDTH:
        height = int(round(view.shape[0] * SNAPSHOT_WIDTH / view.shape[1]))
        view = cv2.resize(view, (SNAPSHOT_WIDTH, height), interpolation=cv2.INTER_AREA)
    return view


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video")
    p.add_argument("--calib", help="calibration for this video (default: only the example counting lines)")
    p.add_argument("--out", default="samples/report", help="output folder (keep it out of git)")
    p.add_argument("--name", help="prefix of the output files (default: the video file name)")
    p.add_argument("--emulate-unoq", action="store_true")
    p.add_argument("--site", choices=["urbano", "lungofiume", "collina"])
    p.add_argument("--snapshots", type=int, default=4, help="frames saved at regular intervals")
    p.add_argument("--max-event-snapshots", type=int, default=6, help="extra frames saved on state changes and events")
    p.add_argument("--save-video", action="store_true",
                   help="also write the annotated video (test footage only: it stores frames)")
    p.add_argument("--video-step", type=int, default=2, help="write one frame out of N in the annotated video")
    p.add_argument("--stabilize", action="store_true",
                   help="hand-held video: align every frame to the first one before processing")
    p.add_argument("--set", action="append", default=[], metavar="section.key=value",
                   help="override a config value, e.g. --set model.conf=0.25")
    args = p.parse_args()

    cfg = load_config(emulate_unoq=args.emulate_unoq)
    for item in args.set:
        path, raw = item.split("=", 1)
        section, key = path.split(".", 1)
        cfg[section][key] = json.loads(raw)
    calib, calib_path = load_calib(cfg, args.calib)
    source = FrameSource(args.video, cfg, realtime=False)
    actuator = SimActuator()
    pipeline = Pipeline(cfg, source.fps, calib, actuator, site=args.site)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    name = args.name or Path(args.video).stem

    cap = cv2.VideoCapture(args.video)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    expected = max(1, int(total_frames / max(1, source._step)))
    regular = {int(expected * (i + 1) / (args.snapshots + 1)) for i in range(args.snapshots)}

    lat: dict[str, list[float]] = {phase: [] for phase in PHASES}
    totals: list[float] = []
    detections_per_frame: list[int] = []
    valid_per_frame: list[int] = []
    first_seen: dict[int, float] = {}
    last_seen: dict[int, float] = {}
    frames_seen: Counter = Counter()
    valid_ids: set[int] = set()
    speed_samples: dict[int, list[float]] = {}
    height_of: dict[int, float] = {}
    box_px: dict[int, list[float]] = {}
    role_of: dict[int, str] = {}
    flags_of: dict[int, set] = {}
    first_box: dict[int, list[float]] = {}
    last_box: dict[int, list[float]] = {}
    state_time: Counter = Counter()
    state_changes: list[dict] = []
    events: list[dict] = []
    snapshots: list[dict] = []
    extra_left = args.max_event_snapshots
    t0 = last_t = None
    last_state = None
    frames = 0
    stabilizer = None
    writer = None

    while True:
        item = source.read()
        if item is None:
            break
        frame, t = item
        if args.stabilize:
            if stabilizer is None:
                stabilizer = Stabilizer(frame)
            else:
                frame = stabilizer.apply(frame)
        result = pipeline.step(frame, t)
        if t0 is None:
            t0 = t
        rel = t - t0
        measured = [v for v in result.lat_ms.values() if v is not None]
        for phase, value in result.lat_ms.items():
            if value is not None:
                lat[phase].append(value)
        if frames > 0:   # the first frame pays for warming up the model
            totals.append(sum(measured))
        detections_per_frame.append(len(result.tracked))
        valid_per_frame.append(int(result.valid.sum()))
        if result.tracked.tracker_id is not None:
            height, width = frame.shape[:2]
            for xyxy, track_id, ok, role in zip(result.tracked.xyxy, result.tracked.tracker_id, result.valid,
                                                result.roles):
                track_id = int(track_id)
                foot = [round(float(xyxy[0] + xyxy[2]) / 2 / width, 3), round(float(xyxy[3]) / height, 3)]
                first_box.setdefault(track_id, foot)
                last_box[track_id] = foot
                first_seen.setdefault(track_id, rel)
                last_seen[track_id] = rel
                frames_seen[track_id] += 1
                if ok:
                    valid_ids.add(track_id)
                    role_of[track_id] = role
                    box_px.setdefault(track_id, []).append(float(xyxy[3] - xyxy[1]))
                    state = pipeline.tracker.tracks.get(track_id)
                    if state is not None:
                        if state.speed_samples > 0:
                            speed_samples.setdefault(track_id, []).append(state.speed)
                        flags_of[track_id] = {flag for flag in ("child", "slow") if state.attrs.get(flag)}
                        if state.heights:
                            height_of[track_id] = float(median(state.heights))
        command = result.command
        if last_t is not None:
            state_time[last_state] += t - last_t
        reason = None
        if command["state"] != last_state:
            reason = f"state {command['state']}"
            state_changes.append({"t": round(rel, 2), "state": command["state"], "led": command["led"],
                                  "reason": command["reason"]})
        last_state, last_t = command["state"], t
        for event in result.events:
            where = {}
            state = pipeline.tracker.tracks.get(event.get("track_id"))
            if event["type"] == "crossing" and state is not None and state.history:
                where = {"x": round(state.history[-1][1], 1), "y": round(state.history[-1][2], 1)}   # bottom centre, px
                line = pipeline.counter.lines[event["line"]]
                at_line = crossing_point(state.history, line["start"], line["end"])
                if at_line:
                    where.update(at_line, t_line=round(at_line["t_line"] - t0, 2))
            events.append({"t": round(rel, 2), **event, **where})
            if event["type"] != "crossing" or reason is None:
                reason = reason or f"{event.get('kind', event['type'])}"

        if args.save_video and frames % max(1, args.video_step) == 0:
            view = annotate(frame, result, pipeline, cfg, f"{name}  t={rel:.1f}s  input {pipeline.detector.input_label}")
            if writer is None:
                writer = cv2.VideoWriter(str(out / f"{name}_annotato.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                         (source.fps or 30.0) / max(1, args.video_step), (view.shape[1], view.shape[0]))
            writer.write(view)
        save_regular = frames in regular
        if save_regular or (reason is not None and extra_left > 0 and frames > 0):
            if not save_regular:
                extra_left -= 1
            file = f"{name}_{len(snapshots):02d}.jpg"
            title = f"{name}  t={rel:.1f}s  input {pipeline.detector.input_label}"
            cv2.imwrite(str(out / file), annotate(frame, result, pipeline, cfg, title),
                        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            snapshots.append({"file": file, "t": round(rel, 2), "why": reason or "regular",
                              "tracks": len(result.tracked), "valid": int(result.valid.sum()),
                              "state": command["state"]})
        frames += 1
    source.release()
    if writer is not None:
        writer.release()

    lifetimes = [last_seen[i] - first_seen[i] for i in valid_ids]
    roles = Counter()
    speeds_by_role: dict[str, list[float]] = {}
    heights_by_role: dict[str, list[float]] = {}
    box_px_by_role: dict[str, list[float]] = {}
    attributes = Counter()
    for track_id in valid_ids:
        role = role_of.get(track_id, "?")
        roles[role] += 1
        if track_id in speed_samples and len(speed_samples[track_id]) >= 5:
            speeds_by_role.setdefault(role, []).append(median(speed_samples[track_id]) * KMH)
        if track_id in height_of:
            heights_by_role.setdefault(role, []).append(height_of[track_id])
        box_px_by_role.setdefault(role, []).append(median(box_px[track_id]))
        for flag in flags_of.get(track_id, ()):
            attributes[flag] += 1
    camera = pipeline.geometry.camera if pipeline.geometry and pipeline.geometry.metric else None
    duration = (last_t - t0) if frames > 1 else 0.0
    total_mean = float(np.mean(totals)) if totals else None
    report = {
        "name": name,
        "video": {"file": Path(args.video).name, "size": size, "fps": native_fps, "frames": total_frames,
                  "duration_s": round(total_frames / native_fps, 1) if native_fps else None},
        "run": {"emulate_unoq": args.emulate_unoq, "input_px": pipeline.detector.input_label,
                "threads": int(cfg["model"]["intra_op_num_threads"]), "conf": cfg["model"]["conf"],
                "frames_processed": frames, "processed_fps": round(source.fps, 1),
                "calib": calib_path.name, "metric": bool(pipeline.geometry and pipeline.geometry.metric),
                "site": pipeline.animals.site_name, "overrides": args.set,
                # Worked out from the calibration: a height or a focal length that make no sense = bad calibration.
                "camera": {"height_m": round(camera["height_m"], 1), "focal_px": round(camera["focal_px"])} if camera else None,
                "stabilized": args.stabilize,
                "max_camera_shift_px": round(stabilizer.max_shift, 1) if stabilizer else None},
        "timing_ms": {phase: {"mean": round(float(np.mean(v)), 2), "p95": round(percentile(v, 95), 2)}
                      for phase, v in lat.items() if v},
        "total_ms": {"mean": round(total_mean, 2) if total_mean else None,
                     "p95": round(percentile(totals, 95), 2) if totals else None},
        "pipeline_fps": round(1000.0 / total_mean, 1) if total_mean else None,
        "tracks_per_frame": {"mean": round(float(np.mean(detections_per_frame)), 1) if detections_per_frame else 0,
                             "max": max(detections_per_frame, default=0)},
        "valid_per_frame": {"mean": round(float(np.mean(valid_per_frame)), 1) if valid_per_frame else 0,
                            "max": max(valid_per_frame, default=0)},
        "track_ids": {"all": len(first_seen), "valid": len(valid_ids),
                      "lifetime_s_median": round(median(lifetimes), 2) if lifetimes else None,
                      "lifetime_s_p90": round(percentile(lifetimes, 90), 2) if lifetimes else None,
                      "shorter_than_1s": sum(1 for v in lifetimes if v < 1.0)},
        "roles": dict(roles.most_common()),
        "speed_kmh": {role: {"n": len(v), "median": round(median(v), 1), "p95": round(percentile(v, 95), 1),
                             "max": round(max(v), 1)} for role, v in sorted(speeds_by_role.items())},
        # Estimated height: adults around 1.7 m tell that the calibration is good.
        "height_m": {role: {"n": len(v), "median": round(median(v), 2), "p10": round(percentile(v, 10), 2),
                            "p90": round(percentile(v, 90), 2)} for role, v in sorted(heights_by_role.items())},
        # Height of the boxes in pixels of the video: how large the objects are for the detector.
        "box_height_px": {role: {"median": round(median(v)), "p10": round(percentile(v, 10)), "p90": round(percentile(v, 90))}
                          for role, v in sorted(box_px_by_role.items())},
        "attributes": dict(attributes),
        "tracks": [{"id": i, "role": role_of.get(i, "?"), "t0": round(first_seen[i], 2), "t1": round(last_seen[i], 2),
                    "frames": frames_seen[i], "from": first_box[i], "to": last_box[i],
                    "kmh": round(median(speed_samples[i]) * KMH, 1) if len(speed_samples.get(i, [])) >= 5 else None,
                    "height_m": round(height_of[i], 2) if i in height_of else None,
                    "flags": sorted(flags_of.get(i, ()))}
                   for i in sorted(valid_ids, key=lambda k: first_seen[k])],
        "counts": pipeline.counter.counts if pipeline.counter else {},
        "counts_text": pipeline.counter.summary() if pipeline.counter else "",
        "events_text": pipeline.events.summary(),
        "events": events,
        "state_share": {s: round(v / duration, 3) for s, v in state_time.items()} if duration > 0 else {},
        "state_changes": state_changes,
        "c1_sent": len(actuator.sent),
        "snapshots": snapshots,
    }
    with open(out / f"{name}.json", "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print(f"{name}: {frames} frames, pipeline {report['pipeline_fps']} FPS, detect {report['timing_ms']['detect']['mean']} ms, "
          f"valid tracks {report['track_ids']['valid']}, roles {report['roles']}")
    print(f"  counts: {report['counts_text']} | {report['events_text']} | states {report['state_share']}")
    print(f"  -> {out / (name + '.json')} and {len(snapshots)} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
