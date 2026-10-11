"""Recorded videos played as if they came from the camera: which video comes next, with which calibration, and the
commands of the technician's page (previous / next video, back / forward a few seconds).

Only for tests and benchmarks: with the camera there is no playlist and the page shows no video buttons.
The commands arrive from the threads of the page and are carried out by the vision loop (take()), between two frames.
"""
from __future__ import annotations

import threading
from pathlib import Path

VIDEO_SUFFIXES = (".mp4", ".mov", ".avi", ".mkv")
ACTIONS = ("prev", "next", "back", "fwd")


def calib_for(video: Path) -> Path | None:
    """The calibration of a sample video in <folder>/calib/, by name: Torino_1.mp4 -> torino_1.json,
    01_strisce_nyc_....mp4 -> 01.json, mdgb_mixkit_4194.mp4 -> 4194.json. None if there is none."""
    try:   # real file names, compared without case: the same answer on macOS and on the board (Linux)
        files = {p.name.lower(): p for p in (video.parent / "calib").iterdir() if p.suffix.lower() == ".json"}
    except OSError:
        return None
    parts = video.stem.lower().split("_")
    for name in (video.stem.lower(), parts[0], parts[-1]):
        if f"{name}.json" in files:
            return files[f"{name}.json"]
    return None


class Playlist:
    """The videos of the folder of the first one, in name order. The first keeps the calibration it was started
    with (--calib); the others take theirs from calib_for()."""

    def __init__(self, first: str | Path, first_calib: str | Path | None = None):
        first = Path(first).resolve()
        self.videos = sorted(p for p in first.parent.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES and p.is_file())
        self.index = self.videos.index(first) if first in self.videos else 0
        if first not in self.videos:
            self.videos.insert(0, first)
        self._first, self._first_calib = first, Path(first_calib) if first_calib else None
        self._lock = threading.Lock()
        self._pending: list[str] = []

    @property
    def current(self) -> Path:
        return self.videos[self.index]

    def calib(self, video: Path | None = None) -> Path | None:
        video = video or self.current
        if video == self._first and self._first_calib is not None:
            return self._first_calib
        return calib_for(video)

    def move(self, step: int) -> Path:
        """The previous (-1) or next (+1) video, going round at the ends."""
        self.index = (self.index + step) % len(self.videos)
        return self.current

    # ---- commands of the technician's page

    def request(self, action: str) -> bool:
        """Called by the page. False for an unknown action."""
        if action not in ACTIONS:
            return False
        with self._lock:
            self._pending.append(action)
        return True

    def take(self) -> list[str]:
        """Called by the vision loop: the commands received since the last call, in order."""
        with self._lock:
            pending, self._pending = self._pending, []
        return pending
