"""EDINET クライアント インメモリキャッシュ（TTL付き）。"""

import time
from typing import Any, Optional

_cache: dict[str, tuple[float, Any]] = {}


def is_fresh(key: str, ttl_hours: float) -> bool:
    entry = _cache.get(key)
    return entry is not None and (time.time() - entry[0]) < ttl_hours * 3600


def get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    return entry[1] if entry is not None else None


def set(key: str, data: Any) -> None:
    _cache[key] = (time.time(), data)


def clear() -> None:
    _cache.clear()
