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
    class_votes: Counter = field(default_factory=Counter)   # COCO class id per frame
    role_votes: Counter = field(default_factory=Counter)    # role per frame, see derive.py
    # Metric state, filled only with a metric calibration (see geometry.Geometry).
    ground: tuple[float, float] | None = None      # last position on the ground, metres
    ground_history: deque = field(default_factory=deque)   # (t, x, y) in metres
    speed_history: deque = field(default_factory=deque)    # (t, speed)
    aspect: float = 0.0                            # width / height of the last box
    velocity: tuple[float, float] = (0.0, 0.0)     # smoothed, m/s in the ground frame
    speed: float = 0.0                             # m/s
    speed_samples: int = 0                         # speed measures taken so far
    accel: float = 0.0                             # m/s^2 along the motion (negative = braking)
    speed_before: float = 0.0                      # speed one window ago, the start of that acceleration
    heights: deque = field(default_factory=deque)  # recent box heights in metres
    precise_heights: deque = field(default_factory=deque)  # the same, only from boxes large enough to trust
    length_m: float | None = None                  # last box width in metres
    zone: str | None = None
    zone_since: float = 0.0                        # time the track entered its current zone
    attrs: dict = field(default_factory=dict)      # child / slow / aid / walk_speed, see attributes.py

    @property
    def role(self) -> str | None:
        """Majority role over the life of the track (pedestrian, cyclist, car, ...)."""
        return self.role_votes.most_common(1)[0][0] if self.role_votes else None

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
        k = cfg["kinematics"]
        self.ema_alpha = 2.0 / (int(k["ema_samples"]) + 1)
        self.max_dt = float(k["max_dt_s"])
        self.window = float(k["window_s"])
        self.min_window = float(k["min_window_s"])
        self.max_speed = float(k["max_speed_ms"])
        self.max_metres_per_px = float(k["max_metres_per_px"])
        self.edge_margin = None if k["edge_margin"] is None else float(k["edge_margin"])
        self.height_samples = int(cfg["attributes"]["height_samples"])
        self.height_min_box_px = float(cfg["attributes"]["height_min_box_px"])
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

    def update(self, detections: sv.Detections, t: float, geometry=None) -> sv.Detections:
        """Feeds one frame of detections. Returns the tracked detections (with tracker_id).

        With a metric geometry, the ground position, speed, acceleration, size and zone of each
        track are updated too.
        """
        self._frame += 1
        tracked = self._bytetrack.update_with_detections(detections)
        if tracked.tracker_id is None:
            return tracked
        metric = geometry is not None and geometry.metric
        for xyxy, class_id, track_id in zip(tracked.xyxy, tracked.class_id, tracked.tracker_id):
            track_id = int(track_id)
            state = self.tracks.get(track_id)
            if state is None:
                state = TrackState(track_id=track_id, first_t=t, history=deque(maxlen=self.history_len),
                                   heights=deque(maxlen=self.height_samples),
                                   precise_heights=deque(maxlen=self.height_samples),
                                   ground_history=deque(maxlen=self.history_len),
                                   speed_history=deque(maxlen=self.history_len))
                self.tracks[track_id] = state
            foot = (float((xyxy[0] + xyxy[2]) / 2), float(xyxy[3]))   # bottom centre: on the ground
            if metric:
                self._update_metric(state, xyxy, foot, t, geometry)
            state.age += 1
            state.last_t = t
            state.last_frame = self._frame
            state.history.append((t, foot[0], foot[1]))
            state.class_votes[int(class_id)] += 1
        self._drop_stale()
        return tracked

    def _measurable(self, xyxy, foot: tuple[float, float], geometry) -> bool:
        """False when the foot point cannot be trusted for a speed: box cut by the border, or too far."""
        if self.edge_margin is not None and geometry.width:
            mx, my = self.edge_margin * geometry.width, self.edge_margin * geometry.height
            if xyxy[0] <= mx or xyxy[2] >= geometry.width - 1 - mx or xyxy[3] >= geometry.height - 1 - my:
                return False   # the object is entering or leaving the image: its box is cut
        return geometry.metres_per_pixel(*foot) <= self.max_metres_per_px

    def _update_metric(self, state: TrackState, xyxy, foot: tuple[float, float], t: float, geometry) -> None:
        position = geometry.to_ground(*foot)
        if not self._measurable(xyxy, foot, geometry):
            # Keep the position (zones still work) but forget the speed: it is not known here.
            state.ground = position
            state.ground_history.clear()
            state.speed_history.clear()
            state.velocity, state.speed, state.accel, state.speed_samples = (0.0, 0.0), 0.0, 0.0, 0
            state.speed_before = 0.0
            zone = geometry.zone_of(*position)
            if zone != state.zone:
                state.zone, state.zone_since = zone, t
            return
        # Speed over a time window, not between two frames: the box of a standing object jitters by a
        # pixel or two, and from frame to frame that looks like metres per second.
        reference = self._reference(state.ground_history, t)
        if reference is not None:
            ref_t, ref_x, ref_y = reference
            dt = t - ref_t
            raw = ((position[0] - ref_x) / dt, (position[1] - ref_y) / dt)
            if (raw[0] * raw[0] + raw[1] * raw[1]) ** 0.5 > self.max_speed:
                # Impossible jump: the tracker put this ID on another object. Start again from here.
                state.ground_history.clear()
                state.speed_history.clear()
                state.velocity, state.speed, state.accel, state.speed_samples = (0.0, 0.0), 0.0, 0.0, 0
            else:
                if state.speed_samples == 0:
                    vx, vy = raw   # first measure: start from it, not from zero
                else:
                    # Exponential moving average over `ema_samples` samples.
                    vx = state.velocity[0] + self.ema_alpha * (raw[0] - state.velocity[0])
                    vy = state.velocity[1] + self.ema_alpha * (raw[1] - state.velocity[1])
                state.velocity, state.speed = (vx, vy), (vx * vx + vy * vy) ** 0.5
                state.speed_samples += 1
                # Acceleration only once the speed has a full window of history: the first speed
                # estimates of a new track still move a lot and would look like hard braking.
                past = self._reference(state.speed_history, t, full_window=True)
                if past is not None:
                    state.accel = (state.speed - past[1]) / (t - past[0])
                    state.speed_before = past[1]
                if dt >= self.window:
                    state.speed_history.append((t, state.speed))   # only speeds measured on a full window
        state.ground = position
        state.ground_history.append((t, position[0], position[1]))
        box_h = float(xyxy[3] - xyxy[1])
        state.aspect = float(xyxy[2] - xyxy[0]) / box_h if box_h > 0 else 0.0

        height = geometry.height_in_metres(box_h, *foot)
        if height is not None:
            state.heights.append(height)
            # Good enough to tell a child from an adult only if: the calibration fits a real camera (else the
            # height is a rough estimate), the box is not tiny (2 px are 10% of 20 px), and it does not
            # touch the top of the image (the head is cut).
            top_inside = self.edge_margin is None or xyxy[1] > self.edge_margin * geometry.height
            if geometry.camera is not None and box_h >= self.height_min_box_px and top_inside:
                state.precise_heights.append(height)
        state.length_m = geometry.size_in_metres(float(xyxy[2] - xyxy[0]), *foot)

        zone = geometry.zone_of(*position)
        if zone != state.zone:
            state.zone, state.zone_since = zone, t

    def vote_roles(self, tracked: sv.Detections, roles: list[str]) -> list[str]:
        """Adds this frame's role of each track and returns the majority role of each one."""
        if tracked.tracker_id is None:
            return []
        out = []
        for track_id, role in zip(tracked.tracker_id, roles):
            state = self.tracks[int(track_id)]
            state.role_votes[role] += 1
            out.append(state.role)
        return out

    def class_names(self, tracked: sv.Detections) -> list[str]:
        """Majority COCO class name of each tracked detection."""
        if tracked.tracker_id is None:
            return []
        return [self.tracks[int(i)].class_name for i in tracked.tracker_id]

    def _reference(self, history: deque, t: float, full_window: bool = False):
        """The sample about `window_s` before t.

        If the history is shorter: the oldest sample at least `min_window_s` old, or None with full_window.
        """
        chosen = None
        for sample in reversed(history):
            age = t - sample[0]
            if age > self.max_dt:
                break               # older than this is another episode
            if age >= self.window:
                return sample
            if age >= self.min_window:
                chosen = sample
        return None if full_window else chosen

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
