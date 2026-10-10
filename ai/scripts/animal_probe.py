"""Animal probe: what does the COCO detector say about photos of animals it was not trained on?

Usage (from ai/):
    python scripts/animal_probe.py <folder with images>

For every image: the best COCO class with its confidence, and the best animal class the system keeps.
At the end: the recall "at least one animal". (spec) Above 70% on wild boar and roe deer, no fine-tuning.
Images are only read, nothing is saved.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from smartcrossing.config import load_config  # noqa: E402
from smartcrossing.detector import COCO_CLASSES, Detector, decode_outputs, letterbox  # noqa: E402

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
NO_FINETUNING_ABOVE = 0.70   # (spec)


def probe(detector: Detector, image: np.ndarray, animal_ids: np.ndarray) -> tuple[str, float, str | None, float]:
    """Best class over all of COCO, and best kept animal class (None below the confidence threshold)."""
    blob, _ = letterbox(image, detector.input_size, detector.pad_value)
    raw = detector.session.run(None, {detector.input_name: blob})[0][0]
    decoded = decode_outputs(raw, detector._grids, detector._strides)
    scores = (decoded[:, 4:5] * decoded[:, 5:]).max(axis=0)
    best = int(scores.argmax())
    best_animal = int(animal_ids[scores[animal_ids].argmax()])
    animal_score = float(scores[best_animal])
    animal = COCO_CLASSES[best_animal] if animal_score >= detector.conf else None
    return COCO_CLASSES[best], float(scores[best]), animal, animal_score


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("folder")
    args = p.parse_args()
    cfg = load_config()
    folder = Path(args.folder)
    images = sorted(f for f in folder.iterdir() if f.suffix.lower() in IMAGE_EXTENSIONS) if folder.is_dir() else []
    if not images:
        print(f"No images in {folder}", file=sys.stderr)
        return 2
    try:
        detector = Detector(cfg)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    animal_names = list(cfg["derive"]["animal_classes"]) + ["bird"]
    animal_ids = np.array([COCO_CLASSES.index(name) for name in animal_names])

    hits = 0
    print(f"{'image':<32}{'best COCO class':<22}{'animal seen as':<18}")
    for path in images:
        image = cv2.imread(str(path))
        if image is None:
            print(f"{path.name:<32}(not readable)")
            continue
        best, score, animal, animal_score = probe(detector, image, animal_ids)
        hits += animal is not None
        seen = f"{animal} {animal_score:.2f}" if animal else f"- ({animal_score:.2f})"
        print(f"{path.name[:30]:<32}{best + f' {score:.2f}':<22}{seen:<18}")
    recall = hits / len(images)
    verdict = "no fine-tuning needed" if recall > NO_FINETUNING_ABOVE else "fine-tuning to consider"
    print(f"\nrecall 'at least one animal': {hits}/{len(images)} = {recall:.0%} -> {verdict} "
          f"(threshold {NO_FINETUNING_ABOVE:.0%}, input {detector.input_size}px, conf {detector.conf})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
