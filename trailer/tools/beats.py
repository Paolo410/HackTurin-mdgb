#!/usr/bin/env python3
"""audio-ducking-and-sync (sync half): beat grid of the music and cut snapping.

  analyze  : librosa beat tracking of the music file -> build/beats.json (tempo, beats in track time)
  grid     : beats placed on the video timeline through the music segments of timeline.json
  snap     : moves scene boundaries inside [--from, --to] onto the nearest beat (max --tol seconds),
             the last shot of each scene absorbs the change. Writes build/timeline.synced.json.

Usage
  python tools/beats.py              # analyze + snap with defaults, prints the cut/beat report
  python tools/beats.py --bpm 120 --offset 0.0   # no librosa: regular grid from a known tempo
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUILD, ROOT, load_json, media, save_json, timeline  # noqa: E402


def analyze(path: Path, bpm: float | None = None, offset: float = 0.0, dur: float | None = None) -> dict:
    if bpm:
        dur = dur or 600.0
        beats = np.arange(offset, dur, 60.0 / bpm)
        return {"tempo": bpm, "beats": [round(float(b), 4) for b in beats], "method": "fixed"}
    import librosa
    y, sr = librosa.load(str(path), sr=22050, mono=True)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, hop_length=256, units="time")
    onset = librosa.onset.onset_strength(y=y, sr=sr, hop_length=256)
    hits = librosa.onset.onset_detect(onset_envelope=onset, sr=sr, hop_length=256, units="time")
    strength = onset[librosa.time_to_frames(hits, sr=sr, hop_length=256)]
    top = hits[strength >= np.percentile(strength, 90)] if len(hits) else hits
    return {"tempo": round(float(np.atleast_1d(tempo)[0]), 2), "beats": [round(float(b), 4) for b in beats],
            "accents": [round(float(h), 3) for h in top], "duration": round(len(y) / sr, 3), "method": "librosa"}


def grid(info: dict, segments: list[dict]) -> np.ndarray:
    """beat times on the video timeline"""
    out = []
    for s in segments:
        b = np.array(info["beats"])
        b = b[(b >= s["src_in"]) & (b < s["src_out"])]
        out.extend(b - s["src_in"] + s["at"])
    return np.array(sorted(out))


def snap(tl: dict, beats: np.ndarray, lo: float, hi: float, tol: float) -> tuple[dict, list[str]]:
    tl = copy.deepcopy(tl)
    report = []
    sc = tl["scenes"]
    for k in range(1, len(sc)):
        b0 = sc[k]["start"]
        if not (lo <= b0 <= hi) or len(beats) == 0:
            continue
        nb = float(beats[np.argmin(np.abs(beats - b0))])
        if abs(nb - b0) > tol:
            continue
        delta = round(nb - b0, 3)
        if delta == 0:
            continue
        prev = sc[k - 1]
        prev["dur"] = round(prev["dur"] + delta, 3)
        prev["shots"][-1]["dur"] = round(prev["shots"][-1]["dur"] + delta, 3)
        sc[k]["start"] = round(nb, 3)
        sc[k]["dur"] = round(sc[k]["dur"] - delta, 3)
        sc[k]["shots"][-1]["dur"] = round(sc[k]["shots"][-1]["dur"] - delta, 3)
        report.append(f"{sc[k]['id']}: cut {b0:.2f}s -> {nb:.3f}s (beat, {delta:+.3f}s)")
    return tl, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bpm", type=float)
    ap.add_argument("--offset", type=float, default=0.0)
    ap.add_argument("--from", dest="lo", type=float, default=31.0, help="snap cuts after this time")
    ap.add_argument("--to", dest="hi", type=float, default=101.0, help="snap cuts before this time")
    ap.add_argument("--tol", type=float, default=0.3)
    args = ap.parse_args()

    tl, md = timeline(), media()
    mus = tl["music"]
    path = ROOT / md["audio"][mus["media"]]["file"]
    cache = BUILD / "beats.json"
    info = load_json(cache) if cache.exists() and not args.bpm and load_json(cache).get("file") == str(path) else None
    if info is None:
        info = analyze(path, args.bpm, args.offset)
        info["file"] = str(path)
        save_json(info, cache)
    vb = grid(info, mus["segments"])
    synced, report = snap(tl, vb, args.lo, args.hi, args.tol)
    synced["beats"] = {"tempo": info["tempo"], "video": [round(float(b), 3) for b in vb]}
    save_json(synced, BUILD / "timeline.synced.json")
    print(f"tempo {info['tempo']} BPM, {len(vb)} beats on the timeline")
    print("\n".join(report) if report else "no cut moved")


if __name__ == "__main__":
    main()
