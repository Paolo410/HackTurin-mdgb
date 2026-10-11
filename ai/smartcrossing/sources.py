"""Frame sources: webcam index, video file, RTSP URL. Frames are never written to disk."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from .config import resolve_path


def default_source(cfg: dict) -> str:
    """First video in the samples folder, otherwise the webcam (index 0)."""
    src = cfg["source"]
    folder = resolve_path(src["samples_dir"])
    extensions = {e.lower() for e in src["video_extensions"]}
    if folder.is_dir():
        videos = sorted(p for p in folder.iterdir() if p.suffix.lower() in extensions)
        if videos:
            return str(videos[0])
    return "0"


def frame_fault(frame: np.ndarray, cfg: dict) -> str | None:
    """Self-check of the camera on one frame: "lens_covered", "glare" or None.

    Lens covered or badly out of focus = almost no detail (variance of the Laplacian below a threshold).
    Glare = a large part of the image is saturated.
    """
    c = cfg["selfcheck"]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if float(np.mean(gray >= int(c["saturated_level"]))) > float(c["saturated_fraction_max"]):
        return "glare"
    if float(cv2.Laplacian(gray, cv2.CV_64F).var()) < float(c["laplacian_var_min"]):
        return "lens_covered"
    return None


def mean_luminance(frame: np.ndarray) -> float:
    """Mean grey level of the frame, 0..255: how bright the scene is."""
    return float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())


class FrameSource:
    """Yields (frame, t) pairs.

    Live sources (webcam, RTSP): t is time.monotonic() at capture.
    Video files: t follows the video timeline (frame index / fps), so speeds measured later do not
    depend on how fast the file is processed. When max_fps is lower than the file rate, frames are
    skipped like a live camera would drop them. Played in real time (the vision on a recorded video, as
    if it came from the camera), the frames that are already late are skipped too (source.file_drop_late):
    a slow board then sees what it would see from the camera, not a slowed-down video. With loop the file
    starts again at the end and the timeline goes on.
    """

    def __init__(self, source: str, cfg: dict, realtime: bool | None = None, loop: bool = False):
        src = cfg["source"]
        self.name = str(source)
        self.resize_width = int(src["resize_width"])
        self.max_fps = float(src["max_fps"])
        self.is_live = self.name.isdigit() or "://" in self.name
        self.realtime = self.is_live or (src["file_realtime"] if realtime is None else realtime)
        self.drop_late = bool(src["file_drop_late"])
        self.loop = bool(loop) and not self.is_live
        self.loops = 0        # times a looped file started again
        self.dropped = 0      # late frames skipped
        self._pos = -1        # last frame read from the file (the timeline, _frame_idx, never goes back)

        if not self.is_live and not Path(self.name).is_file():
            raise FileNotFoundError(f"Video not found: {self.name}")
        self._cap = cv2.VideoCapture(int(self.name) if self.name.isdigit() else self.name)
        if not self._cap.isOpened():
            hint = ""
            if self.name.isdigit():
                hint = (" (camera missing, busy or not authorized: on macOS allow your terminal in"
                        " System Settings > Privacy & Security > Camera)")
            raise RuntimeError(f"Cannot open source: {self.name}{hint}")

        native = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.native_fps = native if native > 0 else 0.0
        # File frames per processed frame: a fraction is kept (8.4 FPS out of 30 = 3.57, steps of 3 and 4 in turn),
        # so a recorded video is analysed at the rate measured on the board, not at the nearest whole step.
        self._ratio = 1.0
        if not self.is_live and self.max_fps > 0 and self.native_fps > self.max_fps:
            self._ratio = self.native_fps / self.max_fps
        self._step = max(1, round(self._ratio))      # typical step, for estimates
        self._emitted = 0
        self._frame_idx = -1
        self._t0 = None   # origin of the file timeline, set when the first frame is read
        self._last_emit = None

    @property
    def fps(self) -> float:
        """Expected rate of the frames returned by read(). 0 if unknown."""
        if self.is_live:
            if self.max_fps > 0 and (self.native_fps == 0 or self.max_fps < self.native_fps):
                return self.max_fps
            return self.native_fps
        return self.native_fps / self._ratio if self.native_fps else 0.0

    def read(self) -> tuple[np.ndarray, float] | None:
        """Returns the next (frame, t), or None when the source ends or fails."""
        if self.is_live:
            self._pace(1.0 / self.max_fps if self.max_fps > 0 else 0.0)
            ok, frame = self._cap.read()
            if not ok:
                return None
            t = time.monotonic()
        else:
            fps = self.native_fps or 1.0
            if self.realtime and self.drop_late and self._t0 is not None:
                # Late: skip the frames a live camera would have dropped while we were busy.
                late = int((time.monotonic() - self._t0) * fps) - (self._frame_idx + self._step)
                for _ in range(max(0, late)):
                    if not self._cap.grab():
                        break             # end of the file: _read_file starts again or stops
                    self._frame_idx += 1
                    self._pos += 1
                    self.dropped += 1
            frame = self._read_file()
            if frame is None:
                return None
            if self._t0 is None:
                self._t0 = time.monotonic() - self._frame_idx / fps
            t = self._t0 + self._frame_idx / fps
            if self.realtime:
                delay = t - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
        return self._resize(frame), t

    def _read_file(self) -> np.ndarray | None:
        """The next file frame, max_fps steps apart. With loop, at the end the file starts again."""
        for _ in range(2):
            step = max(1, round(self._emitted * self._ratio) - self._frame_idx)
            ok = True
            for _ in range(step - 1):
                if not self._cap.grab():
                    ok = False
                    break
            if ok:
                ok, frame = self._cap.read()
            if ok:
                self._frame_idx += step
                self._pos += step
                self._emitted = max(self._emitted + 1, int(self._frame_idx / self._ratio) + 1)
                return frame
            if not self.loop or self._frame_idx < 0:
                return None
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)    # the timeline (frame index) goes on
            self._pos = -1
            self.loops += 1
        return None

    # ---- position in a video file (technician's page: back / forward)

    @property
    def duration_s(self) -> float:
        n = float(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        return n / self.native_fps if self.native_fps and not self.is_live else 0.0

    @property
    def position_s(self) -> float:
        return max(self._pos, 0) / self.native_fps if self.native_fps and not self.is_live else 0.0

    def seek(self, seconds: float) -> None:
        """Moves back or forward in a video file. The timeline goes on (like a cut in the video): the tracks of
        the old scene simply end. Nothing happens with a camera."""
        if self.is_live or not self.native_fps:
            return
        last = max(int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) - 1, 0)
        target = min(max(self._pos + int(round(seconds * self.native_fps)), 0), last)
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, target)
        self._pos = target - 1

    def _pace(self, min_period: float) -> None:
        now = time.monotonic()
        if self._last_emit is not None and min_period > 0:
            wait = min_period - (now - self._last_emit)
            if wait > 0:
                time.sleep(wait)
        self._last_emit = time.monotonic()

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        if self.resize_width > 0 and w > self.resize_width:
            new_h = int(round(h * self.resize_width / w))
            frame = cv2.resize(frame, (self.resize_width, new_h), interpolation=cv2.INTER_AREA)
        return frame

    def release(self) -> None:
        self._cap.release()
