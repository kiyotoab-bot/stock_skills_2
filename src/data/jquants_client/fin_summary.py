"""J-Quants 決算サマリー（会社予想）取得。

決算短信そのものの数値を返す。第三者の推定値ではなく企業自身の開示なので、
予想EPS・予想配当の一次情報として使える。

背景（2026-08-05）: yfinance の予想値には実測で誤りが混入していた。
  6436.T アマノ  dividendRate 250円（会社予想は 180円）→ 利回りを 6.44% と誤認
  6701.T 日本電気 forwardEps 718.96（会社予想の約3.3倍）→ PER 6.4 と誤認
検証した5銘柄のうち2件（40%）が誤りだったため、日本株の会社予想は
このモジュールを一次情報とし、yfinance はフォールバックに降格する。

⚠️ IFRS・Non-GAAP 開示の企業では ``FEPS``/``FNP`` が空のことがある
（実測: 6701 NEC / 4568 第一三共 / 9364 上組）。取得できない場合は
None を返す。「間違った値」ではなく「値がない」ことを明示するのが目的。
"""

import datetime as _dt
from typing import Any, Optional

from src.data.jquants_client._client import get_client, is_available

# 決算短信の項目 → 正規化キー
# F プレフィックス = Forecast（当期の会社予想）
_FORECAST_FIELDS = {
    "forecast_sales": "FSales",
    "forecast_operating_profit": "FOP",
    "forecast_ordinary_profit": "FOdP",
    "forecast_net_income": "FNP",
    "forecast_eps": "FEPS",
    "forecast_dps_annual": "FDivAnn",
    "forecast_payout_ratio": "FPayoutRatioAnn",
}
_ACTUAL_FIELDS = {
    "actual_sales": "Sales",
    "actual_operating_profit": "OP",
    "actual_ordinary_profit": "OdP",
    "actual_net_income": "NP",
    "actual_eps": "EPS",
    "actual_dps_annual": "DivAnn",
    "equity_ratio": "EqAR",
    "bps": "BPS",
    "shares_outstanding": "ShOutFY",
    "treasury_shares": "TrShFY",
    "average_shares": "AvgSh",
}


def normalize_code(symbol: str) -> str:
    """'7751.T' / '7751' / '77510' → J-Quants が受け付ける 4桁コード。"""
    code = str(symbol).strip().upper().split(".")[0]
    # J-Quants は内部的に5桁（末尾0埋め）だが、問い合わせは4桁で通る
    if len(code) == 5 and code.endswith("0"):
        code = code[:4]
    return code


