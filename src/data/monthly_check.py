"""月次チェックの計算部分 (KIK-738).

日次・週次があるのに月次が無かった。だが**意思決定は月次でしか起きない**——
冷却期間は買付から4週、月次上限は売買1回、投入計画も月1銘柄。
「今月の1回をどう使うか」を正面から扱う枠が無いまま、月に紐づく宿題
（翌月枠の銘柄未定・conviction 未認定）が週次のたびに持ち越されていた。

判断はしない。エージェントが読む事実だけを返す。
"""

import datetime
import glob
import re
from typing import Optional

# 投入計画は次の形で書かれる（行頭が年月、そのあとに銘柄・株数・金額が続く）:
#   "  2026-09     9104.T 商船三井   200株 ¥1,237,200  conviction"
#   "  2026-10     非Industrials枠  ―    ¥1,100,000"
#
# 行頭アンカーだけでは足りない。実データには行頭が日付の**散文**が普通にある:
#   "2026-08-03 の 7259.T アイシン 100株購入を、月次上限のカウントから除外する。"
#   "2026-09-01 に 8725.T を買った"
# これらを計画行と誤認すると、売却済み銘柄が「今月の投入枠 確定」として出る。
# 年月の直後が助詞（の/に/は/を/で/が/から/まで）で始まる行は散文として除外する。
_PLAN_ROW = re.compile(
    r"^[ \t]*(\d{4})-(\d{1,2})(?:-\d{1,2})?[ \t]+"
    r"(?![のにはをでがへとや]|から|まで|時点|現在|の時点)\S",
    re.MULTILINE,
)
_SYMBOL_PAT = re.compile(r"\b(\d{4}\.T)\b")
# 計画表らしさ: 株数・金額・tier のいずれかが同じ行にある
_PLAN_CELL = re.compile(r"(\d+\s*株|[¥￥]\s*[\d,]{4,}|conviction|normal)")


def _first(rec: dict, *keys: str):
    """最初に見つかった有効値。空文字は「無い」とみなす.

    `a or b` だと 0 を偽として次のキーに落とし、実現損益0の手仕舞いが消える。
    """
    for k in keys:
        v = rec.get(k)
        if v is not None and v != "":
            return v
    return None


