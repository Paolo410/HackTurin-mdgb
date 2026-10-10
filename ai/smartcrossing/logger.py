"""C3 events for comms/ and app/: append-only JSONL files. Never frames, only metadata.

Transport rules of docs/CONTRACTS.md (draft v1, owner: communication engineer):
- folder $MDGB_C3_DIR, default logs/c3/ in the root of the repository (ignored by git);
- file c3-YYYYMMDD-HHMMSS.jsonl (UTC time of opening): alphabetical order is time order;
- one complete line per write, ended by "\n" and flushed; files are never rewritten or truncated;
- rotation = close the file and open a new one.
Works offline: it only writes to the local disk.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable

from .config import resolve_path

C3_VERSION = 1


def c3_dir(cfg: dict) -> Path:
    env = os.environ.get("MDGB_C3_DIR")
    return Path(env) if env else resolve_path(cfg["logger"]["dir"]).resolve()


class C3Logger:
    def __init__(self, cfg: dict, directory: str | Path | None = None, clock: Callable[[], float] = time.time):
        lg = cfg["logger"]
        self.dir = Path(directory) if directory else c3_dir(cfg)
        self.prefix = lg["prefix"]
        self.rotate_s = float(lg["rotate_s"])
        self.status_every_s = float(lg["status_every_s"])
        self._clock = clock
        self._file = None
        self._opened_at = 0.0
        self._last_status = -float("inf")
        self.path: Path | None = None
        self.written = 0

    def write(self, event: dict) -> dict:
        """Adds v and ts and appends the event as one line. Returns the line as written."""
        now = self._clock()
        line = {"v": C3_VERSION, "ts": round(now, 2), **event}
        if self._file is None or now - self._opened_at >= self.rotate_s:
            self._rotate(now)
        self._file.write(json.dumps(line, separators=(",", ":"), ensure_ascii=False) + "\n")
        self._file.flush()
        self.written += 1
        return line

    def status_due(self) -> bool:
        return self._clock() - self._last_status >= self.status_every_s

    def write_status(self, state: str, fps: float, lat_ms: dict, counts: dict) -> dict:
        self._last_status = self._clock()
        return self.write({"type": "status", "state": state, "fps": round(fps, 1),
                           "lat_ms": {k: round(v) for k, v in lat_ms.items() if v is not None}, "counts": counts})

    def _rotate(self, now: float) -> None:
        if self._file is not None:
            self._file.close()
        self.dir.mkdir(parents=True, exist_ok=True)
        name = time.strftime(f"{self.prefix}-%Y%m%d-%H%M%S.jsonl", time.gmtime(now))
        self.path = self.dir / name
        self._file = open(self.path, "a", encoding="utf-8")   # append: a file is never truncated
        self._opened_at = now

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def flat_counts(counts: dict[str, dict[str, dict[str, int]]]) -> dict[str, int]:
    """LineCounter.counts -> the flat "counts" of the status event, e.g. {"ped_in": 14, "car_in": 52}."""
    out: dict[str, int] = {}
    for per_role in counts.values():
        for role, per_dir in per_role.items():
            name = "ped" if role == "pedestrian" else role
            for direction, n in per_dir.items():
                if n:
                    out[f"{name}_{direction}"] = out.get(f"{name}_{direction}", 0) + n
    return out
