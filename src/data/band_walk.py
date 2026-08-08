"""バンドウォーク（ボリンジャーバンド +2σ 沿いの強トレンド）の終了判定。

Sho's投資情報局の「バンドウォーク終了を見極める4工程」を定量化したもの。
NotebookLM から取得した定義を実装時に定着させたため、実行時に NotebookLM は参照しない。

4工程（順序が重要 — 順番どおりに満たされないと stage は進まない）:
  1. 剥離        : 終値が +2σ ラインから離れてバンド内に入る
  2. 日柄調整    : すぐ急落せず、中央線を割らないまま横ばいが続く
  3. 指標の転換  : パラボリックSAR が終値の上に点灯 + MACD デッドクロス
  4. 軌道修正    : 終値が中央線（SMA25）まで引き戻される

⚠️ 中央線は **25日**（Sho式の定義）。#160 の大底圏検出が使う BB(20, 2σ) とは
   期間が異なる。両者を混同しないこと。

detect_band_walk_end : 4工程の充足状況を返すメイン関数
"""

from __future__ import annotations

import statistics

# バンドウォークとみなす +2σ 到達の連続本数
BAND_WALK_MIN_RUN = 3

# 工程2（日柄調整）とみなす剥離後の最小経過本数
CONSOLIDATION_MIN_BARS = 3

# 工程2 の「横ばい」の定量条件。剥離直後 CONSOLIDATION_MIN_BARS 本の終値レンジが
# 平均の何%以内なら横ばいとみなすか。これが無いと「中央線に向かってまっすぐ下げた」
# だけの局面も日柄調整と誤判定する（工程2を飛ばした下落と区別できなくなる）。
CONSOLIDATION_MAX_RANGE_PCT = 3.0

# バンドウォークを遡って探す範囲（本）
DEFAULT_LOOKBACK = 60

# パラボリックSAR のパラメータ（標準値）
SAR_AF_START = 0.02
SAR_AF_STEP = 0.02
SAR_AF_MAX = 0.2

# MACD のパラメータ（標準値）
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# MACD のウォームアップ本数。EMA を SMA でシードする都合上、系列の先頭付近では
# MACD 線がシード値から収束する過程で必ず1回シグナル線を下抜ける。これは相場の
# 転換ではなく計算上の過渡現象なので、この本数までのクロスは無視する。
MACD_WARMUP = MACD_SLOW + 2 * MACD_SIGNAL

# detect_band_walk_end に必要な最小本数（工程3の MACD 判定が成立する長さ）
MIN_BARS = MACD_WARMUP + 10


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def _ema(values: list[float], period: int) -> list[float | None]:
    """指数移動平均。先頭 period-1 本は None。"""
    if len(values) < period:
        return [None] * len(values)

    out: list[float | None] = [None] * (period - 1)
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out.append(prev)
    for v in values[period:]:
        prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def _macd_dead_cross(closes: list[float], since: int) -> bool:
    """since 以降に MACD がシグナル線を上から下抜けたか。"""
    fast = _ema(closes, MACD_FAST)
    slow = _ema(closes, MACD_SLOW)
    macd = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast, slow)
    ]
    valid = [m for m in macd if m is not None]
    if len(valid) < MACD_SIGNAL + 1:
        return False

    offset = len(macd) - len(valid)
    sig_valid = _ema(valid, MACD_SIGNAL)
    signal: list[float | None] = [None] * offset + list(sig_valid)

    start = max(since, MACD_WARMUP)
    for i in range(start, len(closes)):
        if None in (macd[i], macd[i - 1], signal[i], signal[i - 1]):
            continue
        if macd[i - 1] >= signal[i - 1] and macd[i] < signal[i]:
            return True
    return False


def _parabolic_sar(highs: list[float], lows: list[float]) -> list[float | None]:
    """パラボリックSAR。先頭2本は初期化のため None を返さず sar[0] を流用する。"""
    n = len(highs)
    if n < 3:
        return [None] * n

    sar: list[float | None] = [None] * n
    uptrend = highs[1] >= highs[0]
    af = SAR_AF_START
    ep = highs[1] if uptrend else lows[1]
    sar[0] = lows[0] if uptrend else highs[0]
    sar[1] = sar[0]

    for i in range(2, n):
        cur = sar[i - 1] + af * (ep - sar[i - 1])
        if uptrend:
            cur = min(cur, lows[i - 1], lows[i - 2])
            if lows[i] < cur:
                uptrend = False
                cur = ep
                ep = lows[i]
                af = SAR_AF_START
            elif highs[i] > ep:
                ep = highs[i]
                af = min(af + SAR_AF_STEP, SAR_AF_MAX)
        else:
            cur = max(cur, highs[i - 1], highs[i - 2])
            if highs[i] > cur:
                uptrend = True
                cur = ep
                ep = highs[i]
                af = SAR_AF_START
            elif lows[i] < ep:
                ep = lows[i]
                af = min(af + SAR_AF_STEP, SAR_AF_MAX)
        sar[i] = cur
    return sar


