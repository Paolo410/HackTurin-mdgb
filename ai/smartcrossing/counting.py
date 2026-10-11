"""Directional counting on the calibrated lines, without double counts.

supervision.LineZone (verified on the pinned supervision 0.30.5):
https://supervision.roboflow.com/latest/detection/tools/line_zone/
- the anchor is the bottom centre of the box (where the object touches the ground);
- minimum_crossing_threshold frames on the other side are needed before a crossing counts, so a track
  that jitters on the line is not counted;
- on top of that, every track is counted at most once per direction on each line.
LineZone forgets the side of a track after it misses crossing_history_length (= threshold + 1) frames: a car hidden
by a pole for 4 detector frames came back with the same ID but no memory, and its crossing was lost. Here the side
is kept for side_memory frames (the life of a lost track in ByteTrack), see _SideKeepingLineZone.

Stitching (counting.stitch_s > 0): a track lost close to the line while heading for it, and a new track that appears
just past the line where the lost one was going, within stitch_s seconds, are one object going over the line (hidden
by a pole, or given a new ID by the tracker). The crossing is counted once, on the new track, and both tracks are
marked as counted in that direction so LineZone does not count it again. Tracklet linking by motion, as in offline
multi-object tracking, restricted to the few metres around the line.
"""
from __future__ import annotations

import numpy as np
import supervision as sv

from .geometry import in_direction, to_pixels

DIRECTIONS = ("in", "out")
PEOPLE = {"pedestrian", "cyclist"}     # the same person may be voted one or the other by two tracks


