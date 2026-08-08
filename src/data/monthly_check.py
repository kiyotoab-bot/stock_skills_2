"""月次チェックの計算部分 (KIK-738).

日次・週次があるのに月次が無かった。だが**意思決定は月次でしか起きない**——
冷却期間は買付から4週、月次上限は売買1回、投入計画も月1銘柄。
「今月の1回をどう使うか」を正面から扱う枠が無いまま、月に紐づく宿題
（翌月枠の銘柄未定・conviction 未認定）が週次のたびに持ち越されていた。

判断はしない。エージェントが読む事実だけを返す。
"""

import datetime
import glob
import json
import re
from pathlib import Path
from typing import Optional

# 投入計画は次の形で書かれる（行頭が年月）:
#   "  2026-09     9104.T 商船三井   200株 ¥1,237,200  conviction"
#   "  2026-10     非Industrials枠  ―    ¥1,100,000"
# 行のどこかに年月と銘柄があれば拾う、という緩い判定にすると
# 「2026-04-13 に 6701.T を買った」のような記述まで計画行として数えてしまう。
# **行頭アンカー**にして計画表の行だけを対象にする。
# MULTILINE 必須。付けないと本文全体に search したとき1行目しか見ない
_PLAN_ROW = re.compile(r"^[ \t]*(\d{4})-(\d{1,2})(?:-\d{1,2})?[ \t]+\S", re.MULTILINE)
_SYMBOL_PAT = re.compile(r"\b(\d{4}\.T)\b")
# 計画表を含む target ノートを見分ける手がかり
_PLAN_MARKERS = ("投入計画", "新計画", "発注指示書")


def month_key(d: datetime.date) -> str:
    return d.strftime("%Y-%m")


def add_months(d: datetime.date, n: int) -> datetime.date:
    """月末日を吸収しつつ n ヶ月進める（1日固定で十分）."""
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    return datetime.date(y, m + 1, 1)


# --- 売買枠 ---------------------------------------------------------------


def load_trades(trade_dir: str = "data/history/trade") -> list[dict]:
    """取引履歴を読む（list/dict 形式・キー名の揺れを吸収）."""
    from src.data.common import load_json_records

    out = []
    for f in sorted(glob.glob(f"{trade_dir}/*.json")):
        try:
            for rec in load_json_records(f):
                d = rec.get("date") or rec.get("trade_date")
                act = (rec.get("action") or rec.get("trade_type") or "").lower()
                if d and act:
                    out.append({
                        "date": d, "action": act, "symbol": rec.get("symbol", ""),
                        "shares": rec.get("shares"), "price": rec.get("price"),
                        "realized_pnl": (rec.get("realized_pnl")
                                         or rec.get("realized_pl") or rec.get("pnl")),
                        "memo": rec.get("memo", ""),
                    })
        except Exception:
            continue
    return out


def trade_budget(
    trades: list[dict],
    today: Optional[datetime.date] = None,
    cooldown_weeks: int = 4,
    monthly_limit: int = 1,
    excluded_dates: Optional[set] = None,
) -> dict:
    """今月あと何回買えるか。冷却期間と月次上限を1つにまとめて返す.

    冷却期間の起点は **買付のみ**（2026-08-06 改訂）。売却はリセットしない。
    月次上限は **売却も数える**（churn の抑制はこちらが担う）。
    """
    today = today or datetime.date.today()
    excluded = excluded_dates or set()
    valid = [t for t in trades if t["date"] not in excluded]
    buys = sorted(t["date"] for t in valid if t["action"] == "buy")
    this_month = [t for t in valid if t["date"][:7] == month_key(today)]

    if buys:
        last_buy = buys[-1]
        cool_end = (datetime.date.fromisoformat(last_buy)
                    + datetime.timedelta(weeks=cooldown_weeks))
        cool_days = (cool_end - today).days
    else:
        last_buy, cool_end, cool_days = None, None, None

    used = len(this_month)
    remaining = max(0, monthly_limit - used)
    can_buy = remaining > 0 and (cool_days is not None and cool_days <= 0)
    return {
        "month": month_key(today),
        "last_buy": last_buy,
        "cooldown_end": cool_end.isoformat() if cool_end else None,
        "cooldown_days_left": max(0, cool_days) if cool_days is not None else None,
        "cooldown_cleared": bool(cool_days is not None and cool_days <= 0),
        "monthly_used": used,
        "monthly_limit": monthly_limit,
        "monthly_remaining": remaining,
        "can_buy_now": can_buy,
        "this_month_trades": this_month,
        # 買えない理由を1つに絞らない。両方塞がっていることがある
        "blockers": [b for b in (
            None if cool_days is None or cool_days <= 0
            else f"冷却期間あと{cool_days}日（{cool_end}解禁）",
            None if remaining > 0 else f"月次上限（今月{used}/{monthly_limit}回）",
        ) if b],
    }