def _to_number(value) -> Optional[float]:
    """`"12,000"` `"¥8,000"` `"+500"` を数値にする。駄目なら None.

    素の `float()` だと桁区切り付きの手書き値が ValueError で黙って捨てられる。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace(",", "").replace("¥", "").replace("￥", "")
    s = s.replace("円", "").replace("+", "")
    try:
        return float(s)
    except ValueError:
        return None


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
            records = load_json_records(f)
        except Exception:
            continue
        for rec in records:
            d = _first(rec, "date", "trade_date")
            act = _first(rec, "action", "trade_type")
            if not (d and act):
                continue
            out.append({
                "date": d, "action": str(act).lower(), "symbol": rec.get("symbol", ""),
                "shares": rec.get("shares"), "price": rec.get("price"),
                # or チェーンだと実現損益 0 を偽として次のキーに落としてしまう
                "realized_pnl": _first(rec, "realized_pnl", "realized_pl", "pnl"),
                "memo": rec.get("memo", ""),
            })
    return out


# sector_matrix.yaml の scale_rules に対応する。**yaml から読めない**ので写しである。
#   → `.claude/agents/risk-assessor/sector_matrix.yaml` は YAML として壊れており
#     （82行目付近で ParserError）、safe_load できない。エージェントが散文として
#     読む前提のファイルなので、機械的な SSoT にはできない。
#   ルールを改訂したら **両方** 直すこと。乖離は check_tier_rules() が検出する。
_TIER_RULES = {
    "small":  {"cooldown_weeks": 4, "monthly_limit": 1},   # 〜$50K
    "medium": {"cooldown_weeks": 2, "monthly_limit": 1},   # $50K〜$200K
    "large":  {"cooldown_weeks": 1, "monthly_limit": 4},   # $200K〜
}
# 運用値。ティアが上がっても自動では緩めない（下記の理由）
_OPERATIVE_TIER = "small"


def tier_rules(total_assets_usd: float) -> dict:
    """PF規模ティアと、実際に適用する冷却期間・月次上限を返す.

    ⚠️ **ティアから自動で冷却期間を緩めない。** 総資産は現在 $50,592 で
    $50K 境界を 1.2% 超えたところにあり、機械的に medium を適用すると
    冷却が 4週→2週 に縮んで「今日買える」に変わる。だが投入計画も記録も
    すべて 4週（8/10 解禁）前提で組まれている。

    2026-08-05 には逆向きの事故が起きている——medium と思い込んで冷却2週・
    月4回で3ヶ月の投入計画を作ったが、実際は small だった
    （`checklist_review.check_pf_tier` の docstring）。境界の 1% で規律が
    自動的に緩むのは、その事故と同じ構造を作ることになる。

    そこで運用値は保守側（small）に固定し、ティアが違う場合は
    ``tier_mismatch`` で見せる。緩めるかどうかは人が決める。
    """
    tier = ("small" if total_assets_usd < 50_000
            else "medium" if total_assets_usd < 200_000 else "large")
    op = _TIER_RULES[_OPERATIVE_TIER]
    near = abs(total_assets_usd - 50_000) < 5_000 or abs(total_assets_usd - 200_000) < 20_000
    return {
        "tier_by_size": tier,
        "operative_tier": _OPERATIVE_TIER,
        "cooldown_weeks": op["cooldown_weeks"],
        "monthly_limit": op["monthly_limit"],
        "total_assets_usd": round(total_assets_usd),
        "near_boundary": near,
        "tier_mismatch": (
            None if tier == _OPERATIVE_TIER else
            f"規模は {tier}（{_TIER_RULES[tier]['cooldown_weeks']}週 / 月"
            f"{_TIER_RULES[tier]['monthly_limit']}回）だが、運用は "
            f"{_OPERATIVE_TIER}（{op['cooldown_weeks']}週 / 月{op['monthly_limit']}回）"
            "のまま。緩めるかは人が判断する"
        ),
        "source": "monthly_check._TIER_RULES（sector_matrix.yaml は YAML として壊れており読めない）",
    }


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

    ``excluded_dates`` は枠のカウントから外すだけで、取引が起きた事実は消さない。
    除外した分は ``this_month_trades`` に ``excluded: True`` を付けて残す
    （消すと同じレポートに「今月0回」と「今月8件の実現損益」が並んで矛盾する）。
    """
    today = today or datetime.date.today()
    excluded = excluded_dates or set()
    dated = [t for t in trades if t.get("date")]
    counted = [t for t in dated if t["date"] not in excluded]
    buys = sorted(t["date"] for t in counted if t.get("action") == "buy")
    this_month = [
        {**t, "excluded": t["date"] in excluded}
        for t in dated if t["date"][:7] == month_key(today)
    ]

    if buys:
        last_buy = buys[-1]
        cool_end = (datetime.date.fromisoformat(last_buy)
                    + datetime.timedelta(weeks=cooldown_weeks))
        cool_days = (cool_end - today).days
    else:
        last_buy, cool_end, cool_days = None, None, None

    used = sum(1 for t in this_month if not t["excluded"])
    remaining = max(0, monthly_limit - used)
    can_buy = remaining > 0 and (cool_days is not None and cool_days <= 0)

    blockers = []
    if cool_days is None:
        # 空にすると「買えません（理由なし）」になる。check_cooldown も
        # 同じ状況で "買付履歴が読めない" を返している
        blockers.append("買付履歴なし（冷却期間を判定できない）")
    elif cool_days > 0:
        blockers.append(f"冷却期間あと{cool_days}日（{cool_end}解禁）")
    if remaining <= 0:
        blockers.append(f"月次上限（今月{used}/{monthly_limit}回）")

    return {
        "month": month_key(today),
        "last_buy": last_buy,
        "cooldown_end": cool_end.isoformat() if cool_end else None,
        "cooldown_days_left": max(0, cool_days) if cool_days is not None else None,
        "cooldown_cleared": bool(cool_days is not None and cool_days <= 0),
        "cooldown_weeks": cooldown_weeks,
        "monthly_used": used,
        "monthly_limit": monthly_limit,
        "monthly_remaining": remaining,
        "can_buy_now": can_buy,
        "this_month_trades": this_month,
        "excluded_count": sum(1 for t in this_month if t["excluded"]),
        "trades_loaded": len(trades),
        "blockers": blockers,
    }


# --- 月次枠の予定 ---------------------------------------------------------