class _SideKeepingLineZone(sv.LineZone):
    """sv.LineZone that keeps the side of an unseen track for max_absent frames instead of threshold + 1.

    Overrides a private method of the pinned supervision 0.30.5 (same code, other limit): covered by
    tests/test_counting.py::test_track_hidden_on_the_line_still_counts.
    """

    def __init__(self, *args, max_absent: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_absent = max(int(max_absent), self.crossing_history_length)

    def _evict_stale_crossing_history(self, current_keys: set[int]) -> None:
        for key in list(self.crossing_state_history):
            if key in current_keys:
                self._tracker_frames_absent.pop(key, None)
                continue
            absent = self._tracker_frames_absent.get(key, 0) + 1
            if absent >= self.max_absent:
                del self.crossing_state_history[key]
                self._confirmed_crossing_side.pop(key, None)
                self._tracker_frames_absent.pop(key, None)
            else:
                self._tracker_frames_absent[key] = absent


class LineCounter:
    """Counts the crossings of the calibrated lines ("ped" along the stripes, "veh" across the lane)."""

    def __init__(self, cfg: dict, calib: dict, frame_size: tuple[int, int]):
        """frame_size is (width, height) of the frames given to the tracker."""
        c = cfg["counting"]
        width, height = frame_size
        # 0 = supervision's own limit (threshold + 1 frames)
        side_memory = int(c.get("side_memory", 0))
        self.stitch_s = float(c.get("stitch_s", 0.0))            # 0 = no stitching
        self.stitch_radius = float(c.get("stitch_radius", 1.0))  # tolerance around the expected point, box heights
        self.stitch_band = float(c.get("stitch_band", 2.0))      # how close to the line both ends must be, box heights
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
                "normal": in_direction(start, end),
                "zone": _SideKeepingLineZone(
                    start=sv.Point(*start),
                    end=sv.Point(*end),
                    triggering_anchors=[sv.Position.BOTTOM_CENTER],
                    minimum_crossing_threshold=int(c["minimum_crossing_threshold"]),
                    max_absent=side_memory,
                ),
            }
        # counts[line][role] = {"in": n, "out": n}
        self.counts: dict[str, dict[str, dict[str, int]]] = {name: {} for name in self.lines}
        self._counted: set[tuple[str, int, str]] = set()
        # per line: track id -> last observation {"t", "x", "y", "h", "vx", "vy", "side", "role", "used"}
        self._seen: dict[str, dict[int, dict]] = {name: {} for name in self.lines}

    def update(self, tracked: sv.Detections, roles: list[str], valid: np.ndarray, t: float | None = None,
               born: dict[int, float] | None = None) -> list[dict]:
        """Feeds one frame. Returns the new crossings as C3-like dicts (type, track_id, cls, dir, line).

        t (seconds) and born (track id -> time the track was first seen) are needed for the stitching only."""
        events: list[dict] = []
        if tracked.tracker_id is None or len(tracked) == 0:
            return events
        roles_arr = np.asarray(roles, dtype=object)
        stitching = self.stitch_s > 0 and t is not None
        for name, line in self.lines.items():
            # Only valid tracks of the classes this line counts.
            mask = valid & np.isin(roles_arr, list(line["classes"]))
            if not mask.any():
                continue
            subset = tracked[mask]
            subset_roles = roles_arr[mask]
            if stitching:
                for track_id, direction, role in self._stitch(name, line, subset, subset_roles, t, born or {}):
                    self._count(name, track_id, direction, role, events)
            crossed_in, crossed_out = line["zone"].trigger(subset)
            for direction, crossed in zip(DIRECTIONS, (crossed_in, crossed_out)):
                for idx in np.flatnonzero(crossed):
                    self._count(name, int(subset.tracker_id[idx]), direction, str(subset_roles[idx]), events)
        return events

    def _count(self, name: str, track_id: int, direction: str, role: str, events: list[dict]) -> None:
        key = (name, track_id, direction)
        if key in self._counted:
            return   # at most once per direction
        self._counted.add(key)
        self.counts[name].setdefault(role, {d: 0 for d in DIRECTIONS})[direction] += 1
        events.append({"type": "crossing", "track_id": track_id, "cls": role, "dir": direction, "line": name})

    def _stitch(self, name: str, line: dict, subset: sv.Detections, roles, t: float, born: dict[int, float]):
        """Updates the last observation of each track near this line and yields (new track id, direction, role) for
        every new track that continues a lost one across the line."""
        seen = self._seen[name]
        nx, ny = line["normal"]                                    # unit vector pointing to the IN side
        (sx, sy), (ex, ey) = line["start"], line["end"]
        length = max(((ex - sx) ** 2 + (ey - sy) ** 2) ** 0.5, 1.0)
        ux, uy = (ex - sx) / length, (ey - sy) / length            # along the line
        current = {int(i) for i in subset.tracker_id}
        found = []
        for xyxy, track_id, role in zip(subset.xyxy, subset.tracker_id, roles):
            track_id, role = int(track_id), str(role)
            x, y, h = float((xyxy[0] + xyxy[2]) / 2), float(xyxy[3]), max(float(xyxy[3] - xyxy[1]), 1.0)
            dist = (x - sx) * nx + (y - sy) * ny                   # signed distance from the line, pixels
            side = 1 if dist > 0 else -1
            prev = seen.get(track_id)
            if prev is None:
                lost = self._lost_match(seen, current, x, y, h, side, dist, role, t, born.get(track_id, t),
                                        (nx, ny), (sx, sy), (ux, uy), length)
                if lost is not None:
                    lost["used"] = True
                    direction = "in" if side > 0 else "out"
                    self._counted.add((name, lost["id"], direction))   # the lost track cannot count it again
                    found.append((track_id, direction, role))
                vx = vy = 0.0
            else:
                dt = t - prev["t"]
                if dt <= 0:
                    vx, vy = prev["vx"], prev["vy"]
                else:
                    a = 0.5                                        # light smoothing of the pixel velocity
                    vx = prev["vx"] + a * ((x - prev["x"]) / dt - prev["vx"]) if prev["n"] else (x - prev["x"]) / dt
                    vy = prev["vy"] + a * ((y - prev["y"]) / dt - prev["vy"]) if prev["n"] else (y - prev["y"]) / dt
            n = prev["n"] + 1 if prev is not None and t > prev["t"] else (prev["n"] if prev else 0)
            seen[track_id] = {"id": track_id, "t": t, "x": x, "y": y, "h": h, "vx": vx, "vy": vy, "side": side,
                              "dist": dist, "role": role, "n": n, "used": bool(prev and prev.get("used"))}
        for track_id in [i for i, o in seen.items() if t - o["t"] > self.stitch_s]:
            del seen[track_id]
        return found

    def _lost_match(self, seen, current, x, y, h, side, dist, role, t, born_t, normal, start, along, length):
        """The lost track that this new one continues across the line, or None."""
        if abs(dist) > self.stitch_band * h:
            return None                                            # the new track starts far from the line
        best, best_score = None, 1.0
        for old in seen.values():
            if old["id"] in current or old["used"] or old["side"] == side or old["n"] < 1:
                continue
            gap = t - old["t"]
            if gap <= 0 or gap > self.stitch_s or born_t < old["t"] - 0.5:
                continue                                           # the new track must start after the old one
            if old["role"] != role and not {old["role"], role} <= PEOPLE:
                continue
            if abs(old["dist"]) > self.stitch_band * old["h"]:
                continue                                           # lost far from the line
            toward = (old["vx"] * normal[0] + old["vy"] * normal[1]) * -old["side"]
            if toward <= 0.3 * old["h"]:
                continue                                           # it was not heading for the line
            along_pos = (old["x"] - start[0]) * along[0] + (old["y"] - start[1]) * along[1]
            if along_pos < -old["h"] or along_pos > length + old["h"]:
                continue                                           # beyond the ends of the line
            px, py = old["x"] + old["vx"] * gap, old["y"] + old["vy"] * gap
            score = ((px - x) ** 2 + (py - y) ** 2) ** 0.5 / (self.stitch_radius * max(old["h"], h))
            if score < best_score:
                best, best_score = old, score
        return best

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
