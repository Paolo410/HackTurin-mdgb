#!/usr/bin/env python3
"""audio-ducking-and-sync (mix half): music edit + narration + sound design -> mastered stereo mix.

  music   : timeline.music.segments (src_in/src_out placed "at" a video time, 60 ms crossfades)
  ducking : the music drops by music.duck_db wherever the narrator speaks (look-ahead 120 ms,
            attack 60 ms, release 450 ms) — computed from the voice envelope, sample accurate
  sfx     : timeline.sfx cues (synth kit in tools/sfx.py); "after": "<line id>" pins a cue to a line end
  master  : two-pass loudnorm to -14 LUFS integrated, -1 dBTP

Outputs: build/audio/mix.wav (+ music_ducked.wav, sfx.wav, voice_st.wav stems)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUILD, ROOT, SR, ffmpeg, load_json, media, run, timeline  # noqa: E402
import sfx as kit  # noqa: E402


def db(x: float) -> float:
    return 10 ** (x / 20)


def decode(path: Path) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "a.wav"
        ffmpeg("-i", str(path), "-ac", "2", "-ar", str(SR), str(out))
        y, _ = sf.read(out, dtype="float32", always_2d=True)
    return y


def music_track(tl: dict, total: int) -> np.ndarray:
    mus = tl["music"]
    y = decode(ROOT / media()["audio"][mus["media"]]["file"])
    out = np.zeros((total, 2), np.float32)
    xf = int(0.06 * SR)
    for s in mus["segments"]:
        a, b = int(s["src_in"] * SR), min(len(y), int(s["src_out"] * SR))
        seg = y[a:b].copy()
        ramp = np.linspace(0, 1, xf)[:, None]
        if s["src_in"] > 0:
            seg[:xf] *= ramp
        seg[-xf:] *= ramp[::-1]
        at = int(s["at"] * SR)
        n = max(0, min(len(seg), total - at))
        out[at:at + n] += seg[:n]
    out *= db(mus.get("gain_db", 0))
    if mus.get("fade_out"):
        f0, f1 = (int(v * SR) for v in mus["fade_out"])
        f1 = min(f1, total)
        out[f0:f1] *= np.linspace(1, 0, f1 - f0)[:, None]
        out[f1:] = 0
    return out


def duck_curve(voice: np.ndarray, duck_db: float, thr_db: float = -42, look=0.12, att=0.06, rel=0.45) -> np.ndarray:
    hop = int(0.01 * SR)
    frames = len(voice) // hop
    rms = np.sqrt(np.mean(voice[: frames * hop].reshape(frames, hop) ** 2, axis=1) + 1e-12)
    active = (20 * np.log10(rms) > thr_db).astype(float)
    shift = int(look / 0.01)
    active = np.concatenate([active[shift:], np.zeros(shift)])          # look-ahead
    g = np.zeros(frames)
    a_c, r_c = np.exp(-0.01 / att), np.exp(-0.01 / rel)
    cur = 0.0
    for i, v in enumerate(active):
        c = a_c if v > cur else r_c
        cur = c * cur + (1 - c) * v
        g[i] = cur
    gain = db(duck_db) ** g                                               # 1 -> duck_db
    return np.repeat(gain, hop)[: len(voice)].astype(np.float32)


def sfx_track(tl: dict, total: int, vo: dict) -> np.ndarray:
    out = np.zeros(total, np.float32)
    ends = {l["id"]: l["end"] for l in vo.get("lines", [])}

    def put(sig: np.ndarray, t: float, g: float) -> None:
        i = int(t * SR)
        if i >= total or i < 0:
            return
        n = min(len(sig), total - i)
        out[i:i + n] += sig[:n] * g

    for c in tl.get("sfx", []):
        g = db(c.get("gain_db", -12))
        fn = kit.KIT[c["kind"]]
        if "from" in c:
            sig = fn()
            t = c["from"]
            while t < c["to"]:
                put(sig, t, g)
                t += c["every"]
            continue
        times = c.get("at", [])
        if "after" in c:
            times = [ends.get(c["after"], 0) + c.get("offset", 0)]
        times = times if isinstance(times, list) else [times]
        for t in times:
            sig = fn(c["dur"]) if "dur" in c else fn()
            put(sig, t, g)
    return out


def loudnorm(src: Path, dst: Path, target=-14.0, tp=-1.0) -> dict:
    p = run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm=I={target}:TP={tp}:LRA=11:print_format=json", "-f", "null", "-"])
    js = p.stderr[p.stderr.rfind("{"): p.stderr.rfind("}") + 1]
    m = json.loads(js)
    af = (f"loudnorm=I={target}:TP={tp}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    ffmpeg("-i", str(src), "-af", af, "-ar", str(SR), "-c:a", "pcm_s24le", str(dst))
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timeline", default=str(BUILD / "timeline.synced.json"))
    ap.add_argument("--voice-db", type=float, default=0.0)
    args = ap.parse_args()
    tl = timeline(args.timeline if Path(args.timeline).exists() else None)
    total = int(tl["meta"]["duration"] * SR)
    adir = BUILD / "audio"
    voice, _ = sf.read(adir / "voice.wav", dtype="float32")
    voice = np.pad(voice, (0, max(0, total - len(voice))))[:total]
    vo = load_json(BUILD / "vo_timeline.json") if (BUILD / "vo_timeline.json").exists() else {}

    music = music_track(tl, total)
    gain = duck_curve(voice, tl["music"].get("duck_db", -8))
    music_d = music * gain[:, None]
    fx = sfx_track(tl, total, vo)
    v_st = np.repeat((voice * db(args.voice_db))[:, None], 2, axis=1)
    mix = music_d + v_st + fx[:, None] * np.array([[1.0, 1.0]], np.float32)
    peak = np.abs(mix).max()
    if peak > 0.98:
        mix *= 0.98 / peak
    sf.write(adir / "music_ducked.wav", music_d, SR)
    sf.write(adir / "sfx.wav", fx, SR)
    sf.write(adir / "voice_st.wav", v_st, SR)
    sf.write(adir / "premix.wav", mix, SR, subtype="FLOAT")
    m = loudnorm(adir / "premix.wav", adir / "mix.wav")
    duck_pct = float((gain < db(-3)).mean() * 100)
    print(f"mix → {adir / 'mix.wav'}  (in: {m['input_i']} LUFS → -14 LUFS, music ducked {duck_pct:.0f}% of the time)")


if __name__ == "__main__":
    main()
