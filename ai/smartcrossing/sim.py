"""Scripted scenes without a camera: actors move on the ground and become detections.

Everything after the detector runs for real (tracker, geometry, counting, attributes, rules, actuator),
so a scenario shows and tests the whole chain, and can drive the real firmware through an actuator.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np
import supervision as sv

from .detector import COCO_CLASSES
from .geometry import Geometry, build_metric_calib
from .pipeline import Pipeline

FRAME_SIZE = (1281, 721)   # width, height of the virtual camera
# The stripes as the virtual camera sees them from the pavement: near kerb (1, 2), far kerb (3, 4).
DEMO_CORNERS = [[0.40, 0.80], [0.60, 0.80], [0.57, 0.50], [0.43, 0.50]]
DEMO_ALONG_M, DEMO_WIDTH_M = 4.0, 7.0
KMH = 3.6


@dataclass
class Actor:
    coco_class: str                                         # person, car, dog, ...
    height_m: float
    width_m: float
    path: Callable[[float], tuple[float, float] | None]     # t -> ground position, None = not in the scene


def demo_calib(cfg: dict) -> dict:
    return build_metric_calib(DEMO_CORNERS, DEMO_ALONG_M, DEMO_WIDTH_M, cfg)


def detections_at(actors: list[Actor], t: float, geometry: Geometry) -> sv.Detections:
    """The boxes a perfect detector would give at time t."""
    boxes, classes = [], []
    for actor in actors:
        position = actor.path(t)
        if position is None:
            continue
        fx, fy = geometry.to_image(*position)
        scale = geometry.pixels_per_metre(fx, fy)
        half, high = actor.width_m * scale / 2, actor.height_m * scale
        boxes.append([fx - half, fy - high, fx + half, fy])
        classes.append(COCO_CLASSES.index(actor.coco_class))
    if not boxes:
        return sv.Detections.empty()
    return sv.Detections(xyxy=np.array(boxes, dtype=np.float32),
                         confidence=np.full(len(boxes), 0.9, dtype=np.float32),
                         class_id=np.array(classes))


def walk_then_wait(start: tuple[float, float], stop: tuple[float, float], speed: float, t0: float = 0.0):
    """Walks from start to stop at the given speed, then stands there."""
    dx, dy = stop[0] - start[0], stop[1] - start[1]
    duration = (dx * dx + dy * dy) ** 0.5 / speed

    def path(t: float):
        if t < t0:
            return None
        k = min(1.0, (t - t0) / duration) if duration > 0 else 1.0
        return start[0] + dx * k, start[1] + dy * k
    return path


def drive(x0: float, y: float, speed: float, t0: float = 0.0, x_end: float | None = None):
    """Drives along the road (x) at constant speed from x0, from time t0."""
    def path(t: float):
        if t < t0:
            return None
        x = x0 + speed * (t - t0)
        if x_end is not None and (x - x_end) * speed > 0:
            return None
        return x, y
    return path


def elderly_and_fast_car() -> tuple[list[Actor], float]:
    """A slow pedestrian reaches the kerb and waits; a car arrives at 50 km/h without braking."""
    pedestrian = Actor("person", 1.65, 0.5, walk_then_wait((-0.8, -0.7), (2.0, -0.7), speed=0.8))
    car = Actor("car", 1.5, 4.4, drive(x0=-110.0, y=1.75, speed=50 / KMH, t0=4.0, x_end=40.0))
    return [pedestrian, car], 16.0


def pedestrian_crossing() -> tuple[list[Actor], float]:
    """A pedestrian waits, crosses the road on the stripes and leaves: one crossing, no vehicle."""
    def path(t: float):
        if t < 2.0:
            return 2.0, -0.7                       # waiting on the near pavement
        y = -0.7 + 1.2 * (t - 2.0)
        return (2.0, y) if y < 9.0 else None       # across the 7 m road and away
    return [Actor("person", 1.75, 0.5, path)], 12.0


SCENARIOS = {"elderly_fast_car": elderly_and_fast_car, "pedestrian_crossing": pedestrian_crossing}


def run_scenario(cfg: dict, name: str, fps: float = 10.0, actuator=None, realtime: bool = False,
                 on_step: Callable[[float, dict, Pipeline], None] | None = None) -> Pipeline:
    """Runs a scenario through the pipeline (no detector). Returns the pipeline for inspection."""
    actors, duration = SCENARIOS[name]()
    pipeline = Pipeline(cfg, frame_rate=fps, calib=demo_calib(cfg), actuator=actuator, load_detector=False)
    pipeline._setup_size(*FRAME_SIZE)
    if pipeline.commander is not None and realtime:
        pipeline.commander.start()
    start = time.monotonic()
    for i in range(int(duration * fps) + 1):
        t = i / fps
        if realtime:
            delay = start + t - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        result = pipeline.process(detections_at(actors, t, pipeline.geometry), t, FRAME_SIZE)
        if on_step is not None:
            on_step(t, result.command, pipeline)
    return pipeline
