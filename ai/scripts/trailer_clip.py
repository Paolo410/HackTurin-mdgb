"""Renders a clip of what the camera sees, for the trailer: a recorded video with the boxes of the vision on it.

Development tool. The vision never saves frames; this script does, and only in ai/samples/trailer/ (ignored by
git). Only what the vision recognises is drawn: no status box at the top and no banner at the bottom, which are
for who debugs, not for who watches.

Usage, from ai/ (needs ffmpeg on the PATH):
    python scripts/trailer_clip.py samples/Torino_2.mp4 --calib samples/calib/torino_2.json
    python scripts/trailer_clip.py samples/Torino_2.mp4 --calib samples/calib/torino_2.json --wide --wide-top 0.85
    python scripts/trailer_clip.py samples/Torino_2.mp4 --calib samples/calib/torino_2.json --input 640 --whole-frame

What is drawn: one box per valid track in the colour of its kind, with what the vision knows about it (kind,
speed, slow / child / aid), and the outline of the stripes and of the waiting zones of the calibration.
The detector works on the frames of the video as they are. The drawing is made on the frame enlarged to the size
of the clip, so lines and text stay sharp. Default: the whole frame, 1080 pixels wide. --wide: a 16:9 band of the
frame at 1920x1080 (--wide-top says where: 0 = top of the frame, 1 = bottom).

Default: the detector as in config.yaml (320 px, the size the board runs) on the part of the frame the calibration
asks for. --input 416 or 640 gives the same model more pixels: it finds more small and far road users, at a speed
the board does not reach. --whole-frame looks at the whole frame, not only at that part. Say which one was used
when the clip is shown: 320 is what the board sees, the others what a faster node would see.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))

from smartcrossing.config import load_config  # noqa: E402
from smartcrossing.geometry import load_calib  # noqa: E402
from smartcrossing.overlay import KMH, ROLE_GROUP  # noqa: E402
from smartcrossing.pipeline import Pipeline  # noqa: E402
from smartcrossing.sources import FrameSource  # noqa: E402

DEFAULT_OUT = AI_DIR / "samples" / "trailer"    # ai/samples/ is ignored by git
TALL_WIDTH = 1080                               # width of the clip that keeps the whole frame
WIDE_SIZE = (1920, 1080)                        # size of the 16:9 clip
CRF = 15                                        # quality of the H.264 file (lower = better, 15 is near lossless)
FONT_PX = 30                                    # height of the text of the labels, on a clip 1080 wide
FONT_MAX_GROWTH = 1.3                           # on a wider clip the text grows at most this much: labels overlap less
LABEL_PAD = (12, 6)                             # space around the text of a label, x and y
LABEL_INK = (22, 26, 29)                        # colour of the text, RGB: the asphalt of the brand
BOX_ALPHA = 0.45                                # how solid the thin outline of a box is
ZONE_ALPHA = 0.35                               # ... and the outline of the zones
ZONE_COLOR = (241, 244, 243)                    # BGR: the white of the brand
THIN, THICK = 2, 5                              # outline of a box and its corners, on a clip 1080 wide
CORNER_SHARE, CORNER_MIN, CORNER_MAX = 0.22, 12, 56   # length of a corner: share of the short side, and limits
HIDDEN_GROUPS = ("pending",)                    # not drawn: tracks too young, two-wheelers shown by their rider
MIN_SPEED_KMH = 1.0                             # below this the speed is not written (standing still)


class Labels:
    """Text labels drawn with Pillow (sharper than the fonts of OpenCV), kept so each one is drawn once."""

    def __init__(self, font_px: int):
        self.font = ImageFont.load_default(size=font_px)
        self.cache: dict[tuple[str, tuple], np.ndarray] = {}

    def image(self, text: str, bgr: tuple) -> np.ndarray:
        """The label as a BGRA picture: the text on a rounded patch of the colour of the box."""
        key = (text, bgr)
        if key not in self.cache:
            left, top, right, bottom = self.font.getbbox(text)
            pad_x, pad_y = LABEL_PAD
            size = (right - left + 2 * pad_x, bottom - top + 2 * pad_y)
            picture = Image.new("RGBA", size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(picture)
            draw.rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=size[1] // 3, fill=bgr[::-1] + (255,))
            draw.text((pad_x - left, pad_y - top), text, font=self.font, fill=LABEL_INK + (255,))
            self.cache[key] = cv2.cvtColor(np.asarray(picture), cv2.COLOR_RGBA2BGRA)
        return self.cache[key]

    def paste(self, frame: np.ndarray, text: str, bgr: tuple, x: int, bottom: int) -> None:
        """Puts the label with its left side at x and its base at bottom, kept inside the frame."""
        label = self.image(text, bgr)
        h, w = label.shape[:2]
        x = min(max(x, 0), max(frame.shape[1] - w, 0))
        y = min(max(bottom - h, 0), max(frame.shape[0] - h, 0))
        part = label[:frame.shape[0] - y, :frame.shape[1] - x]
        alpha = part[:, :, 3:4].astype(np.float32) / 255.0
        area = frame[y:y + part.shape[0], x:x + part.shape[1]]
        area[:] = (part[:, :, :3] * alpha + area * (1.0 - alpha)).astype(np.uint8)


def label_text(role: str, state) -> str:
    """What the vision knows about a track, in a few words: 'pedestrian 4 km/h slow'."""
    words = [role]
    if state is not None and state.speed_samples > 0 and state.speed * KMH >= MIN_SPEED_KMH:
        words.append(f"{state.speed * KMH:.0f} km/h")
    if state is not None:
        words += [flag for flag in ("child", "slow") if state.attrs.get(flag)]
        if state.attrs.get("aid") not in (None, "normal"):
            words.append(str(state.attrs["aid"]))
    return "  ".join(words)


def draw(frame: np.ndarray, result, pipeline: Pipeline, cfg: dict, to_clip, k: float, labels: Labels) -> None:
    """Zones and boxes on the enlarged frame. to_clip turns a point of the video into a point of the clip;
    k is the size of the drawing against a clip 1080 wide."""
    colors = cfg["overlay"]["colors"]
    thin, thick = max(1, round(THIN * k)), max(2, round(THICK * k))
    soft = frame.copy()                                    # what is drawn here is blended, not laid on top
    geometry = pipeline.geometry
    if geometry is not None and geometry.metric:
        for name in cfg["overlay"]["zones"]:
            polygon = geometry.zones.get(name)
            if polygon:
                points = np.array([to_clip(*geometry.to_image(x, y)) for x, y in polygon], dtype=np.int32)
                cv2.polylines(soft, [points], True, ZONE_COLOR, thin, cv2.LINE_AA)
        cv2.addWeighted(soft, ZONE_ALPHA, frame, 1.0 - ZONE_ALPHA, 0, frame)
        soft = frame.copy()

    tracked = result.tracked
    boxes = []
    if tracked.tracker_id is not None:
        for i, (xyxy, track_id, valid) in enumerate(zip(tracked.xyxy, tracked.tracker_id, result.valid)):
            state = pipeline.tracker.tracks.get(int(track_id))
            role = result.roles[i] if i < len(result.roles) else (state.class_name if state else "?")
            group = ROLE_GROUP.get(role, "animal") if valid else "pending"
            if group in HIDDEN_GROUPS:
                continue
            color = tuple(int(c) for c in colors[group])
            (x1, y1), (x2, y2) = to_clip(xyxy[0], xyxy[1]), to_clip(xyxy[2], xyxy[3])
            if x2 < 0 or y2 < 0 or x1 >= frame.shape[1] or y1 >= frame.shape[0]:
                continue                                   # outside the band of the frame that the clip shows
            boxes.append((x1, y1, x2, y2, color, label_text(role, state)))
            cv2.rectangle(soft, (x1, y1), (x2, y2), color, thin, cv2.LINE_AA)
    cv2.addWeighted(soft, BOX_ALPHA, frame, 1.0 - BOX_ALPHA, 0, frame)
    for x1, y1, x2, y2, color, text in boxes:
        side = int(min(max(CORNER_SHARE * min(x2 - x1, y2 - y1), CORNER_MIN * k), CORNER_MAX * k))
        for cx, cy, dx, dy in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
            cv2.line(frame, (cx, cy), (cx + dx * side, cy), color, thick, cv2.LINE_AA)
            cv2.line(frame, (cx, cy), (cx, cy + dy * side), color, thick, cv2.LINE_AA)
        labels.paste(frame, text, color, x1 - thick // 2, y1 - thick)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("video", help="recorded video")
    p.add_argument("--calib", help="calibration of that view (zones, speeds); without it only the boxes")
    p.add_argument("--start", type=float, default=0.0, help="second of the video where the clip starts")
    p.add_argument("--seconds", type=float, default=0.0, help="length of the clip (default: to the end)")
    p.add_argument("--wide", action="store_true", help="16:9 band of the frame at 1920x1080")
    p.add_argument("--wide-top", type=float, default=0.5, help="where the band is: 0 = top, 1 = bottom")
    p.add_argument("--input", type=int, help="input size of the detector (default: model.input_size of config.yaml)")
    p.add_argument("--whole-frame", action="store_true", help="detector on the whole frame, not on the roi of the calibration")
    p.add_argument("--name", help="name of the clip (default: <video>_vista or <video>_vista_16x9)")
    p.add_argument("--out", default=str(DEFAULT_OUT), help="folder of the clips (default: ai/samples/trailer)")
    args = p.parse_args(argv)

    cfg = load_config(None, "pc")
    cfg["source"]["max_fps"] = 0                           # every frame of the video
    if args.input:
        cfg["model"]["input_size"] = args.input
    try:
        calib, _ = load_calib(cfg, args.calib)
        source = FrameSource(args.video, cfg, realtime=False)
        pipeline = Pipeline(cfg, source.fps, calib)
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 2
    pipeline.detector.set_roi(None if args.whole_frame else calib.get("roi"))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{args.name or Path(args.video).stem.lower() + ('_vista_16x9' if args.wide else '_vista')}.mp4"
    encoder = None
    written = 0
    labels = first_t = None
    try:
        while (item := source.read()) is not None:
            frame, t = item
            result = pipeline.step(frame, t)               # from the first frame: tracks and speeds are ready
            first_t = t if first_t is None else first_t    # t is a clock, not the second of the video
            if t - first_t < args.start:
                continue
            if args.seconds and t - first_t >= args.start + args.seconds:
                break
            height, width = frame.shape[:2]
            if args.wide:
                size = WIDE_SIZE
                band = width * size[1] / size[0]
                top = min(max(args.wide_top, 0.0), 1.0) * (height - band)
                view = frame[round(top):round(top + band)]
            else:
                size = (TALL_WIDTH, round(height * TALL_WIDTH / width / 2) * 2)   # even height, for H.264
                top, view = 0.0, frame
            scale = size[0] / width
            clip = cv2.resize(view, size, interpolation=cv2.INTER_LANCZOS4)
            if encoder is None:
                k = size[0] / TALL_WIDTH
                labels = Labels(round(FONT_PX * min(k, FONT_MAX_GROWTH)))
                encoder = subprocess.Popen(
                    ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{size[0]}x{size[1]}",
                     "-r", f"{source.fps:.6f}", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", str(CRF),
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], stdin=subprocess.PIPE)
            draw(clip, result, pipeline, cfg,
                 lambda x, y: (round(float(x) * scale), round((float(y) - round(top)) * scale)), k, labels)
            encoder.stdin.write(clip.tobytes())
            written += 1
    finally:
        source.release()
        if encoder is not None:
            encoder.stdin.close()
            encoder.wait()
    if not written:
        print("Nessun fotogramma scritto: --start è oltre la fine del video?", file=sys.stderr)
        return 1
    print(f"{path}: {written} fotogrammi, {written / source.fps:.1f} s, {size[0]}x{size[1]}, detector "
          f"{pipeline.detector.input_label}" + (", tutta l'inquadratura" if args.whole_frame else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
