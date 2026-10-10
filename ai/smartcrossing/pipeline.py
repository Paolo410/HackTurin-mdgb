"""One processing step per frame: detect -> track -> rules -> act, with per-phase timings."""
from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

import numpy as np
import supervision as sv

from .animals import AnimalMonitor
from .attributes import AidClassifier, AttributeEstimator, public_attrs
from .counting import LineCounter
from .derive import derive_roles
from .detector import Detector
from .events import EventDetector, approach_distance
from .geometry import Geometry
from .rules import WAITING_ZONES, PedestrianInfo, RuleEngine, Scene, VehicleInfo
from .sources import frame_fault
from .tracking import Tracker

# Phases reported on screen and in the C3 status event.
PHASES = ("detect", "track", "rules", "act")
ROAD_ZONES = ("carriageway", "crosswalk")


@dataclass
class FrameResult:
    tracked: sv.Detections            # detections with tracker_id
    valid: np.ndarray                 # per detection: track older than min_track_age
    lat_ms: dict[str, float | None]   # None = phase not run on this frame
    detected: bool                    # False when the detector was skipped (detect_every_n)
    roles: list[str] = field(default_factory=list)    # per detection: majority role of its track
    events: list[dict] = field(default_factory=list)  # crossings counted on this frame
    command: dict | None = None       # C1 fields decided by the rule
    sent: bool = False                # a C1 line went to the actuator on this frame


def build_scene(tracker: Tracker, tracked: sv.Detections, roles: list[str], valid: np.ndarray,
                geometry: Geometry | None, t: float, cfg: dict) -> Scene:
    """What the rule needs to know, in metres and seconds, from the valid tracks."""
    r = cfg["rules"]
    metric = geometry is not None and geometry.metric
    scene = Scene(W=geometry.W if metric and geometry.W else float(r["default_W_m"]))
    if not metric or tracked.tracker_id is None:
        return scene
    ped_roles, veh_roles = set(r["pedestrian_roles"]), set(r["vehicle_roles"])
    along = geometry.along or 0.0
    for track_id, role, ok in zip(tracked.tracker_id, roles, valid):
        state = tracker.tracks.get(int(track_id))
        if not ok or state is None or state.ground is None:
            continue
        x, y = state.ground
        vx, vy = state.velocity
        if role in ped_roles:
            waiting = state.zone in WAITING_ZONES
            # The road is at y > 0 for the near pavement and at y < W for the far one.
            toward = vy if state.zone == "waiting_zone_left" else -vy if state.zone == "waiting_zone_right" else 0.0
            a = state.attrs
            scene.pedestrians.append(PedestrianInfo(
                track_id=state.track_id, zone=state.zone,
                waiting_s=t - state.zone_since if waiting else 0.0, toward_road_ms=toward,
                walk_speed_ms=a.get("walk_speed"), child=a.get("child"), slow=a.get("slow"), aid=a.get("aid")))
        elif role in veh_roles and state.zone in ROAD_ZONES:
            # Distance to the nearest edge of the stripes, only while driving towards them (else negative).
            d = approach_distance(state, along)
            scene.vehicles.append(VehicleInfo(state.track_id, d=-1.0 if d is None else d, v=abs(vx),
                                              a=state.accel, role=role, x=x, vx=vx))
    return scene