def plan_rows(content: str) -> list[tuple[str, str]]:
    """本文から計画表の行だけを (月キー, 行) で返す.

    条件は2つとも満たすこと:
      1. 行頭が年月で、直後が助詞でない（散文の日付を弾く）
      2. 同じ行に株数・金額・tier のいずれかがある（計画表のセルらしさ）
    """
    out = []
    for line in (content or "").splitlines():
        mm = _PLAN_ROW.match(line)
        if not mm or not _PLAN_CELL.search(line):
            continue
        out.append((f"{mm.group(1)}-{int(mm.group(2)):02d}", line.strip()))
    return out


def latest_plan_note(notes: list[dict]) -> Optional[dict]:
    """投入計画表を持つ **最新の** target ノートを1件返す.

    全ノートを横断して行を拾うと、破棄済みの旧計画（2026-08-07 に「全銘柄100株」
    から集中版へ差し替え済み）の行まで現在の計画として数えてしまう。

    ⚠️ 「投入計画」等のキーワードが本文にあるか、では判定しない。実データでは
    その語を含むだけの散文ノートが複数あり、選ばれると**売却済みの 6268.T が
    「今月の投入枠 確定」**として出た。計画表の**形**（horizon 内かに関わらず、
    異なる年月の計画行が2行以上ある）で判定する。
    """
    cands = []
    for n in notes:
        if n.get("type") != "target":
            continue
        rows = plan_rows(n.get("content") or "")
        if len({m for m, _ in rows}) >= 2:
            cands.append(n)
    if not cands:
        return None
    return max(cands, key=lambda n: (n.get("timestamp") or n.get("date") or ""))


def planned_slots(notes: list[dict], today: Optional[datetime.date] = None,
                  horizon: int = 3) -> list[dict]:
    """最新の投入計画から「N月に何を買う予定か」を拾う.

    自然文の完全な解析はしない。判定できなかったものは黙って落とさず
    根拠行をそのまま返す。目的は「10月枠が未定のまま9月末を迎える」を
    防ぐことであって、銘柄を正確に構造化することではない。

    ``horizon`` を超える計画行も落とさず ``beyond_horizon`` に載せる。
    現行計画は 2026-08〜12 の5ヶ月あり、horizon=3 だと 12月のアイシン
    （conviction 認定が要る）が8月・9月の実行時に一切現れなかった。
    """
    today = today or datetime.date.today()
    months = [month_key(add_months(today, i)) for i in range(horizon + 1)]
    found: dict[str, dict] = {m: {"month": m, "symbols": [], "lines": []} for m in months}

    note = latest_plan_note(notes)
    rows = plan_rows((note or {}).get("content") or "")
    beyond: dict[str, dict] = {}
    for key, line in rows:
        bucket = found.get(key)
        if bucket is None:
            if key < month_key(today):
                continue          # 過ぎた月は出さない
            bucket = beyond.setdefault(key, {"month": key, "symbols": [], "lines": []})
        bucket["lines"].append(line)
        for s in _SYMBOL_PAT.findall(line):
            if s not in bucket["symbols"]:
                bucket["symbols"].append(s)

    out = []
    for m in months + sorted(beyond):
        e = found.get(m) or beyond[m]
        e["decided"] = bool(e["symbols"])
        e["status"] = "確定" if e["decided"] else ("枠あり銘柄未定" if e["lines"]
                                                  else "記載なし")
        e["source"] = (note or {}).get("id")
        e["beyond_horizon"] = m not in found
        out.append(e)
    return out


# --- conviction 認定 -------------------------------------------------------

_CV_ID = ("CV1", "CV2", "CV3")


