"""Shock sensitivity scoring -- 4-layer framework (KIK-340).

Quantifies each stock's vulnerability to market shocks using a 4-layer model:
  Layer 1: Fundamental sensitivity (PER, PBR, dividend, size)
  Layer 2: Technical sensitivity (RSI, MA deviation, surge, volume heat)
  Layer 3: Concentration multiplier (provided externally by concentration.py)
  Layer 4: Integrated shock = base_shock x L1 x L2 x L3
"""

import numpy as np
import pandas as pd
from typing import Optional

from src.core.common import safe_float as _safe_float
from src.core.technicals import compute_rsi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(value: float, lo: float = 0.5, hi: float = 2.0) -> float:
    """Clamp *value* to [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Layer 1: Fundamental sensitivity
# ---------------------------------------------------------------------------

def compute_fundamental_sensitivity(stock_info: dict) -> dict:
    """Compute Layer-1 fundamental sensitivity score.

    Parameters
    ----------
    stock_info : dict
        Return value of ``yahoo_client.get_stock_info()``.  Uses the keys
        ``per``, ``pbr``, ``dividend_yield``, ``market_cap``, and ``beta``.

    Returns
    -------
    dict
        ``score`` (0.5--2.0, 1.0 = neutral, higher = more vulnerable),
        per_score, pbr_score, dividend_score, size_score, volatility_score,
        and a human-readable ``detail`` string.
    """
    per = _safe_float(stock_info.get("per"))
    pbr = _safe_float(stock_info.get("pbr"))
    dividend_yield = _safe_float(stock_info.get("dividend_yield"))
    market_cap = _safe_float(stock_info.get("market_cap"))
    beta = _safe_float(stock_info.get("beta"))

    # --- PER score ---
    if per <= 0:
        # Negative or zero PER (loss-making) -> treat as vulnerable
        per_score = 1.5
    elif per < 15:
        per_score = 0.7
    elif per <= 30:
        per_score = 1.0
    else:
        per_score = 1.5

    # --- PBR score ---
    if pbr <= 0:
        pbr_score = 1.0  # unusual; treat as neutral
    elif pbr < 1:
        pbr_score = 0.7
    elif pbr <= 3:
        pbr_score = 1.0
    else:
        pbr_score = 1.3

    # --- Dividend score (yield is a ratio, e.g. 0.03 = 3%) ---
    if dividend_yield >= 0.03:
        dividend_score = 0.7
    elif dividend_yield >= 0.01:
        dividend_score = 1.0
    else:
        dividend_score = 1.3

    # --- Size score (market_cap in currency units; assume JPY or USD) ---
    # Thresholds: large-cap > 1T (1e12) JPY ~ 10B USD
    #             mid-cap > 100B (1e11) JPY ~ 1B USD
    if market_cap <= 0:
        size_score = 1.0  # unknown -> neutral
    elif market_cap >= 1e12:
        size_score = 0.8
    elif market_cap >= 1e11:
        size_score = 1.0
    else:
        size_score = 1.3

    # --- Volatility (beta) score ---
    if beta <= 0:
        volatility_score = 1.0  # unknown -> neutral
    elif beta < 0.8:
        volatility_score = 0.8
    elif beta <= 1.2:
        volatility_score = 1.0
    else:
        volatility_score = min(1.0 + (beta - 1.2) * 0.5, 2.0)

    # --- Weighted average ---
    # Weights: PER 0.30, PBR 0.20, Dividend 0.20, Size 0.15, Volatility 0.15
    raw_score = (
        per_score * 0.30
        + pbr_score * 0.20
        + dividend_score * 0.20
        + size_score * 0.15
        + volatility_score * 0.15
    )
    score = _clamp(raw_score)

    # Build human-readable detail
    details_parts = []
    if per_score >= 1.3:
        details_parts.append(f"PER({per:.1f})高め")
    elif per_score <= 0.8:
        details_parts.append(f"PER({per:.1f})割安")
    if pbr_score >= 1.3:
        details_parts.append(f"PBR({pbr:.2f})高め")
    elif pbr_score <= 0.8:
        details_parts.append(f"PBR({pbr:.2f})割安")
    if dividend_score <= 0.8:
        details_parts.append(f"高配当({dividend_yield*100:.1f}%)")
    elif dividend_score >= 1.2:
        details_parts.append("低配当")
    if size_score <= 0.9:
        details_parts.append("大型株")
    elif size_score >= 1.2:
        details_parts.append("小型株")

    detail = "; ".join(details_parts) if details_parts else "中立的なファンダメンタル"

    return {
        "score": round(score, 4),
        "per_score": round(per_score, 4),
        "pbr_score": round(pbr_score, 4),
        "dividend_score": round(dividend_score, 4),
        "size_score": round(size_score, 4),
        "volatility_score": round(volatility_score, 4),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Layer 2: Technical sensitivity
# ---------------------------------------------------------------------------

def compute_technical_sensitivity(hist: pd.DataFrame, period: int = 14) -> dict:
    """Compute Layer-2 technical sensitivity score.

    Parameters
    ----------
    hist : pd.DataFrame
        Return value of ``yahoo_client.get_price_history()`` -- must contain
        ``Close`` and ``Volume`` columns.
    period : int
        RSI look-back period (default 14).

    Returns
    -------
    dict
        ``score`` (0.5--2.0), rsi, rsi_score, ma_deviation, ma_deviation_score,
        surge_score, volume_heat_score, and ``detail``.
    """
    # -- Defensive: insufficient data -> neutral --
    neutral = {
        "score": 1.0,
        "rsi": float("nan"),
        "rsi_score": 1.0,
        "ma_deviation": float("nan"),
        "ma_deviation_score": 1.0,
        "surge_score": 1.0,
        "volume_heat_score": 1.0,
        "detail": "データ不足のため中立値",
    }

    if hist is None or hist.empty or "Close" not in hist.columns:
        return neutral

    close = hist["Close"]
    if len(close) < 50:
        return neutral

    volume = hist["Volume"] if "Volume" in hist.columns else pd.Series(dtype=float)

    current_price = float(close.iloc[-1])

    # --- RSI ---
    rsi_series = compute_rsi(close, period=period)
    current_rsi = float(rsi_series.iloc[-1]) if len(rsi_series) >= 1 else float("nan")

    if np.isnan(current_rsi):
        rsi_score = 1.0
    elif current_rsi > 70:
        rsi_score = 1.5
    elif current_rsi > 50:
        rsi_score = 1.0
    elif current_rsi > 30:
        rsi_score = 0.8
    else:
        # RSI < 30: deeply oversold
        # Could be a sign of panic (vulnerable to further drops) or a floor.
        # Treat as slightly below neutral -- the stock has already fallen.
        rsi_score = 0.9

    # --- MA deviation: (price - SMA50) / SMA50 ---
    sma50 = close.rolling(window=50).mean()
    current_sma50 = float(sma50.iloc[-1])
    if current_sma50 > 0:
        ma_deviation = (current_price - current_sma50) / current_sma50
    else:
        ma_deviation = 0.0

    if ma_deviation >= 0.15:
        ma_deviation_score = 1.5
    elif ma_deviation >= 0.05:
        ma_deviation_score = 1.2
    elif ma_deviation >= -0.05:
        ma_deviation_score = 1.0
    elif ma_deviation >= -0.15:
        ma_deviation_score = 0.8
    else:
        ma_deviation_score = 0.7

    # --- Surge: 30-day return ---
    if len(close) >= 30:
        price_30d_ago = float(close.iloc[-30])
        if price_30d_ago > 0:
            surge = (current_price - price_30d_ago) / price_30d_ago
        else:
            surge = 0.0
    else:
        surge = 0.0

    if surge >= 0.20:
        surge_score = 1.5
    elif surge >= 0.10:
        surge_score = 1.2
    elif surge >= 0.0:
        surge_score = 1.0
    else:
        surge_score = 0.8

    # --- Volume heat: 5-day avg / 20-day avg ---
    if len(volume) >= 20 and volume.sum() > 0:
        vol_5 = float(volume.iloc[-5:].mean())
        vol_20 = float(volume.iloc[-20:].mean())
        if vol_20 > 0:
            volume_heat = vol_5 / vol_20
        else:
            volume_heat = 1.0
    else:
        volume_heat = 1.0

    if volume_heat >= 1.5:
        volume_heat_score = 1.3
    elif volume_heat >= 1.0:
        volume_heat_score = 1.0
    else:
        volume_heat_score = 0.9

    # --- Weighted average ---
    # Weights: RSI 0.35, MA deviation 0.25, Surge 0.25, Volume heat 0.15
    raw_score = (
        rsi_score * 0.35
        + ma_deviation_score * 0.25
        + surge_score * 0.25
        + volume_heat_score * 0.15
    )
    score = _clamp(raw_score)

    # Detail string
    parts = []
    if rsi_score >= 1.3:
        parts.append(f"RSI({current_rsi:.1f})過熱")
    elif rsi_score <= 0.85:
        parts.append(f"RSI({current_rsi:.1f})売られ過ぎ")
    if ma_deviation_score >= 1.3:
        parts.append(f"MA乖離(+{ma_deviation*100:.1f}%)大")
    elif ma_deviation_score <= 0.8:
        parts.append(f"MA乖離({ma_deviation*100:.1f}%)下方")
    if surge_score >= 1.3:
        parts.append(f"30日急騰(+{surge*100:.1f}%)")
    if volume_heat_score >= 1.2:
        parts.append(f"出来高過熱({volume_heat:.2f}x)")

    detail = "; ".join(parts) if parts else "テクニカル中立"

    return {
        "score": round(score, 4),
        "rsi": round(current_rsi, 2) if not np.isnan(current_rsi) else float("nan"),
        "rsi_score": round(rsi_score, 4),
        "ma_deviation": round(ma_deviation, 4),
        "ma_deviation_score": round(ma_deviation_score, 4),
        "surge_score": round(surge_score, 4),
        "volume_heat_score": round(volume_heat_score, 4),
        "detail": detail,
    }


# ---------------------------------------------------------------------------
# Quadrant classification
# ---------------------------------------------------------------------------

def classify_quadrant(fundamental_score: float, technical_score: float) -> dict:
    """Classify the stock into one of four vulnerability quadrants.

    Axes:
      - Fundamental: vulnerable (> 1.2) vs. sound (< 1.0)
      - Technical: overbought (> 1.2) vs. oversold (< 0.9)

    Returns
    -------
    dict
        quadrant name, emoji, and description.
    """
    f_vulnerable = fundamental_score > 1.2
    t_overbought = technical_score > 1.2
    t_oversold = technical_score < 0.9
    f_sound = fundamental_score < 1.0

    if f_vulnerable and t_overbought:
        return {
            "quadrant": "最危険",
            "emoji": "\U0001f534",  # red circle
            "description": "ファンダ脆弱かつテクニカル過熱。ショック時に最も大きな下落リスク。",
        }
    if f_vulnerable and t_oversold:
        return {
            "quadrant": "底抜けリスク",
            "emoji": "\u26a0",  # warning sign
            "description": "ファンダ脆弱かつ既に売り込まれている。更なる底抜けの懸念。",
        }
    if f_sound and t_overbought:
        return {
            "quadrant": "短期調整リスク",
            "emoji": "\u26a0",  # warning sign
            "description": "ファンダ健全だがテクニカル過熱。短期的な調整に注意。",
        }
    if f_sound and t_oversold:
        return {
            "quadrant": "耐性最強",
            "emoji": "\u2705",  # check mark
            "description": "ファンダ健全かつ売られ過ぎ水準。ショック耐性が最も高い。",
        }

    # Middle zone: does not clearly fit any quadrant
    return {
        "quadrant": "中立",
        "emoji": "\u25cb",  # white circle
        "description": "明確な象限に分類されない中間領域。",
    }


# ---------------------------------------------------------------------------
# Layer 4: Integrated shock
# ---------------------------------------------------------------------------

def compute_integrated_shock(
    base_shock: float,
    fundamental_score: float,
    technical_score: float,
    concentration_multiplier: float,
) -> dict:
    """Compute the integrated (adjusted) shock for a single stock.

    Parameters
    ----------
    base_shock : float
        Base shock rate (e.g. -0.20 for a -20% market shock).
    fundamental_score : float
        Layer-1 score (0.5--2.0).
    technical_score : float
        Layer-2 score (0.5--2.0).
    concentration_multiplier : float
        Layer-3 multiplier from ``concentration.py`` (typically >= 1.0).

    Returns
    -------
    dict
        adjusted_shock, per-layer contributions, and quadrant classification.
    """
    # Ensure scores are within bounds
    f = _clamp(fundamental_score)
    t = _clamp(technical_score)
    c = max(concentration_multiplier, 0.5)  # floor at 0.5

    adjusted_shock = base_shock * f * t * c

    quadrant = classify_quadrant(f, t)

    return {
        "adjusted_shock": round(adjusted_shock, 6),
        "fundamental_contribution": round(f, 4),
        "technical_contribution": round(t, 4),
        "concentration_contribution": round(c, 4),
        "quadrant": quadrant,
    }


# ---------------------------------------------------------------------------
# Entry-point: full sensitivity analysis for one stock
# ---------------------------------------------------------------------------

def analyze_stock_sensitivity(
    stock_info: dict,
    hist: Optional[pd.DataFrame],
    concentration_multiplier: float = 1.0,
    base_shock: float = -0.20,
) -> dict:
    """Run the complete 4-layer shock-sensitivity analysis for a single stock.

    Parameters
    ----------
    stock_info : dict
        Return value of ``yahoo_client.get_stock_info()``.
    hist : pd.DataFrame or None
        Return value of ``yahoo_client.get_price_history()``.
    concentration_multiplier : float
        Layer-3 multiplier (default 1.0 = no concentration effect).
    base_shock : float
        Hypothetical market-wide shock rate (default -20%).

    Returns
    -------
    dict
        symbol, fundamental, technical, integrated, and a one-line summary.
    """
    symbol = stock_info.get("symbol", "UNKNOWN")
    name = stock_info.get("name", "")

    # Layer 1
    fundamental = compute_fundamental_sensitivity(stock_info)

    # Layer 2
    if hist is not None and not hist.empty:
        technical = compute_technical_sensitivity(hist)
    else:
        technical = {
            "score": 1.0,
            "rsi": float("nan"),
            "rsi_score": 1.0,
            "ma_deviation": float("nan"),
            "ma_deviation_score": 1.0,
            "surge_score": 1.0,
            "volume_heat_score": 1.0,
            "detail": "価格履歴なし",
        }

    # Layer 4 (integrates L1, L2, L3)
    integrated = compute_integrated_shock(
        base_shock=base_shock,
        fundamental_score=fundamental["score"],
        technical_score=technical["score"],
        concentration_multiplier=concentration_multiplier,
    )

    quadrant_name = integrated["quadrant"]["quadrant"]
    adjusted_pct = integrated["adjusted_shock"] * 100

    summary = (
        f"{symbol}"
        f"{'(' + name + ')' if name else ''}: "
        f"ファンダ={fundamental['score']:.2f}, "
        f"テクニカル={technical['score']:.2f}, "
        f"集中度={concentration_multiplier:.2f} -> "
        f"調整後ショック={adjusted_pct:+.1f}% "
        f"[{quadrant_name}]"
    )

    return {
        "symbol": symbol,
        "fundamental": fundamental,
        "technical": technical,
        "integrated": integrated,
        "summary": summary,
    }
