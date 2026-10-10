"""Makes the input size of the official YOLOX-nano ONNX free, so it can run at 320 px.

The official file declares a fixed 1x3x416x416 input, but the network has no size baked in (checked:
Slice with open ends, Resize by scale, Reshape to [1, 85, -1]). Only the declared shapes change here;
the weights are untouched. Needs the `onnx` package (development only, see requirements-dev.txt).
onnx Python API: https://onnx.ai/onnx/api/

Usage (from ai/):
    python scripts/make_dynamic_model.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import onnx

AI_DIR = Path(__file__).resolve().parent.parent
SOURCE = AI_DIR / "models" / "yolox_nano.onnx"
DEST = AI_DIR / "models" / "yolox_nano_dynamic.onnx"


def main() -> int:
    if not SOURCE.is_file():
        print(f"Missing {SOURCE}. Run: bash scripts/get_model.sh", file=sys.stderr)
        return 1
    model = onnx.load(str(SOURCE))
    graph = model.graph

    in_dims = graph.input[0].type.tensor_type.shape.dim     # N, C, H, W
    in_dims[2].dim_param, in_dims[3].dim_param = "height", "width"
    out_dims = graph.output[0].type.tensor_type.shape.dim   # N, anchors, 5 + classes
    out_dims[1].dim_param = "anchors"
    # Intermediate shapes recorded for 416 px are no longer valid.
    del graph.value_info[:]

    onnx.checker.check_model(model)
    onnx.save(model, str(DEST))
    print(f"Saved: {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
