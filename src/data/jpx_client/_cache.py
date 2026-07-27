"""JPXクライアント用ファイルキャッシュ（週次168h / 日次24h）。"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"

_TTL_HOURS = {
    "weekly": 168,
    "daily": 24,
}


def _cache_path(kind: str, key: str) -> Path:
    safe_key = re.sub(r"[^a-zA-Z0-9]", "_", key)
    return CACHE_DIR / f"jpx_{kind}_{safe_key}.json"


def read_cache(kind: str, key: str, ttl_mode: str = "weekly") -> Optional[dict]:
    path = _cache_path(kind, key)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
        ttl = timedelta(hours=_TTL_HOURS.get(ttl_mode, 24))
        if datetime.now() - cached_at > ttl:
            return None
        return data
    except (json.JSONDecodeError, ValueError, KeyError, OSError):
        return None


def write_cache(kind: str, key: str, data: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["_cached_at"] = datetime.now().isoformat()
    path = _cache_path(kind, key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def week_key() -> str:
    """現在の ISO 年週キー (例: '202618')。"""
    iso = datetime.now().isocalendar()
    return f"{iso[0]}{iso[1]:02d}"


def date_key() -> str:
    """本日の日付キー (例: '20260430')。"""
    return datetime.now().strftime("%Y%m%d")
