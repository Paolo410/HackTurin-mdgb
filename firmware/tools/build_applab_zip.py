"""Builds the App Lab app of MDGB as a zip to import in Arduino App Lab (My Apps > import).

The app is firmware/unoq_mcu/ (sketch, main.py, vision.py, web page). The vision code is not copied by hand:
this script puts next to main.py the files of ai/ that the app needs, as they are on this checkout:

    python/smartcrossing/        <- ai/smartcrossing/*.py
    python/config.yaml           <- ai/config.yaml
    python/calib*.json           <- ai/calib.json (if present) and the committed examples
    python/models/*.onnx         <- yolox_nano_dynamic.onnx (+ aid_cls.onnx if present), git-ignored

With --panel it builds instead the old mdgb app (vision outside App Lab) with the technician's panel and no
vision inside: app.yaml and python/ from firmware/unoq_panel/, plus the sketch, the page (assets/) and
python/health.py of firmware/unoq_mcu/. Nothing of ai/ goes in, no model is needed.

Usage (from the root of the repo, any OS):
    python firmware/tools/build_applab_zip.py [--models-dir ai/models] [--out firmware/dist/mdgb.zip]
    python firmware/tools/build_applab_zip.py --panel [--out firmware/dist/mdgb-pannello.zip]
"""
from __future__ import annotations

import argparse
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "firmware" / "unoq_mcu"
PANEL_DIR = ROOT / "firmware" / "unoq_panel"
PANEL_SHARED = (".gitignore", "sketch", "assets", "python/health.py")   # taken from unoq_mcu for --panel
AI_DIR = ROOT / "ai"
APP_NAME = "mdgb"                       # top folder of the zip = name of the app in App Lab
REQUIRED_MODEL = "yolox_nano_dynamic.onnx"
OPTIONAL_MODELS = ("aid_cls.onnx",)
AI_FILES = ("config.yaml", "calib.json", "calib.example.json", "calib_thermal.json", "calib_thermal.example.json")
SKIP_PARTS = {"__pycache__", ".cache", ".pytest_cache"}
TEXT_SUFFIXES = {".py", ".ino", ".yaml", ".yml", ".js", ".html", ".css", ".md", ".json", ".txt", ".gitignore"}
# README.md at the root of the app, as App Lab creates it (the README.md in the repo folders is for the team).
APP_README = {
    "app": "# 🚦 mdgb\n\nMDGB con la visione dentro l'app: camera, riconoscimento, semaforo e pannello del tecnico "
           "(porta 7000). Sorgenti nel repo HackTurin-mdgb, firmware/unoq_mcu.\n",
    "panel": "# 🚦 mdgb\n\nLo sketch dell'app `test` di Salvatore con in più il semaforo comandato dalla visione "
             "(`mdgb_line`), il fail-safe e l'antifurto, più il pannello del tecnico (porta 7000). La camera non si apre "
             "qui: la usa la visione, che gira accanto a questa app (`~/HackTurin-mdgb/ai`). Sorgenti nel repo "
             "HackTurin-mdgb, firmware/unoq_panel.\n",
}


def _tree(base: Path, rel: str = "") -> list[tuple[Path, str]]:
    """Files under base/rel (or the file itself), with their path relative to base."""
    start = base / rel if rel else base
    paths = [start] if start.is_file() else sorted(start.rglob("*"))
    files = []
    for src in paths:
        arc = src.relative_to(base)
        if src.is_file() and not SKIP_PARTS & set(arc.parts) and arc.name != "README.md":
            files.append((src, arc.as_posix()))
    return files


def panel_files() -> list[tuple[Path, str]]:
    """The old mdgb app with the technician's panel: no vision, no model."""
    files = _tree(PANEL_DIR)
    for rel in PANEL_SHARED:
        files += _tree(APP_DIR, rel)
    return files


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


def write_zip(out: Path, files: list[tuple[Path, str]], readme: str) -> None:
    """Zip laid out like the ones App Lab exports (code1.zip): Unix entries with permissions, one entry per folder
    before its files, LF line endings in the text files. A zip made on Windows has none of this, and App Lab
    did not show its files."""
    stamp = time.localtime()[:6]
    entries: dict[str, bytes | None] = {"README.md": readme.encode("utf-8")}   # None = folder
    for src, arc in files:
        data = src.read_bytes()
        if src.suffix in TEXT_SUFFIXES or src.name in TEXT_SUFFIXES:
            data = data.replace(b"\r\n", b"\n")
        if arc == "assets/index.html":   # new version in every zip: the browser must not keep the old CSS/JS
            data = data.replace(b"__BUILD__", time.strftime("%Y%m%d%H%M%S").encode())
        entries[arc] = data
        parts = arc.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            entries.setdefault("/".join(parts[:i]) + "/", None)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc in sorted(entries):
            info = zipfile.ZipInfo(f"{APP_NAME}/{arc}", date_time=stamp)
            info.create_system = 3                                  # Unix
            data = entries[arc]
            if data is None:
                info.external_attr = (0o40755 << 16) | 0x10         # drwxr-xr-x + MS-DOS directory flag
                zf.writestr(info, b"")
            else:
                info.external_attr = 0o100644 << 16                # -rw-r--r--
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--models-dir", type=Path, default=AI_DIR / "models", help="folder with the ONNX models")
    p.add_argument("--panel", action="store_true", help="old mdgb app with the technician's panel, no vision inside")
    p.add_argument("--out", type=Path, help="zip to write (default: firmware/dist/mdgb.zip or mdgb-pannello.zip)")
    args = p.parse_args()
    if args.out is None:
        args.out = ROOT / "firmware" / "dist" / (f"{APP_NAME}-pannello.zip" if args.panel else f"{APP_NAME}.zip")
    try:
        files = panel_files() if args.panel else app_files(args.models_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_zip(args.out, files, APP_README["panel" if args.panel else "app"])
    size = args.out.stat().st_size / 1e6
    print(f"{args.out} ({len(files)} files, {size:.1f} MB)")
    if args.panel:
        return 0
    calib = "calib.json" if (AI_DIR / "calib.json").is_file() else "calib.example.json (no ai/calib.json)"
    print(f"calibration: {calib}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
