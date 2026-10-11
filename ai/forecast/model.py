"""Inference of the gradient boosting model in pure Python: the control-room app needs no numpy or scikit-learn.

model.json is written by train.py: for every target a baseline and a list of regression trees, each stored as
parallel arrays (f feature index, t threshold, l/r children, v leaf value, m "missing goes left"). A leaf has
l = -1. The trees were fitted with a Poisson loss, so the prediction is exp(baseline + sum of the leaves).
"""
import json
import math
import os

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")


class Model:
    def __init__(self, data):
        self.features = list(data["features"])
        self.targets = data["targets"]
        self.meta = {k: v for k, v in data.items() if k != "targets"}

    @classmethod
    def load(cls, path=MODEL_PATH):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def raw(self, target, x):
        """Log of the expected count. x: values in the order of self.features, None = missing."""
        m = self.targets[target]
        total = m["baseline"]
        for tree in m["trees"]:
            f, t, left, right, miss = tree["f"], tree["t"], tree["l"], tree["r"], tree["m"]
            i = 0
            while left[i] >= 0:
                v = x[f[i]]
                if v is None:
                    i = left[i] if miss[i] else right[i]
                else:
                    i = left[i] if v <= t[i] else right[i]
            total += tree["v"][i]
        return total

    def predict(self, features):
        """features: {name: value or None} -> {target: expected count in one 15-minute window}."""
        x = [features.get(name) for name in self.features]
        return {target: math.exp(self.raw(target, x)) for target in self.targets}
