#!/usr/bin/env bash
# Downloads the YOLOX-nano COCO ONNX weights (Apache-2.0) into ai/models/ (git-ignored).
# Official release assets: https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0
set -euo pipefail

URL="https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_nano.onnx"
DEST_DIR="$(cd "$(dirname "$0")/.." && pwd)/models"
DEST="$DEST_DIR/yolox_nano.onnx"

mkdir -p "$DEST_DIR"
if [ -s "$DEST" ]; then
  echo "Already present: $DEST"
else
  echo "Downloading $URL"
  curl -fL --retry 3 -o "$DEST.part" "$URL"
  mv "$DEST.part" "$DEST"
  echo "Saved: $DEST ($(wc -c < "$DEST" | tr -d ' ') bytes)"
fi

# The official file has a fixed 416 px input: make the copy with a free input size (needed for 320 px).
AI_DIR="$(dirname "$DEST_DIR")"
PY="$AI_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
"$PY" "$AI_DIR/scripts/make_dynamic_model.py"
