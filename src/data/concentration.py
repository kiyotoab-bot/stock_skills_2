"""集中度判定 (KIK-735)。

``config/allocation.yaml`` の ``concentration`` を単一の出所として、集中度を
**機械的に**判定する。従来は agent.md の散文で「1銘柄 < 15%」と書いてあるだけで、
分母の定義が無かったため同じPFが日によって逆の判定になっていた
（2026-08-06: 8031.T は総資産比 6.2% / 株式比 30.0%）。

設計上の要点:

1. **分母は株式部分**。現金は集中リスクを持たない。現金79%の再構築期に総資産比で
   見ると、どれだけ偏っていても永久に警告が出ない。
2. **上限は「これ以上買わない」の基準**であって、売却の根拠ではない。
   ``check_concentration`` は超過を報告するが、トリム提案は生成しない。
3. **conviction は自己申告ではなく条件**（CV1/CV2/CV3）。満たさなければ normal 扱い。
4. **conviction_override（ユーザーが無条件保有と明言）は上限判定の対象外**。
   7453.T 良品計画は株式比 26.8% で conviction limit 25% を超えるが、
   これを理由にトリムを提案してはならない（ユーザー指示）。
"""

from __future__ import annotations

import os
from typing import Any, Optional

import yaml

GREEN = "green"
YELLOW = "yellow"
RED = "red"
EXEMPT = "exempt"

_DEFAULT_CONFIG = os.path.join("config", "allocation.yaml")


def load_concentration_config(path: str = _DEFAULT_CONFIG) -> dict:
    """``allocation.yaml`` の concentration 関連セクションを読む。"""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return {
        "concentration": cfg.get("concentration", {}),
        "conviction_criteria": cfg.get("conviction_criteria", []),
        "conviction_override": cfg.get("conviction_override", {}),
    }


def classify_conviction(
    symbol: str,
    notes: list[dict],
    stop_levels: Optional[dict] = None,
) -> dict:
    """CV1/CV2/CV3 を判定し、``normal`` / ``conviction`` / ``conviction_override`` を返す。

    Parameters
    ----------
    notes
        ``load_notes()`` の結果。thesis / exit-rule を探す。
    stop_levels
        ``note_manager.get_stop_levels()`` の結果。CV3 の判定に使う。

    Returns
    -------
    dict
        ``tier`` / ``criteria``（CV毎の bool）/ ``reasons``
    """
    sym = (symbol or "").upper()
    mine = [n for n in notes if str(n.get("symbol") or "").upper() == sym]
    stop = (stop_levels or {}).get(symbol) or (stop_levels or {}).get(sym) or {}

    # conviction_override: ユーザーが「テーゼ関係なく保持」と明言したもの
    override = bool(stop.get("conviction"))
    if not override:
        for n in mine:
            content = str(n.get("content") or "")
            if "conviction_override" in content or "無条件conviction" in content:
                override = True
                break

    theses = [n for n in mine
              if (n.get("note_type") or n.get("type")) == "thesis"]
    cv2 = bool(theses)

    # CV1: 一次情報での検証を明示した thesis があるか
    _PRIMARY = ("J-Quants", "決算短信", "会社発表", "会社予想", "一次情報")
    cv1 = any(any(k in str(n.get("content") or "") for k in _PRIMARY) for n in theses)

    # CV3: exit 条件（ストップ値 or 撤退条件）が残っているか
    cv3 = stop.get("stop") is not None
    if not cv3:
        cv3 = any((n.get("note_type") or n.get("type")) == "exit-rule" for n in mine)

    criteria = {"CV1": cv1, "CV2": cv2, "CV3": cv3}
    if override:
        tier = "conviction_override"
    elif all(criteria.values()):
        tier = "conviction"
    else:
        tier = "normal"

    reasons = [k for k, v in criteria.items() if not v]
    return {"symbol": symbol, "tier": tier, "criteria": criteria,
            "unmet": reasons, "override": override}


def planned_equity(total_assets: float, cash_target_pct: float = 20.0) -> float:
    """フル投資時に見込まれる株式額。**再構築期の集中度判定はこれを分母にする。**

    現在の株式額を分母にすると、株式が総資産の20%しかない再構築期には
    100株買うだけで必ず上限を超える。実測（2026-08-07）:
      株式 ¥1,609,100 に 7751.T キヤノン100株 ¥452,700 を足すと株式比 **22.0%**
      → normal limit 15% を突破するが、総資産比では 5.7% でリスクは小さい
    「最初の1銘柄は必ず100%」になる分母は、集中度の指標として使えない。

    ``cash_target_pct`` は ``role_targets`` の cash 中央値（normal なら [15,25] → 20）。
    """
    if total_assets is None or total_assets <= 0:
        return 0.0
    ratio = max(0.0, min(100.0, float(cash_target_pct))) / 100.0
    return float(total_assets) * (1.0 - ratio)


def _level(value: float, warn: float, limit: float) -> str:
    if value >= limit:
        return RED
    if value >= warn:
        return YELLOW
    return GREEN


