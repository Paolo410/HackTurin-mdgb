"""Directional counting on the calibrated lines, without double counts.

supervision.LineZone (verified on the pinned supervision 0.30.5):
https://supervision.roboflow.com/latest/detection/tools/line_zone/
- the anchor is the bottom centre of the box (where the object touches the ground);
- minimum_crossing_threshold frames on the other side are needed before a crossing counts, so a track
  that jitters on the line is not counted;
- on top of that, every track is counted at most once per direction on each line.
"""
from __future__ import annotations

import numpy as np
import supervision as sv

from .geometry import to_pixels

DIRECTIONS = ("in", "out")


class LineCounter:
    """Counts the crossings of the calibrated lines ("ped" along the stripes, "veh" across the lane)."""

    def __init__(self, cfg: dict, calib: dict, frame_size: tuple[int, int]):
        """frame_size is (width, height) of the frames given to the tracker."""
        c = cfg["counting"]
        width, height = frame_size
        self.lines: dict[str, dict] = {}
        for name, classes in c["lines"].items():
            spec = (calib.get("lines") or {}).get(name)
            if spec is None:
                continue   # line not calibrated: not counted
            start, end = to_pixels(spec["start"], width, height), to_pixels(spec["end"], width, height)
            self.lines[name] = {
                "start": start,
                "end": end,
                "classes": set(classes),
                "zone": sv.LineZone(
                    start=sv.Point(*start),
                    end=sv.Point(*end),
                    triggering_anchors=[sv.Position.BOTTOM_CENTER],
                    minimum_crossing_threshold=int(c["minimum_crossing_threshold"]),
                ),
            }
        # counts[line][role] = {"in": n, "out": n}
        self.counts: dict[str, dict[str, dict[str, int]]] = {name: {} for name in self.lines}
        self._counted: set[tuple[str, int, str]] = set()

    def update(self, tracked: sv.Detections, roles: list[str], valid: np.ndarray) -> list[dict]:
        """Feeds one frame. Returns the new crossings as C3-like dicts (type, track_id, cls, dir, line)."""
        events: list[dict] = []
        if tracked.tracker_id is None or len(tracked) == 0:
            return events
        roles_arr = np.asarray(roles, dtype=object)
        for name, line in self.lines.items():
            # Only valid tracks of the classes this line counts.
            mask = valid & np.isin(roles_arr, list(line["classes"]))
            if not mask.any():
                continue
            subset = tracked[mask]
            crossed_in, crossed_out = line["zone"].trigger(subset)
            for direction, crossed in zip(DIRECTIONS, (crossed_in, crossed_out)):
                for idx in np.flatnonzero(crossed):
                    track_id = int(subset.tracker_id[idx])
                    key = (name, track_id, direction)
                    if key in self._counted:
                        continue   # at most once per direction
                    self._counted.add(key)
                    role = str(roles_arr[mask][idx])
                    self.counts[name].setdefault(role, {d: 0 for d in DIRECTIONS})[direction] += 1
                    events.append({"type": "crossing", "track_id": track_id, "cls": role,
                                   "dir": direction, "line": name})
        return events

    def totals(self, name: str) -> dict[str, int]:
        """IN and OUT of a line, all classes together."""
        return {d: sum(per_role[d] for per_role in self.counts[name].values()) for d in DIRECTIONS}

    def summary(self) -> str:
        """One line per counting line, for the screen and the terminal."""
        parts = []
        for name in self.lines:
            total = self.totals(name)
            detail = "  ".join(f"{role} {c['in']}/{c['out']}" for role, c in sorted(self.counts[name].items()))
            parts.append(f"{name}: IN {total['in']} OUT {total['out']}" + (f"  ({detail})" if detail else ""))
        return " | ".join(parts) if parts else "no counting lines"
