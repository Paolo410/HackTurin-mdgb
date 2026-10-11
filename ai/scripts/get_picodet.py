"""Downloads PP-PicoDet-S (PaddleDetection, Apache-2.0) as ONNX for the detector (model.family: picodet).

The official files list the weights also as graph inputs, which stops onnxruntime from folding constants: here they
are removed from the inputs (the weights are untouched). Output: models/picodet_s_320.onnx and picodet_s_416.onnx.
Model zoo and downloads: https://github.com/PaddlePaddle/PaddleDetection/tree/release/2.8/configs/picodet

Usage (from ai/, development: needs the onnx package):  python scripts/get_picodet.py
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import onnx

MODELS = Path(__file__).resolve().parent.parent / "models"
URL = "https://paddledet.bj.bcebos.com/deploy/third_engine/picodet_s_{size}_coco_lcnet.onnx"


def main() -> int:
    MODELS.mkdir(exist_ok=True)
    for size in (320, 416):
        raw = MODELS / f"picodet_s_{size}_coco_lcnet.onnx"
        if not raw.is_file():
            print(f"Downloading {URL.format(size=size)}")
            urllib.request.urlretrieve(URL.format(size=size), raw)
        model = onnx.load(str(raw))
        weights = {i.name for i in model.graph.initializer}
        inputs = [i for i in model.graph.input if i.name not in weights]
        del model.graph.input[:]
        model.graph.input.extend(inputs)
        out = MODELS / f"picodet_s_{size}.onnx"
        onnx.save(model, str(out))
        print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
