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


# --- 枠 (KIK-751) -----------------------------------------------------------
#
# 中長期の投入計画（core）と短期売買（tactical）を別勘定で回す。
# 取引レコードに sleeve が無いものはすべて core。既存の履歴を書き換えずに
# 分離できるようにしてある。
CORE_SLEEVE = "core"
TACTICAL_SLEEVE = "tactical"


def filter_sleeve(trades: list[dict], sleeve: str = CORE_SLEEVE) -> list[dict]:
    """指定した枠の取引だけ返す。``sleeve=None`` で全件."""
    if sleeve is None:
        return list(trades)
    return [t for t in trades if (t.get("sleeve") or CORE_SLEEVE) == sleeve]


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
                # KIK-751: 枠の区別。未指定の過去レコードはすべて core（中長期）
                "sleeve": str(_first(rec, "sleeve", "role") or CORE_SLEEVE).lower(),
                # KIK-763: 月次上限の免除（ストップ執行など）。
                # ⚠️ ここは**ホワイトリスト**なので、載せ忘れたキーは黙って消える。
                # 保存側 (save_trade) に足しただけでは枠の判定まで届かない。
                "limit_exempt": bool(rec.get("limit_exempt")),
                "exempt_reason": rec.get("exempt_reason", ""),
            })
    return out


# sector_matrix.yaml を読めなかったときだけ使う非常用の写し。
# ルールの出典は yaml 側。改訂するときは yaml を直す。
#
# ⚠️ KIK-739 はここに「sector_matrix.yaml は YAML として壊れていて読めない」と
#    書いたが誤りだった。ワークツリー（HEAD から切る）で検証したため、
#    2026-08-06 の冷却期間改訂を含む**未コミットの修正版**を見ていなかった。
#    実際に動いているファイルは正常にパースできる。
_TIER_FALLBACK = {
    "small":  {"cooldown_weeks": 4, "monthly_limit": 1},   # 〜$50K
    "medium": {"cooldown_weeks": 2, "monthly_limit": 1},   # $50K〜$200K
    "large":  {"cooldown_weeks": 1, "monthly_limit": 4},   # $200K〜
}
# 運用ティア。規模が上がっても自動では緩めない（下記の理由）
_OPERATIVE_TIER = "small"
_COOLDOWN_RE = re.compile(r"(\d+)\s*週")


def load_tier_rules() -> dict:
    """`sector_matrix.yaml` からティア別の冷却期間・月次上限を読む.

      - 月次上限: `scale_rules.{tier}.max_trades`
      - 冷却期間: `do_nothing_checks` の「冷却期間」項の `cooldown`（"4週" 等）

    読めなければ `_TIER_FALLBACK` に落ちる。月次チェック自体は動かす。
    """
    import os

    import yaml

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(root, ".claude", "agents", "risk-assessor", "sector_matrix.yaml")
    rules = {k: dict(v) for k, v in _TIER_FALLBACK.items()}
    source = "fallback（sector_matrix.yaml を読めず）"
    try:
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        for tier, entry in (doc.get("scale_rules") or {}).items():
            if tier in rules and isinstance(entry, dict) and "max_trades" in entry:
                rules[tier]["monthly_limit"] = int(entry["max_trades"])
        for check in (doc.get("do_nothing_checks") or []):
            if isinstance(check, dict) and check.get("check") == "冷却期間":
                for tier, raw in (check.get("cooldown") or {}).items():
                    m = _COOLDOWN_RE.search(str(raw))
                    if tier in rules and m:
                        rules[tier]["cooldown_weeks"] = int(m.group(1))
        source = "sector_matrix.yaml"
    except Exception:
        pass
    return {"rules": rules, "source": source}


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
    loaded = load_tier_rules()
    table = loaded["rules"]
    tier = ("small" if total_assets_usd < 50_000
            else "medium" if total_assets_usd < 200_000 else "large")
    op = table[_OPERATIVE_TIER]
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
            f"規模は {tier}（{table[tier]['cooldown_weeks']}週 / 月"
            f"{table[tier]['monthly_limit']}回）だが、運用は "
            f"{_OPERATIVE_TIER}（{op['cooldown_weeks']}週 / 月{op['monthly_limit']}回）"
            "のまま。緩めるかは人が判断する"
        ),
        "source": loaded["source"],
    }


