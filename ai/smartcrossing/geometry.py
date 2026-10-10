"""Calibration file (calib.json) and image geometry helpers.

AI-M2: counting lines only, in normalized image coordinates (0..1), so they survive a resize.
The homography, the zones and the metric API arrive with AI-M3 in the same file.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import resolve_path

CALIB_VERSION = 1


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


def to_normalized(point: tuple[int, int], width: int, height: int) -> list[float]:
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
