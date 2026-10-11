"""Benchmark of the counting: how many crossings the vision counts, and in which direction, against a reference.

Videos: benchmarks/videos.json (files in samples/, not in git). Reference crossings: benchmarks/reference/<name>.json,
made with a large model at full quality and then reviewed by eye where it disagreed with the board (see the
"review" field of each file). Variants of the settings to compare: benchmarks/variants.json.

Usage (from ai/):
    python scripts/benchmark.py run riferimento                                  # reference: large model, full quality
    python scripts/benchmark.py reference                                        # store its crossings in benchmarks/
    python scripts/benchmark.py run scheda                                       # the board settings on every video
    python scripts/benchmark.py score scheda [other variants...]                 # numbers, and sentences for everybody
    python scripts/benchmark.py review scheda torino_1                           # images of the disagreements, to check

Development tool: `run` and `review` write frames to samples/report (not in git), the product never does.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

AI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI))

from smartcrossing.scoring import KINDS, add_up, match_crossings, pct, sentence  # noqa: E402

BENCH = AI / "benchmarks"
SAMPLES = AI / "samples"
RUNS = SAMPLES / "report" / "bench"
REVIEW = SAMPLES / "report" / "review"
WINDOW_S = 2.0          # a counted crossing this close in time to the reference one is the same crossing
MAX_PX = 120.0          # ... and this close in the image (bottom centre of the box), when both positions are known


def videos() -> list[dict]:
    return json.loads((BENCH / "videos.json").read_text())["videos"]


def variants() -> dict:
    return json.loads((BENCH / "variants.json").read_text())["variants"]


def crossings_of(report: dict) -> list[dict]:
    """The crossings of a run, at the moment and point where the object went over the line when known (t_line,
    x_line, y_line), else at the moment it was counted."""
    keep = ("t", "line", "dir", "cls", "track_id", "x", "y")
    out = []
    for e in report["events"]:
        if e.get("type") != "crossing":
            continue
        c = {k: e[k] for k in keep if k in e}
        if "t_line" in e:
            c.update(t=e["t_line"], x=e["x_line"], y=e["y_line"], t_count=e["t"])
        out.append(c)
    return out


def reference_of(name: str) -> list[dict] | None:
    """The reference crossings of a video after the review: removed ones out, added ones in."""
    path = BENCH / "reference" / f"{name}.json"
    if not path.is_file():
        return None
    ref = json.loads(path.read_text())
    review = ref.get("review", {})
    removed = set(review.get("removed", []))
    kept = [e for i, e in enumerate(ref["crossings"]) if i not in removed]
    return sorted(kept + review.get("added", []), key=lambda e: e["t"])


def cmd_reference(args) -> int:
    src = Path(args.source)
    (BENCH / "reference").mkdir(parents=True, exist_ok=True)
    for v in videos():
        report_path = src / f"{v['name']}.json"
        if not report_path.is_file():
            print(f"{v['name']}: no report in {src}")
            continue
        report = json.loads(report_path.read_text())
        out = BENCH / "reference" / f"{v['name']}.json"
        old = json.loads(out.read_text()) if out.is_file() else {}
        data = {"video": v["video"], "calib": v["calib"], "made_with": report["run"],
                "overrides": report["run"].get("overrides", []), "crossings": crossings_of(report),
                "review": old.get("review", {"removed": [], "added": [], "notes": []})}
        out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        print(f"{v['name']}: {len(data['crossings'])} reference crossings -> {out.relative_to(AI)}")
    return 0


def cmd_run(args) -> int:
    spec = variants()[args.variant]
    out = RUNS / args.variant
    for v in videos():
        if args.only and v["name"] not in args.only:
            continue
        target = out / f"{v['name']}.json"
        if target.is_file() and not args.force:
            continue
        cmd = [sys.executable, str(AI / "scripts" / "evaluate.py"), str(SAMPLES / v["video"]),
               "--calib", str(SAMPLES / "calib" / v["calib"]), "--name", v["name"], "--out", str(out),
               "--snapshots", "0", "--max-event-snapshots", "0", *spec["args"]]
        done = subprocess.run(cmd, cwd=AI, capture_output=True, text=True)
        status = "ok" if target.is_file() else f"FAILED: {done.stderr.strip().splitlines()[-1:]}"
        print(f"{args.variant} {v['name']}: {status}", flush=True)
    return 0


def score_variant(variant: str) -> tuple[dict, dict]:
    per_video = {}
    for v in videos():
        ref = reference_of(v["name"])
        run = RUNS / variant / f"{v['name']}.json"
        if ref is None or not run.is_file():
            continue
        report = json.loads(run.read_text())
        per_video[v["name"]] = {"result": match_crossings(ref, crossings_of(report), WINDOW_S, MAX_PX),
                                "fps": report["pipeline_fps"], "detect_ms": report["timing_ms"]["detect"]["mean"]}
    total = add_up([r["result"] for r in per_video.values()])
    return per_video, total


def cmd_score(args) -> int:
    (BENCH / "results").mkdir(parents=True, exist_ok=True)
    for variant in args.variants:
        per_video, total = score_variant(variant)
        print(f"\n=== {variant}: {variants()[variant]['what']} ({len(per_video)} videos)")
        print(f"{'video':16s} {'kind':10s} {'ref':>4s} {'counted':>8s} {'ok %':>6s} {'dir ok':>7s} {'kind ok':>8s} "
              f"{'missed':>7s} {'extra':>6s}")
        rows = list(per_video.items()) + [("TOTAL", {"result": total})]
        for name, r in rows:
            for kind, k in r["result"].items():
                print(f"{name:16s} {kind:10s} {k['reference']:4d} {k['matched']:8d} {pct(k['matched'], k['reference']):>6s} "
                      f"{pct(k['same_dir'], k['matched']):>7s} {pct(k['same_kind'], k['matched']):>8s} {k['missed']:7d} "
                      f"{k['extra']:6d}")
        print()
        for kind in KINDS:
            if kind in total:
                print("  " + sentence(kind, total[kind]))
        out = {"variant": variant, "what": variants()[variant]["what"], "total": total,
               "sentences": [sentence(k, total[k]) for k in KINDS if k in total],
               "per_video": {n: {"fps": r["fps"], "detect_ms": r["detect_ms"],
                                 "kinds": {k: {key: val for key, val in v.items() if not key.endswith(("pairs", "idx"))}
                                           for k, v in r["result"].items()}} for n, r in per_video.items()}}
        (BENCH / "results" / f"{variant}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    return 0


def cmd_review(args) -> int:
    """For every disagreement (missed, extra, wrong direction) three crops around the crossing: 1 s before, at the
    crossing, 1 s after, with the counting line. One sheet per video, to look at."""
    import cv2
    import numpy as np
    from smartcrossing.geometry import load_calib
    from smartcrossing.config import load_config

    v = next(x for x in videos() if x["name"] == args.name)
    ref = reference_of(v["name"])
    report = json.loads((RUNS / args.variant / f"{v['name']}.json").read_text())
    got = crossings_of(report)
    result = match_crossings(ref, got, WINDOW_S, MAX_PX)
    cases = []
    for kind, k in result.items():
        if args.kind and kind != args.kind:
            continue
        cases += [("MISSED", ref[i]) for i in k["missed_idx"]] + [("EXTRA", got[j]) for j in k["extra_idx"]]
        cases += [("DIR", got[j]) for i, j in k["pairs"] if ref[i]["dir"] != got[j]["dir"]]
    if not cases:
        print("no disagreements")
        return 0
    calib, _ = load_calib(load_config(), SAMPLES / "calib" / v["calib"])
    cap = cv2.VideoCapture(str(SAMPLES / v["video"]))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    tiles = []
    for label, e in sorted(cases, key=lambda c: c[1]["t"]):
        row = []
        for dt in (-1.0, 0.0, 1.0):
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int((e["t"] + dt) * fps)))
            ok, frame = cap.read()
            if not ok:
                frame = np.zeros((240, 240, 3), np.uint8)
            h, w = frame.shape[:2]
            line = calib["lines"][e["line"]]
            p0 = (int(line["start"][0] * w), int(line["start"][1] * h))
            p1 = (int(line["end"][0] * w), int(line["end"][1] * h))
            cv2.line(frame, p0, p1, (0, 255, 255), 2)
            x, y = int(e.get("x") or w / 2), int(e.get("y") or h / 2)
            if dt == 0.0 and e.get("x") is not None:
                cv2.circle(frame, (x, y), 8, (0, 0, 255), 2)
            half = 110
            x0, y0 = min(max(x - half, 0), max(w - 2 * half, 0)), min(max(y - half, 0), max(h - 2 * half, 0))
            crop = cv2.resize(frame[y0:y0 + 2 * half, x0:x0 + 2 * half], (220, 220))
            cv2.putText(crop, f"{dt:+.0f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            row.append(crop)
        strip = np.hstack(row)
        bar = np.zeros((22, strip.shape[1], 3), np.uint8)
        cv2.putText(bar, f"{label} t={e['t']:.1f}s {e['cls']} {e['line']} {e['dir']}", (4, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        tiles.append(np.vstack([bar, strip]))
    REVIEW.mkdir(parents=True, exist_ok=True)
    per_sheet = 8
    for n in range(0, len(tiles), per_sheet):
        sheet = np.vstack(tiles[n:n + per_sheet])
        path = REVIEW / f"{args.variant}_{v['name']}_{n // per_sheet}.jpg"
        cv2.imwrite(str(path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
        print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reference")
    r.add_argument("--from", dest="source", default=str(RUNS / "riferimento"))
    r = sub.add_parser("run")
    r.add_argument("variant")
    r.add_argument("--only", nargs="*")
    r.add_argument("--force", action="store_true")
    r = sub.add_parser("score")
    r.add_argument("variants", nargs="+")
    r = sub.add_parser("review")
    r.add_argument("variant")
    r.add_argument("name")
    r.add_argument("--kind", choices=list(KINDS))
    args = p.parse_args(argv)
    return {"reference": cmd_reference, "run": cmd_run, "score": cmd_score, "review": cmd_review}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