def trade_budget(
    trades: list[dict],
    today: Optional[datetime.date] = None,
    cooldown_weeks: int = 4,
    monthly_limit: int = 1,
    excluded_dates: Optional[set] = None,
    sleeve: Optional[str] = CORE_SLEEVE,
) -> dict:
    """今月あと何回買えるか。冷却期間と月次上限を1つにまとめて返す.

    冷却期間の起点は **買付のみ**（2026-08-06 改訂）。売却はリセットしない。
    月次上限は **売却も数える**（churn の抑制はこちらが担う）。

    ``excluded_dates`` は枠のカウントから外すだけで、取引が起きた事実は消さない。
    除外した分は ``this_month_trades`` に ``excluded: True`` を付けて残す
    （消すと同じレポートに「今月0回」と「今月8件の実現損益」が並んで矛盾する）。

    ``sleeve`` (KIK-751) で枠を絞る。既定は core（中長期）で、tactical の取引は
    中長期の冷却期間・月次上限を消費しない。``None`` を渡すと全件を数える。

    取引レコードの ``limit_exempt`` (KIK-763) も枠から外す。ストップ抵触による
    売却など、裁量で起こしたのではない取引に ``save_trade()`` が付ける印。
    ``excluded_dates`` が**呼び出し側の記憶に依存する**のに対し、こちらは
    レコード自身が持つので渡し忘れが起きない。2026-08-17 のルール確定
    「ストップ執行は月次上限の枠外」を仕組みで担保するのはこちら。

    ⚠️ ``limit_exempt`` は枠だけを外す。実現損益は ``realized_pnl()`` が
    通常どおり ``realized_pnl`` に計上する（``excluded_pnl`` に回さない）。
    ``excluded_dates`` は両方から外すので、性質が違う。混同しないこと。
    """
    today = today or datetime.date.today()
    excluded = excluded_dates or set()
    trades = filter_sleeve(trades, sleeve)
    dated = [t for t in trades if t.get("date")]

    def _off_budget(t: dict) -> bool:
        return t["date"] in excluded or bool(t.get("limit_exempt"))

    counted = [t for t in dated if not _off_budget(t)]
    buys = sorted(t["date"] for t in counted if t.get("action") == "buy")
    this_month = [
        {**t, "excluded": _off_budget(t)}
        for t in dated if t["date"][:7] == month_key(today)
    ]

    if buys:
        last_buy = buys[-1]
        cool_end = (datetime.date.fromisoformat(last_buy)
                    + datetime.timedelta(weeks=cooldown_weeks))
        cool_days = (cool_end - today).days
    elif cooldown_weeks <= 0:
        # KIK-751: 冷却期間を置かない枠（tactical）。判定すべき冷却が存在しない
        # ので「買付履歴なし」を塞ぐ理由にしない。塞いでいないものを blockers に
        # 並べると、can_buy_now=True と矛盾して読める。
        last_buy, cool_end, cool_days = None, None, 0
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
        "sleeve": sleeve,
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
                 excluded_dates: Optional[set] = None,
                 sleeve: Optional[str] = CORE_SLEEVE) -> dict:
    """指定月の確定売買と実現損益。月1回しか売買しないので月次がちょうどよい.

    ``excluded_dates``（誤発注日など）は枠のカウントから外すためのもので、
    損益は実際に発生している。**消さずに分けて返す**。

    ⚠️ ``limit_exempt`` (KIK-763) は**ここでは見ない。これは意図**である。
    ストップ抵触による売却は月次上限から外すが、実現損益は実在するので
    ``realized_pnl`` に通常どおり計上する。「枠から外れているのに損益に入っている」
    のは不整合ではなく、2026-08-17 のルール確定そのもの。
    ここに ``limit_exempt`` の除外を足すと、目標 ¥10,000,000 への進捗から
    ストップ執行分が消える。

    ``sleeve`` (KIK-751) で枠を絞る。既定は core。tactical の損益を混ぜると
    「中長期の投入計画がどれだけ効いたか」が測れなくなる。
    """
    excluded = excluded_dates or set()
    trades = filter_sleeve(trades, sleeve)
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
        "sleeve": sleeve,
    }


# --- 短期売買枠 (KIK-751) ---------------------------------------------------


_TACTICAL_DEFAULTS = {
    "enabled": False, "max_pct_of_total": 5, "max_positions": 1,
    "monthly_limit": 2, "cooldown_weeks": 0, "max_hold_weeks": 8,
    "hard_deadline": "12-31", "stop_pct": 8,
}


