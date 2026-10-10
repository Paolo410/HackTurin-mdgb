"""Attributes of a pedestrian, each decided once per track and then kept:

- child: median of the estimated height over a few frames below a threshold;
- slow: measured walking speed (median, only while moving, in the waiting zone or on the stripes)
  below a threshold;
- aid: optional ONNX classifier on 96x96 crops (normal / wheelchair / walking_aid / stroller).
  The model is trained separately; when its file is missing aid stays None and nothing fails.
  Model contract (ours): input 1x3x96x96 float32, BGR, 0..255; output one score per class, in the order
  of attributes.aid_classes in config.yaml.
"""
from __future__ import annotations

from collections import Counter, deque
from statistics import median

import cv2
import numpy as np
import onnxruntime as ort

from .config import resolve_path
from .tracking import TrackState

MEASURE_ZONES = ("waiting_zone_left", "waiting_zone_right", "crosswalk")


class AidClassifier:
    def __init__(self, session: ort.InferenceSession, cfg: dict):
        a = cfg["attributes"]
        self.session = session
        self.input_name = session.get_inputs()[0].name
        self.size = int(a["aid_input_size"])
        self.classes = list(a["aid_classes"])

    @classmethod
    def load(cls, cfg: dict) -> "AidClassifier | None":
        """None when the optional model file is not there."""
        path = resolve_path(cfg["attributes"]["aid_model_path"])
        if not path.is_file():
            return None
        return cls(ort.InferenceSession(str(path), providers=["CPUExecutionProvider"]), cfg)

    def classify(self, crop: np.ndarray) -> str:
        resized = cv2.resize(crop, (self.size, self.size), interpolation=cv2.INTER_LINEAR)
        blob = np.ascontiguousarray(resized.transpose(2, 0, 1), dtype=np.float32)[None]
        scores = self.session.run(None, {self.input_name: blob})[0][0]
        return self.classes[int(np.argmax(scores))]


class AttributeEstimator:
    def __init__(self, cfg: dict, aid_classifier: AidClassifier | None = None):
        a = cfg["attributes"]
        self.child_height = float(a["child_height_m"])
        self.height_samples = int(a["height_samples"])
        self.slow_speed = float(a["slow_speed_ms"])
        self.slow_min_time = float(a["slow_min_time_s"])
        self.moving_min = float(a["moving_min_speed_ms"])
        self.walk_samples = int(a["walk_speed_samples"])
        self.aid = aid_classifier
        self.aid_votes = int(a["aid_votes"])
        self.aid_min_votes = int(a["aid_min_votes"])
        self.aid_every = int(a["aid_every_n_frames"])

    def update(self, state: TrackState, dt: float, frame: np.ndarray | None = None, xyxy=None) -> dict:
        """Updates and returns state.attrs: child, slow, aid (None = not decided), walk_speed."""
        attrs = state.attrs
        if not attrs:
            attrs.update(child=None, slow=None, aid=None, walk_speed=None, _walk_time=0.0,
                         _walk_speeds=deque(maxlen=self.walk_samples), _aid_votes=Counter())

        if attrs["child"] is None and len(state.heights) >= self.height_samples:
            attrs["child"] = median(state.heights) < self.child_height

        # Walking speed: only the time spent moving counts, a pedestrian standing at the kerb is not slow.
        # The median ignores the moments of starting and stopping.
        if state.zone in MEASURE_ZONES and state.speed >= self.moving_min and dt > 0:
            attrs["_walk_time"] += dt
            attrs["_walk_speeds"].append(state.speed)
            attrs["walk_speed"] = median(attrs["_walk_speeds"])
            if attrs["slow"] is None and attrs["_walk_time"] >= self.slow_min_time:
                attrs["slow"] = attrs["walk_speed"] < self.slow_speed

        if (self.aid is not None and attrs["aid"] is None and frame is not None and xyxy is not None
                and state.age % self.aid_every == 0):
            x1, y1, x2, y2 = (int(v) for v in xyxy)
            crop = frame[max(y1, 0):y2, max(x1, 0):x2]
            if crop.size:
                votes = attrs["_aid_votes"]
                votes[self.aid.classify(crop)] += 1
                total = sum(votes.values())
                if total >= self.aid_votes or (total >= self.aid_min_votes and votes.most_common(1)[0][1] > total / 2):
                    attrs["aid"] = votes.most_common(1)[0][0]
        return attrs


def public_attrs(attrs: dict) -> dict:
    """The attributes as they go in a C3 event: child, slow, aid."""
    return {"child": attrs.get("child"), "slow": attrs.get("slow"), "aid": attrs.get("aid")}
