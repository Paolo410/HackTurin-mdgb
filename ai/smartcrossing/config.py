"""Loads config.yaml and applies the profile and --emulate-unoq overrides."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

AI_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = AI_DIR / "config.yaml"

_OVERRIDE_KEYS = ("profiles", "emulate_unoq")


def _deep_merge(base: dict, override: dict) -> dict:
    """Returns base updated with override, merging nested dicts."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: str | Path | None = None, profile: str = "pc", emulate_unoq: bool = False) -> dict:
    """Reads the YAML file and returns the effective configuration as a plain dict."""
    with open(path or DEFAULT_CONFIG, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    profiles = raw.get("profiles") or {}
    if profile not in profiles:
        raise ValueError(f"Unknown profile '{profile}'. Available: {sorted(profiles)}")

    cfg = {k: v for k, v in raw.items() if k not in _OVERRIDE_KEYS}
    cfg = _deep_merge(cfg, profiles[profile])
    if emulate_unoq:
        cfg = _deep_merge(cfg, raw.get("emulate_unoq"))
    cfg["profile"] = profile
    cfg["emulate_unoq"] = emulate_unoq
    return cfg


def resolve_path(path: str | Path) -> Path:
    """Paths in the config are relative to the ai/ folder."""
    p = Path(path)
    return p if p.is_absolute() else AI_DIR / p
