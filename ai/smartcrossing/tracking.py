"""ByteTrack tracking plus a small per-track state (age, position history, class votes).

supervision.ByteTrack API (verified on the pinned supervision 0.30.5):
https://supervision.roboflow.com/latest/trackers/
ByteTrack is deprecated in supervision and removed in 0.31: keep the pin in requirements.txt below 0.31.
"""
from __future__ import annotations

import warnings
from collections import Counter, deque
from dataclasses import dataclass, field

import numpy as np
import supervision as sv

from .detector import COCO_CLASSES


@dataclass
class TrackState:
    track_id: int
    first_t: float
    last_t: float = 0.0
    last_frame: int = 0
    age: int = 0                                   # frames in which the track was seen
    history: deque = field(default_factory=deque)  # (t, x_bottom_center, y_bottom) in frame pixels
    class_votes: Counter = field(default_factory=Counter)

    @property
    def class_id(self) -> int:
        """Majority class over the life of the track."""
        return self.class_votes.most_common(1)[0][0]

    @property
    def class_name(self) -> str:
        return COCO_CLASSES[self.class_id]


class Tracker:
    def __init__(self, cfg: dict, frame_rate: float = 0.0):
        t = cfg["tracking"]
        self.min_track_age = int(t["min_track_age"])
        self.history_len = int(t["history_len"])
        self.lost_track_buffer = int(t["lost_track_buffer"])
        with warnings.catch_warnings():
            # Known deprecation of sv.ByteTrack: the version is pinned, see the module docstring.
            warnings.simplefilter("ignore", FutureWarning)
            self._bytetrack = sv.ByteTrack(
                track_activation_threshold=float(t["track_activation_threshold"]),
                lost_track_buffer=self.lost_track_buffer,
                minimum_matching_threshold=float(t["minimum_matching_threshold"]),
                frame_rate=frame_rate if frame_rate > 0 else float(t["default_frame_rate"]),
                minimum_consecutive_frames=int(t["minimum_consecutive_frames"]),
            )
        self.tracks: dict[int, TrackState] = {}
        self._frame = 0

    def update(self, detections: sv.Detections, t: float) -> sv.Detections:
        """Feeds one frame of detections. Returns the tracked detections (with tracker_id)."""
        self._frame += 1
        tracked = self._bytetrack.update_with_detections(detections)
        if tracked.tracker_id is None:
            return tracked
        for xyxy, class_id, track_id in zip(tracked.xyxy, tracked.class_id, tracked.tracker_id):
            track_id = int(track_id)
            state = self.tracks.get(track_id)
            if state is None:
                state = TrackState(track_id=track_id, first_t=t, history=deque(maxlen=self.history_len))
                self.tracks[track_id] = state
            state.age += 1
            state.last_t = t
            state.last_frame = self._frame
            state.history.append((t, float((xyxy[0] + xyxy[2]) / 2), float(xyxy[3])))
            state.class_votes[int(class_id)] += 1
        self._drop_stale()
        return tracked

    def is_valid(self, track_id: int) -> bool:
        """A track counts only after min_track_age frames."""
        state = self.tracks.get(int(track_id))
        return state is not None and state.age >= self.min_track_age

    def valid_mask(self, tracked: sv.Detections) -> np.ndarray:
        if tracked.tracker_id is None:
            return np.zeros((0,), dtype=bool)
        return np.array([self.is_valid(i) for i in tracked.tracker_id], dtype=bool)

    def _drop_stale(self) -> None:
        limit = self._frame - self.lost_track_buffer
        for track_id in [i for i, s in self.tracks.items() if s.last_frame < limit]:
            del self.tracks[track_id]
