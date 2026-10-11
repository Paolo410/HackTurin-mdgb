#!/usr/bin/env python3
"""One command for the whole trailer: python tools/build.py [steps...]

Steps (default: all, in this order)
  media   conform the clips used by timeline.json      (tools/prep_media.py)
  beats   beat grid of the music + snap cuts to beats   (tools/beats.py)
  voice   English narration with the configured TTS     (tools/tts.py)
  mix     music edit + ducking + sfx + loudness         (tools/mix.py)
  detect  real detections for the HUD scenes            (tools/detect.py, team's YOLOX)
  data    timeline for Remotion -> build/public/data/timeline.json
  render  Remotion render of the picture                (motion/)
  mux     picture + mix -> output/<name>.mp4 (+ .srt)

Examples
  python tools/build.py                      # everything
  python tools/build.py data render mux      # after editing on-screen text or overlays
  python tools/build.py voice mix mux        # after changing the narration (picture unchanged)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUILD, OUTPUT, PUBLIC, ROOT, ffmpeg, load_json, media, probe, save_json, timeline  # noqa: E402

PY = sys.executable
T = ROOT / "tools"
STEPS = ["media", "beats", "voice", "mix", "detect", "data", "render", "mux"]
SYNCED = BUILD / "timeline.synced.json"


def sh(cmd: list[str], cwd: Path | None = None) -> None:
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def step_media() -> None:
    sh([PY, T / "prep_media.py"])


def step_beats() -> None:
    sh([PY, T / "beats.py"])


def step_voice() -> None:
    sh([PY, T / "tts.py", "--timeline", SYNCED if SYNCED.exists() else ROOT / "timeline.json"])


def step_mix() -> None:
    sh([PY, T / "mix.py"])


def step_detect() -> None:
    tl = timeline()
    for sc in tl["scenes"]:
        for shot in sc["shots"]:
            clip = shot.get("detections")
            if not clip or (PUBLIC / "data" / f"detections_{clip}.json").exists():
                continue
            opts = shot.get("detect", {})
            cmd = [PY, T / "detect.py", clip, "--model", opts.get("model", "yolox_nano"),
                   "--size", str(opts.get("size", 416)), "--conf", str(opts.get("conf", 0.3))]
            if opts.get("line"):
                cmd += ["--line", opts["line"]]
            if opts.get("tiles"):
                cmd += ["--tiles", opts["tiles"]]
            if opts.get("movingOnly"):
                cmd += ["--moving-only"]
            sh(cmd)


def step_data() -> None:
    if not SYNCED.exists() or SYNCED.stat().st_mtime < (ROOT / "timeline.json").stat().st_mtime:
        step_beats()
    tl = load_json(SYNCED)
    md = media()
    for sc in tl["scenes"]:
        for i, shot in enumerate(sc["shots"]):
            shot["src"] = f"plates/{sc['id']}_{i}.{'jpg' if 'freeze' in shot else 'mp4'}"
    vo_path = BUILD / "vo_timeline.json"
    tl["vo"] = load_json(vo_path)["lines"] if vo_path.exists() else []
    used = sorted({s["media"] for sc in tl["scenes"] for s in sc["shots"]})
    tl["credits"] = [f"{md['clips'][m]['title']} — {md['clips'][m]['author']} (Pexels {md['clips'][m]['source_id']})" for m in used]
    save_json(tl, PUBLIC / "data" / "timeline.json")
    print(f"  data → {PUBLIC / 'data' / 'timeline.json'} ({len(tl['scenes'])} scenes, {len(tl['vo'])} narration lines)")


def step_render() -> None:
    """Remotion render of the picture. RENDER_CHUNKS=4 renders 4 parts (re-render one part by deleting it)."""
    motion = ROOT / "motion"
    if not (motion / "node_modules").exists():
        sh(["npm", "install", "--no-audit", "--no-fund"], cwd=motion)
    tl = load_json(PUBLIC / "data" / "timeline.json")
    total = int(round(tl["meta"]["duration"] * tl["meta"]["fps"]))
    n = max(1, int(os.environ.get("RENDER_CHUNKS", "1")))
    parts = []
    for k in range(n):
        a, b = k * total // n, (k + 1) * total // n - 1
        part = BUILD / (f"video_part{k + 1}.mp4" if n > 1 else "video.mp4")
        parts.append(part)
        if n > 1 and part.exists() and part.stat().st_mtime > (PUBLIC / "data" / "timeline.json").stat().st_mtime:
            print(f"  part {k + 1}/{n} up to date")
            continue
        cmd = ["npx", "remotion", "render", "src/index.ts", "Trailer", str(part), f"--frames={a}-{b}",
               f"--public-dir={PUBLIC}", "--codec=h264", "--crf=15", "--muted",
               "--concurrency=" + os.environ.get("RENDER_CONCURRENCY", "2")]
        if os.environ.get("REMOTION_BROWSER"):
            cmd += [f"--browser-executable={os.environ['REMOTION_BROWSER']}", "--gl=swangle"]
        sh(cmd, cwd=motion)
    if n > 1:
        lst = BUILD / "parts.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
        ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(BUILD / "video.mp4"))


def step_mux() -> None:
    tl = timeline()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    name = os.environ.get("TRAILER_NAME", "MDGB_trailer_PoC_v1")
    out = OUTPUT / f"{name}.mp4"
    # finishing in ffmpeg: soft vignette + fine animated film grain, then the delivery encode
    ffmpeg("-i", str(BUILD / "video.mp4"), "-i", str(BUILD / "audio" / "mix.wav"), "-map", "0:v:0", "-map", "1:a:0",
           "-vf", "vignette=angle=PI/6:mode=forward,noise=c0s=4:c0f=t+u,format=yuv420p",
           "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high", "-tune", "film",
           "-c:a", "aac", "-b:a", "320k", "-t", str(tl["meta"]["duration"]), "-movflags", "+faststart", str(out))
    if (BUILD / "subtitles_en.srt").exists():
        shutil.copy(BUILD / "subtitles_en.srt", OUTPUT / f"{name}.en.srt")
    info = probe(out)
    print(f"  ✓ {out}  {info['duration']:.2f}s  {out.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    steps = sys.argv[1:] or STEPS
    if steps == ["all"]:
        steps = STEPS
    for s in steps:
        if s not in STEPS:
            sys.exit(f"unknown step {s}; choose from {STEPS}")
    for s in STEPS:
        if s in steps:
            t0 = time.time()
            print(f"▶ {s}")
            globals()[f"step_{s}"]()
            print(f"  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
