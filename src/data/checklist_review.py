"""チェックリストの機械的レビュー (KIK-734)。

``config/checklists.yaml`` の項目のうち **コードで検証できるものを実際に検証する**。

なぜ機械的にやるか: 2026-08-06 時点で外部LLM（GPT / Gemini / Grok）が3つとも
使えず、レビューは「私が自分の判断を自分で検証する」形にしかならなかった。
それでは見落としを見つけられない（実際このセッションで15件見落とした）。
主観を挟まず判定できる項目だけでも自動化すれば、自己レビューより信頼できる。

⚠️ ここで検証できるのは「機械的に判定できる項目」だけ。
   `config/checklists.yaml` の 31項目中、ここで自動判定するのは 12項目。
   残りは人間／エージェントが目で通す必要がある。**PASS は「全部確認した」ではなく
   「自動判定できる範囲で問題なし」を意味する。**
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Optional

# 判定結果
PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
NA = "N/A"

_SEVERITY_ORDER = {FAIL: 0, WARN: 1, PASS: 2, NA: 3}


def _result(item_id: str, status: str, detail: str) -> dict:
    return {"id": item_id, "status": status, "detail": detail}


# ---------------------------------------------------------------------------
# データ品質 (DQ)
# ---------------------------------------------------------------------------

#: DQ3 で「安すぎる」と見なす予想PER。5 では 6701.T の 6.4 を取りこぼした
DQ3_PER_FLOOR = 8.0


def check_data_quality(infos: dict[str, dict]) -> list[dict]:
    """DQ1 / DQ2 / DQ3 / DQ7 を ``get_stock_info()`` の結果に対して判定する。"""
    out: list[dict] = []
    jp = {s: i for s, i in infos.items() if str(s).upper().endswith(".T") and i}
    if not jp:
        return [_result("DQ1", NA, "日本株が対象に含まれていない")]

    yf_only = [s for s, i in jp.items() if i.get("forecast_source") != "jquants"]
    out.append(_result(
        "DQ1",
        WARN if yf_only else PASS,
        f"会社予想(J-Quants)不採用: {', '.join(yf_only)}" if yf_only
        else f"{len(jp)}銘柄すべて会社予想を採用",
    ))

    suspects = [
        s for s, i in jp.items()
        if i.get("forecast_suspect") is True or i.get("dividend_yield_suspect") is True
    ]
    out.append(_result(
        "DQ2",
        FAIL if suspects else PASS,
        f"suspect=True: {', '.join(suspects)} → 一次情報の確認まで判断に使わない"
        if suspects else "乖離フラグなし",
    ))

    # DQ3: 極端に良く見える数字。誤データは常に魅力的な方向に出る
    odd = []
    for s, i in jp.items():
        per = i.get("per_forward_company") or i.get("forward_per")
        dy = i.get("dividend_yield_company") or i.get("dividend_yield")
        if per is not None and 0 < per < DQ3_PER_FLOOR:
            odd.append(f"{s} 予想PER{per:.1f}")
        if dy is not None and dy > 0.06:
            odd.append(f"{s} 利回り{dy * 100:.1f}%")
    out.append(_result(
        "DQ3", WARN if odd else PASS,
        f"極端値: {', '.join(odd)} → 一次情報で裏を取る" if odd else "極端値なし",
    ))

    # DQ7: forecast_source=='jquants' でも会社予想EPSが空なら PER は yfinance のまま。
    # 6701.T は配当だけ J-Quants から入るため DQ1 を PASS してしまう。
    no_eps = [
        s for s, i in jp.items()
        if i.get("per_forward_company") is None and i.get("forward_per") is not None
    ]
    out.append(_result(
        "DQ7", WARN if no_eps else PASS,
        f"会社予想EPS欠落のまま yfinance PER を使用: {', '.join(no_eps)}"
        " → PER を割安判断の根拠にしない" if no_eps
        else "会社予想EPSは全銘柄で取得済み",
    ))
    return out


# ---------------------------------------------------------------------------
# ルール (RL)
# ---------------------------------------------------------------------------

def check_pf_tier(total_assets: float, usdjpy: float) -> list[dict]:
    """RL1: PF規模ティアを実測で確認する。

    2026-08-05 に medium と思い込んで冷却2週・月4回で3ヶ月の投入計画を作ったが、
    実際は small（4週・月1回）だった。$50K 境界の近くでは特に確認が要る。
    """
    if not usdjpy or usdjpy <= 0:
        return [_result("RL1", NA, "USDJPY が取得できず判定不能")]
    usd = total_assets / usdjpy
    tier = "small" if usd < 50_000 else ("medium" if usd < 200_000 else "large")
    near = abs(usd - 50_000) < 5_000 or abs(usd - 200_000) < 20_000
    return [_result(
        "RL1", WARN if near else PASS,
        f"総資産 ${usd:,.0f} → tier={tier}"
        + ("（境界付近。ティアが変わると冷却期間・月次上限が変わる）" if near else ""),
    )]


def check_stop_sigma(stop_distances: dict[str, float]) -> list[dict]:
    """RL5: ストップ距離を日次σ倍で見る。1.0σ以内はノイズ圏。"""
    if not stop_distances:
        return [_result("RL5", NA, "ストップ設定なし")]
    noise = {s: v for s, v in stop_distances.items() if v is not None and v <= 1.0}
    return [_result(
        "RL5", FAIL if noise else PASS,
        f"ノイズ圏(≦1.0日σ): {', '.join(f'{s} {v:.2f}σ' for s, v in noise.items())}"
        if noise else f"{len(stop_distances)}銘柄すべて1.0日σ超",
    )]


# ---------------------------------------------------------------------------
# 実行の追跡 (FT)
# ---------------------------------------------------------------------------

def check_followthrough(
    notes: list[dict],
    today: Optional[datetime.date] = None,
) -> list[dict]:
    """FT1: 自分が「○日に再評価する」と書いた項目を実行したか。

    2026-07-28 に「7259.T を 8/3 に再評価」と記録しながら実行せず、
    その未実行のまま 8/3 に約定した。予定を書くだけで実行しないと、
    **その予定を前提に意思決定が進む**。
    """
    today = today or datetime.date.today()
    overdue = []
    for n in notes:
        if n.get("type") != "target":
            continue
        text = " ".join(str(n.get(k) or "") for k in ("trigger", "expected_action"))
        if not text.strip():
            continue
        for token in text.replace("/", "-").split():
            try:
                d = datetime.date.fromisoformat(token[:10])
            except ValueError:
                continue
            if d <= today:
                overdue.append(f"{n.get('symbol') or 'general'} {d} 「{text[:44]}」")
                break
    return [_result(
        "FT1", WARN if overdue else PASS,
        f"期限到来済みの未確認項目 {len(overdue)}件: " + " / ".join(overdue[:4])
        if overdue else "期限到来済みの未処理項目なし",
    )]


# ---------------------------------------------------------------------------
# 発注前 (PO)
# ---------------------------------------------------------------------------

def check_cooldown(
    trade_dir: str = "data/history/trade",
    cooldown_weeks: int = 4,
    excluded_dates: Optional[set[str]] = None,
    today: Optional[datetime.date] = None,
) -> list[dict]:
    """PO1: 冷却期間（**買付**起点）と月次上限を取引履歴から計算する。

    2026-08-06 の改訂で起点を「売買」から「買付」に限定した。
    exit-rule の売却が買い直しをブロックする逆機能を避けるため。

    レコードの ``limit_exempt`` (KIK-763) が立っている取引は月次上限に数えない。
    ストップ抵触による売却がこれにあたる（2026-08-17 のルール確定）。
    ``trade_budget()`` と同じ判定にしてある。片方だけ直すと、同じレポートに
    「今月0回（PO1）」と「今月1回（budget）」が並ぶ。
    """
    from src.data.monthly_check import load_trades

    today = today or datetime.date.today()
    excluded = excluded_dates or set()
    buys, all_trades = [], []
    # ⚠️ 生JSONを自前で読まない。``save_trade()`` は ``trade_type`` で書き、
    # 別の経路は ``action`` で書く。ここで ``action`` だけを見ていたため
    # 2026-08-10 のキヤノン買付（trade_type のみ）が買付として数えられず、
    # 冷却期間の起点が 2026-07-13 にずれていた（2026-08-16 に発覚）。
    # 正規化は ``load_trades()`` の1箇所に寄せる。
    for t in load_trades(trade_dir):
        d = t.get("date")
        if not d or d in excluded or t.get("limit_exempt"):
            continue
        all_trades.append(d)
        if t.get("action") == "buy":
            buys.append(d)
    if not buys:
        return [_result("PO1", WARN, "買付履歴が読めない")]
    last = max(buys)
    cool_end = datetime.date.fromisoformat(last) + datetime.timedelta(weeks=cooldown_weeks)
    this_month = [d for d in all_trades if d[:7] == today.isoformat()[:7]]
    ok = today >= cool_end and len(this_month) < 1
    detail = (
        f"直近買付 {last} +{cooldown_weeks}週 = {cool_end}"
        f"（{'経過済み' if today >= cool_end else f'あと{(cool_end - today).days}日'}）/ "
        f"今月の売買 {len(this_month)}回"
    )
    return [_result("PO1", PASS if ok else FAIL, detail)]


def _check_order_concentration(
    symbol: str, info: dict, positions: list[dict], tier: str,
    denominator: Optional[float] = None,
) -> list[dict]:
    """PO8: 買った後に集中度の上限を割らないか（2026-08-07 の集中投資導入）。

    上限は「これ以上買わない」の基準。既存保有のトリム提案には使わない。
    """
    from src.data.concentration import max_additional_shares

    price = info.get("price")
    if not price or price <= 0:
        return [_result("PO8", NA, "現在値が無く集中度を試算できない")]
    try:
        room = max_additional_shares(symbol, float(price), positions, tier=tier,
                                     denominator=denominator)
    except Exception as exc:  # noqa: BLE001  設定不備で発注チェック全体を止めない
        return [_result("PO8", WARN, f"集中度を判定できない: {exc}")]

    if tier == "conviction_override":
        return [_result("PO8", WARN,
                        "conviction_override は上限対象外。買い増しの根拠にはしない")]
    lots = room.get("lots", 0)
    if lots <= 0:
        return [_result("PO8", FAIL,
                        f"買い増すと上限超過（{room.get('reason')}）")]
    return [_result("PO8", PASS,
                    f"{lots}単元（{room['shares']}株 / ¥{room['amount']:,.0f}）まで可 "
                    f"— tier={tier} / {room.get('reason')}")]


def check_order(
    symbol: str,
    info: dict,
    revision: Optional[dict] = None,
    margin: Optional[dict] = None,
    price_cap: Optional[float] = None,
    positions: Optional[list[dict]] = None,
    tier: str = "normal",
    denominator: Optional[float] = None,
) -> list[dict]:
    """PO2 / PO3 / PO4 / PO7 / PO8 を1銘柄に対して判定する。

    ``positions`` を渡すと PO8（集中度）も判定する。省略時は従来どおり。
    """
    out: list[dict] = []
    price = info.get("price")

    src = info.get("forecast_source")
    sus = info.get("forecast_suspect")
    out.append(_result(
        "PO2", PASS if (src == "jquants" and sus is not True) else WARN,
        f"forecast_source={src} / suspect={sus}"
        + (f" / 会社予想PER {info['per_forward_company']:.1f}"
           if info.get("per_forward_company") else ""),
    ))

    if revision is None or revision.get("revision_in_fy") is None:
        out.append(_result("PO3", NA, "改訂率が測れない（IFRS等で会社予想が空）"))
    elif revision.get("fy_end_passed"):
        # 8725.T MS&AD の +34.7% は終了済 FY2026/3 の改訂だった。
        # 業績モメンタムとして読むと逆の結論になる（今期予想は前期比 -45.5%）。
        out.append(_result(
            "PO3", WARN,
            f"改訂 {revision['revision_in_fy']:+.1f}% は終了済の決算期"
            f"（{revision.get('current_fy')}）のもの → 今の業績モメンタムではない",
        ))
    else:
        rv = revision["revision_in_fy"]
        status = PASS if rv > 1 else (WARN if rv >= -1 else FAIL)
        out.append(_result("PO3", status, f"期初計画からの改訂 {rv:+.1f}%"))

    if price_cap is None:
        out.append(_result("PO4", NA, "中止条件が未設定"))
    elif price is None:
        out.append(_result("PO4", WARN, "現在値が取得できず照合不能"))
    else:
        ok = price <= price_cap
        out.append(_result(
            "PO4", PASS if ok else FAIL,
            f"現在値 ¥{price:,.0f} / 中止条件 ¥{price_cap:,.0f}（{(price_cap / price - 1) * 100:+.1f}%）",
        ))

    if positions is not None:
        out += _check_order_concentration(symbol, info, positions, tier, denominator)

    if not margin or not margin.get("available"):
        out.append(_result("PO7", WARN, "信用倍率が取得できていない"))
    else:
        r = margin.get("margin_ratio")
        try:
            r = float(r)
        except (TypeError, ValueError):
            r = None
        if r is None:
            out.append(_result("PO7", WARN, "信用倍率が数値でない"))
        else:
            status = FAIL if r >= 30 else (WARN if r >= 15 else PASS)
            out.append(_result("PO7", status, f"信用倍率 {r:.2f}倍"))
    return out


# ---------------------------------------------------------------------------
# 集約
# ---------------------------------------------------------------------------

def summarize(results: list[dict]) -> dict:
    """個別判定を PASS / WARN / FAIL に集約する。

    ⚠️ 総合 PASS は「チェックリスト31項目を全部通した」ではなく
    「**自動判定できた項目に問題がなかった**」という意味しか持たない。
    """
    counts = {k: 0 for k in (PASS, WARN, FAIL, NA)}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    verdict = FAIL if counts[FAIL] else (WARN if counts[WARN] else PASS)
    return {
        "verdict": verdict,
        "counts": counts,
        "checked": len(results),
        "results": sorted(results, key=lambda r: _SEVERITY_ORDER.get(r["status"], 9)),
        "caveat": (
            "自動判定できる項目のみ。checklists.yaml の残りは目視確認が必要。"
            "PASS は『全項目確認済み』を意味しない。"
        ),
    }


# ---------------------------------------------------------------------------
# レビュー実施の追跡 (KIK-734 / auto_review の発火保証)
# ---------------------------------------------------------------------------

# レビュー対象になる判断の種別。orchestration.yaml の auto_review trigger に対応する。
_DECISION_NOTE_TYPES = frozenset({"target", "exit-rule"})


def latest_review_date(reviews_dir: str = "data/reviews") -> Optional[str]:
    """``data/reviews/`` から最終レビュー日を拾う（``*_YYYYMMDD.json``）。"""
    import re
    from pathlib import Path

    d = Path(reviews_dir)
    if not d.is_dir():
        return None
    dates = []
    for p in d.glob("*.json"):
        m = re.search(r"(\d{8})", p.stem)
        if m:
            s = m.group(1)
            dates.append(f"{s[:4]}-{s[4:6]}-{s[6:]}")
    return max(dates) if dates else None


# DQ4 のコード化は循環 import を避けるため別モジュール（KIK-761）。
# ここから re-export して、DQ 系の入口を1つに保つ。
def check_data_freshness(latest_by_symbol, today=None, nan_tail_by_symbol=None):
    """DQ4: 価格データの基準日を検証する。詳細は src.data.data_freshness 参照。"""
    from src.data.data_freshness import check_data_freshness as _impl

    return _impl(latest_by_symbol, today=today,
                 nan_tail_by_symbol=nan_tail_by_symbol)


ORDER_CHECK_NOTE_TYPE = "order-check"


def check_order_verification(
    symbol: str,
    order_date: str,
    notes: list[dict],
) -> list[dict]:
    """PO9: 発注**後**に証券会社の注文一覧と指示書を突合した記録があるか。

    pre_order の PO1-PO8 はすべて発注**前**の検査であり、指示書が正しいことしか
    確かめていない。2026年8月に起きた2件はどちらも指示書が正しく、**入力の工程**
    で食い違った:

      2026-08-04  逆指値（売り）のつもりが**指値売り**として発注され、7銘柄が
                  寄付きで無条件約定した。記録上のストップにはいずれも未到達
      2026-08-10  キヤノン買いで指値¥4,635のつもりが**成行**になっており、
                  指値を超える¥4,651-4,652で約定した（結果は許容範囲）

    6日で2件。planning ではなく entry で起きているので、発注前をいくら固めても
    捕まらない。ここは「注文一覧を実際に見て突合した」という**記録**を要求する。

    check_review_coverage と同じ考え方で、記録が無ければ FAIL にする。
    目視で確認したつもりを検証する手段が他にないため、**記録が唯一の証拠**になる。
    """
    matched = [
        n for n in notes
        if n.get("type") == ORDER_CHECK_NOTE_TYPE
        and str(n.get("symbol") or "") == symbol
        and (n.get("date") or "") >= (order_date or "")
    ]
    if matched:
        latest = max(str(n.get("date") or "") for n in matched)
        return [_result("PO9", PASS,
                        f"{symbol} の注文突合記録あり（{latest}）")]
    return [_result("PO9", FAIL,
                    f"{symbol} の発注後突合記録なし。証券会社の注文一覧を開き、"
                    "注文種別・価格・株数・有効期限を指示書と照合して "
                    f'save_note(note_type="{ORDER_CHECK_NOTE_TYPE}") で残すこと')]


def check_review_coverage(
    notes: list[dict],
    last_review: Optional[str],
    today: Optional[datetime.date] = None,
) -> list[dict]:
    """判断がレビューを通らずに確定していないかを検知する。

    ``orchestration.yaml`` の ``auto_review`` は strategist / screener の実行や
    「売却・購入・入替」を含む出力で Reviewer を自動起動する設計だが、
    **仕組みで強制されていないため実際には一度も発火しなかった**。
    2026-08-03〜06 の間に該当する判断が6件あったのに、``data/reviews/`` の
    最新は 2026-04-26 のままだった。目標・期限・配分・11銘柄の投入計画・
    ルール改訂のすべてが未レビューで確定していた。

    ここでは「最終レビュー以降に確定した判断ノートの件数」を数える。
    ゼロにできない性質の指標なので、**溜まったら促す**ことを目的にする。
    """
    today = today or datetime.date.today()
    unreviewed = [
        n for n in notes
        if n.get("type") in _DECISION_NOTE_TYPES
        and (n.get("date") or "") > (last_review or "")
    ]
    if not unreviewed:
        return [_result("REVIEW", PASS, f"最終レビュー {last_review or '記録なし'} 以降の未レビュー判断なし")]

    days = None
    if last_review:
        try:
            days = (today - datetime.date.fromisoformat(last_review)).days
        except ValueError:
            days = None
    status = FAIL if len(unreviewed) >= 5 else WARN
    syms = [str(n.get("symbol") or "general") for n in unreviewed[:6]]
    return [_result(
        "REVIEW", status,
        f"未レビューの判断 {len(unreviewed)}件"
        + (f"（最終レビュー {last_review} = {days}日前）" if days is not None
           else "（レビュー実施の記録なし）")
        + f" 対象: {', '.join(syms)}",
    )]


# ---------------------------------------------------------------------------
# 外部LLMによる補強（任意・使えなければ明示的に劣化）
# ---------------------------------------------------------------------------

def llm_availability() -> dict[str, str]:
    """レビューに使える外部LLMを**実際に叩いて**確認する。

    ⚠️ ``is_provider_available()`` は環境変数の有無しか見ない。
    2026-08-06 にそれを「Grok が使える」と読んで報告したが、実際に叩くと
    403 Forbidden だった。**鍵があること ≠ 使えること**。ここでは実呼び出しで確かめる。
    """
    import yaml

    try:
        routing = yaml.safe_load(open("config/llm_routing.yaml", encoding="utf-8"))
        models = routing.get("available_models", {})
    except (OSError, yaml.YAMLError):
        return {}
    try:
        from tools.llm import call_llm, is_provider_available
    except ImportError:
        return {}

    out: dict[str, str] = {}
    for provider, cfg in models.items():
        if provider == "claude":
            continue  # 自分自身なので独立レビューにならない
        if not is_provider_available(provider):
            out[provider] = "鍵が未設定"
            continue
        model = (cfg.get("models") or [{}])[0].get("model")
        if not model:
            out[provider] = "モデル未定義"
            continue
        try:
            r = call_llm(provider, model, "OK とだけ返してください", timeout=20)
            out[provider] = "利用可能" if r else "空応答"
        except Exception as exc:  # noqa: BLE001
            out[provider] = f"{type(exc).__name__}: {str(exc)[:60]}"
    return out


def independent_review(context: str, timeout: int = 180) -> dict:
    """使える外部LLMがあれば独立レビューを取る。無ければその事実を返す。

    独立性のないレビュー（Claude が Claude の判断を見る）は
    「レビュー済み」と記録してはいけない。``independent=False`` を明示する。
    """
    import yaml

    avail = llm_availability()
    usable = [p for p, s in avail.items() if s == "利用可能"]
    if not usable:
        return {
            "independent": False,
            "availability": avail,
            "note": (
                "外部LLMが利用できないため独立レビューは実施できていない。"
                "機械的チェックの結果のみで判断すること。"
            ),
            "reviews": {},
        }

    import yaml as _yaml
    routing = _yaml.safe_load(open("config/llm_routing.yaml", encoding="utf-8"))
    from tools.llm import call_llm

    sysmsg = "投資判断の独立レビュアー。同意より問題点の指摘に価値がある。日本語で具体的に、簡潔に。"
    reviews = {}
    for p in usable:
        model = routing["available_models"][p]["models"][0]["model"]
        try:
            reviews[p] = call_llm(p, model, context, system_prompt=sysmsg, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            reviews[p] = f"(失敗: {type(exc).__name__})"
    return {"independent": True, "availability": avail, "reviews": reviews, "note": ""}


def save_review(summary: dict, reviews_dir: str = "data/reviews") -> str:
    """レビュー結果を ``data/reviews/`` に保存する。

    ``check_review_coverage()`` はこのファイルの日付を見るので、
    **保存して初めてレビューを実施したことになる**。
    """
    import datetime as _dt
    from pathlib import Path

    Path(reviews_dir).mkdir(parents=True, exist_ok=True)
    stamp = _dt.date.today().strftime("%Y%m%d")
    path = Path(reviews_dir) / f"checklist_{stamp}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# 単一の入口（段階的縮退）
# ---------------------------------------------------------------------------

LEVEL_MECHANICAL = "mechanical_only"
LEVEL_INDEPENDENT = "mechanical_plus_independent"


def run_review(
    checks: list[dict],
    llm_context: Optional[str] = None,
    reviews_dir: str = "data/reviews",
    save: bool = True,
) -> dict:
    """レビューの唯一の入口。段階的に縮退しつつ、**発火だけは必ず保証する**。

    段階:
      1. 機械的チェック — 常に実行する（``checks`` を呼び出し側が集めて渡す）
      2. 外部LLMによる独立レビュー — 実際に叩いて使えたときだけ付く
      3. 記録 — 上のどちらであっても ``data/reviews/`` に必ず保存する

    設計の意図: 最初は 1/2/3 を別々の関数として公開したが、**呼び出し側が
    組み立てる限り組み立て忘れが起きる**。実際 ``orchestration.yaml`` の
    ``auto_review`` は「条件に合えば Reviewer を起動する」と書いてあるだけで
    仕組みで強制されておらず、2026-08-03〜06 に該当判断が多数あったのに
    一度も発火しなかった。ここを単一の入口にして、``save`` を既定で True に
    することで「レビューしたが記録しなかった」を起こせなくする。

    Returns
    -------
    dict
        ``summarize()`` の結果に ``level`` / ``independent_review`` / ``saved_to``
        を加えたもの。``level`` で縮退段階が分かる。
    """
    summary = summarize(checks)

    ind = independent_review(llm_context) if llm_context else {
        "independent": False,
        "availability": llm_availability(),
        "reviews": {},
        "note": "llm_context 未指定のため独立レビューを試行していない",
    }
    summary["independent_review"] = ind
    summary["level"] = LEVEL_INDEPENDENT if ind.get("independent") else LEVEL_MECHANICAL

    if not ind.get("independent"):
        # 独立性が無いことを結論に必ず添える。PASS でも「検証済み」ではない。
        summary["caveat"] += (
            "  さらに外部LLMが使えず独立レビューは未実施。"
            "自分の判断を自分で見ているだけであることに留意。"
        )

    summary["saved_to"] = save_review(summary, reviews_dir) if save else None
    return summary
