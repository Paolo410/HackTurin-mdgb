import numpy as np
import pytest

from smartcrossing.config import load_config, resolve_path
from smartcrossing.detector import (
    COCO_CLASSES, Detector, decode_outputs, letterbox, make_grids, nms, postprocess,
)

STRIDES = [8, 16, 32]


def test_coco_has_80_classes_in_official_order():
    assert len(COCO_CLASSES) == 80
    assert COCO_CLASSES[0] == "person" and COCO_CLASSES[2] == "car" and COCO_CLASSES[16] == "dog"


def test_letterbox_pads_bottom_right_keeps_bgr_and_range():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[..., 0] = 255  # pure blue in BGR
    blob, ratio = letterbox(frame, 416, 114)
    assert blob.shape == (1, 3, 416, 416) and blob.dtype == np.float32
    assert ratio == pytest.approx(1.3)
    # Image area: channel order unchanged, values not normalized.
    assert blob[0, 0, 0, 0] == 255 and blob[0, 1, 0, 0] == 0 and blob[0, 2, 0, 0] == 0
    # 240 * 1.3 = 312 rows of image, then padding with 114.
    assert blob[0, :, 311, 0].tolist() == [255, 0, 0]
    assert np.all(blob[0, :, 312:, :] == 114)


def test_grid_count_matches_model_output():
    grids, strides = make_grids(416, STRIDES)
    assert grids.shape == (3549, 2) and strides.shape == (3549, 1)   # 52*52 + 26*26 + 13*13
    assert make_grids(320, STRIDES)[0].shape == (2100, 2)            # 40*40 + 20*20 + 10*10


def test_decode_uses_grid_and_stride():
    grids, strides = make_grids(416, STRIDES)
    raw = np.zeros((3549, 85), dtype=np.float32)
    # Cell (x=3, y=2) of the stride-8 level is at index 2 * 52 + 3.
    idx = 2 * 52 + 3
    raw[idx, :4] = [0.5, 0.25, np.log(2.0), np.log(4.0)]
    out = decode_outputs(raw, grids, strides)
    assert out[idx, :4].tolist() == pytest.approx([(3 + 0.5) * 8, (2 + 0.25) * 8, 16.0, 32.0])
    # First cell of the stride-16 level.
    assert out[52 * 52, :4].tolist() == pytest.approx([0.0, 0.0, 16.0, 16.0])


def test_nms_keeps_best_of_overlapping_boxes():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    scores = np.array([0.6, 0.9, 0.5], dtype=np.float32)
    assert nms(boxes, scores, 0.45).tolist() == [1, 2]


def _prediction(cx, cy, w, h, obj, class_id, prob):
    row = np.zeros(85, dtype=np.float32)
    row[:5] = [cx, cy, w, h, obj]
    row[5 + class_id] = prob
    return row


def test_postprocess_filters_classes_scales_and_runs_per_class_nms():
    person, car, chair = COCO_CLASSES.index("person"), COCO_CLASSES.index("car"), COCO_CLASSES.index("chair")
    decoded = np.stack([
        _prediction(100, 100, 40, 80, 0.9, person, 0.9),   # kept
        _prediction(102, 101, 40, 80, 0.9, person, 0.7),   # same person, suppressed by NMS
        _prediction(100, 100, 40, 80, 0.9, car, 0.8),      # same place, other class: kept
        _prediction(300, 300, 50, 50, 0.9, chair, 0.9),    # class not kept
        _prediction(200, 200, 20, 20, 0.2, person, 0.5),   # below the confidence threshold
    ])
    keep_ids = np.array([person, car])
    boxes, scores, class_ids = postprocess(decoded, ratio=0.5, frame_shape=(832, 832), conf=0.3,
                                           nms_threshold=0.45, keep_ids=keep_ids)
    assert sorted(class_ids.tolist()) == [person, car]
    assert scores.max() == pytest.approx(0.81)
    # ratio 0.5: input pixels are doubled back to frame pixels.
    assert boxes[class_ids == person][0].tolist() == pytest.approx([160, 120, 240, 280])


def test_cross_class_duplicates_are_merged_but_person_on_bicycle_survives():
    person, bicycle, bird = (COCO_CLASSES.index(n) for n in ("person", "bicycle", "bird"))
    decoded = np.stack([
        _prediction(100, 100, 60, 120, 0.9, bird, 0.8),      # one object seen as two classes:
        _prediction(100, 100, 60, 122, 0.9, person, 0.6),    # only the best score stays
        _prediction(300, 100, 40, 100, 0.9, person, 0.9),    # rider ...
        _prediction(300, 130, 60, 60, 0.9, bicycle, 0.8),    # ... and the bicycle below: both stay
    ])
    boxes, scores, class_ids = postprocess(decoded, ratio=1.0, frame_shape=(416, 416), conf=0.3,
                                           nms_threshold=0.45, keep_ids=np.array([person, bicycle, bird]),
                                           cross_class_threshold=0.85)
    assert sorted(class_ids.tolist()) == sorted([bird, person, bicycle])


def test_postprocess_without_detections_is_empty():
    boxes, scores, class_ids = postprocess(np.zeros((10, 85), np.float32), 1.0, (100, 100), 0.3, 0.45,
                                           np.array([0]))
    assert boxes.shape == (0, 4) and scores.shape == (0,) and class_ids.shape == (0,)


needs_model = pytest.mark.skipif(not resolve_path(load_config()["model"]["path"]).is_file(),
                                 reason="model not prepared (bash scripts/get_model.sh)")


@needs_model
@pytest.mark.parametrize("size, rows", [(320, 2100), (416, 3549)])
def test_model_accepts_both_input_sizes(size, rows):
    cfg = load_config()
    cfg["model"]["input_size"] = size
    detector = Detector(cfg)
    assert detector.input_size == size
    blob, _ = letterbox(np.full((480, 640, 3), 114, dtype=np.uint8), size, 114)
    raw = detector.session.run(None, {detector.input_name: blob})[0]
    assert raw.shape == (1, rows, 85)
    assert len(detector.detect(np.full((480, 640, 3), 114, dtype=np.uint8))) == 0


@needs_model
def test_input_size_must_be_a_multiple_of_the_largest_stride():
    cfg = load_config()
    cfg["model"]["input_size"] = 330
    with pytest.raises(ValueError):
        Detector(cfg)


@needs_model
def test_free_size_model_matches_the_official_one_at_416():
    official = resolve_path("models/yolox_nano.onnx")
    if not official.is_file():
        pytest.skip("official model not downloaded")
    import onnxruntime as ort
    cfg = load_config()
    cfg["model"]["input_size"] = 416
    detector = Detector(cfg)
    rng = np.random.default_rng(0)
    blob = (rng.random((1, 3, 416, 416)) * 255).astype(np.float32)
    reference = ort.InferenceSession(str(official), providers=["CPUExecutionProvider"])
    expected = reference.run(None, {reference.get_inputs()[0].name: blob})[0]
    actual = detector.session.run(None, {detector.input_name: blob})[0]
    assert np.array_equal(actual, expected)