def _num(value: Any) -> Optional[float]:
    """文字列混じりの API レスポンスを安全に float 化する。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN を除く


def get_company_forecast(symbol: str) -> dict:
    """最新の決算短信から会社予想と実績を取り出す。

    Returns
    -------
    dict
        ``available`` が False の場合は ``reason`` を含む。
        True の場合は forecast_* / actual_* と開示メタ情報を返す。
        個々の項目は取得できなければ None（推定で埋めない）。
    """
    if not is_available():
        return {"available": False, "reason": "J-Quants API キーが未設定"}

    code = normalize_code(symbol)
    try:
        df = get_client().get_fin_summary(code=code)
    except Exception as exc:  # noqa: BLE001 - API 側の例外は種類が多い
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}

    if df is None or len(df) == 0:
        return {"available": False, "reason": "開示データなし"}

    row = df.iloc[-1]
    out: dict = {
        "available": True,
        "symbol": symbol,
        "code": str(row.get("Code", code)),
        "disclosed_date": str(row.get("DiscDate", ""))[:10],
        "period_type": row.get("CurPerType"),
        "doc_type": row.get("DocType"),
        "fiscal_year_end": str(row.get("CurFYEn", ""))[:10],
    }
    for key, col in {**_FORECAST_FIELDS, **_ACTUAL_FIELDS}.items():
        out[key] = _num(row.get(col))

    # 予想が1件も取れなかった場合は明示する（IFRS 勢で発生する）
    out["has_forecast"] = any(
        out.get(k) is not None for k in _FORECAST_FIELDS
    )
    return out


def get_forecast_history(symbol: str, limit: int = 12) -> list[dict]:
    """会社予想の履歴（新しい順）。``fiscal_year_end`` を必ず含める。

    ⚠️ 決算期末を見ずに隣り合う2件を比べてはいけない。1Q 開示は**新しい決算期**の
    予想なので、直前の 3Q 開示（前期の予想）と比べると「上方修正」ではなく
    **前期比の成長率**を測ってしまう。2026-08-05 に実際にこの誤りでスクリーニングを
    走らせ、日立 +18.4% / ローム +190% を「上方修正」と誤って報告しかけた。
    比較は ``analyze_revisions()`` を使うこと。
    """
    if not is_available():
        return []
    try:
        df = get_client().get_fin_summary(code=normalize_code(symbol))
    except Exception:  # noqa: BLE001
        return []
    if df is None or len(df) == 0:
        return []

    rows = []
    for _, row in df.tail(limit).iloc[::-1].iterrows():
        rows.append({
            "disclosed_date": str(row.get("DiscDate", ""))[:10],
            "period_type": row.get("CurPerType"),
            "fiscal_year_end": str(row.get("CurFYEn", ""))[:10],
            "next_fiscal_year_end": str(row.get("NxtFYEn", ""))[:10],
            "forecast_net_income": _num(row.get("FNP")),
            "forecast_eps": _num(row.get("FEPS")),
            "forecast_dps_annual": _num(row.get("FDivAnn")),
            "forecast_operating_profit": _num(row.get("FOP")),
            # 期末決算では「翌期の期初計画」がここに入る。期内改訂の基準点になる。
            "next_fy_net_income": _num(row.get("NxFNp")) or _num(row.get("NxFNP")),
            "next_fy_eps": _num(row.get("NxFEPS")),
            "next_fy_operating_profit": _num(row.get("NxFOP")),
        })
    return rows


_NEXT_FIELD = {
    "forecast_net_income": "next_fy_net_income",
    "forecast_eps": "next_fy_eps",
    "forecast_operating_profit": "next_fy_operating_profit",
}


def analyze_revisions(symbol: str, field: str = "forecast_net_income",
                      today=None) -> dict:
    """会社予想を「今期内の改訂」と「前期比」に分けて評価する。

    ⚠️ この2つは全く別の指標であり、混同すると結論が逆になる。
      revision_in_fy : **期初計画からの改訂**。業績モメンタムの直接の指標
      yoy_guidance   : 今期計画 ÷ 前期実績見込み。計画の水準そのものの前期比

    期初計画は、前期の期末決算開示の ``NxF*``（翌期予想）列に入っている。
    ここを見ないと 1Q 開示しかない3月決算企業で改訂を測れず、
    隣接開示を単純比較して「前期比」を「上方修正」と誤読する
    （2026-08-05 に実際に発生。日立+18.4% / ローム+190% を上方修正と誤報告しかけた）。

    Returns
    -------
    dict
        revision_in_fy   : 期初計画→最新の改訂率（%）
        revision_count   : 今期内で予想が開示された回数
        revision_latest  : 直近1回の改訂率（%）
        yoy_guidance     : 今期最新予想 ÷ 前期最終予想 - 1（%）
        initial_value    : 期初計画
        current_value    : 今期の最新予想
        current_fy       : 今期の決算期末
        fy_end_passed    : current_fy が既に終了しているか（下記⚠️）
        next_fy_guidance : current_fy の翌期のガイダンス（NxF*）
        next_fy_end      : そのガイダンスが指す決算期末

    ⚠️ ``current_fy`` は「``field`` が入っている最新の開示」から決まる。
      IFRS/Non-GAAP 開示や、今期の F* 開示がまだ無い銘柄では **終わった期**を
      指すことがある。その場合 ``fy_end_passed=True`` になり、``revision_in_fy``
      は今の業績モメンタムを表さないので判断に使ってはいけない。
        8725.T MS&AD  : +34.7% は FY2026/3（終了済）の改訂。今期 FY2027/3 の
                        ガイダンスは 4,250億で前期 7,800億から -45.5%
        6701.T 日本電気: +10.3% は FY2025/3 の改訂（2年前）
      いずれも 2026-08-07 の週次で「上方修正銘柄」として扱いかけた。
    """
    hist = get_forecast_history(symbol, limit=16)
    out = {
        "symbol": symbol, "field": field,
        "revision_in_fy": None, "revision_count": 0, "revision_latest": None,
        "yoy_guidance": None, "initial_value": None, "current_value": None,
        "current_fy": None, "fy_end_passed": None,
        "next_fy_guidance": None, "next_fy_end": None,
    }
    vals = [h for h in hist if h.get(field) is not None and h.get("fiscal_year_end")]
    if not vals:
        return out

    current_fy = vals[0]["fiscal_year_end"]
    out["current_fy"] = current_fy
    cur = [v for v in vals if v["fiscal_year_end"] == current_fy]  # 新しい順
    out["current_value"] = cur[0][field]
    out["revision_count"] = len(cur)

    # 期初計画: 前期の期末開示が持つ「翌期予想」。無ければ今期最古の開示で代用
    nxt_field = _NEXT_FIELD.get(field)
    initial = None
    if nxt_field:
        for h in hist:
            if h.get("next_fiscal_year_end") == current_fy and h.get(nxt_field):
                initial = h[nxt_field]
                break
    if initial is None and len(cur) >= 2:
        initial = cur[-1][field]
    out["initial_value"] = initial

    if initial and initial > 0 and out["current_value"]:
        out["revision_in_fy"] = (out["current_value"] / initial - 1) * 100
    if len(cur) >= 2 and cur[1][field] and cur[1][field] > 0:
        out["revision_latest"] = (out["current_value"] / cur[1][field] - 1) * 100

    prev_fy = [v for v in vals if v["fiscal_year_end"] != current_fy]
    if prev_fy and prev_fy[0][field] and prev_fy[0][field] > 0 and out["current_value"]:
        out["yoy_guidance"] = (out["current_value"] / prev_fy[0][field] - 1) * 100

    out["fy_end_passed"] = _fy_end_passed(current_fy, today)
    # current_fy より後を指す NxF* ガイダンス。current_fy が終わっている銘柄では
    # これが実際の「今期予想」になる。
    if nxt_field:
        for h in hist:
            nxt_end = h.get("next_fiscal_year_end")
            if h.get(nxt_field) and nxt_end and _fy_key(nxt_end) > _fy_key(current_fy):
                out["next_fy_guidance"] = h[nxt_field]
                out["next_fy_end"] = nxt_end
                break
    return out


def _fy_key(fy_end) -> str:
    """決算期末を比較可能な ``YYYY-MM-DD`` 文字列にする（NaT/None は空文字）。"""
    if fy_end is None:
        return ""
    text = (fy_end.isoformat() if hasattr(fy_end, "isoformat") else str(fy_end))[:10]
    try:
        _dt.date.fromisoformat(text)
    except ValueError:
        return ""
    return text


def _fy_end_passed(fy_end, today=None) -> Optional[bool]:
    """``fy_end`` が既に終了しているか。判定できなければ None。"""
    key = _fy_key(fy_end)
    if not key:
        return None
    return _dt.date.fromisoformat(key) < (today or _dt.date.today())
