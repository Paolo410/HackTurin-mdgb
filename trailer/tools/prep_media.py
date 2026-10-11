#!/usr/bin/env python3
"""ffmpeg-core-processor, step 1: conform every clip, then render one graded "plate" per shot.

For each media id referenced by a shot:
  assets/... (any size, fps, codec)  ->  build/public/media/<id>.mp4
  1920x1080 (scale to cover + centre crop), 30 fps CFR, yuv420p H.264, GOP 1 s, no audio,
  trimmed to the furthest point the timeline uses (+0.5 s).
Then, per shot of every scene: build/public/plates/<scene>_<n>.mp4 (or .jpg for freeze-frames) =
the exact in/out of the shot, speed, colour grade (night / dusk / dusk2night / dawn / neutral /
neutralDark), tilt-shift and privacy blur baked in with ffmpeg, so Remotion only composites graphics.

Usage
  python tools/prep_media.py              # only clips that changed
  python tools/prep_media.py --force      # re-encode everything
  python tools/prep_media.py --ingest SRC ID   # copy a new/own clip into assets/b-roll as ID
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PUBLIC, ROOT, ffmpeg, load_json, media, probe, save_json, timeline  # noqa: E402

W, H, FPS = 1920, 1080, 30


def needed_spans(tl: dict) -> dict[str, float]:
    """media id -> seconds of source needed from 0."""
    need: dict[str, float] = {}
    for sc in tl["scenes"]:
        for sh in sc["shots"]:
            if "freeze" in sh:
                end = sh["freeze"] + 0.2
            else:
                end = sh.get("in", 0) + sh["dur"] * sh.get("speed", 1.0)
            need[sh["media"]] = max(need.get(sh["media"], 0), end + 0.5)
    return need


def conform(src: Path, dst: Path, seconds: float) -> None:
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={W}:{H},fps={FPS},setsar=1,format=yuv420p")
    ffmpeg("-i", str(src), "-t", f"{seconds:.3f}", "-an", "-vf", vf,
           "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-g", str(FPS), "-bf", "2",
           "-movflags", "+faststart", str(dst))


# ------------------------------------------------------------------ grades (same names as motion/src/types.ts)
LOOKS = {   # brightness (x), contrast, saturation, hue (deg), soft-light tint top/bottom, tint opacity
    "night":       (0.60, 1.20, 0.68, -6, "0B2236", "0E1B2A", 0.62),
    "dusk":        (0.84, 1.12, 0.90, 0, "22324F", "7A4A1E", 0.42),
    "dawn":        (0.90, 1.08, 0.86, 0, "1C3247", "B8792C", 0.34),
    "neutral":     (0.90, 1.10, 0.88, 0, "10202B", "2A2016", 0.30),
    "neutralDark": (0.66, 1.16, 0.80, 0, "0B1C26", "141010", 0.46),
}


def grade_graph(src: str, out: str, grade: str, dur: float, sat_boost: float = 1.0) -> str:
    """filtergraph fragment: [src] -> graded [out] (planar RGB soft-light tint)"""
    b, c, s, h, top, bot, a = LOOKS[grade]
    g = f"{out}_g"
    return (f"[{src}]colorchannelmixer=rr={b}:gg={b}:bb={b},eq=contrast={c}:saturation={s * sat_boost:.3f},hue=h={h},format=gbrp[{out}_v];"
            f"gradients=s={W}x{H}:c0=0x{top}:c1=0x{bot}:x0={W // 2}:y0=0:x1={W // 2}:y1={H}:n=2:d={dur:.3f}:r={FPS},format=gbrp[{g}];"
            f"[{out}_v][{g}]blend=all_mode=softlight:all_opacity={a},format=yuv420p[{out}]")


def plate_graph(shot: dict, dur: float) -> str:
    grade = shot.get("grade", "neutral")
    sat = 1.35 if shot.get("tiltShift") else 1.0
    if grade == "dusk2night":
        g = (f"[0:v]split[d0][n0];{grade_graph('d0', 'd1', 'dusk', dur)};{grade_graph('n0', 'n1', 'night', dur)};"
             f"[n1]colorchannelmixer=rr=0.9:gg=0.9:bb=0.9[n2];[d1][n2]xfade=transition=fade:duration={dur * 0.75:.3f}:offset={dur * 0.15:.3f}[g]")
    else:
        g = grade_graph("0:v", "g", grade, dur, sat)
    last = "g"
    if shot.get("tiltShift"):        # miniature look: blurred copy kept only in the top and bottom bands
        g += (f";[{last}]split[ts0][ts1];[ts1]boxblur=12:2[tsb];[1:v]format=gray,scale={W}:{H}[tsm];"
              f"[tsb][tsm]alphamerge[tsa];[ts0][tsa]overlay=format=auto[ts]")
        last = "ts"
    if shot.get("blur"):             # privacy blur: crossfade sharp -> blurred
        t0, t1, px = shot["blur"]
        g += f";[{last}]split[pb0][pb1];[pb1]boxblur={max(2, int(px / 2))}:3[pbb];[pb0][pbb]xfade=transition=fade:duration={t1 - t0:.3f}:offset={t0:.3f}[pb]"
        last = "pb"
    return g + f";[{last}]format=yuv420p[out]"


def tilt_mask(path: Path) -> None:
    import numpy as np
    from PIL import Image
    y = np.linspace(0, 1, H)[:, None]
    m = np.clip(np.maximum((0.38 - y) / 0.38, (y - 0.64) / 0.36), 0, 1) ** 0.8
    Image.fromarray((np.repeat(m, W, axis=1) * 255).astype("uint8"), "L").save(path)


def make_plates(tl: dict, force: bool) -> None:
    pdir = PUBLIC / "plates"
    pdir.mkdir(parents=True, exist_ok=True)
    mask = PUBLIC / "fx" / "tiltmask.png"
    mask.parent.mkdir(parents=True, exist_ok=True)
    if not mask.exists():
        tilt_mask(mask)
    stamp_file = pdir / ".stamps.json"
    stamps = load_json(stamp_file) if stamp_file.exists() else {}
    for sc in tl["scenes"]:
        for i, sh in enumerate(sc["shots"]):
            name = f"{sc['id']}_{i}"
            src = PUBLIC / "media" / f"{sh['media']}.mp4"
            key = hashlib.md5((json.dumps(sh, sort_keys=True) + str(src.stat().st_mtime) + "p3").encode()).hexdigest()
            out = pdir / (f"{name}.jpg" if "freeze" in sh else f"{name}.mp4")
            if out.exists() and stamps.get(name) == key and not force:
                continue
            if "freeze" in sh:
                ffmpeg("-ss", f"{sh['freeze']:.3f}", "-i", str(src), "-filter_complex", plate_graph(sh, 0.04).replace("[out]", "[o]"),
                       "-map", "[o]", "-frames:v", "1", "-q:v", "2", str(out))
            else:
                speed = float(sh.get("speed", 1.0))
                dur = float(sh["dur"]) + 0.1
                inputs = ["-ss", f"{sh.get('in', 0):.3f}", "-t", f"{dur * speed + 0.05:.3f}", "-i", str(src)]
                if sh.get("tiltShift"):
                    inputs += ["-loop", "1", "-i", str(mask)]
                pre = f"[0:v]setpts=PTS/{speed},fps={FPS},trim=duration={dur:.3f},setpts=PTS-STARTPTS[sp];" if speed != 1 else ""
                graph = plate_graph(sh, dur)
                if pre:
                    graph = pre + graph.replace("[0:v]", "[sp]", 1)
                ffmpeg(*inputs, "-filter_complex", graph, "-map", "[out]", "-t", f"{dur:.3f}", "-an",
                       "-c:v", "libx264", "-preset", "fast", "-crf", "16", "-g", str(FPS), "-movflags", "+faststart", str(out))
            stamps[name] = key
            print(f"plate {name:6s} {sh['media']:26s} {sh.get('grade', 'neutral'):11s} {'freeze' if 'freeze' in sh else str(sh['dur']) + 's'}")
    save_json(stamps, stamp_file)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ingest", nargs=2, metavar=("SRC", "ID"), help="copy a clip into assets/b-roll/ID.mp4")
    args = ap.parse_args()

    if args.ingest:
        src, cid = Path(args.ingest[0]), args.ingest[1]
        dst = ROOT / "assets" / "b-roll" / f"{cid}.mp4"
        dst.parent.mkdir(parents=True, exist_ok=True)
        ffmpeg("-i", str(src), "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "15",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst))
        print(f"ingested {src} -> {dst}  {probe(dst)['duration']:.2f}s")
        return

    tl, md = timeline(), media()
    out_dir = PUBLIC / "media"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp_file = out_dir / ".stamps.json"
    stamps = load_json(stamp_file) if stamp_file.exists() else {}

    for mid, secs in sorted(needed_spans(tl).items()):
        entry = md["clips"].get(mid)
        if not entry:
            sys.exit(f"{mid}: not in media.json")
        src = ROOT / entry["file"]
        if not src.exists():
            sys.exit(f"{mid}: missing {entry['file']} (run tools/fetch_broll.py or fix media.json)")
        dst = out_dir / f"{mid}.mp4"
        key = hashlib.md5(f"{src.stat().st_size}|{src.stat().st_mtime}|{secs:.2f}|v2".encode()).hexdigest()
        if dst.exists() and stamps.get(mid) == key and not args.force:
            continue
        avail = probe(src)["duration"] or secs
        conform(src, dst, min(secs, avail))
        stamps[mid] = key
        print(f"{mid:26s} {min(secs, avail):5.1f}s  <- {entry['file']}")

    for sc in tl["scenes"]:                       # stills for freeze-frames
        for sh in sc["shots"]:
            if "freeze" in sh:
                jpg = out_dir / f"{sh['media']}_freeze_{sh['freeze']:.2f}.jpg"
                if not jpg.exists() or args.force:
                    ffmpeg("-ss", f"{sh['freeze']:.3f}", "-i", str(out_dir / f"{sh['media']}.mp4"),
                           "-frames:v", "1", "-q:v", "2", str(jpg))
    save_json(stamps, stamp_file)
    print("media conformed in", out_dir)
    sync = ROOT / "build" / "timeline.synced.json"
    make_plates(load_json(sync) if sync.exists() else tl, args.force)
    print("plates rendered in", PUBLIC / "plates")


if __name__ == "__main__":
    main()
