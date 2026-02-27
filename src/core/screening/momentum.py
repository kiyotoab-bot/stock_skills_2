"""Momentum technical indicators for momentum-based screening.

Detects oversold stocks with positive momentum reversals using:
- RSI (Relative Strength Index) for overbought/oversold conditions
- MACD (Moving Average Convergence Divergence) for momentum changes
- Rate of Change (ROC) for price velocity
- Volume trend for confirmation
"""

import numpy as np
import pandas as pd


def compute_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute MACD (Moving Average Convergence Divergence).

    Parameters
    ----------
    close : pd.Series
        Close prices
    fast : int
        Fast EMA period (default 12)
    slow : int
        Slow EMA period (default 26)
    signal : int
        Signal line EMA period (default 9)

    Returns
    -------
    tuple[pd.Series, pd.Series, pd.Series]
        (macd_line, signal_line, histogram)
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_roc(close: pd.Series, period: int = 12) -> pd.Series:
    """Compute Rate of Change (momentum).

    Parameters
    ----------
    close : pd.Series
        Close prices
    period : int
        Period for ROC calculation (default 12)

    Returns
    -------
    pd.Series
        Rate of Change as percentage
    """
    roc = ((close - close.shift(period)) / close.shift(period)) * 100
    return roc


def detect_momentum_reversal(hist: pd.DataFrame) -> dict:
    """Detect momentum reversal opportunity in stocks.

    Detects oversold conditions with positive momentum signals:
    1. RSI < 30 (oversold zone)
    2. MACD histogram positive and increasing (momentum reversal)
    3. ROC positive (price accelerating upward)
    4. Volume increasing (confirmation)

    Parameters
    ----------
    hist : pd.DataFrame
        DataFrame from yfinance ticker.history() with Close and Volume columns.

    Returns
    -------
    dict
        Momentum analysis results with keys: rsi, is_oversold, macd_histogram,
        macd_positive, roc, volume_trend, momentum_score, momentum_details,
        current_price, all_conditions.
    """
    default = {
        "rsi": float("nan"),
        "is_oversold": False,
        "macd_histogram": float("nan"),
        "macd_positive": False,
        "roc": float("nan"),
        "volume_trend": float("nan"),
        "momentum_score": 0.0,
        "momentum_details": {
            "rsi_oversold": False,
            "macd_reversal": False,
            "roc_positive": False,
            "volume_surge": False,
        },
        "current_price": float("nan"),
        "all_conditions": False,
    }

    close = hist["Close"]
    volume = hist["Volume"]

    # Need sufficient data
    if len(close) < 26:
        return default

    # Compute indicators
    from src.core.screening.technicals import compute_rsi, compute_bollinger_bands

    rsi_series = compute_rsi(close, period=14)
    macd_line, signal_line, histogram = compute_macd(close)
    roc_series = compute_roc(close, period=12)

    current_price = float(close.iloc[-1])
    current_rsi = float(rsi_series.iloc[-1]) if len(rsi_series) > 0 else float("nan")
    prev_rsi = float(rsi_series.iloc[-2]) if len(rsi_series) >= 2 else float("nan")

    current_macd_hist = float(histogram.iloc[-1]) if len(histogram) > 0 else float("nan")
    prev_macd_hist = float(histogram.iloc[-2]) if len(histogram) >= 2 else float("nan")

    current_roc = float(roc_series.iloc[-1]) if len(roc_series) > 0 else float("nan")

    # Volume trend: 5-day avg / 20-day avg
    vol_5 = volume.rolling(window=5).mean().iloc[-1] if len(volume) >= 5 else float("nan")
    vol_20 = volume.rolling(window=20).mean().iloc[-1] if len(volume) >= 20 else float("nan")
    volume_ratio = float(vol_5 / vol_20) if not np.isnan(vol_5) and not np.isnan(vol_20) and vol_20 > 0 else float("nan")

    # Condition 1: RSI oversold (< 30) or approaching oversold (< 35)
    rsi_oversold = current_rsi < 30
    rsi_approaching = current_rsi < 35

    # Condition 2: MACD histogram turning positive (reversal signal)
    macd_positive = current_macd_hist > 0
    macd_reversal = (
        prev_macd_hist < 0 and macd_positive
    )  # Cross from negative to positive

    # Condition 3: ROC positive (upward momentum)
    roc_positive = not np.isnan(current_roc) and current_roc > 0

    # Condition 4: Volume increasing
    volume_surge = not np.isnan(volume_ratio) and volume_ratio > 1.0

    # Score calculation
    momentum_score = 0.0
    momentum_details = {
        "rsi_oversold": False,
        "macd_reversal": False,
        "roc_positive": False,
        "volume_surge": False,
    }

    if rsi_oversold:
        momentum_score += 30
        momentum_details["rsi_oversold"] = True
    elif rsi_approaching:
        momentum_score += 15

    if macd_reversal:
        momentum_score += 35
        momentum_details["macd_reversal"] = True
    elif macd_positive:
        momentum_score += 20

    if roc_positive:
        momentum_score += 20
        momentum_details["roc_positive"] = True

    if volume_surge:
        momentum_score += 15
        momentum_details["volume_surge"] = True

    # All conditions: at least 3 signals must be true
    all_conditions = sum(
        [rsi_oversold, macd_reversal, roc_positive, volume_surge]
    ) >= 3

    return {
        "rsi": round(current_rsi, 2),
        "is_oversold": rsi_oversold,
        "macd_histogram": round(current_macd_hist, 4),
        "macd_positive": macd_positive,
        "roc": round(current_roc, 2),
        "volume_trend": round(volume_ratio, 4) if not np.isnan(volume_ratio) else float("nan"),
        "momentum_score": round(momentum_score, 2),
        "momentum_details": momentum_details,
        "current_price": round(current_price, 2),
        "all_conditions": all_conditions,
    }
