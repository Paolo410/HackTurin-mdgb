"""Sets exposure and gain of the board's camera for the light of this moment, once, before the camera starts.

Why: with libcamera's software ISP the automatic exposure of the IMX219 does not settle (the brightness cycles
dark / medium / bright every three frames), so it is switched off (deploy/camera_tuning) and the sensor keeps
the values it has when the camera opens. A value changed while the camera runs is overwritten at once.

Usage, on the board, from ~/HackTurin-mdgb/ai, with the camera free (deploy/vision_service.sh does it by itself
before starting the vision on the camera):
    ~/venv/bin/python scripts/camera_exposure.py            # measure, set, check
    ~/venv/bin/python scripts/camera_exposure.py --show     # only print the current values

It never stops who calls it: if the sensor or the tools are not there it says so and ends with 0.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR))

from smartcrossing.config import load_config  # noqa: E402

TUNING_DIR = AI_DIR / "deploy" / "camera_tuning"
SUBDEV_NAMES = Path("/sys/class/video4linux")


def gain_factor(code: int, cam: dict) -> float:
    """Analogue gain of the sensor as a multiplier. IMX219: 256 / (256 - code)."""
    return float(cam["gain_base"]) / (float(cam["gain_base"]) - code)


def gain_code(factor: float, cam: dict) -> int:
    code = round(float(cam["gain_base"]) - float(cam["gain_base"]) / max(factor, 1.0))
    return int(min(max(code, int(cam["gain_min"])), int(cam["gain_max"])))


def next_settings(brightness: float, exposure: int, gain: int, cam: dict) -> tuple[int, int]:
    """Exposure (lines) and gain (code) that should bring the measured brightness to the target.

    The gain does the work, because a longer exposure blurs who moves; the exposure grows only when the gain
    is at its top, and shrinks only when the gain is already at 1.
    """
    wanted = float(cam["target_brightness"]) / max(brightness, 1.0) * gain_factor(gain, cam)
    top = gain_factor(int(cam["gain_max"]), cam)
    if wanted > top:
        exposure = min(int(cam["exposure_max"]), round(exposure * wanted / top))
        wanted = top
    elif wanted < 1.0:
        exposure = max(int(cam["exposure_min"]), round(exposure * wanted))
        wanted = 1.0
    return int(exposure), gain_code(wanted, cam)


def in_band(brightness: float, cam: dict) -> bool:
    low, high = cam["brightness_band"]
    return float(low) <= brightness <= float(high)


def find_sensor(name: str) -> str | None:
    """The /dev/v4l-subdevN of the sensor: its number changes from one boot to the next."""
    for entry in sorted(SUBDEV_NAMES.glob("v4l-subdev*")):
        try:
            if name in (entry / "name").read_text():
                return f"/dev/{entry.name}"
        except OSError:
            continue
    return None


def _plain_env() -> dict:
    """The environment without libcamerify's preload: v4l2-ctl must talk to the sensor, not to libcamera."""
    return {k: v for k, v in os.environ.items() if k != "LD_PRELOAD"}


def read_controls(device: str) -> tuple[int, int] | None:
    out = subprocess.run(["v4l2-ctl", "-d", device, "-C", "exposure,analogue_gain"], capture_output=True, text=True,
                         env=_plain_env()).stdout
    values = dict(re.findall(r"(\w+): (-?\d+)", out))
    if "exposure" not in values or "analogue_gain" not in values:
        return None
    return int(values["exposure"]), int(values["analogue_gain"])


def write_controls(device: str, exposure: int, gain: int) -> None:
    subprocess.run(["v4l2-ctl", "-d", device, "-c", f"exposure={exposure},analogue_gain={gain}"],
                   capture_output=True, env=_plain_env())


def measure_here(cam: dict) -> float | None:
    """Mean brightness of the camera, read in THIS process (run under libcamerify with the tuning folder)."""
    import cv2
    cap = cv2.VideoCapture(0)
    levels = []
    try:
        for _ in range(int(cam["measure_frames"])):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                levels.append(float(frame[::8, ::8].mean()))
            time.sleep(float(cam["measure_period_s"]))
    except cv2.error:
        pass
    finally:
        cap.release()
    keep = levels[-int(cam["measure_keep"]):]
    return sum(keep) / len(keep) if keep else None


def measure(cam: dict) -> float | None:
    """One measurement in its own process: opening the camera twice in one process is not reliable."""
    env = {**os.environ, "LIBCAMERA_IPA_CONFIG_PATH": str(TUNING_DIR)}
    command = [sys.executable, str(Path(__file__).resolve()), "--measure"]
    if shutil.which("libcamerify"):
        command.insert(0, "libcamerify")
    try:
        out = subprocess.run(command, capture_output=True, text=True, env=env, timeout=float(cam["measure_timeout_s"])).stdout
    except subprocess.TimeoutExpired:
        return None
    found = re.findall(r"^brightness (\d+(?:\.\d+)?)$", out, flags=re.M)
    return float(found[-1]) if found else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--show", action="store_true", help="only print the current exposure and gain")
    p.add_argument("--measure", action="store_true", help=argparse.SUPPRESS)
    args = p.parse_args(argv)
    cam = load_config(profile="unoq")["camera"]

    if args.measure:
        level = measure_here(cam)
        if level is not None:
            print(f"brightness {level:.1f}")
        return 0
    device = find_sensor(cam["sensor"]) if shutil.which("v4l2-ctl") else None
    current = read_controls(device) if device else None
    if current is None:
        print(f"camera_exposure: sensore {cam['sensor']} o v4l2-ctl non trovati: esposizione lasciata com'è")
        return 0
    exposure, gain = current
    if args.show:
        print(f"{device}: exposure={exposure} analogue_gain={gain} (x{gain_factor(gain, cam):.1f})")
        return 0
    for attempt in range(int(cam["attempts"])):
        level = measure(cam)
        if level is None:
            print("camera_exposure: nessuna misura dalla camera (occupata?): esposizione lasciata com'è")
            return 0
        if in_band(level, cam):
            break
        exposure, gain = next_settings(level, exposure, gain, cam)
        write_controls(device, exposure, gain)
        print(f"camera_exposure: luminosità {level:.0f}, imposto exposure={exposure} analogue_gain={gain} "
              f"(x{gain_factor(gain, cam):.1f})")
    print(f"camera_exposure: luminosità {level:.0f} con exposure={exposure} analogue_gain={gain} "
          f"(x{gain_factor(gain, cam):.1f}), fissa fino al prossimo avvio della camera")
    return 0


if __name__ == "__main__":
    sys.exit(main())