class Pipeline:
    def __init__(self, cfg: dict, frame_rate: float = 0.0, calib: dict | None = None, actuator=None,
                 detector: Detector | None = None, load_detector: bool = True, site: str | None = None):
        """calib: content of calib.json (None = no counting, no rules geometry).
        actuator: where C1/C2 go (None = decide but do not send).
        site: urbano | lungofiume | collina (None = the default of config.yaml).
        """
        from .actuator import Commander   # local import: actuator.py does not depend on the pipeline

        self.cfg = cfg
        self.calib = calib
        self.detector = detector if detector is not None else (Detector(cfg) if load_detector else None)
        self.detect_every_n = max(1, int(cfg["model"]["detect_every_n"]))
        # ByteTrack only sees the frames on which the detector runs.
        self.tracker = Tracker(cfg, frame_rate / self.detect_every_n if frame_rate > 0 else 0.0)
        self.geometry = Geometry(calib, cfg) if calib is not None else None
        self.counter: LineCounter | None = None   # created on the first frame, when the size is known
        self.attributes = AttributeEstimator(cfg, AidClassifier.load(cfg))
        self.rules = RuleEngine(cfg)
        self.animals = AnimalMonitor(cfg, site)
        self.events = EventDetector(cfg)
        self.commander = Commander(actuator, cfg) if actuator is not None else None
        self.selfcheck_every = max(1, int(cfg["selfcheck"]["every_n_frames"]))
        self.fault: str | None = None             # last result of the camera self-check
        self.scene = Scene(W=float(cfg["rules"]["default_W_m"]))
        self._frame = 0
        self._last = sv.Detections.empty()
        self._last_roles: list[str] = []
        self._last_t: float | None = None
        self._last_frame_t: float | None = None
        self._command: dict | None = None
        self._animals: list = []

    def _setup_size(self, width: int, height: int) -> None:
        if self.geometry is not None and self.geometry.width == 0:
            self.geometry.set_frame_size(width, height)
        if self.counter is None and self.calib is not None:
            self.counter = LineCounter(self.cfg, self.calib, (width, height))

    def step(self, frame: np.ndarray, t: float) -> FrameResult:
        """Full step on a camera frame."""
        height, width = frame.shape[:2]
        self._setup_size(width, height)
        run_detector = self._frame % self.detect_every_n == 0
        if self._frame % self.selfcheck_every == 0:
            self.fault = frame_fault(frame, self.cfg)
        detections, detect_ms = None, None
        if run_detector:
            t0 = perf_counter()
            detections = self.detector.detect(frame)
            detect_ms = (perf_counter() - t0) * 1000.0
        return self.process(detections, t, (width, height), frame, detect_ms)

    def process(self, detections: sv.Detections | None, t: float, frame_size: tuple[int, int],
                frame: np.ndarray | None = None, detect_ms: float | None = None) -> FrameResult:
        """Everything after the detector. detections=None holds the last tracks (detector skipped)."""
        self._setup_size(*frame_size)
        self._frame += 1
        self._last_frame_t = t
        lat_ms: dict[str, float | None] = dict.fromkeys(PHASES)
        lat_ms["detect"] = detect_ms
        events: list[dict] = []
        if detections is not None:
            # "track" also covers the per-track bookkeeping: roles, counting, attributes.
            t1 = perf_counter()
            tracked = self.tracker.update(detections, t, self.geometry)
            frame_roles = derive_roles(tracked.xyxy, self.tracker.class_names(tracked), self.cfg)
            roles = self.tracker.vote_roles(tracked, frame_roles)
            valid = self.tracker.valid_mask(tracked)
            self._update_attributes(tracked, roles, t, frame)
            if self.counter is not None:
                events = [self._describe(event) for event in self.counter.update(tracked, roles, valid)]
            self._last, self._last_roles, self._last_t = tracked, roles, t
            lat_ms["track"] = (perf_counter() - t1) * 1000.0

        valid = self.tracker.valid_mask(self._last)
        t2 = perf_counter()
        self.scene = build_scene(self.tracker, self._last, self._last_roles, valid, self.geometry, t, self.cfg)
        self.scene.fault = self.fault
        if detections is not None:
            # "rules" also covers what the rule needs from the trajectories: animals and events.
            self.scene.animals = self.animals.update(self.tracker, self._last, self._last_roles, valid, self.geometry, t)
            self.scene.animal_margin_m = self.animals.margin_m
            self._animals = self.scene.animals
            events += self.events.update(self.tracker, self._last, self._last_roles, valid, self.geometry, t)
        else:
            self.scene.animals, self.scene.animal_margin_m = self._animals, self.animals.margin_m
        self._command = self.rules.step(self.scene, t)
        t3 = perf_counter()
        sent = self.commander.update(self._command) if self.commander is not None else False
        lat_ms["rules"] = (t3 - t2) * 1000.0
        lat_ms["act"] = (perf_counter() - t3) * 1000.0
        return FrameResult(self._last, valid, lat_ms, detections is not None, self._last_roles, events,
                           self._command, sent)

    def no_frame(self, t: float) -> dict:
        """The camera gave no frame: the rule runs on the age of the last one (DEGRADED after the timeout)."""
        age = t - self._last_frame_t if self._last_frame_t is not None else float("inf")
        self.scene = Scene(W=self.scene.W, video_age_s=age)
        self._command = self.rules.step(self.scene, t)
        if self.commander is not None:
            self.commander.update(self._command)
        return self._command

    def _describe(self, event: dict) -> dict:
        """Adds to a crossing what C3 wants to know about who crossed."""
        state = self.tracker.tracks.get(event["track_id"])
        if state is None:
            return event
        if event["cls"] == "pedestrian":
            event["attrs"] = public_attrs(state.attrs)
        elif event["cls"] in ("animal", "bird"):
            event["coco"] = state.class_name
        return event

    def _update_attributes(self, tracked: sv.Detections, roles: list[str], t: float, frame) -> None:
        if tracked.tracker_id is None:
            return
        dt = t - self._last_t if self._last_t is not None else 0.0
        ped_roles = set(self.cfg["rules"]["pedestrian_roles"])
        for xyxy, track_id, role in zip(tracked.xyxy, tracked.tracker_id, roles):
            if role in ped_roles:
                self.attributes.update(self.tracker.tracks[int(track_id)], dt, frame, xyxy)


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