# --- 月次枠の予定 ---------------------------------------------------------


def latest_plan_note(notes: list[dict]) -> Optional[dict]:
    """投入計画を含む **最新の** target ノートを1件返す.

    全ノートを横断して拾うと、破棄済みの旧計画の行まで現在の計画として
    数えてしまう（実際 2026-08-07 に計画は「全銘柄100株」から集中版へ
    差し替えられており、両方の記述がノートに残っている）。
    """
    cands = [n for n in notes
             if n.get("type") == "target"
             and any(m in (n.get("content") or "") for m in _PLAN_MARKERS)
             and _PLAN_ROW.search(n.get("content") or "")]
    if not cands:
        return None
    return max(cands, key=lambda n: (n.get("timestamp") or n.get("date") or ""))


def planned_slots(notes: list[dict], today: Optional[datetime.date] = None,
                  horizon: int = 3) -> list[dict]:
    """最新の投入計画から「N月に何を買う予定か」を拾う.

    自然文の完全な解析はしない。**計画表の行**（行頭が年月）だけを対象にし、
    判定できなかったものは黙って落とさず根拠行をそのまま返す。
    目的は「10月枠が未定のまま9月末を迎える」を防ぐことであって、
    銘柄を正確に構造化することではない。
    """
    today = today or datetime.date.today()
    months = [month_key(add_months(today, i)) for i in range(horizon + 1)]
    found: dict[str, dict] = {m: {"month": m, "symbols": [], "lines": []} for m in months}

    note = latest_plan_note(notes)
    for line in ((note or {}).get("content") or "").splitlines():
        mm = _PLAN_ROW.match(line)
        if not mm:
            continue
        key = f"{mm.group(1)}-{int(mm.group(2)):02d}"
        if key not in found:
            continue
        found[key]["lines"].append(line.strip())
        for s in _SYMBOL_PAT.findall(line):
            if s not in found[key]["symbols"]:
                found[key]["symbols"].append(s)

    out = []
    for m in months:
        e = found[m]
        e["decided"] = bool(e["symbols"])
        e["status"] = "確定" if e["decided"] else ("枠あり銘柄未定" if e["lines"]
                                                  else "記載なし")
        e["source"] = (note or {}).get("id")
        out.append(e)
    return out


# --- conviction 認定 -------------------------------------------------------

_CV_LABEL = {
    "CV1": "一次情報で検証済み",
    "CV2": "投資テーゼが thesis ノートとして文書化されている",
    "CV3": "exit 条件（ストップ値 or 撤退条件）が明記されている",
}
_CV_NEGATIVE = ("未充足", "未認定", "未設定", "未検証")


def conviction_status(symbol: str, notes: list[dict]) -> dict:
    """conviction 認定の記録があるかを調べる.

    ⚠️ 充足を**推測しない**。「ストップ」「テーゼ」等のキーワードで判定すると、
    どの銘柄も何かの記述に引っかかって全部 3/3 になり、警告装置として死ぬ。
    **CV1/CV2/CV3 と明示的に書かれた行**だけを根拠にする。

    ⚠️ 対象は ``symbol`` フィールドがその銘柄のノートに限る。本文に銘柄名が
    出てくるだけの汎用ノート（日次レポート等）まで拾うと、同じノートに載った
    別銘柄の「CV1・CV2・CV3 が3つとも未充足」を巻き込んで、認定済みの銘柄まで
    未充足にしてしまう。構造化されている symbol フィールドだけを信じる。
    """
    evidence: dict[str, list[str]] = {c: [] for c in _CV_LABEL}
    negated: set = set()
    for n in notes:
        if n.get("symbol") != symbol:
            continue
        for line in (n.get("content") or "").splitlines():
            for cid in _CV_LABEL:
                if cid in line:
                    evidence[cid].append(line.strip())
                    if any(w in line for w in _CV_NEGATIVE):
                        negated.add(cid)

    checks = {}
    for cid, label in _CV_LABEL.items():
        has = bool(evidence[cid])
        checks[cid] = {
            "label": label,
            "recorded": has,
            "met": has and cid not in negated,
            "evidence": evidence[cid][:3],
        }
    met = sum(1 for c in checks.values() if c["met"])
    return {
        "symbol": symbol, "checks": checks, "met": met, "total": len(_CV_LABEL),
        "qualified": met == len(_CV_LABEL),
        "tier": "conviction" if met == len(_CV_LABEL) else "normal",
        "note": ("CV1-CV3 と明示された記述のみを根拠にしている。"
                 "記録が無い＝未認定であって、条件を満たしていないとは限らない"),
    }


