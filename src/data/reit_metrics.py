"""J-REIT の評価指標 — KIK-760.

J-REIT は投資法人であり、株式の物差しが当たらない。2026-08-15 に
`get_stock_info` の値をそのまま並べて誤った提示をした:

  - **PBR 0.33（yfinance）に対し実際は 1.52**。8951/8952 で4.7〜4.9倍の誤差。
    投資口分割が反映されていないとみられる。「割安」と読める方向に外れていた
  - 信用倍率 1881倍（3234.T）をそのまま掲載。REIT は売り残がほぼ無いので
    比率が発散する。15倍/30倍の閾値は当てはまらない
  - 「一次情報が取れない」と書いたが、取りに行く先が違っただけだった

J-Quants の決算短信には REIT 専用の DocType があり、必要な項目が揃っている:

    DocType  FYFinancialStatements_Consolidated_REIT / REITEarnForecastRevision
    BPS      1口当たり純資産  → NAV倍率 = 投資口価格 ÷ BPS
    TA / Eq  総資産 / 純資産  → LTV = (TA - Eq) / TA
    DivUnit  1口当たり分配金（実績）
    NxFDivUnit 次期予想分配金 → 予想分配金利回り

⚠️ **決算は半期**（年2回）。分配金利回りは年換算する必要がある。
⚠️ レコードは**日付順に並んでいない**。開示日で並べ直してから使う。

is_reit          : REIT かどうか
get_reit_metrics : NAV倍率・LTV・分配金利回りをまとめて返す
"""

from __future__ import annotations

from typing import Optional

# J-Quants の DocType に含まれる REIT の印
_REIT_DOCTYPE_MARKER = "REIT"

# LTV の目安（J-REIT 業界の一般的な水準）
LTV_CONSERVATIVE = 45.0   # これ未満は保守的
LTV_WARN = 55.0           # これ以上は高め
LTV_LIMIT = 60.0          # これ以上は財務余力が乏しい

# NAV倍率の目安
NAV_CHEAP = 1.0           # 1.0 割れ = 純資産価値を下回る
NAV_RICH = 1.3            # これ以上は割高圏


def _num(value) -> Optional[float]:
    if value is None or value == "" or value == "-":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if f != f else f          # NaN 除外


def _fetch_summary(code: str):
    """J-Quants の決算短信レコード（開示日の昇順）。取れなければ空リスト。"""
    from src.data.jquants_client._client import get_client
    from src.data.jquants_client.fin_summary import normalize_code

    client = get_client()
    if client is None:
        return []
    df = client.get_fin_summary(code=normalize_code(code))
    if df is None or not len(df):
        return []
    rows = df.to_dict("records")
    # ⚠️ API は日付順に返さない。開示日で並べ直す
    rows.sort(key=lambda r: str(r.get("DiscDate") or ""))
    return rows


def is_reit(symbol: str) -> bool:
    """決算短信の DocType から REIT か判定する。

    銘柄コードの範囲や業種名では判定しない。J-Quants の 33業種は
    REIT を「その他」に入れるため区別がつかない。
    """
    try:
        rows = _fetch_summary(symbol)
    except Exception:
        return False
    return any(_REIT_DOCTYPE_MARKER in str(r.get("DocType") or "") for r in rows)


