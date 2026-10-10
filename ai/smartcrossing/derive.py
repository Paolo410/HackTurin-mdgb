"""Road-user role of each detection: pedestrian, cyclist, motorcyclist, vehicles, animal, bird.

A cyclist is a person overlapping a bicycle (IoU above a threshold, person box above the bicycle box);
a motorcyclist is the same with a motorcycle. The role of a track is the majority of its frames
(see TrackState.role).
"""
from __future__ import annotations

import numpy as np

# Role given to the rider of each two-wheeler.
RIDER_ROLE = {"bicycle": "cyclist", "motorcycle": "motorcyclist"}
# A two-wheeler with a rider: the rider's track represents the pair, this one is not counted.
RIDDEN = "ridden"
PEDESTRIAN = "pedestrian"
ANIMAL = "animal"


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between every xyxy box of a (N, 4) and every box of b (M, 4): shape (N, M)."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.where(union > 0, union, 1), 0.0).astype(np.float32)


def derive_roles(xyxy: np.ndarray, class_names: list[str], cfg: dict) -> list[str]:
    """One role per detection of the frame. class_names are COCO names (the majority class of each track)."""
    d = cfg["derive"]
    rider_iou = float(d["rider_iou"])
    animals = set(d["animal_classes"])

    roles = []
    for name in class_names:
        if name == "person":
            roles.append(PEDESTRIAN)
        elif name in animals:
            roles.append(ANIMAL)
        else:
            roles.append(name)   # car, bus, truck, bird, bicycle, motorcycle

    persons = [i for i, name in enumerate(class_names) if name == "person"]
    wheels = [i for i, name in enumerate(class_names) if name in RIDER_ROLE]
    if not persons or not wheels:
        return roles

    boxes = np.asarray(xyxy, dtype=np.float32)
    iou = iou_matrix(boxes[persons], boxes[wheels])
    center_y = (boxes[:, 1] + boxes[:, 3]) / 2
    taken = set()
    for w_pos, w in enumerate(wheels):
        best, best_iou = None, rider_iou
        for p_pos, p in enumerate(persons):
            # Image y grows downwards: the rider's box is above the two-wheeler's.
            if p in taken or center_y[p] >= center_y[w]:
                continue
            if iou[p_pos, w_pos] > best_iou:
                best, best_iou = p, iou[p_pos, w_pos]
        if best is not None:
            taken.add(best)
            roles[best] = RIDER_ROLE[class_names[w]]
            roles[w] = RIDDEN
    return roles
