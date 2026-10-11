"""Shared helpers for the trailer pipeline: paths, JSON, ffmpeg/ffprobe wrappers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # trailer/
BUILD = ROOT / "build"                                 # intermediates (git-ignored)
PUBLIC = BUILD / "public"                              # served to Remotion (--public-dir)
OUTPUT = ROOT / "output"                               # final renders (git-ignored)
SR = 48000                                             # audio sample rate for every stem


def load_json(path: os.PathLike | str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(obj, path: os.PathLike | str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def timeline(path: os.PathLike | str | None = None) -> dict:
    return load_json(path or ROOT / "timeline.json")


def media(path: os.PathLike | str | None = None) -> dict:
    return load_json(path or ROOT / "media.json")


def ffmpeg_bin() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise SystemExit("ffmpeg not found: install it (macOS: brew install ffmpeg)")
    return exe


def run(cmd: list[str], quiet: bool = True) -> subprocess.CompletedProcess:
    """Run a command, raise with its stderr tail on failure."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(cmd[:6])} …\n{tail}")
    if not quiet and p.stdout:
        print(p.stdout)
    return p


def ffmpeg(*args: str) -> None:
    run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args])


def probe(path: os.PathLike | str) -> dict:
    """Duration, size, fps and codecs of a media file (ffprobe JSON, summarised)."""
    p = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(p.stdout)
    out = {"duration": float(info["format"].get("duration", 0) or 0), "streams": []}
    for s in info.get("streams", []):
        d = {"type": s.get("codec_type"), "codec": s.get("codec_name")}
        if s.get("codec_type") == "video":
            num, den = (s.get("r_frame_rate") or "0/1").split("/")
            d.update(width=s.get("width"), height=s.get("height"), fps=round(float(num) / float(den or 1), 3))
        if s.get("codec_type") == "audio":
            d.update(sample_rate=int(s.get("sample_rate", 0)), channels=s.get("channels"))
        out["streams"].append(d)
    return out


def rel(p: os.PathLike | str) -> str:
    """Path relative to trailer/ (for logs and JSON)."""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)
