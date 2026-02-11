"""Output formatters for screening results."""

from typing import Optional


def _fmt_pct(value: Optional[float]) -> str:
    """Format a decimal ratio as a percentage string (e.g. 0.035 -> '3.50%')."""
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def _fmt_float(value: Optional[float], decimals: int = 2) -> str:
    """Format a float with the given decimal places, or '-' if None."""
    if value is None:
        return "-"
    return f"{value:.{decimals}f}"


def format_markdown(results: list[dict]) -> str:
    """Format screening results as a Markdown table.

    Parameters
    ----------
    results : list[dict]
        Each dict should contain: symbol, name, price, per, pbr,
        dividend_yield, roe, value_score.

    Returns
    -------
    str
        A Markdown-formatted table string.
    """
    if not results:
        return "該当する銘柄が見つかりませんでした。"

    lines = [
        "| 順位 | 銘柄 | 株価 | PER | PBR | 配当利回り | ROE | スコア |",
        "|---:|:-----|-----:|----:|----:|---------:|----:|------:|",
    ]

    for rank, row in enumerate(results, start=1):
        symbol = row.get("symbol", "-")
        name = row.get("name") or ""
        label = f"{symbol} {name}".strip() if name else symbol

        price = _fmt_float(row.get("price"), decimals=0) if row.get("price") is not None else "-"
        per = _fmt_float(row.get("per"))
        pbr = _fmt_float(row.get("pbr"))
        div_yield = _fmt_pct(row.get("dividend_yield"))
        roe = _fmt_pct(row.get("roe"))
        score = _fmt_float(row.get("value_score"))

        lines.append(
            f"| {rank} | {label} | {price} | {per} | {pbr} | {div_yield} | {roe} | {score} |"
        )

    return "\n".join(lines)


def format_query_markdown(results: list[dict]) -> str:
    """Format EquityQuery screening results as a Markdown table.

    Includes sector column since QueryScreener results span diverse sectors.

    Parameters
    ----------
    results : list[dict]
        Each dict should contain: symbol, name, price, per, pbr,
        dividend_yield, roe, value_score, sector.

    Returns
    -------
    str
        A Markdown-formatted table string.
    """
    if not results:
        return "該当する銘柄が見つかりませんでした。"

    lines = [
        "| 順位 | 銘柄 | セクター | 株価 | PER | PBR | 配当利回り | ROE | スコア |",
        "|---:|:-----|:---------|-----:|----:|----:|---------:|----:|------:|",
    ]

    for rank, row in enumerate(results, start=1):
        symbol = row.get("symbol", "-")
        name = row.get("name") or ""
        label = f"{symbol} {name}".strip() if name else symbol
        sector = row.get("sector") or "-"

        price = _fmt_float(row.get("price"), decimals=0) if row.get("price") is not None else "-"
        per = _fmt_float(row.get("per"))
        pbr = _fmt_float(row.get("pbr"))
        div_yield = _fmt_pct(row.get("dividend_yield"))
        roe = _fmt_pct(row.get("roe"))
        score = _fmt_float(row.get("value_score"))

        lines.append(
            f"| {rank} | {label} | {sector} | {price} | {per} | {pbr} | {div_yield} | {roe} | {score} |"
        )

    return "\n".join(lines)


