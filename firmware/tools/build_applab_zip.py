"""Builds the App Lab app of MDGB as a zip to import in Arduino App Lab (My Apps > import).

The app is firmware/unoq_mcu/ (sketch, main.py, vision.py, web page). The vision code is not copied by hand:
this script puts next to main.py the files of ai/ that the app needs, as they are on this checkout:

    python/smartcrossing/        <- ai/smartcrossing/*.py
    python/config.yaml           <- ai/config.yaml
    python/calib*.json           <- ai/calib.json (if present) and the committed examples
    python/models/*.onnx         <- yolox_nano_dynamic.onnx (+ aid_cls.onnx if present), git-ignored

Usage (from the root of the repo, any OS):
    python firmware/tools/build_applab_zip.py [--models-dir ai/models] [--out firmware/dist/mdgb.zip]
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "firmware" / "unoq_mcu"
AI_DIR = ROOT / "ai"
APP_NAME = "mdgb"                       # top folder of the zip = name of the app in App Lab
REQUIRED_MODEL = "yolox_nano_dynamic.onnx"
OPTIONAL_MODELS = ("aid_cls.onnx",)
AI_FILES = ("config.yaml", "calib.json", "calib.example.json", "calib_thermal.json", "calib_thermal.example.json")
SKIP_PARTS = {"__pycache__", ".cache", ".pytest_cache"}


def app_files(models_dir: Path) -> list[tuple[Path, str]]:
    """(source file, path inside the zip) for every file of the app."""
    files = []
    for src in sorted(APP_DIR.rglob("*")):
        rel = src.relative_to(APP_DIR)
        if src.is_file() and not SKIP_PARTS & set(rel.parts) and rel.name != "README.md":
            files.append((src, rel.as_posix()))
    for src in sorted((AI_DIR / "smartcrossing").glob("*.py")):
        files.append((src, f"python/smartcrossing/{src.name}"))
    for name in AI_FILES:
        if (AI_DIR / name).is_file():
            files.append((AI_DIR / name, f"python/{name}"))
    model = models_dir / REQUIRED_MODEL
    if not model.is_file():
        raise FileNotFoundError(f"{model} missing: run `bash ai/scripts/get_model.sh` or pass --models-dir")
    files.append((model, f"python/models/{REQUIRED_MODEL}"))
    for name in OPTIONAL_MODELS:
        if (models_dir / name).is_file():
            files.append((models_dir / name, f"python/models/{name}"))
    return files


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--models-dir", type=Path, default=AI_DIR / "models", help="folder with the ONNX models")
    p.add_argument("--out", type=Path, default=ROOT / "firmware" / "dist" / f"{APP_NAME}.zip")
    args = p.parse_args()
    try:
        files = app_files(args.models_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.out, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, arc in files:
            zf.write(src, f"{APP_NAME}/{arc}")
    size = args.out.stat().st_size / 1e6
    print(f"{args.out} ({len(files)} files, {size:.1f} MB)")
    calib = "calib.json" if (AI_DIR / "calib.json").is_file() else "calib.example.json (no ai/calib.json)"
    print(f"calibration: {calib}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
