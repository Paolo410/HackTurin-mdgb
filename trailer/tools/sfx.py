"""Small synthesized sound-design kit (no samples, no licences): ticks, drone, whoosh, boom,
riser, UI blips, heartbeat beeps, sonar pings. All mono float32 at 48 kHz."""
from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter

SR = 48000
rng = np.random.default_rng(11)


def _t(d: float) -> np.ndarray:
    return np.arange(int(d * SR)) / SR


def _env(n: int, a: float, r: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / max(r, 1e-4))


def _band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    b, a = butter(2, [lo / (SR / 2), min(hi, SR / 2 - 100) / (SR / 2)], "band")
    return lfilter(b, a, x)


def tick() -> np.ndarray:
    """accessible-signal style click: short bright knock"""
    t = _t(0.06)
    x = np.sin(2 * np.pi * 1850 * t) * np.exp(-t / 0.006) + 0.5 * _band(rng.standard_normal(len(t)), 2500, 7000) * np.exp(-t / 0.004)
    return (x / np.abs(x).max() * 0.9).astype(np.float32)


def drone(dur: float) -> np.ndarray:
    t = _t(dur)
    x = 0.6 * np.sin(2 * np.pi * 43 * t) + 0.3 * np.sin(2 * np.pi * 86.3 * t + 0.4 * np.sin(2 * np.pi * 0.2 * t))
    x += 0.15 * _band(rng.standard_normal(len(t)), 60, 400)
    env = np.minimum(1, t / 2.5) * np.minimum(1, (dur - t) / 1.5)
    return (x * env / 1.2).astype(np.float32)


def whoosh(dur: float = 0.9) -> np.ndarray:
    t = _t(dur)
    n = rng.standard_normal(len(t))
    out = np.zeros_like(n)
    for i, (lo, hi) in enumerate([(300, 1200), (800, 3000), (2000, 7000)]):
        out += _band(n, lo, hi) * np.exp(-((t - dur * (0.35 + 0.15 * i)) ** 2) / (2 * (dur * 0.18) ** 2))
    return (out / np.abs(out).max() * 0.8).astype(np.float32)


def boom(dur: float = 2.6) -> np.ndarray:
    t = _t(dur)
    f = 55 * np.exp(-t / 0.5) + 32
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t / 0.9)
    x += 0.35 * _band(rng.standard_normal(len(t)), 40, 900) * np.exp(-t / 0.25)
    x = np.tanh(2.2 * x)
    return (x / np.abs(x).max() * 0.95).astype(np.float32)


def riser(dur: float = 3.4) -> np.ndarray:
    t = _t(dur)
    k = t / dur
    n = rng.standard_normal(len(t))
    hp = np.zeros_like(n)
    for s in range(0, len(t), SR // 20):                       # sweep the band upward in steps
        e = min(len(t), s + SR // 20)
        lo = 300 + 6000 * (s / len(t)) ** 2
        hp[s:e] = _band(n[max(0, s - 2000):e], lo, lo * 3)[-(e - s):]
    tone = np.sin(2 * np.pi * np.cumsum(120 + 900 * k ** 2) / SR) * 0.35
    x = (hp + tone) * k ** 2.2
    return (x / np.abs(x).max() * 0.9).astype(np.float32)


def blip(freq: float = 2200) -> np.ndarray:
    t = _t(0.09)
    x = np.sin(2 * np.pi * freq * t) * _env(len(t), 0.002, 0.03)
    return (x * 0.8).astype(np.float32)


def heartbeat_beep() -> np.ndarray:
    t = _t(0.035)
    return (np.sin(2 * np.pi * 1320 * t) * _env(len(t), 0.001, 0.012) * 0.7).astype(np.float32)


def ping() -> np.ndarray:
    t = _t(1.4)
    x = np.sin(2 * np.pi * 1180 * t) * _env(len(t), 0.003, 0.25)
    for d, g in ((0.18, 0.4), (0.36, 0.2), (0.54, 0.1)):     # echoes
        k = int(d * SR)
        x[k:] += g * x[: len(x) - k]
    return (x / np.abs(x).max() * 0.8).astype(np.float32)


KIT = {"tick": tick, "drone": drone, "whoosh": whoosh, "boom": boom, "riser": riser, "blip": blip,
       "heartbeat": heartbeat_beep, "ping": ping}