def conviction_status(symbol: str, notes: list[dict],
                      stop_levels: Optional[dict] = None) -> dict:
    """conviction tier を返す。判定は ``concentration.classify_conviction`` に委譲.

    ⚠️ ここで CV1-CV3 を独自判定してはいけない。KIK-738 では本文の "CV1" という
    文字列の有無で判定していたが、同じ CV1-CV3 を**構造から**判定する
    ``concentration.classify_conviction`` が既にあり、答えが食い違っていた:

      7453.T 良品計画 → concentration: conviction_override / 独自判定: normal
      7259.T アイシン → concentration: conviction            / 独自判定: normal

    とくに ``conviction_override``（ユーザーが無条件保有と決めた銘柄。売却提案
    禁止・上限判定の対象外）の概念が独自判定には無く、**免除した銘柄に毎月
    認定作業を催促する**ことになっていた。また上限が 25% と 15% で食い違うため、
    月次と発注前チェックで発注可能数量が変わる。

    本文の "CV1" 等の記述は判定には使わず、``evidence``（人が読む根拠）として
    添えるだけにする。否定語のホワイトリスト（未充足/未取得/未整備…）で
    充足を判定する方式もやめた——語彙から漏れた瞬間に全部 3/3 に戻る。
    """
    from src.data.concentration import classify_conviction

    verdict = classify_conviction(symbol, notes, stop_levels)

    evidence: dict[str, list[str]] = {c: [] for c in _CV_ID}
    for n in notes:
        if n.get("symbol") != symbol:
            continue
        for line in (n.get("content") or "").splitlines():
            for cid in _CV_ID:
                if cid in line:
                    evidence[cid].append(line.strip())

    criteria = verdict.get("criteria") or {}
    checks = {cid: {"met": bool(criteria.get(cid)), "evidence": evidence[cid][:3]}
              for cid in _CV_ID}
    met = sum(1 for c in checks.values() if c["met"])
    tier = verdict.get("tier", "normal")
    return {
        "symbol": symbol,
        "tier": tier,
        # override は「認定済み」ではなくユーザーによる免除。認定作業を促さない
        "qualified": tier in ("conviction", "conviction_override"),
        "exempt": tier == "conviction_override",
        "checks": checks, "met": met, "total": len(_CV_ID),
        "reasons": verdict.get("reasons"),
        "note": "判定は concentration.classify_conviction。evidence は根拠の抜粋",
    }


# --- 目標進捗 ---------------------------------------------------------------


def _cagr(start: float, end_value: float, years: float) -> Optional[float]:
    if start <= 0 or end_value <= 0 or years <= 0:
        return None
    return ((end_value / start) ** (1 / years) - 1) * 100


def load_goal() -> dict:
    """目標額と期限を config/allocation.yaml から読む.

    KIK-738 では Python のデフォルト引数に埋めていたが、同じ目標が
    allocation.yaml のコメント / target ノート / コードの3箇所にあり、
    既に1箇所（allocation.yaml の「2030年3月末」）が古くなっていた。
    期限は2日で1回改訂されているので、出典は1つにする。
    """
    import os

    import yaml

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        with open(os.path.join(root, "config", "allocation.yaml"), encoding="utf-8") as f:
            g = (yaml.safe_load(f) or {}).get("goal") or {}
        return {"amount": float(g["amount"]), "deadline": str(g["deadline"]),
                "source": "config/allocation.yaml"}
    except Exception:
        return {"amount": 10_000_000.0, "deadline": "2031-04-30", "source": "fallback"}


