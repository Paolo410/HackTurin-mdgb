"""Animals near the crossing: size, leash, herd. The alarm itself is decided in rules.py.

- size from the calibration: large (length >= 0.8 m or height >= 0.6 m), medium (0.3-0.8 m), small (log only);
- on a leash: a person within 2 m, moving in a similar direction, for at least 1 s -> no alarm of its own;
- herd: animals within 3 m of each other;
- a bird counts only on some sites, on the road, long enough (goose or swan, not a pigeon) and for more than 2 s;
- the site (--site) says which COCO classes can raise an alarm. The original COCO class is always kept.
"""
from __future__ import annotations

import math
from statistics import median

import supervision as sv

from .geometry import Geometry
from .rules import AnimalInfo
from .tracking import Tracker

ROAD_ZONES = ("carriageway", "crosswalk")


def size_class(length_m: float | None, height_m: float | None, cfg: dict) -> str:
    a = cfg["animals"]
    length, height = length_m or 0.0, height_m or 0.0
    if length >= float(a["large_length_m"]) or height >= float(a["large_height_m"]):
        return "large"
    if length >= float(a["medium_length_m"]):
        return "medium"
    return "small"


def similar_direction(v1: tuple[float, float], v2: tuple[float, float], max_angle_deg: float, still_ms: float) -> bool:
    """True when the two velocities point the same way, or when either is standing still."""
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 < still_ms or n2 < still_ms:
        return True
    cos = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return cos >= math.cos(math.radians(max_angle_deg))


class AnimalMonitor:
    def __init__(self, cfg: dict, site: str | None = None):
        self.cfg = cfg
        self.site_name = site or cfg["site"]
        site_cfg = cfg["sites"][self.site_name]
        self.alarm_classes = set(site_cfg["animal_classes"])
        self.birds = bool(site_cfg["birds"])
        self.margin_m = float(site_cfg["animal_margin_m"])
        a = cfg["animals"]
        self.leash_distance = float(a["leash_distance_m"])
        self.leash_angle = float(a["leash_angle_deg"])
        self.leash_time = float(a["leash_time_s"])
        self.herd_distance = float(a["herd_distance_m"])
        self.bird_min_length = float(a["bird_min_length_m"])
        self.bird_min_time = float(a["bird_min_time_s"])
        self.still = float(cfg["attributes"]["moving_min_speed_ms"])
        self._near_since: dict[int, tuple[int, float]] = {}   # animal id -> (person id, since)
        self._road_since: dict[int, float] = {}               # bird id -> time it entered the road
        self.logged: set[int] = set()                         # tracks already written to the log
        self.groups: dict[int, int] = {}                      # animal id -> person id (leash)
        self.herds: dict[int, int] = {}                       # animal id -> herd id

    def update(self, tracker: Tracker, tracked: sv.Detections, roles: list[str], valid, geometry: Geometry | None,
               t: float) -> list[AnimalInfo]:
        """The animals that the rule must consider on this frame."""
        if geometry is None or not geometry.metric or tracked.tracker_id is None:
            return []
        people, animals = [], []
        for track_id, role, ok in zip(tracked.tracker_id, roles, valid):
            state = tracker.tracks.get(int(track_id))
            if not ok or state is None or state.ground is None:
                continue
            if role == "pedestrian":
                people.append(state)
            elif role in ("animal", "bird"):
                animals.append((state, role))

        infos: list[AnimalInfo] = []
        positions: dict[int, tuple[float, float]] = {}
        self.groups = {}
        seen = set()
        for state, role in animals:
            seen.add(state.track_id)
            coco = state.class_name
            on_road = state.zone in ROAD_ZONES
            height = median(state.heights) if state.heights else None
            size = size_class(state.length_m, height, self.cfg)

            if role == "bird":
                if not on_road:
                    self._road_since.pop(state.track_id, None)
                    continue
                since = self._road_since.setdefault(state.track_id, t)
                if not self.birds or (state.length_m or 0.0) < self.bird_min_length or t - since <= self.bird_min_time:
                    continue
            elif coco not in self.alarm_classes:
                continue   # this site ignores the class (it stays in the counts and in the log)

            free = not self._on_leash(state, people, t)
            positions[state.track_id] = state.ground
            infos.append(AnimalInfo(track_id=state.track_id, coco=coco, size=size, on_road=on_road, free=free,
                                    x=state.ground[0], length_m=state.length_m))
        for gone in [i for i in self._near_since if i not in seen]:
            del self._near_since[gone]

        # Herds: free animals closer than herd_distance, chained (A near B, B near C -> one herd).
        self.herds = {}
        loose = [i for i in infos if i.free]
        for info in loose:
            self.herds.setdefault(info.track_id, info.track_id)
            for other in loose:
                if other.track_id != info.track_id and math.dist(positions[info.track_id], positions[other.track_id]) <= self.herd_distance:
                    a, b = self.herds[info.track_id], self.herds.setdefault(other.track_id, other.track_id)
                    if a != b:
                        for key, value in self.herds.items():
                            if value == b:
                                self.herds[key] = a
        for info in loose:
            info.herd_size = sum(1 for value in self.herds.values() if value == self.herds[info.track_id])
        return infos

    def _on_leash(self, animal, people, t: float) -> bool:
        """A person close by and going the same way for long enough."""
        for person in people:
            if (math.dist(animal.ground, person.ground) <= self.leash_distance
                    and similar_direction(animal.velocity, person.velocity, self.leash_angle, self.still)):
                previous = self._near_since.get(animal.track_id)
                since = previous[1] if previous and previous[0] == person.track_id else t
                self._near_since[animal.track_id] = (person.track_id, since)
                if t - since >= self.leash_time:
                    self.groups[animal.track_id] = person.track_id
                    return True
                return False
        self._near_since.pop(animal.track_id, None)
        return False

    def new_sightings(self, infos: list[AnimalInfo]) -> list[AnimalInfo]:
        """Animals seen for the first time: one log line each (small ones never raise an alarm)."""
        fresh = [i for i in infos if i.track_id not in self.logged]
        self.logged.update(i.track_id for i in fresh)
        return fresh
