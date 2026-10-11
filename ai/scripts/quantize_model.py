"""INT8 copy of the YOLOX-nano detector, for the CPU of the UNO Q (Cortex-A53, no NPU).

Post-training static quantization with onnxruntime (QDQ format, per-channel weights): the convolutions run on 8-bit
integers, the decoding of the outputs stays in float. The scales of the activations come from frames of the
benchmark videos, cut and resized exactly as the detector does (region of interest of the calibration, same input
size). No training, no new data: the weights are the same, only stored and computed with fewer bits.
onnxruntime quantization: https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html

Usage (from ai/, development only: needs the onnx package and the sample videos):
    python scripts/quantize_model.py [--frames 200] [--out models/yolox_nano_int8.onnx]

Result on 11/10 (ai/DECISIONS.md, point 45): with the first 4 convolutions and the head in float it finds the same
objects as the float model (395/395 on 65 benchmark frames, 88% of the boxes overlapping), but on the UNO Q it is
SLOWER (283 ms against 208-230 ms per frame): the Cortex-A53 has no int8 dot-product instructions. Not used.
Worth trying again on a board with a newer CPU (Cortex-A55/A76: sdot).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

AI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI))

from smartcrossing.config import load_config  # noqa: E402
from smartcrossing.detector import fit_input, letterbox  # noqa: E402


def calibration_blobs(n_frames: int, budget: int) -> list[np.ndarray]:
    """Frames spread over the benchmark videos, prepared like Detector.detect (ROI, aspect-shaped input)."""
    cfg = load_config()
    m = cfg["model"]
    videos = json.loads((AI / "benchmarks" / "videos.json").read_text())["videos"]
    per_video = max(1, n_frames // len(videos))
    blobs = []
    for v in videos:
        calib = json.loads((AI / "samples" / "calib" / v["calib"]).read_text())
        cap = cv2.VideoCapture(str(AI / "samples" / v["video"]))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        for idx in np.linspace(0, max(total - 1, 0), per_video).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            if w > int(cfg["source"]["resize_width"]) > 0:      # the source resizes wide frames first
                scale = cfg["source"]["resize_width"] / w
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
                h, w = frame.shape[:2]
            roi = calib.get("roi")
            if roi:
                frame = frame[int(roi[1] * h):int(roi[3] * h), int(roi[0] * w):int(roi[2] * w)]
            size = fit_input(frame.shape[1], frame.shape[0], budget, max(m["strides"])) if m["match_aspect"] else budget
            blobs.append(letterbox(frame, size, int(m["pad_value"]))[0])
        cap.release()
    return blobs


def main(argv: list[str] | None = None) -> int:
    from onnxruntime.quantization import (CalibrationDataReader, CalibrationMethod, QuantFormat, QuantType,
                                          quantize_static)

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--model", default=str(AI / "models" / "yolox_nano_dynamic.onnx"))
    p.add_argument("--out", default=str(AI / "models" / "yolox_nano_int8.onnx"))
    p.add_argument("--frames", type=int, default=200)
    p.add_argument("--budget", type=int, default=320, help="input size of the board (model.input_size)")
    p.add_argument("--float-stem", type=int, default=4, help="first convolutions kept in float (they see raw pixels)")
    args = p.parse_args(argv)

    blobs = calibration_blobs(args.frames, args.budget)
    # The official YOLOX export is opset 11: per-channel quantization (DequantizeLinear with an axis) needs 13.
    import onnx
    from onnx import version_converter
    source = Path(args.out).with_suffix(".opset13.onnx")
    onnx.save(version_converter.convert_version(onnx.load(args.model), 13), str(source))

    class Reader(CalibrationDataReader):
        def __init__(self):
            self.items = iter(blobs)

        def get_next(self):
            blob = next(self.items, None)
            return None if blob is None else {"images": blob}

    # In float: the last convolutions of the head (box, objectness, 80 classes) and the first ones, which see the raw
    # 0-255 pixels. All in 8 bits, objects found fell from 983 to 114 on the benchmark frames; like this, 882.
    model = onnx.load(str(source))
    weights = {i.name: i for i in model.graph.initializer}
    convs = [n for n in model.graph.node if n.op_type == "Conv"]
    head = [n.name for n in convs if n.input[1] in weights and weights[n.input[1]].dims[0] in (1, 4, 80)]
    head += [n.name for n in convs[:args.float_stem]]
    quantize_static(str(source), args.out, Reader(), quant_format=QuantFormat.QDQ, op_types_to_quantize=["Conv"],
                    nodes_to_exclude=head, per_channel=True, weight_type=QuantType.QInt8,
                    activation_type=QuantType.QUInt8, calibrate_method=CalibrationMethod.MinMax)
    source.unlink()
    print(f"{len(blobs)} calibration frames -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