def _bands(closes: list[float], window: int, sigma: float):
    """(中央線, +σ上限) を返す。先頭 window-1 本は None。

    標準偏差が 0 の区間（完全な横ばい）はバンドが潰れて上限 == 中央線になり、
    「終値 >= 上限」が常に成立してしまう。バンド未定義として upper=None を返す。
    """
    mid: list[float | None] = [None] * len(closes)
    upper: list[float | None] = [None] * len(closes)
    for i in range(window - 1, len(closes)):
        chunk = closes[i - window + 1:i + 1]
        m = sum(chunk) / window
        sd = statistics.pstdev(chunk)
        mid[i] = m
        upper[i] = m + sigma * sd if sd > 0 else None
    return mid, upper


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def detect_band_walk_end(
    closes: list[float],
    highs: list[float] | None = None,
    lows: list[float] | None = None,
    window: int = 25,
    sigma: float = 2.0,
    lookback: int = DEFAULT_LOOKBACK,
) -> dict:
    """バンドウォーク終了の4工程を判定する（上昇バンドウォークのみ対象）。

    Parameters
    ----------
    closes : list[float]
        終値の時系列（古い順）。最低 max(window + 20, MIN_BARS) 本必要。
        工程3の MACD 判定にウォームアップが要るため、実運用では
        3ヶ月（約60本）以上の日足を渡すこと。
    highs, lows : list[float] | None
        高値・安値。省略時は終値で代用する（SAR の精度は落ちる）。
    window : int
        中央線の期間。Sho式の定義に従い既定は 25（#160 の BB20 とは別物）。
    sigma : float
        バンド幅。既定 2.0。
    lookback : int
        バンドウォークを遡って探す本数。

    Returns
    -------
    dict with keys:
        in_band_walk : bool  — 直近もまだ +2σ 沿いを歩いているか
        stage        : int   — 0〜4（順序どおりに満たされた工程数）
        stages       : dict  — detach / consolidation / indicators / reversion の各真偽
        bars_since_detach : int | None — 剥離からの経過本数
        signal       : "band_walk" | "ending" | "ended" | "none" | "unavailable"
        label        : str   — 人間可読1行ラベル
    """
    _na = {
        "in_band_walk": False,
        "stage": 0,
        "stages": {
            "detach": False,
            "consolidation": False,
            "indicators": False,
            "reversion": False,
        },
        "bars_since_detach": None,
        "signal": "unavailable",
        "label": "データ不足",
    }

    if not closes or len(closes) < max(window + 20, MIN_BARS):
        return _na
    if any(c is None or c <= 0 for c in closes):
        return _na

    highs = highs if highs and len(highs) == len(closes) else list(closes)
    lows = lows if lows and len(lows) == len(closes) else list(closes)

    mid, upper = _bands(closes, window, sigma)
    last = len(closes) - 1
    earliest = max(window - 1 + BAND_WALK_MIN_RUN - 1, last - lookback)

    def _touching(i: int) -> bool:
        return upper[i] is not None and closes[i] >= upper[i]

    # 直近の「+2σ に BAND_WALK_MIN_RUN 本連続で到達した」最終日を探す
    walk_end = None
    for i in range(last, earliest - 1, -1):
        if all(_touching(j) for j in range(i - BAND_WALK_MIN_RUN + 1, i + 1)):
            walk_end = i
            break

    if walk_end is None:
        return {**_na, "signal": "none", "label": "バンドウォークなし"}

    if walk_end == last:
        return {
            **_na,
            "in_band_walk": True,
            "signal": "band_walk",
            "label": f"バンドウォーク継続中（+{sigma:.0f}σ沿い）",
        }

    # 工程1: 剥離した最初の日
    detach_idx = next(
        (i for i in range(walk_end + 1, last + 1) if not _touching(i)), None
    )
    if detach_idx is None:
        return {
            **_na,
            "in_band_walk": True,
            "signal": "band_walk",
            "label": f"バンドウォーク継続中（+{sigma:.0f}σ沿い）",
        }

    bars_since = last - detach_idx

    # 工程2: 剥離後、中央線を割らないまま横ばいが CONSOLIDATION_MIN_BARS 本以上続く
    consolidation = False
    if bars_since >= CONSOLIDATION_MIN_BARS:
        idx = range(detach_idx, detach_idx + CONSOLIDATION_MIN_BARS)
        chunk = [closes[i] for i in idx]
        above_mid = all(mid[i] is not None and closes[i] >= mid[i] for i in idx)
        avg = sum(chunk) / len(chunk)
        range_pct = (max(chunk) - min(chunk)) / avg * 100
        consolidation = above_mid and range_pct <= CONSOLIDATION_MAX_RANGE_PCT

    # 工程3: SAR が終値の上 + MACD デッドクロス
    sar = _parabolic_sar(highs, lows)
    sar_bearish = any(
        sar[i] is not None and sar[i] > closes[i]
        for i in range(detach_idx, last + 1)
    )
    indicators = sar_bearish and _macd_dead_cross(closes, detach_idx)

    # 工程4: 中央線まで軌道修正
    reversion = mid[last] is not None and closes[last] <= mid[last]

    stages = {
        "detach": True,
        "consolidation": consolidation,
        "indicators": indicators,
        "reversion": reversion,
    }

    stage = 0
    for key in ("detach", "consolidation", "indicators", "reversion"):
        if not stages[key]:
            break
        stage += 1

    if stage >= 4:
        signal = "ended"
        label = f"バンドウォーク終了（4/4工程完了・{bars_since}本経過）"
    else:
        signal = "ending"
        label = f"バンドウォーク終了過程（{stage}/4工程・剥離から{bars_since}本）"

    return {
        "in_band_walk": False,
        "stage": stage,
        "stages": stages,
        "bars_since_detach": bars_since,
        "signal": signal,
        "label": label,
    }