def format_pullback_markdown(results: list[dict]) -> str:
    """Format pullback screening results as a Markdown table."""
    if not results:
        return "押し目条件に合致する銘柄が見つかりませんでした。（上昇トレンド中の押し目銘柄なし）"

    lines = [
        "| 順位 | 銘柄 | 株価 | PER | 押し目% | RSI | 出来高比 | SMA50 | SMA200 | スコア | 一致度 | 総合スコア |",
        "|---:|:-----|-----:|----:|------:|----:|-------:|------:|-------:|------:|:------:|------:|",
    ]

    for rank, row in enumerate(results, start=1):
        symbol = row.get("symbol", "-")
        name = row.get("name") or ""
        label = f"{symbol} {name}".strip() if name else symbol

        price = _fmt_float(row.get("price"), decimals=0) if row.get("price") is not None else "-"
        per = _fmt_float(row.get("per"))
        pullback = _fmt_pct(row.get("pullback_pct"))
        rsi = _fmt_float(row.get("rsi"), decimals=1)
        vol_ratio = _fmt_float(row.get("volume_ratio"))
        sma50 = _fmt_float(row.get("sma50"), decimals=0) if row.get("sma50") is not None else "-"
        sma200 = _fmt_float(row.get("sma200"), decimals=0) if row.get("sma200") is not None else "-"

        # Bounce score
        bounce_score = row.get("bounce_score")
        bounce_str = f"{bounce_score:.0f}点" if bounce_score is not None else "-"

        # Match type
        match_type = row.get("match_type", "full")
        match_str = "★完全一致" if match_type == "full" else "△部分一致"

        score = _fmt_float(row.get("final_score") or row.get("value_score"))

        lines.append(
            f"| {rank} | {label} | {price} | {per} | {pullback} | {rsi} | {vol_ratio} | {sma50} | {sma200} | {bounce_str} | {match_str} | {score} |"
        )

    return "\n".join(lines)


def format_alpha_markdown(results: list[dict]) -> str:
    """Format alpha signal screening results as a Markdown table.

    Shows 2-axis scoring: value_score (100pt) + change_score (100pt) = total_score (200pt+).
    Also shows pullback status and key change indicators.
    """
    if not results:
        return "アルファシグナル条件に合致する銘柄が見つかりませんでした。"

    lines = [
        "| 順位 | 銘柄 | 株価 | PER | PBR | 割安 | 変化 | 総合 | 押し目 | ア | 加速 | FCF | ROE趨勢 |",
        "|---:|:-----|-----:|----:|----:|----:|----:|----:|:------:|:--:|:---:|:---:|:------:|",
    ]

    for rank, row in enumerate(results, start=1):
        symbol = row.get("symbol", "-")
        name = row.get("name") or ""
        label = f"{symbol} {name}".strip() if name else symbol

        price = _fmt_float(row.get("price"), decimals=0) if row.get("price") is not None else "-"
        per = _fmt_float(row.get("per"))
        pbr = _fmt_float(row.get("pbr"))

        value_score = _fmt_float(row.get("value_score"))
        change_score = _fmt_float(row.get("change_score"))
        total_score = _fmt_float(row.get("total_score"))

        # Pullback status
        pullback = row.get("pullback_match", "none")
        if pullback == "full":
            pb_str = "★"
        elif pullback == "partial":
            pb_str = "△"
        else:
            pb_str = "-"

        # Change indicators: ◎(>=20) ○(>=15) △(>=10) ×(<10)
        def _indicator(score):
            if score is None:
                return "-"
            if score >= 20:
                return "◎"
            if score >= 15:
                return "○"
            if score >= 10:
                return "△"
            return "×"

        accruals = _indicator(row.get("accruals_score"))
        rev_accel = _indicator(row.get("rev_accel_score"))
        fcf = _indicator(row.get("fcf_yield_score"))
        roe_trend = _indicator(row.get("roe_trend_score"))

        lines.append(
            f"| {rank} | {label} | {price} | {per} | {pbr} "
            f"| {value_score} | {change_score} | {total_score} | {pb_str} "
            f"| {accruals} | {rev_accel} | {fcf} | {roe_trend} |"
        )

    # Legend
    lines.append("")
    lines.append("**凡例**: 割安=割安スコア(100点) / 変化=変化スコア(100点) / 総合=割安+変化(+押し目ボーナス)")
    lines.append("**変化指標**: ア=アクルーアルズ(利益の質) / 加速=売上成長加速度 / FCF=FCF利回り / ROE趨勢=ROE改善トレンド")
    lines.append("**判定**: ◎=優秀(20+) ○=良好(15+) △=普通(10+) ×=不足(<10)")

    return "\n".join(lines)
