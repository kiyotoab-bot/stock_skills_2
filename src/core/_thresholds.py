"""Centralised threshold loader (KIK-446).

Reads ``config/thresholds.yaml`` once and exposes a simple accessor:

    from src.core._thresholds import th
    value = th("health", "rsi_drop_threshold", 40)

If the YAML file is missing or unreadable the accessor falls back to the
caller-supplied default, so existing behaviour is always preserved.
"""

import yaml
from pathlib import Path

_THRESHOLDS: dict | None = None


def get_thresholds() -> dict:
    """Return the full thresholds dict, loading from disk on first call."""
    global _THRESHOLDS
    if _THRESHOLDS is None:
        try:
            p = Path(__file__).resolve().parent.parent.parent / "config" / "thresholds.yaml"
            with open(p) as f:
                _THRESHOLDS = yaml.safe_load(f) or {}
        except Exception:
            _THRESHOLDS = {}
    return _THRESHOLDS


def th(section: str, key: str, default):
    """Look up *section.key* in thresholds, returning *default* on miss."""
    return get_thresholds().get(section, {}).get(key, default)
