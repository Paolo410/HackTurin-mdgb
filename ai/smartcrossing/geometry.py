"""Calibration file (calib.json) and geometry: image <-> ground metres, zones, local scale.

Everything in the file is independent of the frame size:
- "lines": counting lines in normalized image coordinates (0..1, may go outside);
- "homography": 3x3 matrix from normalized image coordinates to ground metres;
- "W": road width in metres (kerb to kerb); "along": size of the crossing along the road;
- "zones": polygons in ground metres (crosswalk, carriageway, waiting_zone_left, waiting_zone_right).

Ground frame: origin on the first clicked corner of the stripes, x along the road, y across it
(y = 0 on the near kerb, y = W on the far kerb).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .config import resolve_path

CALIB_VERSION = 1
# Zones checked in this order: the crosswalk lies inside the carriageway.
ZONE_ORDER = ("crosswalk", "waiting_zone_left", "waiting_zone_right", "carriageway")


def load_calib(cfg: dict, path: str | Path | None = None) -> tuple[dict, Path]:
    """Loads the calibration. Without an explicit path: calib.json, else the committed example.

    Returns (calibration, path actually read).
    """
    c = cfg["counting"]
    if path is not None:
        candidates = [Path(path)]
    else:
        candidates = [resolve_path(c["calib_path"]), resolve_path(c["example_calib_path"])]
    for candidate in candidates:
        if candidate.is_file():
            with open(candidate, "r", encoding="utf-8") as fh:
                return json.load(fh), candidate
    raise FileNotFoundError(f"Calibration not found: {', '.join(str(p) for p in candidates)}")


def save_calib(calib: dict, path: str | Path) -> None:
    calib = {"v": CALIB_VERSION, **{k: v for k, v in calib.items() if k != "v"}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(calib, fh, indent=2)
        fh.write("\n")


def to_pixels(point: list[float], width: int, height: int) -> tuple[int, int]:
    """Normalized (x, y) -> pixel coordinates of a frame of the given size."""
    return int(round(point[0] * (width - 1))), int(round(point[1] * (height - 1)))


def to_normalized(point: tuple[float, float], width: int, height: int) -> list[float]:
    return [round(point[0] / (width - 1), 4), round(point[1] / (height - 1), 4)]


def in_direction(start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
    """Unit vector (image coordinates) of the movement counted as IN across the line start -> end.

    Matches supervision.LineZone (checked by a test): for a line drawn top to bottom, IN is left to right.
    Swap start and end to swap IN and OUT.
    """
    vx, vy = end[0] - start[0], end[1] - start[1]
    norm = (vx * vx + vy * vy) ** 0.5
    if norm == 0:
        raise ValueError("A counting line needs two different points")
    return vy / norm, -vx / norm


def find_homography(src: list[list[float]], dst: list[list[float]]) -> np.ndarray:
    """3x3 homography that maps the 4 src points onto the 4 dst points (direct linear transform)."""
    if len(src) != 4 or len(dst) != 4:
        raise ValueError("Exactly 4 point pairs are needed")
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    h = np.linalg.solve(np.array(rows, dtype=np.float64), np.array(rhs, dtype=np.float64))
    return np.append(h, 1.0).reshape(3, 3)


def apply_homography(matrix: np.ndarray, x: float, y: float) -> tuple[float, float]:
    u, v, w = matrix @ np.array([x, y, 1.0])
    return float(u / w), float(v / w)


def point_in_polygon(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray casting. Points on the boundary count as inside for our rectangles' lower edges."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def build_metric_calib(corners_norm: list[list[float]], along_m: float, width_m: float, cfg: dict) -> dict:
    """Calibration from the 4 corners of the stripes and their two sizes in metres.

    corners_norm: normalized image points, in order: the two corners on the near kerb (1, 2), then the
    two on the far kerb going around (3 opposite to 2, 4 opposite to 1).
    along_m: distance 1-2 (size of the crossing along the road); width_m: distance 2-3 (road width W).
    Zones and counting lines are derived from these, with the margins of config.yaml.
    """
    g = cfg["geometry"]
    a, w = float(along_m), float(width_m)
    if a <= 0 or w <= 0:
        raise ValueError("Sizes must be positive")
    ground = [[0.0, 0.0], [a, 0.0], [a, w], [0.0, w]]
    homography = find_homography(corners_norm, ground)
    to_image = np.linalg.inv(homography)

    m, depth, extent = float(g["waiting_zone_margin_m"]), float(g["waiting_zone_depth_m"]), float(g["carriageway_extent_m"])
    zones = {
        "crosswalk": ground,
        "carriageway": [[-extent, 0.0], [a + extent, 0.0], [a + extent, w], [-extent, w]],
        "waiting_zone_left": [[-m, -depth], [a + m, -depth], [a + m, 0.0], [-m, 0.0]],
        "waiting_zone_right": [[-m, w], [a + m, w], [a + m, w + depth], [-m, w + depth]],
    }

    def image_point(x: float, y: float) -> list[float]:
        u, v = apply_homography(to_image, x, y)
        return [round(u, 4), round(v, 4)]

    lm, offset = float(g["ped_line_margin_m"]), float(g["veh_line_offset_m"])
    lines = {
        # Along the stripes, in the middle of the road: crossed by who walks across.
        "ped": {"start": image_point(-lm, w / 2), "end": image_point(a + lm, w / 2)},
        # Across the road, just before the stripes: crossed by who drives along.
        "veh": {"start": image_point(-offset, 0.0), "end": image_point(-offset, w)},
    }
    return {
        "v": CALIB_VERSION,
        "corners": [[round(c[0], 4), round(c[1], 4)] for c in corners_norm],
        "along": a,
        "W": w,
        "homography": [[float(x) for x in row] for row in homography],
        "zones": zones,
        "lines": lines,
    }


class Geometry:
    """Metric view of one camera. Without a homography in the calibration, metric is False."""

    def __init__(self, calib: dict, cfg: dict):
        self.cfg = cfg
        self.metric = "homography" in calib
        self.width = self.height = 0
        self.zones: dict[str, list[list[float]]] = calib.get("zones") or {}
        self.W = float(calib["W"]) if "W" in calib else None
        self.along = float(calib["along"]) if "along" in calib else None
        if self.metric:
            self._to_ground = np.array(calib["homography"], dtype=np.float64)
            self._to_image = np.linalg.inv(self._to_ground)

    def set_frame_size(self, width: int, height: int) -> None:
        self.width, self.height = int(width), int(height)

    def to_ground(self, x_px: float, y_px: float) -> tuple[float, float]:
        """Image pixel (a point on the ground, e.g. the bottom centre of a box) -> metres."""
        return apply_homography(self._to_ground, x_px / (self.width - 1), y_px / (self.height - 1))

    def to_image(self, x_m: float, y_m: float) -> tuple[float, float]:
        u, v = apply_homography(self._to_image, x_m, y_m)
        return u * (self.width - 1), v * (self.height - 1)

    def pixels_per_metre(self, x_px: float, y_px: float) -> float:
        """Image pixels covered by one metre at this ground point, measured across the image.

        Used to turn the size of a box into metres: an object standing at this point is at the same
        distance from the camera as the ground under it.
        """
        probe = float(self.cfg["geometry"]["scale_probe_px"])
        ax, ay = self.to_ground(x_px - probe, y_px)
        bx, by = self.to_ground(x_px + probe, y_px)
        metres = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        return 2 * probe / metres if metres > 0 else 0.0

    def size_in_metres(self, size_px: float, x_px: float, y_px: float) -> float | None:
        """Height or length of a box in metres, from its size in pixels and its foot point."""
        scale = self.pixels_per_metre(x_px, y_px)
        if scale <= 0:
            return None
        return size_px / scale * float(self.cfg["geometry"]["height_scale"])

    def zone_of(self, x_m: float, y_m: float) -> str | None:
        for name in ZONE_ORDER:
            polygon = self.zones.get(name)
            if polygon and point_in_polygon(x_m, y_m, polygon):
                return name
        return None
