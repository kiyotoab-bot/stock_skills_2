"""ストップ算定の統一式とトレーリング判定 — KIK-759.

    stop = max(簿価×0.85, min(局面高値×0.92, 現値×(1-0.85σ_h60)))

2026-08-07 以降この式を使っているが**関数が無く、毎回手計算していた**。
実際に手で出した値: 7751.T ¥4,350 / 9104.T ¥5,787 / 6701.T ¥4,609。
手計算は検算されないし、σ の期間や高値の窓を取り違えても誰も気づかない。

⚠️ **切り下げない。** トレーリングは上げるだけ。株価が下がると
「局面高値×0.92」も「現値×(1-0.85σ)」も下がるので、機械的に再計算すると
ストップが下がって損失を広げる。``check_trailing_stop`` は現行値より
上のときだけ ``should_raise=True`` を返す。

calc_stop           : 統一式で1銘柄のストップを出す
check_trailing_stop : 現行ストップと比べ、切り上げ可能かを返す
"""

from __future__ import annotations

import statistics
from typing import Optional, Sequence

# 統一式の係数（2026-08-07 決定）
HARD_FLOOR_RATIO = 0.85      # 簿価×0.85 — これより下には置かない
PHASE_HIGH_RATIO = 0.92      # 局面高値×0.92
SIGMA_MULTIPLIER = 0.85      # 0.85σ
SIGMA_WINDOW = 20            # σ_h60 の h は 20日ホライズン
SIGMA_LOOKBACK = 60          # 日次σ の推定に使う本数
PHASE_HIGH_LOOKBACK = 60     # 局面高値の窓


def calc_stop(
    closes: Sequence[float],
    book_value: float,
    sigma_lookback: int = SIGMA_LOOKBACK,
    phase_high_lookback: int = PHASE_HIGH_LOOKBACK,
) -> dict:
    """統一式でストップを算定する。

    Parameters
    ----------
    closes : Sequence[float]
        終値（古い順）。σ 推定に ``sigma_lookback`` 本以上必要。
    book_value : float
        簿価（取得単価）。**取得前は現値を入れない** — ハード基準が
        現値に連動して意味を失う。購入前の算定は仮の値であり、
        発注日に簿価で引き直すこと（concentration の
        conviction_provisional 判定を参照）。

    Returns
    -------
    dict with keys:
        stop            : float | None
        hard_floor      : 簿価×0.85
        phase_high_base : 局面高値×0.92
        vol_base        : 現値×(1-0.85σ)
        binding         : "hard" | "phase_high" | "vol" — どれが効いたか
        current_price / phase_high / daily_sigma_pct / distance_pct / distance_sigma
        label           : 人間可読1行
    """
    _na = {
        "stop": None, "hard_floor": None, "phase_high_base": None, "vol_base": None,
        "binding": None, "current_price": None, "phase_high": None,
        "daily_sigma_pct": None, "distance_pct": None, "distance_sigma": None,
        "label": "データ不足",
    }
    if not closes or len(closes) < sigma_lookback + 1:
        return _na
    if any(c is None or c <= 0 for c in closes):
        return _na
    if not book_value or book_value <= 0:
        return _na

    price = float(closes[-1])
    rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    sigma = statistics.pstdev(rets[-sigma_lookback:])
    phase_high = max(closes[-phase_high_lookback:])

    hard = book_value * HARD_FLOOR_RATIO
    phase_base = phase_high * PHASE_HIGH_RATIO
    vol_base = price * (1 - SIGMA_MULTIPLIER * sigma * (SIGMA_WINDOW ** 0.5))

    inner = min(phase_base, vol_base)
    stop = max(hard, inner)
    if stop == hard and hard > inner:
        binding = "hard"
    else:
        binding = "phase_high" if inner == phase_base else "vol"

    dist_pct = (price - stop) / price * 100
    dist_sigma = (price - stop) / (sigma * price) if sigma > 0 else None

    return {
        "stop": round(stop),
        "hard_floor": round(hard),
        "phase_high_base": round(phase_base),
        "vol_base": round(vol_base),
        "binding": binding,
        "current_price": price,
        "phase_high": phase_high,
        "daily_sigma_pct": round(sigma * 100, 2),
        "distance_pct": round(dist_pct, 2),
        "distance_sigma": round(dist_sigma, 2) if dist_sigma is not None else None,
        "label": (f"ストップ ¥{stop:,.0f}（{binding} 基準）— 現値 ¥{price:,.0f} から "
                  f"{dist_pct:-.1f}%"
                  + (f" = {dist_sigma:.1f}σ" if dist_sigma is not None else "")),
    }


