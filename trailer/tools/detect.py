#!/usr/bin/env python3
"""Real detections for the HUD overlays, made with the team's own pipeline.

Runs ai/smartcrossing's YOLOX detector (same pre/post-processing as the product) + ByteTrack on a
conformed clip (build/public/media/<id>.mp4) and writes build/public/data/detections_<id>.json:
  frames[i] = [{id, cls, conf, box:[x1,y1,x2,y2]}]   (1920x1080 pixels, 30 fps)
  main[i]   = largest pedestrian box (smoothed) — used to pin labels to a person
  events    = crossings of the counting line (in/out), if --line is given

When you swap in your own S1 footage, just re-run this on it: the overlay follows the new boxes.

Usage
  python tools/detect.py c17_pole_view --line 0,0.78,1,0.70
  python tools/detect.py c25_topdown_crowd --model yolox_s --size 640 --conf 0.2
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PUBLIC, ROOT, save_json  # noqa: E402

AI_DIR = ROOT.parent / "ai"
sys.path.insert(0, str(AI_DIR))
from smartcrossing.detector import COCO_CLASSES, Detector  # noqa: E402  (team code, ai/)
import supervision as sv  # noqa: E402

KEEP = ["person", "bicycle", "car", "motorcycle", "bus", "truck", "dog", "cat"]
ROLE = {"person": "pedestrian", "bicycle": "bicycle", "motorcycle": "motorcyclist", "car": "car",
        "bus": "bus", "truck": "truck", "dog": "dog", "cat": "cat"}


def iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter + 1e-9)


def detect_tiled(det, frame, tiles: str):
    """Runs the detector on C x R overlapping tiles upscaled 2x, merges with NMS (sv.Detections)."""
    cols, rows = (int(v) for v in tiles.lower().split("x"))
    H, W = frame.shape[:2]
    tw, th, ov = W // cols, H // rows, 60
    xyxy, conf, cls = [], [], []
    for r in range(rows):
        for c in range(cols):
            x0, y0 = max(0, c * tw - ov), max(0, r * th - ov)
            x1, y1 = min(W, (c + 1) * tw + ov), min(H, (r + 1) * th + ov)
            tile = cv2.resize(frame[y0:y1, x0:x1], ((x1 - x0) * 2, (y1 - y0) * 2))
            d = det.detect(tile)
            for b, s, k in zip(d.xyxy, d.confidence, d.class_id):
                xyxy.append(b / 2 + np.array([x0, y0, x0, y0])); conf.append(s); cls.append(k)
    if not xyxy:
        return sv.Detections.empty()
    d = sv.Detections(xyxy=np.array(xyxy, np.float32), confidence=np.array(conf, np.float32), class_id=np.array(cls, int))
    return d.with_nms(threshold=0.4, class_agnostic=True)


def side(line, pt) -> float:
    (x1, y1, x2, y2), (px, py) = line, pt
    return np.sign((x2 - x1) * (py - y1) - (y2 - y1) * (px - x1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip", help="media id (build/public/media/<id>.mp4)")
    ap.add_argument("--model", default="yolox_nano", help="yolox_nano | yolox_s | path to .onnx")
    ap.add_argument("--size", type=int, default=416)
    ap.add_argument("--conf", type=float, default=0.3)
    ap.add_argument("--line", help="counting line x1,y1,x2,y2 (0-1 of the frame)")
    ap.add_argument("--tiles", help="CxR: run on C x R upscaled tiles (small people seen from a drone)")
    ap.add_argument("--moving-only", action="store_true", help="drop tracks that only follow the camera pan")
    args = ap.parse_args()

    if args.model.endswith(".onnx"):
        model = Path(args.model)
    else:   # trailer/models first (setup.sh), then the team's ai/models
        model = next((p for p in (ROOT / "models" / f"{args.model}.onnx", AI_DIR / "models" / f"{args.model}.onnx") if p.exists()),
                     ROOT / "models" / f"{args.model}.onnx")
    cfg = {"model": {"path": str(model), "input_size": args.size, "conf": args.conf, "nms": 0.45,
                     "nms_cross_class": 0.85, "intra_op_num_threads": 0, "strides": [8, 16, 32],
                     "pad_value": 114, "keep_classes": KEEP}}
    det = Detector(cfg)
    tracker = sv.ByteTrack(track_activation_threshold=args.conf, lost_track_buffer=30,
                           minimum_matching_threshold=0.8, frame_rate=30)
    src = PUBLIC / "media" / f"{args.clip}.mp4"
    cap = cv2.VideoCapture(str(src))
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    line = None
    if args.line:
        x1, y1, x2, y2 = (float(v) for v in args.line.split(","))
        line = [x1 * W, y1 * H, x2 * W, y2 * H]

    frames, main_boxes, events, last_side = [], [], [], {}
    ema, prev_gray, pan, pans = None, None, np.zeros(2), []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        gray = np.float32(cv2.cvtColor(cv2.resize(frame, (W // 2, H // 2)), cv2.COLOR_BGR2GRAY))
        if prev_gray is not None:
            (dx, dy), _ = cv2.phaseCorrelate(prev_gray, gray)
            pan = pan + np.array([dx, dy]) * 2
        pans.append(pan.copy())
        prev_gray = gray
        d = tracker.update_with_detections(detect_tiled(det, frame, args.tiles) if args.tiles else det.detect(frame))
        items = []
        if d.tracker_id is not None:
            for xyxy, conf, cid, tid in zip(d.xyxy, d.confidence, d.class_id, d.tracker_id):
                items.append({"id": int(tid), "cls": ROLE.get(COCO_CLASSES[int(cid)], COCO_CLASSES[int(cid)]),
                              "conf": round(float(conf), 2), "box": [round(float(v), 1) for v in xyxy]})
        # derive cyclists: a person riding a bicycle box becomes "cyclist" (the bicycle box is dropped)
        bikes = [it for it in items if it["cls"] in ("bicycle", "motorcyclist")]
        for it in items:
            if it["cls"] == "pedestrian" and any(iou(it["box"], b["box"]) > 0.2 for b in bikes):
                it["cls"] = "cyclist"
        items = [it for it in items if it["cls"] != "bicycle" or not any(
            o["cls"] == "cyclist" and iou(o["box"], it["box"]) > 0.2 for o in items)]
        frames.append(items)

        peds = [it for it in items if it["cls"] in ("pedestrian", "cyclist")]
        if peds:
            big = max(peds, key=lambda it: (it["box"][2] - it["box"][0]) * (it["box"][3] - it["box"][1]))
            b = np.array(big["box"])
            ema = b if ema is None else ema * 0.7 + b * 0.3
        main_boxes.append({"f": len(frames) - 1, "box": [round(float(v), 1) for v in ema] if ema is not None else None})

        if line is not None:
            for it in items:
                x1, y1, x2, y2 = it["box"]
                s = side(line, ((x1 + x2) / 2, y2))
                prev = last_side.get(it["id"])
                if prev is not None and s != 0 and prev != 0 and s != prev:
                    events.append({"f": len(frames) - 1, "id": it["id"], "dir": "in" if s < 0 else "out", "cls": it["cls"]})
                if s != 0:
                    last_side[it["id"]] = s

    if args.moving_only:                      # keep tracks that move relative to the (panning) ground
        path: dict[int, list] = {}
        for fi, items in enumerate(frames):
            for it in items:
                x1, y1, x2, y2 = it["box"]
                path.setdefault(it["id"], []).append((fi, (x1 + x2) / 2 - pans[fi][0], (y1 + y2) / 2 - pans[fi][1]))
        moving = {tid for tid, pts in path.items() if len(pts) >= 8 and
                  np.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2]) > 25}
        frames = [[it for it in items if it["id"] in moving] for items in frames]

    out = {"clip": args.clip, "fps": 30, "size": [W, H], "model": model.name, "frames": frames,
           "main": main_boxes, "line": line, "events": events}
    save_json(out, PUBLIC / "data" / f"detections_{args.clip}.json")
    n = sum(len(f) for f in frames)
    classes = sorted({it["cls"] for f in frames for it in f})
    print(f"{args.clip}: {len(frames)} frames, {n} boxes, classes={classes}, events={len(events)}")


if __name__ == "__main__":
    main()
