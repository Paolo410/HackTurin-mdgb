#!/usr/bin/env python3
"""tts-audio-synthesizer: narration lines of timeline.json -> placed English voice track.

Engines
  kokoro      offline neural TTS (default; no key). Voice blends: "am_michael:0.65,am_onyx:0.35"
  edge        Microsoft Edge neural voices (free, needs internet). e.g. en-US-ChristopherNeural
  elevenlabs  needs ELEVENLABS_API_KEY (+ ELEVENLABS_VOICE_ID or --voice)
  openai      needs OPENAI_API_KEY (gpt-4o-mini-tts, voice e.g. onyx)

Outputs (in --out, default build/audio)
  vo/<line>.wav          one processed file per line (48 kHz mono)
  voice.wav              full-length track with every line at its place on the timeline
  ../vo_timeline.json    start/end of every line (used by the mix, the subtitles and Remotion)
  ../subtitles_en.srt    English subtitles of the narration

Usage
  python tools/tts.py                          # whole timeline, engine from timeline.json
  python tools/tts.py --engine edge --voice en-US-ChristopherNeural
  python tools/tts.py --only L05 --dry-run     # print placement only
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUILD, ROOT, SR, ffmpeg, save_json, timeline  # noqa: E402

MODELS = ROOT / "models"
NARRATOR_STYLE = ("Deep, calm, cinematic trailer narrator. Warm and protective, unhurried, "
                  "slight pause after numbers and short sentences. No advertising hype.")


# ----------------------------------------------------------------------------- engines
def synth_kokoro(text: str, voice: str, speed: float, lang: str) -> tuple[np.ndarray, int]:
    from kokoro_onnx import Kokoro
    model = os.environ.get("KOKORO_MODEL", str(MODELS / "kokoro-v1.0.onnx"))
    voices = os.environ.get("KOKORO_VOICES", str(MODELS / "voices-v1.0.bin"))
    if not Path(model).exists():
        raise SystemExit(f"Kokoro model missing: {model} (run setup.sh, it downloads it)")
    k = Kokoro(model, voices)
    if ":" in voice or "," in voice:            # weighted blend "a:0.6,b:0.4"
        style = None
        for part in voice.split(","):
            name, _, w = part.partition(":")
            v = k.get_voice_style(name.strip()) * float(w or 1)
            style = v if style is None else style + v
        voice_arg = style
    else:
        voice_arg = voice
    samples, sr = k.create(text, voice=voice_arg, speed=speed, lang=lang)
    return np.asarray(samples, dtype=np.float32), sr


def _decode(blob: bytes) -> tuple[np.ndarray, int]:
    with tempfile.TemporaryDirectory() as td:
        src, dst = Path(td) / "in.bin", Path(td) / "out.wav"
        src.write_bytes(blob)
        ffmpeg("-i", str(src), "-ac", "1", "-ar", str(SR), str(dst))
        y, sr = sf.read(dst, dtype="float32")
    return y, sr


def synth_edge(text: str, voice: str, speed: float, lang: str) -> tuple[np.ndarray, int]:
    import edge_tts
    rate = f"{round((speed - 1) * 100):+d}%"

    async def go() -> bytes:
        buf = io.BytesIO()
        async for chunk in edge_tts.Communicate(text, voice or "en-US-ChristopherNeural", rate=rate, pitch="-4Hz").stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()

    return _decode(asyncio.run(go()))


def synth_elevenlabs(text: str, voice: str, speed: float, lang: str) -> tuple[np.ndarray, int]:
    import requests
    key = os.environ.get("ELEVENLABS_API_KEY") or sys.exit("ELEVENLABS_API_KEY not set")
    vid = voice or os.environ.get("ELEVENLABS_VOICE_ID") or sys.exit("set --voice or ELEVENLABS_VOICE_ID")
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{vid}",
                      headers={"xi-api-key": key, "accept": "audio/mpeg"},
                      json={"text": text, "model_id": "eleven_multilingual_v2",
                            "voice_settings": {"stability": 0.55, "similarity_boost": 0.8, "style": 0.25, "speed": speed}},
                      timeout=120)
    r.raise_for_status()
    return _decode(r.content)


def synth_openai(text: str, voice: str, speed: float, lang: str) -> tuple[np.ndarray, int]:
    import requests
    key = os.environ.get("OPENAI_API_KEY") or sys.exit("OPENAI_API_KEY not set")
    r = requests.post("https://api.openai.com/v1/audio/speech",
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": "gpt-4o-mini-tts", "voice": voice or "onyx", "input": text,
                            "instructions": NARRATOR_STYLE, "speed": speed, "response_format": "wav"},
                      timeout=120)
    r.raise_for_status()
    return _decode(r.content)


ENGINES = {"kokoro": synth_kokoro, "edge": synth_edge, "elevenlabs": synth_elevenlabs, "openai": synth_openai}


# ----------------------------------------------------------------------------- processing
def resample(y: np.ndarray, sr: int, target: int = SR) -> np.ndarray:
    if sr == target:
        return y
    from scipy.signal import resample_poly
    g = np.gcd(sr, target)
    return resample_poly(y, target // g, sr // g).astype(np.float32)


def trim_silence(y: np.ndarray, thr_db: float = -45.0) -> np.ndarray:
    a = np.abs(y)
    thr = 10 ** (thr_db / 20) * max(a.max(), 1e-6)
    idx = np.where(a > thr)[0]
    if idx.size == 0:
        return y
    pad = int(0.03 * SR)
    return y[max(0, idx[0] - pad): idx[-1] + pad]


def room(y: np.ndarray, wet: float = 0.09, rt60: float = 0.7, predelay: float = 0.018, seed: int = 7) -> np.ndarray:
    """Small, dark plate: exponentially decaying filtered noise convolved with the dry voice."""
    from scipy.signal import butter, fftconvolve, lfilter
    rng = np.random.default_rng(seed)
    n = int(rt60 * SR)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-6.9 * t / rt60)
    b, a = butter(2, 4500 / (SR / 2), "low")
    ir = lfilter(b, a, ir)
    ir = np.concatenate([np.zeros(int(predelay * SR)), ir])
    ir /= np.sqrt(np.sum(ir ** 2)) + 1e-9
    n_out = len(y) + len(ir)
    w = np.zeros(n_out)
    conv = fftconvolve(y, ir)
    w[: len(conv)] = conv[:n_out]
    out = np.concatenate([y, np.zeros(len(ir))]) * (1 - wet) + w * wet * 1.4
    return out.astype(np.float32)


def voice_chain(y: np.ndarray, deepen_semitones: float) -> np.ndarray:
    """EQ + compression (+ optional slight deepening) with ffmpeg, then the room."""
    with tempfile.TemporaryDirectory() as td:
        a, b = Path(td) / "a.wav", Path(td) / "b.wav"
        sf.write(a, y, SR)
        f = 2 ** (-deepen_semitones / 12)
        chain = []
        if deepen_semitones:
            chain += [f"asetrate={SR * f:.0f}", f"aresample={SR}", f"atempo={1 / f:.5f}"]
        chain += ["highpass=f=65", "equalizer=f=115:t=q:w=0.9:g=2.5", "equalizer=f=320:t=q:w=1.2:g=-1.5",
                  "equalizer=f=3300:t=q:w=1.3:g=2.0", "deesser=i=0.35",
                  "acompressor=threshold=-21dB:ratio=3:attack=6:release=140:makeup=3.5"]
        ffmpeg("-i", str(a), "-af", ",".join(chain), "-ar", str(SR), "-ac", "1", str(b))
        out, _ = sf.read(b, dtype="float32")
    out = room(out)
    peak = np.abs(out).max() or 1.0
    return (out / peak * 0.89).astype(np.float32)


# ----------------------------------------------------------------------------- placement
def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(entries: list[dict], path: Path) -> None:
    lines = []
    for i, e in enumerate(entries, 1):
        lines += [str(i), f"{srt_time(e['start'])} --> {srt_time(e['end'])}", e["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--timeline", default=str(ROOT / "timeline.json"))
    ap.add_argument("--out", default=str(BUILD / "audio"))
    ap.add_argument("--engine", choices=sorted(ENGINES))
    ap.add_argument("--voice")
    ap.add_argument("--speed", type=float)
    ap.add_argument("--deepen", type=float, default=0.5, help="semitones of extra depth (0 = off)")
    ap.add_argument("--only", nargs="*", help="line ids to (re)generate")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tl = timeline(args.timeline)
    vc = tl.get("voice", {})
    engine = args.engine or vc.get("engine", "kokoro")
    voice = args.voice or vc.get("voice", "am_michael")
    speed = args.speed or float(vc.get("speed", 0.9))
    lang = vc.get("lang", "en-us")
    lead, gap = float(vc.get("lead", 0.35)), float(vc.get("gap", 0.3))
    total = float(tl["meta"]["duration"])
    out = Path(args.out)
    (out / "vo").mkdir(parents=True, exist_ok=True)
    synth = ENGINES[engine]

    track = np.zeros(int(total * SR) + SR, dtype=np.float32)
    placed, prev_end = [], 0.0
    for sc in tl["scenes"]:
        vo = sc.get("vo")
        if not vo:
            continue
        lid, text = vo["id"], vo["text"]
        wav = out / "vo" / f"{lid}.wav"
        sp = float(vo.get("speed", speed))
        sig = out / "vo" / f"{lid}.sig"
        key = f"{engine}|{voice}|{sp}|{args.deepen}|{text}"
        stale = not wav.exists() or not sig.exists() or sig.read_text(encoding="utf-8") != key
        if (args.only is None and stale) or (args.only and lid in args.only):
            if not args.dry_run:
                y, sr = synth(text, voice, sp, lang)
                y = trim_silence(resample(y, sr))
                y = voice_chain(y, args.deepen)
                sf.write(wav, y, SR)
                sig.write_text(key, encoding="utf-8")
        y, _ = sf.read(wav, dtype="float32") if wav.exists() else (np.zeros(SR), SR)
        start = float(vo.get("at", sc["start"] + lead))
        start = max(start, prev_end + gap)
        end = start + len(y) / SR
        scene_end = sc["start"] + sc["dur"]
        flag = "  <-- spills into next scene" if end > scene_end + 0.6 else ""
        print(f"{lid}  {start:7.2f} → {end:7.2f}  ({len(y) / SR:4.1f}s, scene {sc['id']} ends {scene_end}){flag}")
        i = int(start * SR)
        track[i:i + len(y)] += y[: max(0, len(track) - i)]
        placed.append({"id": lid, "scene": sc["id"], "start": round(start, 3), "end": round(end, 3), "text": text})
        prev_end = end

    if args.dry_run:
        return
    sf.write(out / "voice.wav", track[: int(total * SR)], SR)
    save_json({"engine": engine, "voice": voice, "speed": speed, "lines": placed}, BUILD / "vo_timeline.json")
    write_srt(placed, BUILD / "subtitles_en.srt")
    print(f"voice track → {out / 'voice.wav'}  ({len(placed)} lines, engine={engine}, voice={voice})")


if __name__ == "__main__":
    main()