def get_reit_metrics(symbol: str, price: Optional[float] = None) -> dict:
    """J-REIT の評価指標を返す。REIT でなければ ``is_reit=False`` のみ。

    Parameters
    ----------
    symbol : str
        '8951.T' / '8951' のいずれでも可。
    price : float | None
        投資口価格。省略時は yahoo_client から取る。

    Returns
    -------
    dict with keys:
        is_reit / bps / nav_ratio / ltv_pct / total_assets / net_assets
        dist_per_unit / dist_forecast / dist_yield_pct / dist_yield_forecast_pct
        period_start / period_end / disclosed / months_in_period
        nav_signal : "cheap" | "fair" | "rich" | None
        ltv_signal : "conservative" | "normal" | "warn" | "limit" | None
        label      : 人間可読1行
    """
    _na = {
        "is_reit": False, "bps": None, "nav_ratio": None, "ltv_pct": None,
        "total_assets": None, "net_assets": None, "dist_per_unit": None,
        "dist_forecast": None, "dist_yield_pct": None,
        "dist_yield_forecast_pct": None, "period_start": None, "period_end": None,
        "disclosed": None, "months_in_period": None,
        "nav_signal": None, "ltv_signal": None, "label": "REIT ではない",
    }

    try:
        rows = _fetch_summary(symbol)
    except Exception:
        return {**_na, "label": "決算短信を取得できない"}

    reit_rows = [r for r in rows
                 if _REIT_DOCTYPE_MARKER in str(r.get("DocType") or "")]
    if not reit_rows:
        return _na

    # BPS を持つ最新の本決算を使う。予想改訂（REITEarnForecastRevision）は
    # BPS を持たないので、そこから NAV倍率を出そうとすると None になる。
    latest = None
    for r in reversed(reit_rows):
        if _num(r.get("BPS")) is not None:
            latest = r
            break
    if latest is None:
        return {**_na, "is_reit": True, "label": "REIT だが BPS が取得できない"}

    bps = _num(latest.get("BPS"))
    ta = _num(latest.get("TA"))
    eq = _num(latest.get("Eq"))

    if price is None:
        try:
            from src.data.yahoo_client.history import get_price_history

            sym = symbol if "." in symbol else f"{symbol}.T"
            hist = get_price_history(sym, period="1mo")
            close = hist["Close"].dropna()
            price = float(close.iloc[-1]) if len(close) else None
        except Exception:
            price = None

    nav = (price / bps) if (price and bps) else None
    ltv = ((ta - eq) / ta * 100) if (ta and eq and ta > 0) else None

    # 分配金は**半期**。年換算しないと利回りが半分に見える
    months = None
    st, en = latest.get("CurPerSt"), latest.get("CurPerEn")
    try:
        import datetime as _dt

        s = _dt.date.fromisoformat(str(st)[:10])
        e = _dt.date.fromisoformat(str(en)[:10])
        months = round(((e - s).days + 1) / 30.44)
    except Exception:
        months = None
    periods_per_year = (12 / months) if months else 2.0

    dist = _num(latest.get("DivUnit"))
    # 予想は本決算に無いことがあるので、予想改訂レコードからも拾う
    fc = _num(latest.get("NxFDivUnit"))
    if fc is None:
        for r in reversed(reit_rows):
            fc = _num(r.get("NxFDivUnit"))
            if fc is not None:
                break

    y = (dist * periods_per_year / price * 100) if (dist and price) else None
    yf_ = (fc * periods_per_year / price * 100) if (fc and price) else None

    nav_signal = None
    if nav is not None:
        nav_signal = ("cheap" if nav < NAV_CHEAP
                      else "rich" if nav >= NAV_RICH else "fair")
    ltv_signal = None
    if ltv is not None:
        ltv_signal = ("conservative" if ltv < LTV_CONSERVATIVE
                      else "limit" if ltv >= LTV_LIMIT
                      else "warn" if ltv >= LTV_WARN else "normal")

    parts = []
    if nav is not None:
        parts.append(f"NAV倍率 {nav:.2f}（{nav_signal}）")
    if yf_ is not None:
        parts.append(f"予想分配金利回り {yf_:.2f}%")
    if ltv is not None:
        parts.append(f"LTV {ltv:.1f}%（{ltv_signal}）")

    return {
        "is_reit": True, "bps": bps, "nav_ratio": round(nav, 3) if nav else None,
        "ltv_pct": round(ltv, 1) if ltv else None,
        "total_assets": ta, "net_assets": eq,
        "dist_per_unit": dist, "dist_forecast": fc,
        "dist_yield_pct": round(y, 2) if y else None,
        "dist_yield_forecast_pct": round(yf_, 2) if yf_ else None,
        "period_start": str(st)[:10] if st else None,
        "period_end": str(en)[:10] if en else None,
        "disclosed": str(latest.get("DiscDate"))[:10] if latest.get("DiscDate") else None,
        "months_in_period": months,
        "nav_signal": nav_signal, "ltv_signal": ltv_signal,
        "label": " / ".join(parts) if parts else "指標を算出できない",
    }
