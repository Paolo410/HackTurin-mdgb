"""Events from the trajectories, no video model: collision, person down, hard braking, near miss,
vehicle standing on the stripes, and whether each approaching vehicle yields to a waiting pedestrian.

Every event is a dict with the fields of contract C3 (v and ts are added by the logger) and is emitted
once per track or per pair of tracks.
"""
from __future__ import annotations

import math

import supervision as sv

from .geometry import Geometry
from .rules import WAITING_ZONES
from .tracking import Tracker, TrackState

ROAD_ZONES = ("carriageway", "crosswalk")
CROSSWALK = "crosswalk"


def approach_distance(state: TrackState, along: float) -> float | None:
    """Distance to the stripes of a vehicle driving towards them, None otherwise."""
    x, vx = state.ground[0], state.velocity[0]
    if x < 0 and vx > 0:
        return -x
    if x > along and vx < 0:
        return x - along
    return None


class EventDetector:
    def __init__(self, cfg: dict):
        self.e = cfg["events"]
        self.vehicle_roles = set(cfg["rules"]["vehicle_roles"])
        self.pedestrian_roles = set(cfg["rules"]["pedestrian_roles"])
        self.vehicle_min = float(cfg["rules"]["vehicle_min_speed_ms"])
        self._done: set[tuple] = set()                 # events already emitted
        self._last_fast: dict[int, float] = {}         # track -> last time it was fast
        self._down_since: dict[int, float] = {}        # track -> time it started lying on the road
        self._stopped_since: dict[int, float] = {}     # track -> time it stopped on the stripes
        self._approach: dict[int, float] = {}          # vehicle -> lowest speed while approaching
        self.yields = {"total": 0, "yielded": 0}
        self.near_misses = 0
        self.incidents = 0

    @property
    def yield_rate(self) -> float | None:
        return self.yields["yielded"] / self.yields["total"] if self.yields["total"] else None

    def summary(self) -> str:
        rate = self.yield_rate
        shown = "-" if rate is None else f"{rate * 100:.0f}% ({self.yields['yielded']}/{self.yields['total']})"
        return f"yield {shown}  near-miss {self.near_misses}  incidents {self.incidents}"

    def update(self, tracker: Tracker, tracked: sv.Detections, roles: list[str], valid, geometry: Geometry | None,
               t: float) -> list[dict]:
        if geometry is None or not geometry.metric or tracked.tracker_id is None:
            return []
        e = self.e
        items: list[tuple[TrackState, str]] = []
        for track_id, role, ok in zip(tracked.tracker_id, roles, valid):
            state = tracker.tracks.get(int(track_id))
            if ok and state is not None and state.ground is not None:
                items.append((state, role))
        vehicles = [(s, r) for s, r in items if r in self.vehicle_roles]
        vulnerable = [(s, r) for s, r in items if r in self.pedestrian_roles or r in ("animal", "bird")]
        events: list[dict] = []

        for state, _ in items:
            if state.speed > float(e["collision_fast_ms"]):
                self._last_fast[state.track_id] = t

        # Hard braking.
        for state, _ in vehicles:
            was_moving = (state.speed >= float(e["hard_brake_min_speed_ms"])
                          or t - self._last_fast.get(state.track_id, -math.inf) <= float(e["collision_window_s"]))
            if state.accel <= -float(e["hard_brake_ms2"]) and was_moving:
                self._incident(events, "hard_brake", state)

        # Person lying on the road.
        for state, role in items:
            if role in self.pedestrian_roles and state.zone in ROAD_ZONES and state.aspect > float(e["person_down_aspect"]):
                since = self._down_since.setdefault(state.track_id, t)
                if t - since > float(e["person_down_time_s"]):
                    self._incident(events, "person_down", state)
            else:
                self._down_since.pop(state.track_id, None)

        # Vehicle standing on the stripes.
        for state, _ in vehicles:
            if state.zone == CROSSWALK and state.speed < float(e["stopped_ms"]):
                since = self._stopped_since.setdefault(state.track_id, t)
                if t - since > float(e["stopped_on_crosswalk_s"]):
                    self._incident(events, "vehicle_on_crosswalk", state)
            else:
                self._stopped_since.pop(state.track_id, None)

        # Collision: two tracks very close, both stopped, and at least one was fast a moment ago.
        for i, (a, role_a) in enumerate(items):
            for b, role_b in items[i + 1:]:
                if role_a not in self.vehicle_roles and role_b not in self.vehicle_roles:
                    continue
                key = ("collision", min(a.track_id, b.track_id), max(a.track_id, b.track_id))
                if key in self._done or math.dist(a.ground, b.ground) >= float(e["collision_distance_m"]):
                    continue
                stopped = a.speed < float(e["collision_stopped_ms"]) and b.speed < float(e["collision_stopped_ms"])
                recent = max(self._last_fast.get(a.track_id, -math.inf), self._last_fast.get(b.track_id, -math.inf))
                if stopped and t - recent <= float(e["collision_window_s"]):
                    self._done.add(key)
                    self.incidents += 1
                    events.append({"type": "incident", "kind": "collision", "track_id": key[1], "other": key[2],
                                   "zone": a.zone})

        # Near miss between a vehicle and a pedestrian or an animal on the road.
        for veh, _ in vehicles:
            for vul, _ in vulnerable:
                key = ("near_miss", vul.track_id, veh.track_id)
                if key in self._done or vul.zone not in ROAD_ZONES:
                    continue
                ttc, pet = self._ttc(veh, vul), self._pet(veh, vul, t)
                if (ttc is not None and ttc < float(e["near_miss_ttc_s"])) or (pet is not None and pet < float(e["near_miss_pet_s"])):
                    self._done.add(key)
                    self.near_misses += 1
                    events.append({"type": "near_miss", "a": vul.track_id, "b": veh.track_id,
                                   "ttc_s": None if ttc is None else round(ttc, 2),
                                   "pet_s": None if pet is None else round(pet, 2)})

        # Yield: every vehicle that arrives while a pedestrian waits either slows below the threshold or not.
        someone_waiting = any(s.zone in WAITING_ZONES for s, r in items if r in self.pedestrian_roles)
        along = geometry.along or 0.0
        for veh, _ in vehicles:
            approaching = veh.zone in ROAD_ZONES and approach_distance(veh, along) is not None
            if approaching:
                if veh.track_id in self._approach:
                    self._approach[veh.track_id] = min(self._approach[veh.track_id], veh.speed)
                elif someone_waiting:
                    self._approach[veh.track_id] = veh.speed
            elif veh.track_id in self._approach:
                yielded = self._approach.pop(veh.track_id) < float(e["yield_speed_ms"])
                self.yields["total"] += 1
                self.yields["yielded"] += int(yielded)
                events.append({"type": "yield", "track_id": veh.track_id, "yielded": yielded})

        self._forget(tracker)
        return events

    def _incident(self, events: list[dict], kind: str, state: TrackState) -> None:
        key = (kind, state.track_id)
        if key not in self._done:
            self._done.add(key)
            self.incidents += 1
            events.append({"type": "incident", "kind": kind, "track_id": state.track_id, "zone": state.zone})

    def _ttc(self, veh: TrackState, vul: TrackState) -> float | None:
        """Time before the vehicle reaches the other track, if it is heading at it."""
        if veh.speed < self.vehicle_min:
            return None
        dx, dy = vul.ground[0] - veh.ground[0], vul.ground[1] - veh.ground[1]
        ux, uy = veh.velocity[0] / veh.speed, veh.velocity[1] / veh.speed
        ahead = dx * ux + dy * uy
        aside = abs(dx * uy - dy * ux)
        if ahead <= 0 or aside > float(self.e["near_miss_lateral_m"]):
            return None
        return ahead / veh.speed

    def _pet(self, veh: TrackState, vul: TrackState, t: float) -> float | None:
        """Post-encroachment time: how long after one left a point the other arrived there."""
        radius = float(self.e["pet_radius_m"])
        best = None
        for here, other in ((veh, vul), (vul, veh)):
            if math.dist(here.ground, other.ground) <= radius:
                continue   # still together at this point: not "after"
            for past_t, x, y in reversed(other.ground_history):
                if math.dist(here.ground, (x, y)) <= radius:
                    gap = t - past_t
                    if gap > 0 and (best is None or gap < best):
                        best = gap
                    break
        return best

    def _forget(self, tracker: Tracker) -> None:
        alive = tracker.tracks.keys()
        for table in (self._last_fast, self._down_since, self._stopped_since, self._approach):
            for track_id in [i for i in table if i not in alive]:
                del table[track_id]
