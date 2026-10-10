"""One processing step per frame (detect -> track) with per-phase timings."""
from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

import numpy as np
import supervision as sv

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


class Pipeline:
    def __init__(self, cfg: dict, frame_rate: float = 0.0):
        self.detector = Detector(cfg)
        self.detect_every_n = max(1, int(cfg["model"]["detect_every_n"]))
        # ByteTrack only sees the frames on which the detector runs.
        self.tracker = Tracker(cfg, frame_rate / self.detect_every_n if frame_rate > 0 else 0.0)
        self._frame = 0
        self._last = sv.Detections.empty()

    def step(self, frame: np.ndarray, t: float) -> FrameResult:
        run_detector = self._frame % self.detect_every_n == 0
        self._frame += 1
        lat_ms: dict[str, float | None] = dict.fromkeys(PHASES)
        if run_detector:
            t0 = perf_counter()
            detections = self.detector.detect(frame)
            t1 = perf_counter()
            self._last = self.tracker.update(detections, t)
            t2 = perf_counter()
            lat_ms["detect"] = (t1 - t0) * 1000.0
            lat_ms["track"] = (t2 - t1) * 1000.0
        # On skipped frames the last tracked boxes are held.
        return FrameResult(self._last, self.tracker.valid_mask(self._last), lat_ms, run_detector)


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
