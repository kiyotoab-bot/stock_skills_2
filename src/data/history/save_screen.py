"""Save screening results to history (KIK-578 split from save.py)."""

import json
from datetime import date, datetime

from src.data.history._helpers import (
    _safe_filename,
    _history_dir,
    _sanitize,
    _write_graph,
)


def save_screening(
    preset: str,
    region: str,
    results: list[dict],
    sector: str | None = None,
    theme: str | None = None,
    base_dir: str = "data/history",
) -> str:
    """Save screening results to JSON.

    Returns the absolute path of the saved file.
    """
    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    identifier = f"{_safe_filename(region)}_{_safe_filename(preset)}"
    filename = f"{today}_{identifier}.json"

    payload = {
        "category": "screen",
        "date": today,
        "timestamp": now,
        "preset": preset,
        "region": region,
        "sector": sector,
        "theme": theme,
        "count": len(results),
        "results": results,
        "_saved_at": now,
    }

    d = _history_dir("screen", base_dir)
    path = d / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(payload), f, ensure_ascii=False, indent=2)

    # Neo4j dual-write -- 変換は graph_writers ひとつ（KIK-741）。
    # payload をそのまま渡すので、後から sync しても同じ結果になる。
    _write_graph("screen", payload)

    return str(path.resolve())
