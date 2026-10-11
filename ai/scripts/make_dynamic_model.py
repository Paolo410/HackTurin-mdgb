"""Makes the input size of an official YOLOX ONNX free, so it can run at any size (nano at 320 px on the board;
the larger s/m/l at high resolution on the PC, as the reference of the benchmark).

The official file declares a fixed 1x3x416x416 input, but the network has no size baked in (checked:
Slice with open ends, Resize by scale, Reshape to [1, 85, -1]). Only the declared shapes change here;
the weights are untouched. Needs the `onnx` package (development only, see requirements-dev.txt).
onnx Python API: https://onnx.ai/onnx/api/

Usage (from ai/):
    python scripts/make_dynamic_model.py                         # models/yolox_nano.onnx -> yolox_nano_dynamic.onnx
    python scripts/make_dynamic_model.py models/yolox_m.onnx     # -> models/yolox_m_dynamic.onnx
    python scripts/make_dynamic_model.py models/yolox_l.onnx --fixed 960   # -> models/yolox_l_960.onnx (fixed 960x960:
                                                                 # CoreML on a Mac runs fixed shapes much faster)
"""
from __future__ import annotations

import sys
from pathlib import Path

import onnx

AI_DIR = Path(__file__).resolve().parent.parent
SOURCE = AI_DIR / "models" / "yolox_nano.onnx"
DEST = AI_DIR / "models" / "yolox_nano_dynamic.onnx"


def main() -> int:
    global SOURCE, DEST
    args = sys.argv[1:]
    fixed = int(args[args.index("--fixed") + 1]) if "--fixed" in args else None
    paths = [a for i, a in enumerate(args) if a != "--fixed" and (i == 0 or args[i - 1] != "--fixed")]
    if paths:
        SOURCE = Path(paths[0]).resolve()
        DEST = SOURCE.with_name(f"{SOURCE.stem}_{fixed}.onnx" if fixed else f"{SOURCE.stem}_dynamic.onnx")
    if not SOURCE.is_file():
        print(f"Missing {SOURCE}. Run: bash scripts/get_model.sh", file=sys.stderr)
        return 1
    model = onnx.load(str(SOURCE))
    graph = model.graph

    in_dims = graph.input[0].type.tensor_type.shape.dim     # N, C, H, W
    out_dims = graph.output[0].type.tensor_type.shape.dim   # N, anchors, 5 + classes
    if fixed:
        in_dims[2].dim_value, in_dims[3].dim_value = fixed, fixed
        out_dims[1].dim_value = sum((fixed // stride) ** 2 for stride in (8, 16, 32))
    else:
        in_dims[2].dim_param, in_dims[3].dim_param = "height", "width"
        out_dims[1].dim_param = "anchors"
    # Intermediate shapes recorded for 416 px are no longer valid.
    del graph.value_info[:]

    onnx.checker.check_model(model)
    onnx.save(model, str(DEST))
    print(f"Saved: {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