# --- 目標進捗 ---------------------------------------------------------------


def _cagr(start: float, end_value: float, years: float) -> Optional[float]:
    if start <= 0 or end_value <= 0 or years <= 0:
        return None
    return ((end_value / start) ** (1 / years) - 1) * 100


def goal_progress(
    equity_value: float,
    cash: float,
    target_amount: float,
    deadline: str,
    today: Optional[datetime.date] = None,
    cash_target_pct: float = 20.0,
) -> dict:
    """目標に対する進捗。**必要リターンは株式部分に対して**計算する.

    現金は複利で増えないので、総資産に対して必要年率を出すと過小評価になる。

    ⚠️ 必要年率は「今の株式額」ではなく「**投入完了後の株式額**」を基準にしないと
    意味が変わる。現金79%を寝かせたままなら必要年率は 18%台になるが、それは
    達成不可能という話ではなく **投入していないことの帰結** でしかない。
    両方返して、どちらの数字を見ているかを取り違えないようにする。
    """
    today = today or datetime.date.today()
    total = equity_value + cash
    end = datetime.date.fromisoformat(deadline)
    years = max((end - today).days / 365.25, 1e-9)

    # A: 現状維持（現金を寝かせたまま株式だけ伸ばす）
    as_is = _cagr(equity_value, target_amount - cash, years)

    # B: 投入完了後（config/allocation.yaml の cash ターゲット中央値まで投入する）
    planned_equity = total * (1 - cash_target_pct / 100)
    planned_cash = total - planned_equity
    fully_invested = _cagr(planned_equity, target_amount - planned_cash, years)

    return {
        "today": today.isoformat(),
        "total": total, "equity": equity_value, "cash": cash,
        "equity_pct": equity_value / total * 100 if total else 0,
        "target": target_amount, "deadline": deadline,
        "years_left": round(years, 2),
        "gap": target_amount - total,
        "progress_pct": total / target_amount * 100 if target_amount else 0,
        "required_cagr_as_is": round(as_is, 2) if as_is is not None else None,
        "required_cagr_fully_invested": (round(fully_invested, 2)
                                         if fully_invested is not None else None),
        "planned_equity": round(planned_equity),
        "cash_target_pct": cash_target_pct,
        "caveat": ("必要年率は株式部分に対する値。as_is は現金を寝かせた場合で、"
                   "高いのは達成不能ではなく未投入の帰結。判断は fully_invested を見る"),
    }


# --- 実現損益 ---------------------------------------------------------------


def realized_pnl(trades: list[dict], month: str) -> dict:
    """指定月の確定売買と実現損益。月1回しか売買しないので月次がちょうどよい."""
    rows = [t for t in trades if t["date"][:7] == month]
    total = 0.0
    counted = 0
    for t in rows:
        v = t.get("realized_pnl")
        try:
            if v is not None:
                total += float(v)
                counted += 1
        except (TypeError, ValueError):
            continue
    return {
        "month": month, "trades": rows, "count": len(rows),
        "realized_pnl": total, "with_pnl": counted,
        "buys": sum(1 for t in rows if t["action"] == "buy"),
        "sells": sum(1 for t in rows if t["action"] == "sell"),
    }


# --- まとめ ---------------------------------------------------------------


def build_monthly_context(
    notes: list[dict],
    positions: list[dict],
    equity_value: float,
    cash: float,
    target_amount: float = 10_000_000,
    deadline: str = "2031-04-30",
    today: Optional[datetime.date] = None,
    trade_dir: str = "data/history/trade",
    excluded_dates: Optional[set] = None,
) -> dict:
    """月次チェックに必要な事実を1呼び出しで集める.

    個別に呼ぶ設計にすると組み立て忘れが起きる（auto_review と同じ構造）ので、
    入口を1つにする。
    """
    today = today or datetime.date.today()
    trades = load_trades(trade_dir)
    slots = planned_slots(notes, today)

    # 直近3ヶ月に登場する銘柄の conviction を見る
    upcoming = []
    for s in slots:
        for sym in s["symbols"]:
            if sym not in upcoming:
                upcoming.append(sym)

    return {
        "month": month_key(today),
        "budget": trade_budget(trades, today, excluded_dates=excluded_dates),
        "slots": slots,
        "conviction": [conviction_status(s, notes) for s in upcoming],
        "goal": goal_progress(equity_value, cash, target_amount, deadline, today),
        "realized": realized_pnl(trades, month_key(today)),
        "last_month_realized": realized_pnl(trades, month_key(add_months(today, -1))),
        "holdings": [p.get("symbol") for p in positions],
    }