def check_trailing_stop(
    closes: Sequence[float],
    book_value: float,
    current_stop: Optional[float],
    exempt: bool = False,
    **kwargs,
) -> dict:
    """現行ストップと統一式を比べ、切り上げ可能かを返す。

    ⚠️ **切り下げは提案しない。** 株価が下がれば式の値も下がるが、
    ストップを下げるのは損失の許容幅を広げることであり、
    トレーリングの逆。``should_raise`` は新値 > 現行のときだけ True。

    Parameters
    ----------
    exempt : bool
        ``conviction_override``（ユーザーが無条件保有と明言し、
        ストップを置かないと決めた銘柄）なら True を渡す。
        ``should_raise`` は常に False になる。

        ``current_stop=None`` は「まだ設定していない」と
        「置かないと決めた」の両方で起こり、値だけでは区別できない。
        区別しないと免除銘柄に毎回ストップ設定を促すことになる
        （2026-08-16 の週次で 7453.T 良品計画に実際に出た）。

    Returns
    -------
    dict
        ``calc_stop`` の結果に以下を加えたもの:
          current_stop / new_stop / should_raise / raise_amount / raise_pct
          exempt             : 免除銘柄として扱ったか
          locked_profit      : 新ストップ到達時に確定する1株あたり利益
          locked_profit_gain : 切り上げで増える1株あたり確定利益
          label              : 切り上げavailable のときだけ内容を持つ
    """
    calc = calc_stop(closes, book_value, **kwargs)
    if calc["stop"] is None:
        return {**calc, "current_stop": current_stop, "new_stop": None,
                "should_raise": False, "raise_amount": None, "raise_pct": None,
                "exempt": bool(exempt),
                "locked_profit": None, "locked_profit_gain": None}

    if exempt:
        return {**calc, "current_stop": None, "new_stop": None,
                "should_raise": False, "raise_amount": None, "raise_pct": None,
                "exempt": True, "locked_profit": None, "locked_profit_gain": None,
                "label": "conviction_override — ストップ免除（切り上げ提案しない）"}

    new_stop = calc["stop"]
    cur = float(current_stop) if current_stop else None
    should_raise = cur is None or new_stop > cur

    out = {
        **calc,
        "current_stop": cur,
        "new_stop": new_stop,
        "should_raise": should_raise,
        "exempt": False,
        "raise_amount": round(new_stop - cur) if cur is not None else None,
        "raise_pct": round((new_stop / cur - 1) * 100, 1) if cur else None,
        "locked_profit": round(new_stop - book_value),
        "locked_profit_gain": (round(new_stop - cur) if cur is not None else None),
    }
    if should_raise and cur is not None:
        out["label"] = (f"ストップ切り上げ可 ¥{cur:,.0f} → ¥{new_stop:,.0f}"
                        f"（+{out['raise_pct']:.1f}% / {calc['binding']} 基準）")
    elif should_raise:
        out["label"] = f"ストップ未設定 → ¥{new_stop:,.0f}（{calc['binding']} 基準）"
    else:
        # 切り下げは提案しない。据え置きであることだけ示す
        out["label"] = f"ストップ据え置き ¥{cur:,.0f}（式の値 ¥{new_stop:,.0f} は現行以下）"
    return out
