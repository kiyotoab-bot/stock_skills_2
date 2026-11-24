"""総資産の推移を構造化して残す（KIK-789）.

それまで総資産の推移は daily / weekly / monthly レポートの本文（「総資産 … ¥N」）にしか
残っておらず、書式もばらばらだった。ダッシュボードで推移を描くために:

- ``backfill_from_reports``: 過去のレポート本文から抜き出す（``source="report_text"``・推計扱い）
- ``record_snapshot``: 日次チェックで1点ずつ ``data/history/assets.jsonl`` に追記（``source="daily"``）
- ``load_asset_history``: 両方を日付で合わせる。同じ日は daily を優先

⚠️ 本文から抜いた値は、その日のレポートが書いた推計（場中・前日終値の混在あり）。
外れ値（前後の点の中央値から ±15% 超）は捨てる。目標額などの誤抽出を防ぐため。
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Optional

DEFAULT_PATH = "data/history/assets.jsonl"
DEFAULT_REPORTS_DIR = "data/reports"

#: 外れ値の判定幅（前後の点の中央値からの乖離）
OUTLIER_PCT = 0.15

_REPORT_RE = re.compile(r"^(daily|weekly|monthly)_(\d{8})(?:_(\d{4}))?\.md$")
#: 「総資産」の後 30 文字以内（改行・別の ¥ を挟まない）に出る ¥ + 7桁以上
_TOTAL_RE = re.compile(r"総資産[^\n¥]{0,30}?¥\s?([\d,]{7,})")
_KIND_RANK = {"daily": 0, "weekly": 1, "monthly": 2}


def _iso(yyyymmdd: str) -> Optional[str]:
    try:
        return datetime.datetime.strptime(yyyymmdd, "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def extract_total(text: str) -> Optional[int]:
    """レポート本文の最初の「総資産 … ¥N」を返す。無ければ None."""
    m = _TOTAL_RE.search(text or "")
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


def drop_outliers(points: list[dict], pct: float = OUTLIER_PCT) -> tuple[list[dict], list[dict]]:
    """前後2点ずつ（自分を除く）の中央値から ``pct`` を超えて離れた点を捨てる.

    Returns (残した点, 捨てた点)。点が3つ未満なら何も捨てない。
    **最初と最後の点は捨てない**。片側しか比べる相手がなく、本当の暴落（最終日の急落）と
    誤抽出を区別できないため。表示側で推計点（破線）と分かるので、残す方に倒す。
    """
    if len(points) < 3:
        return list(points), []
    keep, dropped = [], []
    vals = [p["total"] for p in points]
    for i, p in enumerate(points):
        if i in (0, len(points) - 1):
            keep.append(p)
            continue
        nb = sorted(vals[max(0, i - 2):i] + vals[i + 1:i + 3])
        n = len(nb)
        med = nb[n // 2] if n % 2 else (nb[n // 2 - 1] + nb[n // 2]) / 2
        if med and abs(p["total"] / med - 1) > pct:
            dropped.append(p)
        else:
            keep.append(p)
    return keep, dropped


def backfill_from_reports(reports_dir: str = DEFAULT_REPORTS_DIR) -> dict:
    """過去レポートの本文から総資産を抜き出す.

    同じ日に複数あれば daily > weekly > monthly、同じ種類なら ``_HHMM`` の新しい方を採る。

    Returns
    -------
    dict
        ``{"points": [...], "dropped": [...], "unparsed": [ファイル名, ...]}``
    """
    best: dict[str, tuple] = {}
    unparsed = []
    for f in sorted(Path(reports_dir).glob("*.md")):
        m = _REPORT_RE.match(f.name)
        if not m:
            continue
        kind, ymd, hhmm = m.group(1), m.group(2), m.group(3) or "0000"
        date = _iso(ymd)
        if not date:
            continue
        try:
            total = extract_total(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            total = None
        if total is None:
            unparsed.append(f.name)
            continue
        key = (-_KIND_RANK[kind], hhmm)  # 大きいほど優先
        if date not in best or key > best[date][0]:
            best[date] = (key, {"date": date, "total": total, "source": "report_text",
                                "file": f.name})
    points = [best[d][1] for d in sorted(best)]
    keep, dropped = drop_outliers(points)
    return {"points": keep, "dropped": dropped, "unparsed": unparsed}


def _valid_date(v) -> bool:
    if not isinstance(v, str):
        return False
    try:
        return datetime.date.fromisoformat(v).isoformat() == v
    except ValueError:
        return False


def _opt_num(v) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _read_jsonl(path: str) -> list[dict]:
    out = []
    p = Path(path)
    if not p.exists():
        return out
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for line in text.splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # 壊れた行は読み飛ばす（途中で書き込みが切れた等）
        if (isinstance(rec, dict) and _valid_date(rec.get("date"))
                and isinstance(rec.get("total"), (int, float)) and not isinstance(rec.get("total"), bool)):
            out.append(rec)
    return out


def record_snapshot(total: float, equity: Optional[float] = None, cash: Optional[float] = None,
                    date: Optional[str] = None, path: str = DEFAULT_PATH) -> dict:
    """日次チェックで総資産を1点記録する。同じ日は上書き."""
    if isinstance(total, bool) or not isinstance(total, (int, float)) or not total > 0 or total == float("inf"):
        raise ValueError(f"total が不正: {total!r}")
    date = date or datetime.date.today().isoformat()
    if not _valid_date(date):
        raise ValueError(f"date は YYYY-MM-DD: {date!r}")
    rec = {"date": date, "total": float(total),
           "equity": _opt_num(equity), "cash": _opt_num(cash), "source": "daily"}
    rows = [r for r in _read_jsonl(path) if r["date"] != rec["date"]]
    rows.append(rec)
    rows.sort(key=lambda r: r["date"])
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(p)
    return rec


def load_asset_history(path: str = DEFAULT_PATH, reports_dir: Optional[str] = DEFAULT_REPORTS_DIR) -> list[dict]:
    """日次の記録とレポート本文からの推計を合わせる。日次の記録が始まった日以降は日次だけ使う."""
    merged: dict[str, dict] = {}
    daily = _read_jsonl(path)
    first_daily = daily[0]["date"] if daily else None
    if reports_dir:
        for p in backfill_from_reports(reports_dir)["points"]:
            # 日次の記録が始まった後は推計を混ぜない（実線と破線が交互になるのを防ぐ）
            if first_daily is None or p["date"] < first_daily:
                merged[p["date"]] = p
    for r in daily:
        merged[r["date"]] = r
    return [merged[d] for d in sorted(merged)]
