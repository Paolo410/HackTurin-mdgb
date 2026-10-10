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


def _width_height(size) -> tuple[int, int]:
    """Input size as (width, height): an int means a square."""
    if isinstance(size, (int, np.integer)):
        return int(size), int(size)
    return int(size[0]), int(size[1])


def letterbox(frame: np.ndarray, size, pad_value: int) -> tuple[np.ndarray, float]:
    """YOLOX preprocess: resize keeping the aspect ratio, pad bottom/right, keep BGR, no normalization.

    size: an int (square input) or (width, height).
    Returns the (1, 3, height, width) float32 blob and the resize ratio.
    """
    in_w, in_h = _width_height(size)
    h, w = frame.shape[:2]
    ratio = min(in_h / h, in_w / w)
    new_w, new_h = max(1, int(w * ratio)), max(1, int(h * ratio))
    padded = np.full((in_h, in_w, 3), pad_value, dtype=np.uint8)
    padded[:new_h, :new_w] = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    blob = np.ascontiguousarray(padded.transpose(2, 0, 1), dtype=np.float32)[None]
    return blob, ratio


def make_grids(size, strides: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Grid cell offsets (N, 2) and the stride of each cell (N, 1), for all head levels.

    size: an int (square input) or (width, height).
    """
    in_w, in_h = _width_height(size)
    grids, expanded = [], []
    for stride in strides:
        xv, yv = np.meshgrid(np.arange(in_w // stride), np.arange(in_h // stride))
        grid = np.stack((xv, yv), axis=2).reshape(-1, 2)
        grids.append(grid)
        expanded.append(np.full((grid.shape[0], 1), stride))
    return np.concatenate(grids).astype(np.float32), np.concatenate(expanded).astype(np.float32)


def fit_input(width: int, height: int, budget: int, multiple: int) -> tuple[int, int]:
    """Input (width, height) with the shape of the image and about budget x budget pixels.

    A 16:9 frame letterboxed into a square wastes almost half of the input on padding. With the same
    number of pixels (so the same cost) shaped like the image, every object is seen larger.
    """
    aspect = width / height
    area = budget * budget
    in_w = max(multiple, round((area * aspect) ** 0.5 / multiple) * multiple)
    in_h = max(multiple, round((area / aspect) ** 0.5 / multiple) * multiple)
    return int(in_w), int(in_h)


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
        self.strides = list(m["strides"])
        if self.input_size % max(self.strides) != 0:
            raise ValueError(f"input_size={self.input_size} must be a multiple of {max(self.strides)}")
        # The official file has a fixed 416 px input; scripts/make_dynamic_model.py frees it.
        fixed = model_input.shape[2]
        self.free_size = not isinstance(fixed, int)
        if not self.free_size and fixed != self.input_size:
            warnings.warn(
                f"{path.name} has a fixed {fixed} px input: ignoring input_size={self.input_size}.",
                stacklevel=2,
            )
            self.input_size = fixed
        # Same pixel budget, shaped like the image (needs the free-size model).
        self.match_aspect = bool(m["match_aspect"]) and self.free_size

        self.pad_value = int(m["pad_value"])
        self.conf = float(m["conf"])
        self.nms_threshold = float(m["nms"])
        self.cross_class_threshold = float(m["nms_cross_class"])
        self.keep_ids = np.array([COCO_CLASSES.index(name) for name in m["keep_classes"]], dtype=np.int64)
        self.roi: tuple[float, float, float, float] | None = None   # normalized x0, y0, x1, y1
        self.input_wh = (self.input_size, self.input_size)          # size used on the last frame
        self._grid_cache: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}

    @property
    def input_label(self) -> str:
        """The input actually used, for the screen: '320' or '416x256'."""
        w, h = self.input_wh
        return str(w) if w == h else f"{w}x{h}"

    def set_roi(self, roi) -> None:
        """Region of interest of the camera (normalized x0, y0, x1, y1), or None for the whole frame."""
        if roi is None:
            self.roi = None
            return
        x0, y0, x1, y1 = (float(v) for v in roi)
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError(f"roi must be x0 < x1 and y0 < y1 within 0..1, got {roi}")
        self.roi = (x0, y0, x1, y1)

    def _grids_for(self, width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
        if self.match_aspect:
            self.input_wh = fit_input(width, height, self.input_size, max(self.strides))
        else:
            self.input_wh = (self.input_size, self.input_size)
        if self.input_wh not in self._grid_cache:
            self._grid_cache[self.input_wh] = make_grids(self.input_wh, self.strides)
        return self._grid_cache[self.input_wh]

    def infer(self, image: np.ndarray) -> tuple[np.ndarray, float]:
        """Runs the network on an image. Returns the decoded predictions and the resize ratio."""
        grids, strides = self._grids_for(image.shape[1], image.shape[0])
        blob, ratio = letterbox(image, self.input_wh, self.pad_value)
        raw = self.session.run(None, {self.input_name: blob})[0][0]
        return decode_outputs(raw, grids, strides), ratio

    def detect(self, frame: np.ndarray) -> sv.Detections:
        x_off = y_off = 0
        image = frame
        if self.roi is not None:
            h, w = frame.shape[:2]
            x_off, y_off = int(self.roi[0] * w), int(self.roi[1] * h)
            image = frame[y_off:int(self.roi[3] * h), x_off:int(self.roi[2] * w)]
        decoded, ratio = self.infer(image)
        xyxy, scores, class_ids = postprocess(
            decoded, ratio, image.shape[:2], self.conf, self.nms_threshold, self.keep_ids,
            self.cross_class_threshold,
        )
        if x_off or y_off:
            xyxy = xyxy + np.array([x_off, y_off, x_off, y_off], dtype=xyxy.dtype)
        return sv.Detections(xyxy=xyxy, confidence=scores, class_id=class_ids)
