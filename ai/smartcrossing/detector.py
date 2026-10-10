"""YOLOX-nano (COCO, ONNX) on onnxruntime: preprocess, decode and NMS in numpy.

Reference implementation (pre/post-processing):
https://github.com/Megvii-BaseDetection/YOLOX/tree/main/demo/ONNXRuntime
onnxruntime Python API (InferenceSession, SessionOptions.intra_op_num_threads):
https://onnxruntime.ai/docs/api/python/api_summary.html
"""
from __future__ import annotations

import warnings

import cv2
import numpy as np
import onnxruntime as ort
import supervision as sv

from .config import resolve_path

COCO_CLASSES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear",
    "hair drier", "toothbrush",
)


_EPS = 1e-9  # avoids a division by zero in the IoU


def letterbox(frame: np.ndarray, size: int, pad_value: int) -> tuple[np.ndarray, float]:
    """YOLOX preprocess: resize keeping the aspect ratio, pad bottom/right, keep BGR, no normalization.

    Returns the (1, 3, size, size) float32 blob and the resize ratio.
    """
    h, w = frame.shape[:2]
    ratio = min(size / h, size / w)
    new_w, new_h = int(w * ratio), int(h * ratio)
    padded = np.full((size, size, 3), pad_value, dtype=np.uint8)
    padded[:new_h, :new_w] = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    blob = np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)[None]
    return blob, ratio


def make_grids(size: int, strides: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Grid cell offsets (N, 2) and the stride of each cell (N, 1), for all head levels."""
    grids, expanded = [], []
    for stride in strides:
        n = size // stride
        xv, yv = np.meshgrid(np.arange(n), np.arange(n))
        grid = np.stack((xv, yv), axis=2).reshape(-1, 2)
        grids.append(grid)
        expanded.append(np.full((grid.shape[0], 1), stride))
    return np.concatenate(grids).astype(np.float32), np.concatenate(expanded).astype(np.float32)


def decode_outputs(raw: np.ndarray, grids: np.ndarray, strides: np.ndarray) -> np.ndarray:
    """Turns raw head outputs (N, 5 + classes) into cx, cy, w, h in input pixels (same layout)."""
    out = raw.astype(np.float32, copy=True)
    out[:, :2] = (out[:, :2] + grids) * strides
    out[:, 2:4] = np.exp(out[:, 2:4]) * strides
    return out


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
    """Plain NMS on xyxy boxes. Returns the kept indices, best score first."""
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        rest = order[1:]
        w = np.maximum(0.0, np.minimum(x2[i], x2[rest]) - np.maximum(x1[i], x1[rest]))
        h = np.maximum(0.0, np.minimum(y2[i], y2[rest]) - np.maximum(y1[i], y1[rest]))
        inter = w * h
        iou = inter / (areas[i] + areas[rest] - inter + _EPS)
        order = rest[iou <= iou_threshold]
    return np.asarray(keep, dtype=np.int64)


def postprocess(
    decoded: np.ndarray,
    ratio: float,
    frame_shape: tuple[int, int],
    conf: float,
    nms_threshold: float,
    keep_ids: np.ndarray,
    cross_class_threshold: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Decoded predictions -> (xyxy in frame pixels, scores, class ids), kept classes only.

    NMS is per class, so a person and the bicycle under it both survive (needed to derive cyclists).
    Boxes of different classes that overlap more than cross_class_threshold are the same object seen
    twice: only the best score is kept.
    """
    empty = (np.zeros((0, 4), np.float32), np.zeros((0,), np.float32), np.zeros((0,), np.int64))
    # Score = objectness * class probability, restricted to the classes we keep.
    cls_scores = decoded[:, 4:5] * decoded[:, 5:][:, keep_ids]
    best = cls_scores.argmax(axis=1)
    scores = cls_scores[np.arange(len(best)), best]
    mask = scores >= conf
    if not mask.any():
        return empty
    scores, class_ids, cxcywh = scores[mask], keep_ids[best[mask]], decoded[mask, :4]

    boxes = np.empty_like(cxcywh)
    boxes[:, 0] = cxcywh[:, 0] - cxcywh[:, 2] / 2
    boxes[:, 1] = cxcywh[:, 1] - cxcywh[:, 3] / 2
    boxes[:, 2] = cxcywh[:, 0] + cxcywh[:, 2] / 2
    boxes[:, 3] = cxcywh[:, 1] + cxcywh[:, 3] / 2
    boxes /= ratio
    h, w = frame_shape
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, w - 1)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, h - 1)

    # Per-class NMS in one pass: shift each class into its own coordinate range.
    offsets = class_ids[:, None].astype(np.float32) * float(max(h, w) + 1)
    keep = nms(boxes + offsets, scores, nms_threshold)
    boxes, scores, class_ids = boxes[keep], scores[keep], class_ids[keep]
    if cross_class_threshold < 1.0:
        keep = nms(boxes, scores, cross_class_threshold)
        boxes, scores, class_ids = boxes[keep], scores[keep], class_ids[keep]
    return boxes, scores, class_ids


class Detector:
    """Runs the ONNX model on a BGR frame and returns supervision Detections."""

    def __init__(self, cfg: dict):
        m = cfg["model"]
        path = resolve_path(m["path"])
        if not path.is_file():
            raise FileNotFoundError(f"Model not found: {path}. Run: bash scripts/get_model.sh")

        options = ort.SessionOptions()
        if int(m["intra_op_num_threads"]) > 0:
            options.intra_op_num_threads = int(m["intra_op_num_threads"])
        # CPU only: the UNO Q has no NPU, and the same code path must run on the PC.
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name

        self.input_size = int(m["input_size"])
        strides = list(m["strides"])
        if self.input_size % max(strides) != 0:
            raise ValueError(f"input_size={self.input_size} must be a multiple of {max(strides)}")
        # The official file has a fixed 416 px input; scripts/make_dynamic_model.py frees it.
        fixed = model_input.shape[2]
        if isinstance(fixed, int) and fixed != self.input_size:
            warnings.warn(
                f"{path.name} has a fixed {fixed} px input: ignoring input_size={self.input_size}.",
                stacklevel=2,
            )
            self.input_size = fixed

        self.pad_value = int(m["pad_value"])
        self.conf = float(m["conf"])
        self.nms_threshold = float(m["nms"])
        self.cross_class_threshold = float(m["nms_cross_class"])
        self.keep_ids = np.array([COCO_CLASSES.index(name) for name in m["keep_classes"]], dtype=np.int64)
        self._grids, self._strides = make_grids(self.input_size, strides)

    def detect(self, frame: np.ndarray) -> sv.Detections:
        blob, ratio = letterbox(frame, self.input_size, self.pad_value)
        raw = self.session.run(None, {self.input_name: blob})[0][0]
        decoded = decode_outputs(raw, self._grids, self._strides)
        xyxy, scores, class_ids = postprocess(
            decoded, ratio, frame.shape[:2], self.conf, self.nms_threshold, self.keep_ids,
            self.cross_class_threshold,
        )
        return sv.Detections(xyxy=xyxy, confidence=scores, class_id=class_ids)
