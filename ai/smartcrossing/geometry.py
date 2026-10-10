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


def camera_from_homography(ground_to_pixels: np.ndarray, width: int, height: int, tolerance: float) -> dict | None:
    """Where the camera is and how it looks, worked out from the ground calibration alone.

    Assumes a normal lens: square pixels, optical axis through the centre of the image (a webcam, a phone;
    not a picture cropped on one side). With that, the homography of a flat ground fixes the focal length
    and the pose (Zhang, "A flexible new technique for camera calibration", 2000, section 3.1: the two
    constraints on the first two columns). Returns None when the two constraints disagree by more than
    tolerance: the four points or the two sizes are not those of a real rectangle seen by such a camera,
    or the view is so far and narrow that the perspective says nothing.
    """
    centre = np.array([[1.0, 0.0, -(width - 1) / 2], [0.0, 1.0, -(height - 1) / 2], [0.0, 0.0, 1.0]])
    h = centre @ ground_to_pixels
    h1, h2 = h[:, 0], h[:, 1]
    # r1 . r2 = 0 and |r1| = |r2|, both linear in 1 / focal^2.
    a = np.array([h1[0] * h2[0] + h1[1] * h2[1], h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
    b = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    if not a @ a > 0:
        return None
    inv_f2 = -(a @ b) / (a @ a)
    if not inv_f2 > 0:
        return None
    focal = inv_f2 ** -0.5
    m = np.diag([1.0 / focal, 1.0 / focal, 1.0]) @ h
    n1, n2 = np.linalg.norm(m[:, 0]), np.linalg.norm(m[:, 1])
    if abs(m[:, 0] @ m[:, 1]) / (n1 * n2) > tolerance or abs(n1 / n2 - 1.0) > tolerance:
        return None
    scale = 2.0 / (n1 + n2)
    if m[2, 2] * scale < 0:          # the ground origin must be in front of the camera
        scale = -scale
    r1, r2, t = m[:, 0] * scale, m[:, 1] * scale, m[:, 2] * scale
    up = np.cross(r1, r2)
    up /= np.linalg.norm(up)
    if up @ t > 0:                   # the camera is above the ground, whichever way the corners were clicked
        up = -up
    return {
        "focal_px": float(focal),
        "height_m": float(-(up @ t)),
        "ground": h * scale,                                        # (x, y, 1) in metres -> centred pixels
        "up": np.array([focal * up[0], focal * up[1], up[2]]),      # what one metre of height adds to it
    }


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


def build_metric_calib(corners_norm: list[list[float]], along_m: float, width_m: float, cfg: dict,
                       ground: list[list[float]] | None = None) -> dict:
    """Calibration from the 4 corners of the stripes and their two sizes in metres.

    corners_norm: normalized image points, in order: the two corners on the near kerb (1, 2), then the
    two on the far kerb going around (3 opposite to 2, 4 opposite to 1).
    along_m: distance 1-2 (size of the crossing along the road); width_m: distance 2-3 (road width W).
    Zones and counting lines are derived from these, with the margins of config.yaml.

    ground: where the 4 points really are, in metres, when they are not the corners of the whole crossing
    (a kerb hidden by a pole, a crossing that leaves the image). Then along_m and width_m still describe
    the whole crossing, from kerb to kerb.
    """
    g = cfg["geometry"]
    a, w = float(along_m), float(width_m)
    if a <= 0 or w <= 0:
        raise ValueError("Sizes must be positive")
    crossing = [[0.0, 0.0], [a, 0.0], [a, w], [0.0, w]]
    homography = find_homography(corners_norm, ground if ground is not None else crossing)
    ground = crossing
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

    lm = float(g["ped_line_margin_m"])
    # Vehicle line: through the middle of the stripes ("middle"), where vehicles of both directions are
    # fully in view, or a number of metres before the stripes.
    veh_x = a / 2 if g["veh_line_offset_m"] == "middle" else -float(g["veh_line_offset_m"])
    lines = {
        # Along the stripes, in the middle of the road: crossed by who walks across.
        "ped": {"start": image_point(-lm, w / 2), "end": image_point(a + lm, w / 2)},
        # Across the road: crossed by who drives along.
        "veh": {"start": image_point(veh_x, -lm / 2), "end": image_point(veh_x, w + lm / 2)},
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
        self.camera: dict | None = None   # focal length and height of the camera, when the calibration gives them
        self.zones: dict[str, list[list[float]]] = calib.get("zones") or {}
        self.W = float(calib["W"]) if "W" in calib else None
        self.along = float(calib["along"]) if "along" in calib else None
        if self.metric:
            self._to_ground = np.array(calib["homography"], dtype=np.float64)
            self._to_image = np.linalg.inv(self._to_ground)

    def set_frame_size(self, width: int, height: int) -> None:
        self.width, self.height = int(width), int(height)
        self.camera = None
        if self.metric:
            ground_to_pixels = np.diag([self.width - 1.0, self.height - 1.0, 1.0]) @ self._to_image
            self.camera = camera_from_homography(ground_to_pixels, self.width, self.height,
                                                 float(self.cfg["geometry"]["camera_tolerance"]))

    def to_ground(self, x_px: float, y_px: float) -> tuple[float, float]:
        """Image pixel (a point on the ground, e.g. the bottom centre of a box) -> metres."""
        return apply_homography(self._to_ground, x_px / (self.width - 1), y_px / (self.height - 1))

    def to_image(self, x_m: float, y_m: float) -> tuple[float, float]:
        u, v = apply_homography(self._to_image, x_m, y_m)
        return u * (self.width - 1), v * (self.height - 1)

    def pixels_per_metre(self, x_px: float, y_px: float) -> float:
        """Image pixels covered by one metre at this ground point, measured across the image.

        Used to turn the width of a box into metres: an object standing at this point is at the same
        distance from the camera as the ground under it.
        """
        probe = float(self.cfg["geometry"]["scale_probe_px"])
        ax, ay = self.to_ground(x_px - probe, y_px)
        bx, by = self.to_ground(x_px + probe, y_px)
        metres = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
        return 2 * probe / metres if metres > 0 else 0.0

    def _height_pixels_per_metre(self, x_px: float, y_px: float) -> float:
        """Pixels covered by one metre of height at this ground point, without knowing where the camera is.

        A camera looking down sees standing things shortened. Around a point the ground is stretched by s
        pixels per metre in one direction and by s * sin(angle) in the other, where angle is how steeply
        the camera looks down there; one metre of height covers s * cos(angle) = sqrt(larger^2 - smaller^2).
        Exact for a far camera, a few tens of percent off for a camera a few metres above the heads.
        """
        probe = float(self.cfg["geometry"]["scale_probe_px"])
        left, right = self.to_ground(x_px - probe, y_px), self.to_ground(x_px + probe, y_px)
        up, down = self.to_ground(x_px, y_px - probe), self.to_ground(x_px, y_px + probe)
        metres_per_px = np.array([[right[0] - left[0], down[0] - up[0]],
                                  [right[1] - left[1], down[1] - up[1]]]) / (2 * probe)
        most, least = np.linalg.svd(metres_per_px, compute_uv=False)
        if least <= 0:
            return 0.0
        larger, smaller = 1.0 / least, 1.0 / most
        floor = float(self.cfg["geometry"]["min_height_ratio"]) * larger   # view from straight above: no height
        return float(max(max(larger * larger - smaller * smaller, 0.0) ** 0.5, floor))

    def _foot_ray(self, x_px: float, y_px: float) -> np.ndarray:
        """The foot point as the camera sees it: (x, y, depth), before the division by the depth."""
        x_m, y_m = self.to_ground(x_px, y_px)
        return self.camera["ground"] @ np.array([x_m, y_m, 1.0])

    def box_height_px(self, height_m: float, x_px: float, y_px: float) -> float:
        """Height in pixels of the box of something height_m tall standing at this foot point."""
        if self.camera is None:
            return height_m * self._height_pixels_per_metre(x_px, y_px)
        top = self._foot_ray(x_px, y_px) + height_m * self.camera["up"]
        return float(y_px - (top[1] / top[2] + (self.height - 1) / 2))

    def height_in_metres(self, size_px: float, x_px: float, y_px: float) -> float | None:
        """Height in metres of a box size_px tall standing at this foot point.

        With the camera position known (see camera_from_homography) this is the exact answer: the head is
        on the vertical through the feet, at the height where the camera sees it at the top of the box.
        A box as wide in metres as it is tall would be wrong: from above a person looks shorter.
        """
        correction = float(self.cfg["geometry"]["height_scale"])
        if self.camera is None:
            scale = self._height_pixels_per_metre(x_px, y_px)
            return size_px / scale * correction if scale > 0 else None
        top_y = y_px - (self.height - 1) / 2 - size_px
        up = self.camera["up"]
        rise = top_y * up[2] - up[1]          # how fast the top goes up in the image per metre of height
        if rise <= 0:
            return None                       # the top of the box is above the horizon of the camera
        return float(self._foot_ray(x_px, y_px)[2] * size_px / rise * correction)

    def metres_per_pixel(self, x_px: float, y_px: float) -> float:
        """How far on the ground one pixel of error moves this point: the precision of the calibration here.

        Far from the camera one pixel is metres of road, and a speed measured there is noise.
        """
        x0, y0 = self.to_ground(x_px, y_px)
        ax, ay = self.to_ground(x_px + 1.0, y_px)
        bx, by = self.to_ground(x_px, y_px + 1.0)
        return max(((ax - x0) ** 2 + (ay - y0) ** 2) ** 0.5, ((bx - x0) ** 2 + (by - y0) ** 2) ** 0.5)

    def size_in_metres(self, size_px: float, x_px: float, y_px: float) -> float | None:
        """Length on the ground, in metres, of a box as wide as size_px at this foot point."""
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
