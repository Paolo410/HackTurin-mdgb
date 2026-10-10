"""Night: a low-resolution thermal camera sees warm bodies where the RGB camera sees nothing.

Sensor available: Grove MLX90621, 16 columns x 4 rows, read by the MCU and forwarded to Linux as 64
temperatures (contract C5, draft: {"v":1,"src":"mcu","type":"thermal","t":[...64 values, row by row...]}).
With 4 rows there are no blobs to find: the sensor looks along the kerb and each column is one slice of
pavement. A column is "warm" when it is a few degrees above the ambient temperature.

Fusion with the RGB camera:
- night mode: the image has been dark for a while;
- recovery: at night, heat in a waiting zone or on the stripes with no person seen there by the RGB camera
  for long enough -> an "unclassified pedestrian", treated as vulnerable (v_ped = 0.8);
- confirmation: a person seen by the RGB camera with heat in the same zone is confirmed; one without
  heat at night is flagged as unconfirmed (it is still protected: see drop_unconfirmed in config.yaml).
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import numpy as np

from .config import resolve_path
from .rules import PedestrianInfo, Scene

# Thermal-only pedestrians have no track: they get negative ids, one per zone.
THERMAL_ID_BASE = -100


def load_thermal_calib(cfg: dict, path: str | Path | None = None) -> dict:
    """Which columns of the sensor look at which zone. calib_thermal.json, else the committed example."""
    t = cfg["thermal"]
    candidates = [Path(path)] if path else [resolve_path(t["calib_path"]), resolve_path(t["example_calib_path"])]
    for candidate in candidates:
        if candidate.is_file():
            with open(candidate, "r", encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError(f"Thermal calibration not found: {', '.join(str(p) for p in candidates)}")


def warm_columns(frame: np.ndarray, delta_c: float) -> tuple[np.ndarray, float]:
    """Per column: is anything in it warmer than ambient + delta? Returns (mask, ambient).

    Ambient is the median of the whole frame: a person fills a couple of columns, the rest is background.
    """
    ambient = float(np.median(frame))
    return frame.max(axis=0) > ambient + delta_c, ambient


class ThermalSource:
    """Interface: read() -> (frame, t), frame = temperatures in Celsius as a (rows, columns) array, or None."""

    def read(self) -> tuple[np.ndarray | None, float]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SimThermalSource(ThermalSource):
    """Scripted frames for tests and demos: script(t) -> list of warm column indices."""

    def __init__(self, cfg: dict, script=None, clock=time.monotonic):
        t = cfg["thermal"]
        self.rows, self.columns = int(t["rows"]), int(t["columns"])
        self.ambient, self.body = float(t["sim_ambient_c"]), float(t["sim_body_c"])
        self.period, self.present = float(t["sim_period_s"]), float(t["sim_present_s"])
        self.sim_columns = list(t["sim_columns"])
        self._script = script
        self._clock = clock
        self._t0 = clock()

    def frame_with(self, columns: list[int]) -> np.ndarray:
        frame = np.full((self.rows, self.columns), self.ambient, dtype=np.float32)
        for column in columns:
            frame[1:3, column] = self.body
        return frame

    def read(self) -> tuple[np.ndarray, float]:
        now = self._clock()
        if self._script is not None:
            columns = self._script(now - self._t0)
        else:   # default demo: somebody stands in front of the sensor for a while, again and again
            columns = self.sim_columns if (now - self._t0) % self.period < self.present else []
        return self.frame_with(columns), now


class McuThermalSource(ThermalSource):
    """Frames forwarded by the MCU. Feed it the C5 lines through on_mcu_line (Actuator.set_listener).

    TODO(verify): the C5 "thermal" line and Actuator.set_listener are in the draft of docs/CONTRACTS.md
    (branch lorenzo/ble-backup), not yet on main and not yet tested against the real firmware.
    """

    def __init__(self, cfg: dict, clock=time.monotonic):
        t = cfg["thermal"]
        self.rows, self.columns = int(t["rows"]), int(t["columns"])
        self.max_age = float(t["max_frame_age_s"])
        self._clock = clock
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._t = 0.0

    def on_mcu_line(self, line: dict) -> None:
        if line.get("type") != "thermal":
            return
        values = line.get("t")
        if not isinstance(values, list) or len(values) != self.rows * self.columns:
            return   # malformed: keep the previous frame
        try:
            frame = np.array(values, dtype=np.float32).reshape(self.rows, self.columns)
        except (TypeError, ValueError):
            return
        with self._lock:
            self._frame, self._t = frame, self._clock()

    def read(self) -> tuple[np.ndarray | None, float]:
        with self._lock:
            if self._frame is None or self._clock() - self._t > self.max_age:
                return None, self._t   # no data, or too old to trust
            return self._frame, self._t


def make_thermal_source(kind: str, cfg: dict, actuator=None) -> ThermalSource | None:
    if kind in (None, "none"):
        return None
    if kind == "sim":
        return SimThermalSource(cfg)
    if kind == "mlx90621":
        source = McuThermalSource(cfg)
        if actuator is not None and hasattr(actuator, "set_listener"):
            actuator.set_listener(source.on_mcu_line)
        return source
    # mlx90640 (32x24) and UVC thermal cameras are in the specification but not in our kit.
    raise RuntimeError(f"--thermal {kind}: this sensor is not available; use mlx90621 (the Grove 16x4) or sim")


class ThermalFusion:
    def __init__(self, cfg: dict, source: ThermalSource, calib: dict | None = None, force_night: bool = False):
        t = cfg["thermal"]
        self.source = source
        self.zones: dict[str, list[int]] = (calib if calib is not None else load_thermal_calib(cfg))["zones"]
        self.delta = float(t["warm_delta_c"])
        self.night_luminance = float(t["night_luminance"])
        self.night_after = float(t["night_after_s"])
        self.recover_after = float(t["recover_after_s"])
        self.drop_unconfirmed = bool(t["drop_unconfirmed"])
        self.force_night = force_night
        self.night = force_night
        self._dark_since: float | None = None
        self._bright_since: float | None = None
        self._heat_only_since: dict[str, float] = {}
        self.warm = np.zeros(int(t["columns"]), dtype=bool)   # last warm columns, for the screen
        self.ambient: float | None = None
        self.unconfirmed: set[int] = set()                    # RGB pedestrians with no heat at night
        self.recovered: list[str] = []                        # zones with a thermal-only pedestrian now

    def update_light(self, luminance: float | None, t: float) -> bool:
        """Night mode from the mean brightness of the image, with the same delay in both directions."""
        if self.force_night:
            self.night = True
            return True
        if luminance is None:
            return self.night
        if luminance < self.night_luminance:
            self._bright_since = None
            if self._dark_since is None:
                self._dark_since = t
            if t - self._dark_since > self.night_after:
                self.night = True
        else:
            self._dark_since = None
            if self._bright_since is None:
                self._bright_since = t
            if t - self._bright_since > self.night_after:
                self.night = False
        return self.night

    def update(self, scene: Scene, t: float, luminance: float | None = None) -> Scene:
        """Adds to the scene what only the thermal camera can see. Call once per frame."""
        self.update_light(luminance, t)
        frame, _ = self.source.read()
        self.unconfirmed, self.recovered = set(), []
        if frame is None:
            self.warm[:] = False
            self._heat_only_since.clear()
            return scene
        self.warm, self.ambient = warm_columns(frame, self.delta)

        for index, (zone, columns) in enumerate(self.zones.items()):
            heat = bool(self.warm[columns].any())
            rgb_here = [p for p in scene.pedestrians if p.zone == zone and not p.thermal_only]
            if heat and not rgb_here and self.night:
                since = self._heat_only_since.setdefault(zone, t)
                if t - since >= self.recover_after:
                    self.recovered.append(zone)
                    scene.pedestrians.append(PedestrianInfo(
                        track_id=THERMAL_ID_BASE - index, zone=zone, waiting_s=t - since, thermal_only=True))
            else:
                self._heat_only_since.pop(zone, None)
                if self.night and not heat:
                    self.unconfirmed.update(p.track_id for p in rgb_here)
        if self.drop_unconfirmed and self.unconfirmed:
            scene.pedestrians = [p for p in scene.pedestrians if p.track_id not in self.unconfirmed]
        return scene

    def summary(self) -> str:
        strip = "".join("#" if w else "." for w in self.warm)
        ambient = "-" if self.ambient is None else f"{self.ambient:.0f}C"
        return f"thermal {'NIGHT' if self.night else 'day'} [{strip}] ambient {ambient}"