def check_concentration(
    positions: list[dict],
    config: Optional[dict] = None,
    cash: float = 0.0,
    denominator: Optional[float] = None,
) -> dict:
    """保有ポジションの集中度を判定する。

    Parameters
    ----------
    positions
        ``[{"symbol", "value", "tier", "sector"}]``。``tier`` は
        ``classify_conviction`` の結果を入れる（省略時 ``normal``）。
    cash
        参考値（総資産比）の算出にのみ使う。**判定には使わない**。
    denominator
        判定に使う分母。再構築期は ``planned_equity()`` を渡す。
        省略時は現在の株式額（フル投資後はこれで正しい）。

    Returns
    -------
    dict
        ``basis`` / ``equity`` / ``stocks`` / ``top3`` / ``sectors`` / ``verdict``
    """
    cfg = (config or load_concentration_config())["concentration"]
    single = cfg.get("single_stock", {})
    basis = cfg.get("basis", "equity")

    equity = sum(float(p.get("value") or 0) for p in positions)
    total = equity + float(cash or 0)
    # 判定分母は「現在の株式」と「計画上の株式」の大きい方。
    # 再構築期に現在の株式を使うと最初の1銘柄が必ず100%になる。
    denom = max(equity, float(denominator or 0))
    if equity <= 0:
        return {"basis": basis, "equity": 0.0, "stocks": [], "top3": None,
                "sectors": [], "verdict": GREEN,
                "note": "株式保有なし — 集中度は判定不能"}

    stocks = []
    for p in positions:
        val = float(p.get("value") or 0)
        pct = val / denom * 100
        tier = p.get("tier") or "normal"
        if tier == "conviction_override":
            level, thr = EXEMPT, None
        else:
            thr = single.get(tier if tier in single else "normal", {})
            level = _level(pct, thr.get("warn", 12), thr.get("limit", 15))
        stocks.append({
            "symbol": p.get("symbol"), "value": val, "tier": tier,
            "pct_equity": pct,
            "pct_total": (val / total * 100) if total > 0 else None,
            "level": level,
            "limit": (thr or {}).get("limit") if thr else None,
            "sector": p.get("sector"),
        })
    stocks.sort(key=lambda s: -s["pct_equity"])

    t3cfg = cfg.get("top3_stocks", {})
    t3 = sum(s["pct_equity"] for s in stocks[:3])
    top3 = {"pct_equity": t3,
            "level": _level(t3, t3cfg.get("warn", 60), t3cfg.get("limit", 70)),
            "limit": t3cfg.get("limit")}

    seccfg = cfg.get("sector", {})
    agg: dict[Any, float] = {}
    for s in stocks:
        agg[s["sector"]] = agg.get(s["sector"], 0.0) + s["pct_equity"]
    sectors = [{"sector": k, "pct_equity": v,
                "level": _level(v, seccfg.get("warn", 35), seccfg.get("limit", 45)),
                "limit": seccfg.get("limit")}
               for k, v in sorted(agg.items(), key=lambda x: -x[1])]

    levels = [s["level"] for s in stocks] + [top3["level"]] + [x["level"] for x in sectors]
    verdict = RED if RED in levels else (YELLOW if YELLOW in levels else GREEN)
    return {"basis": basis, "equity": equity, "total_assets": total,
            "denominator": denom, "denominator_is_planned": denom > equity,
            "stocks": stocks, "top3": top3, "sectors": sectors, "verdict": verdict}


def max_additional_shares(
    symbol: str,
    price: float,
    positions: list[dict],
    tier: str = "normal",
    config: Optional[dict] = None,
    lot: int = 100,
    denominator: Optional[float] = None,
) -> dict:
    """上限に触れずに買い増せる株数を返す（日本株は100株単位）。

    「上限は買い増しの基準であって売却の根拠ではない」という方針を、
    実際に使える形にしたもの。既に上限超過なら 0 株を返す。

    ``denominator`` に ``planned_equity()`` を渡すと、再構築期でも意味のある
    答えが出る。渡さないと現在の株式額が分母になり、株式が小さい時期は
    どの銘柄も1単元すら買えないという結論になる。
    """
    cfg = (config or load_concentration_config())["concentration"]
    if tier == "conviction_override":
        # 上限判定の対象外。ただし買い増しは推奨しない
        return {"symbol": symbol, "lots": 0, "shares": 0, "reason":
                "conviction_override は上限対象外だが買い増しの根拠にもしない"}
    thr = cfg.get("single_stock", {}).get(
        tier if tier in cfg.get("single_stock", {}) else "normal", {})
    limit = float(thr.get("limit", 15)) / 100.0
    if price <= 0 or limit <= 0 or limit >= 1:
        return {"symbol": symbol, "lots": 0, "shares": 0, "reason": "計算不能"}

    current = sum(float(p.get("value") or 0) for p in positions
                  if str(p.get("symbol")) == str(symbol))
    equity = sum(float(p.get("value") or 0) for p in positions)
    denom = max(equity, float(denominator or 0))

    if denom > equity:
        # 計画株式額が分母。買い増しても分母は変わらない（現金から株式へ移るだけ）
        room = limit * denom - current
    else:
        # フル投資後: 買い増すと分子と分母の両方が増える
        #   (current + x) / (equity + x) <= limit  →  x <= (limit*equity - current)/(1-limit)
        room = (limit * equity - current) / (1 - limit)
    if room <= 0:
        return {"symbol": symbol, "lots": 0, "shares": 0,
                "reason": f"既に上限 {limit * 100:.0f}% に到達（現在 "
                          f"{current / denom * 100:.1f}%）" if denom > 0 else "計算不能"}
    lots = int(room // (price * lot))
    return {"symbol": symbol, "lots": lots, "shares": lots * lot,
            "amount": lots * lot * price, "room_jpy": room,
            "reason": f"上限 {limit * 100:.0f}% まで あと ¥{room:,.0f}"}
