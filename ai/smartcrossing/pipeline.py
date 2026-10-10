"""One processing step per frame (detect -> track) with per-phase timings."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

import numpy as np
import supervision as sv

from .counting import LineCounter
from .derive import derive_roles
from .detector import Detector
from .tracking import Tracker

# Phases reported on screen and in the C3 status event. "rules" and "act" arrive with AI-M3.
PHASES = ("detect", "track", "rules", "act")


@dataclass
class FrameResult:
    tracked: sv.Detections            # detections with tracker_id
    valid: np.ndarray                 # per detection: track older than min_track_age
    lat_ms: dict[str, float | None]   # None = phase not run on this frame
    detected: bool                    # False when the detector was skipped (detect_every_n)
    roles: list[str] = field(default_factory=list)    # per detection: majority role of its track
    events: list[dict] = field(default_factory=list)  # crossings counted on this frame


class Pipeline:
    def __init__(self, cfg: dict, frame_rate: float = 0.0, calib: dict | None = None):
        """calib: content of calib.json. Without it nothing is counted."""
        self.cfg = cfg
        self.calib = calib
        self.detector = Detector(cfg)
        self.detect_every_n = max(1, int(cfg["model"]["detect_every_n"]))
        # ByteTrack only sees the frames on which the detector runs.
        self.tracker = Tracker(cfg, frame_rate / self.detect_every_n if frame_rate > 0 else 0.0)
        self.counter: LineCounter | None = None   # created on the first frame, when the size is known
        self._frame = 0
        self._last = sv.Detections.empty()
        self._last_roles: list[str] = []

    def step(self, frame: np.ndarray, t: float) -> FrameResult:
        if self.counter is None and self.calib is not None:
            height, width = frame.shape[:2]
            self.counter = LineCounter(self.cfg, self.calib, (width, height))

        run_detector = self._frame % self.detect_every_n == 0
        self._frame += 1
        lat_ms: dict[str, float | None] = dict.fromkeys(PHASES)
        events: list[dict] = []
        if run_detector:
            t0 = perf_counter()
            detections = self.detector.detect(frame)
            t1 = perf_counter()
            # "track" also covers the per-track bookkeeping: roles and line counting.
            tracked = self.tracker.update(detections, t)
            frame_roles = derive_roles(tracked.xyxy, self.tracker.class_names(tracked), self.cfg)
            roles = self.tracker.vote_roles(tracked, frame_roles)
            if self.counter is not None:
                events = self.counter.update(tracked, roles, self.tracker.valid_mask(tracked))
            t2 = perf_counter()
            self._last, self._last_roles = tracked, roles
            lat_ms["detect"] = (t1 - t0) * 1000.0
            lat_ms["track"] = (t2 - t1) * 1000.0
        # On skipped frames the last tracked boxes are held.
        return FrameResult(self._last, self.tracker.valid_mask(self._last), lat_ms, run_detector,
                           self._last_roles, events)


class LatencyStats:
    """Collects per-phase timings and prints mean and percentile."""

    def __init__(self):
        self._samples: dict[str, list[float]] = {phase: [] for phase in PHASES}
        self._totals: list[float] = []

    def add(self, lat_ms: dict[str, float | None]) -> None:
        measured = [v for v in lat_ms.values() if v is not None]
        if not measured:
            return
        for phase, value in lat_ms.items():
            if value is not None:
                self._samples[phase].append(value)
        self._totals.append(sum(measured))

    def mean(self, phase: str) -> float | None:
        values = self._samples[phase]
        return float(np.mean(values)) if values else None

    def total_mean(self) -> float | None:
        return float(np.mean(self._totals)) if self._totals else None

    def table(self, percentile: float) -> str:
        label = f"p{percentile:g} ms"
        lines = [f"{'phase':<8}{'mean ms':>10}{label:>10}"]
        for name, values in list(self._samples.items()) + [("total", self._totals)]:
            if values:
                lines.append(f"{name:<8}{np.mean(values):>10.2f}{np.percentile(values, percentile):>10.2f}")
            else:
                lines.append(f"{name:<8}{'-':>10}{'-':>10}")
        return "\n".join(lines)
