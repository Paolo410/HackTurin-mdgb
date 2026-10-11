#!/usr/bin/env bash
# One-time setup of the trailer toolchain (macOS or Linux). Run from anywhere: bash trailer/setup.sh
set -euo pipefail
cd "$(dirname "$0")"

need() { command -v "$1" >/dev/null 2>&1; }
if ! need ffmpeg; then
  if need brew; then brew install ffmpeg; else echo "Install ffmpeg first (brew install ffmpeg / conda install -c conda-forge ffmpeg)"; exit 1; fi
fi
if ! need node; then
  if need brew; then brew install node; else echo "Install Node.js 18+ first (https://nodejs.org)"; exit 1; fi
fi

PY=${PYTHON:-python3}
"$PY" -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

mkdir -p models
dl() { [ -s "$2" ] || { echo "↓ $(basename "$2")"; curl -fL --retry 3 -o "$2.part" "$1" && mv "$2.part" "$2"; }; }
dl https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx models/kokoro-v1.0.onnx
dl https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin models/voices-v1.0.bin
dl https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx models/yolox_nano.onnx
dl https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx models/yolox_s.onnx

(cd motion && npm install --no-audit --no-fund)
[ -f .env ] || cp .env.example .env
echo "✓ Ready. Full build:  .venv/bin/python tools/build.py"