def _tactical_config() -> dict:
    """config/allocation.yaml の tactical セクション。読めなければ既定値."""
    try:
        import yaml
        with open("config/allocation.yaml", encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        return {**_TACTICAL_DEFAULTS, **(cfg.get("tactical") or {})}
    except Exception:
        return dict(_TACTICAL_DEFAULTS)


def tactical_status(
    trades: list[dict],
    positions: list[dict],
    total_assets: float,
    today: Optional[datetime.date] = None,
    config: Optional[dict] = None,
) -> dict:
    """短期売買枠の状態。中長期枠とは完全に別勘定で数える.

    保有期限が肝。「短期のつもりが塩漬けて中長期保有になる」を制度で防ぐために
    ``max_hold_weeks`` と年末の ``hard_deadline`` の両方を見て、超過したものを
    ``overdue`` として返す。損益に関係なく手仕舞う対象。
    """
    today = today or datetime.date.today()
    # 部分的な dict を渡されても既定で埋める。埋めないと max_pct_of_total が
    # 欠けたときに size_cap=0 になり、枠が黙って使えなくなる。
    cfg = {**_TACTICAL_DEFAULTS, **(config or _tactical_config())}
    # ``or`` で既定に落とすと 0 を潰す。0 は「置かない」という意思表示なので尊重する
    max_positions = int(cfg["max_positions"] if cfg.get("max_positions") is not None
                        else _TACTICAL_DEFAULTS["max_positions"])

    budget = trade_budget(trades, today,
                          cooldown_weeks=int(cfg.get("cooldown_weeks") or 0),
                          monthly_limit=int(cfg.get("monthly_limit") or 2),
                          sleeve=TACTICAL_SLEEVE)

    held = [p for p in positions
            if str(p.get("role") or "").lower() == TACTICAL_SLEEVE]
    tac_trades = filter_sleeve(trades, TACTICAL_SLEEVE)

    # 建玉ごとの経過週数。エントリー日は同一銘柄の直近 buy から引く
    open_positions = []
    for p in held:
        sym = p.get("symbol")
        buys = sorted(t["date"] for t in tac_trades
                      if t.get("symbol") == sym and t.get("action") == "buy")
        entry = buys[-1] if buys else None
        weeks = deadline = None
        if entry:
            d = datetime.date.fromisoformat(entry)
            weeks = (today - d).days / 7
            deadline = (d + datetime.timedelta(weeks=int(cfg["max_hold_weeks"]))).isoformat()
        open_positions.append({
            "symbol": sym, "shares": p.get("shares"), "entry_date": entry,
            "weeks_held": round(weeks, 1) if weeks is not None else None,
            "hold_deadline": deadline,
        })

    # 年末の強制手仕舞い日
    mm, dd = str(cfg.get("hard_deadline") or "12-31").split("-")
    year_end = datetime.date(today.year, int(mm), int(dd))

    overdue = []
    for op in open_positions:
        if op["weeks_held"] is not None and op["weeks_held"] >= cfg["max_hold_weeks"]:
            overdue.append(f"{op['symbol']}: 保有{op['weeks_held']}週 "
                           f"（上限{cfg['max_hold_weeks']}週）")
        elif op["entry_date"] is None:
            overdue.append(f"{op['symbol']}: エントリー日が取引履歴から引けない")
    if today >= year_end and open_positions:
        overdue.append(f"年末期限 {year_end.isoformat()} を過ぎている")

    cap = total_assets * float(cfg.get("max_pct_of_total") or 0) / 100

    blockers = list(budget["blockers"])
    if len(open_positions) >= max_positions:
        blockers.append(f"同時保有上限（{len(open_positions)}/{max_positions}銘柄）")
    if not cfg.get("enabled"):
        blockers.append("短期枠が無効（config/allocation.yaml の tactical.enabled）")

    return {
        "enabled": bool(cfg.get("enabled")),
        "max_pct_of_total": cfg.get("max_pct_of_total"),
        "size_cap": round(cap),
        "max_positions": max_positions,
        "max_hold_weeks": cfg.get("max_hold_weeks"),
        "year_end_deadline": year_end.isoformat(),
        "days_to_year_end": (year_end - today).days,
        "stop_pct": cfg.get("stop_pct"),
        "monthly_used": budget["monthly_used"],
        "monthly_limit": budget["monthly_limit"],
        "monthly_remaining": budget["monthly_remaining"],
        "open_positions": open_positions,
        "overdue": overdue,
        "can_buy_now": budget["monthly_remaining"] > 0
                       and len(open_positions) < max_positions
                       and bool(cfg.get("enabled")),
        "blockers": blockers,
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
        # KIK-751: 短期枠。core とは別勘定なので実現損益も分けて返す
        "tactical": tactical_status(trades, positions, equity_value + cash, today),
        "tactical_realized": realized_pnl(trades, month_key(today), excluded_dates,
                                          sleeve=TACTICAL_SLEEVE),
        "holdings": [p.get("symbol") for p in positions],
    }
