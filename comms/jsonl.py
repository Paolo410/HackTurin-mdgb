"""Append-only JSONL files with time-based rotation (docs/CONTRACTS.md v1, C3 transport rules).

- File name: <prefix>-YYYYMMDD-HHMMSS.jsonl (UTC time of creation): alphabetical order = time order.
- One complete line per write, terminated by "\n" and flushed. Files are never rewritten or truncated.
- Rotation = close the current file and open a new one.
"""
from __future__ import annotations

import json
import os
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_c3_dir() -> str:
    """$MDGB_C3_DIR, or logs/c3/ in the repo root (ignored by git)."""
    return os.environ.get("MDGB_C3_DIR") or os.path.join(REPO_ROOT, "logs", "c3")


class JsonlWriter:
    def __init__(self, directory: str, prefix: str, rotate_s: float = 3600, fsync: bool = False, clock=time.time):
        self.dir = directory
        self.prefix = prefix
        self.rotate_s = rotate_s
        self.fsync = fsync              # also survive a power cut, at the cost of one fsync per line
        self._clock = clock
        self._lock = threading.Lock()
        self._f = None
        self._opened_at = 0.0
        self.path = None

    def write(self, obj: dict) -> None:
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self._lock:
            now = self._clock()
            if self._f is None or now - self._opened_at >= self.rotate_s:
                self._rotate(now)
            self._f.write(line)
            self._f.flush()
            if self.fsync:
                os.fsync(self._f.fileno())

    def _rotate(self, now: float) -> None:
        if self._f is not None:
            self._f.close()
        os.makedirs(self.dir, exist_ok=True)
        name = time.strftime(f"{self.prefix}-%Y%m%d-%H%M%S.jsonl", time.gmtime(now))
        self.path = os.path.join(self.dir, name)
        self._f = open(self.path, "a", encoding="utf-8")
        self._opened_at = now

    def close(self) -> None:
        with self._lock:
            if self._f is not None:
                self._f.close()
                self._f = None
