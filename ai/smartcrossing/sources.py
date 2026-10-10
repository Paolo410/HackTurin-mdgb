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


class FrameSource:
    """Yields (frame, t) pairs.

    Live sources (webcam, RTSP): t is time.monotonic() at capture.
    Video files: t follows the video timeline (frame index / fps), so speeds measured later do not
    depend on how fast the file is processed. When max_fps is lower than the file rate, frames are
    skipped like a live camera would drop them.
    """

    def __init__(self, source: str, cfg: dict, realtime: bool | None = None):
        src = cfg["source"]
        self.name = str(source)
        self.resize_width = int(src["resize_width"])
        self.max_fps = float(src["max_fps"])
        self.is_live = self.name.isdigit() or "://" in self.name
        self.realtime = self.is_live or (src["file_realtime"] if realtime is None else realtime)

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
        # Number of file frames consumed per processed frame.
        self._step = 1
        if not self.is_live and self.max_fps > 0 and self.native_fps > self.max_fps:
            self._step = max(1, round(self.native_fps / self.max_fps))
        self._frame_idx = -1
        self._t0 = time.monotonic()
        self._last_emit = None

    @property
    def fps(self) -> float:
        """Expected rate of the frames returned by read(). 0 if unknown."""
        if self.is_live:
            if self.max_fps > 0 and (self.native_fps == 0 or self.max_fps < self.native_fps):
                return self.max_fps
            return self.native_fps
        return self.native_fps / self._step if self.native_fps else 0.0

    def read(self) -> tuple[np.ndarray, float] | None:
        """Returns the next (frame, t), or None when the source ends or fails."""
        if self.is_live:
            self._pace(1.0 / self.max_fps if self.max_fps > 0 else 0.0)
            ok, frame = self._cap.read()
            if not ok:
                return None
            t = time.monotonic()
        else:
            for _ in range(self._step - 1):
                if not self._cap.grab():
                    return None
            ok, frame = self._cap.read()
            if not ok:
                return None
            self._frame_idx += self._step
            fps = self.native_fps or 1.0
            t = self._t0 + self._frame_idx / fps
            if self.realtime:
                delay = t - time.monotonic()
                if delay > 0:
                    time.sleep(delay)
        return self._resize(frame), t

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