def goal_progress(
    equity_value: float,
    cash: float,
    target_amount: Optional[float] = None,
    deadline: Optional[str] = None,
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
    from src.data.common import safe_float
    from src.data.concentration import planned_equity as _planned_equity

    goal = load_goal()
    target_amount = safe_float(target_amount if target_amount is not None
                               else goal["amount"])
    deadline = deadline or goal["deadline"]
    today = today or datetime.date.today()
    equity_value = safe_float(equity_value)
    cash = safe_float(cash)
    total = equity_value + cash

    try:
        end = datetime.date.fromisoformat(deadline)
    except ValueError:
        return {"today": today.isoformat(), "deadline": deadline,
                "error": f"期限を日付として読めない: {deadline!r}"}

    # ⚠️ 下限クランプ（旧 max(..., 1e-9)）は絶対に入れないこと。_cagr の
    # years<=0 ガードを到達不能にし、期限当日に ratio**1e9 で OverflowError、
    # 期限超過では静かに -100% を返していた。
    years = (end - today).days / 365.25
    expired = years <= 0

    # A: 現状維持（現金を寝かせたまま株式だけ伸ばす）
    as_is = _cagr(equity_value, target_amount - cash, years)

    # B: 投入完了後（allocation.yaml の cash ターゲットまで投入した株式額が分母）
    pe = _planned_equity(total, cash_target_pct)
    fully_invested = _cagr(pe, target_amount - (total - pe), years)

    return {
        "today": today.isoformat(),
        "total": total, "equity": equity_value, "cash": cash,
        "equity_pct": equity_value / total * 100 if total else 0,
        "target": target_amount, "deadline": deadline, "goal_source": goal["source"],
        "years_left": round(years, 2),
        "expired": expired,
        "gap": target_amount - total,
        "progress_pct": total / target_amount * 100 if target_amount else 0,
        "required_cagr_as_is": round(as_is, 2) if as_is is not None else None,
        "required_cagr_fully_invested": (round(fully_invested, 2)
                                         if fully_invested is not None else None),
        "planned_equity": round(pe),
        "cash_target_pct": cash_target_pct,
        "caveat": ("必要年率は株式部分に対する値。as_is は現金を寝かせた場合で、"
                   "高いのは達成不能ではなく未投入の帰結。判断は fully_invested を見る。"
                   "expired=True のとき必要年率は None（計算できない）"),
    }


# --- 実現損益 ---------------------------------------------------------------


def realized_pnl(trades: list[dict], month: str,
                 excluded_dates: Optional[set] = None) -> dict:
    """指定月の確定売買と実現損益。月1回しか売買しないので月次がちょうどよい.

    ``excluded_dates``（誤発注日など）は枠のカウントから外すためのもので、
    損益は実際に発生している。**消さずに分けて返す**。
    """
    excluded = excluded_dates or set()
    rows = [t for t in trades if (t.get("date") or "")[:7] == month]
    total = 0.0
    parsed = unparsed = 0
    excluded_pnl = 0.0
    for t in rows:
        v = _to_number(t.get("realized_pnl"))
        if t.get("realized_pnl") is not None and v is None:
            unparsed += 1
            continue
        if v is None:
            continue
        parsed += 1
        if (t.get("date") or "") in excluded:
            excluded_pnl += v
        else:
            total += v
    sells = [t for t in rows if t.get("action") == "sell"]
    return {
        "month": month, "trades": rows,
        "trade_count": len(rows),
        "realized_pnl": total,
        "excluded_pnl": excluded_pnl,
        "excluded_count": sum(1 for t in rows if (t.get("date") or "") in excluded),
        # with_pnl は sells と比べる値。trade_count と比べると買付の分だけ
        # 常に足りなく見えて「取りこぼし」と誤読される
        "sells_with_pnl": parsed,
        "sells_missing_pnl": max(0, len(sells) - parsed),
        "unparsed_pnl": unparsed,
        "buys": sum(1 for t in rows if t.get("action") == "buy"),
        "sells": len(sells),
    }


# --- まとめ ---------------------------------------------------------------


def build_monthly_context(
    notes: list[dict],
    positions: list[dict],
    equity_value: float,
    cash: float,
    target_amount: Optional[float] = None,
    deadline: Optional[str] = None,
    today: Optional[datetime.date] = None,
    trade_dir: str = "data/history/trade",
    excluded_dates: Optional[set] = None,
    stop_levels: Optional[dict] = None,
    usdjpy: float = 157.0,
) -> dict:
    """月次チェックに必要な事実を1呼び出しで集める.

    個別に呼ぶ設計にすると組み立て忘れが起きる（auto_review と同じ構造）ので、
    入口を1つにする。目標額・期限を省略すると config/allocation.yaml から読む。
    """
    today = today or datetime.date.today()
    trades = load_trades(trade_dir)
    slots = planned_slots(notes, today)
    rules = tier_rules((equity_value + cash) / max(usdjpy, 1e-6))

    # 計画に登場する銘柄すべての conviction を見る（horizon 外も含む。
    # 12月のアイシンは認定が要るのに horizon=3 だと8月時点で現れなかった）
    upcoming = []
    for s in slots:
        for sym in s["symbols"]:
            if sym not in upcoming:
                upcoming.append(sym)

    return {
        "month": month_key(today),
        "tier_rules": rules,
        "budget": trade_budget(trades, today,
                               cooldown_weeks=rules["cooldown_weeks"],
                               monthly_limit=rules["monthly_limit"],
                               excluded_dates=excluded_dates),
        "slots": slots,
        "conviction": [conviction_status(s, notes, stop_levels) for s in upcoming],
        "goal": goal_progress(equity_value, cash, target_amount, deadline, today),
        "realized": realized_pnl(trades, month_key(today), excluded_dates),
        "last_month_realized": realized_pnl(trades, month_key(add_months(today, -1)),
                                            excluded_dates),
        "holdings": [p.get("symbol") for p in positions],
    }
