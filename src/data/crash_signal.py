"""暴落時の全力買いサイン検知（『投資家の父から娘への教え』・2026-09-21 導入）.

書籍の3条件のうち機械判定できる2つを J-Quants の全銘柄日足1回で判定する:
  ① ストップ安銘柄数 >= 100（LL フラグ）
  ② 売買代金 / 時価総額 の比率が閾値超
③「テレビ・新聞で株価暴落がトップニュース」は人間が判定する。

2026-09-22 レビュー修正（コミット 0d44467 のコードレビュー6件対応）:
  #1 平日朝は当日バーが未確定で常に None になっていた
     → **前営業日へフォールバック**する（max_lookback 営業日まで遡る）
  #2 裸の except → None で障害と平常が区別不能だった
     → 常に dict を返し ``available`` / ``reason`` で縮退を明示する
     （src/data/jquants_client/prices.py と同じパターン）
  #4 書籍の閾値1%は「プライム売買代金/プライム時価総額・2024年」基準。
     全市場合算では平常日が既に 0.80%（2026-09-18 実測）で誤発火圏だった。
     → (a) **MktCap が取れる行だけ**で分子分母を揃える（レバETF等は
        売買代金だけ分子に入り時価総額が分母から抜ける偏りがあった。
        平常日実測で分子の 2.7% を占め、暴落日はさらに跳ねる）
       (b) 閾値を全市場・2026年水準で**再較正**: 平常 ≈0.80%、
        2024-08-05 型の暴落日は平常の約1.8倍と実測されるため、
        1.75×平常 = **1.4%** を採用。売買水準は年々変わるので
        年1回（または平常値が 0.9% を超えたら）再較正すること。

⚠️ サインが揃っても**発注は自動化しない**。月次上限・冷却期間と両立しない
   ため（lesson 2026-08-09）、「N/2 成立」を報告し人が判断する。
   書籍の作法: 成立時の注文は 14:30 以降。保有株は売らない。
"""

from __future__ import annotations

from typing import Optional

CRASH_STOP_LOW_MIN = 100
# 全市場・MktCap行限定ベース。較正 2026-09-22（平常0.80%の1.75倍）。
CRASH_TURNOVER_CAP_RATIO = 0.014
CRASH_CALIBRATION_NOTE = "全市場基準・2026-09-22較正（書籍のプライム1%を再較正）"


def evaluate_crash_buy_signal(stop_low_count: int,
                              turnover_jpy: float,
                              market_cap_jpy: float,
                              ratio_threshold: float = CRASH_TURNOVER_CAP_RATIO) -> dict:
    """暴落サインの機械判定部（純関数・テスト可能）。"""
    ratio = (turnover_jpy / market_cap_jpy) if market_cap_jpy else None
    sig_stop = stop_low_count >= CRASH_STOP_LOW_MIN
    sig_turn = ratio is not None and ratio > ratio_threshold
    n = int(sig_stop) + int(sig_turn)
    if n == 2:
        label = (f"🔴 暴落サイン 2/2 成立（ストップ安 {stop_low_count}銘柄 / "
                 f"売買代金比 {ratio*100:.2f}%）— ③報道の確認を。成立なら書籍の作法は "
                 "14:30以降の買い・保有株は売らない。発注は枠と併せて人が判断")
    elif n == 1:
        which = "ストップ安" if sig_stop else "売買代金比"
        label = f"⚠ 暴落サイン 1/2（{which}のみ）— もう一方を監視"
    else:
        label = (f"🟢 平常（ストップ安 {stop_low_count}銘柄 / "
                 f"売買代金比 {f'{ratio*100:.2f}%' if ratio is not None else 'n/a'}）")
    return {
        "available": True,
        "stop_low_count": stop_low_count,
        "turnover_jpy": turnover_jpy,
        "market_cap_jpy": market_cap_jpy,
        "turnover_cap_ratio": ratio,
        "ratio_threshold": ratio_threshold,
        "signal_stop_low": sig_stop,
        "signal_turnover": sig_turn,
        "mechanical_signals": n,
        "label": label,
    }


def _na(reason: str) -> dict:
    """判定不能。平常と区別できる形で返す（#2）。"""
    return {"available": False, "reason": reason,
            "label": f"⚪ 暴落サイン n/a — {reason}"}


def _candidate_dates(date_yyyymmdd: Optional[str], max_lookback: int) -> list[str]:
    """判定候補日（新しい順）。当日バー未確定に備えて前営業日まで遡る（#1）。"""
    if date_yyyymmdd:
        return [date_yyyymmdd]
    import datetime as _dt

    from src.data.data_freshness import _load_calendar
    iso = _dt.date.today().isoformat()
    biz = [d for d, is_b in _load_calendar() if is_b and d <= iso]
    if not biz:
        return [iso.replace("-", "")]
    return [d.replace("-", "") for d in biz[-max_lookback:]][::-1]


def detect_crash_buy_signal(date_yyyymmdd: Optional[str] = None,
                            max_lookback: int = 3) -> dict:
    """J-Quants 全銘柄日足で暴落サインを判定する。**常に dict を返す**。

    ``available=False`` は「判定できなかった」（設定・障害・データ未確定）であり
    「暴落なし」ではない。呼び出し側はラベルをそのまま表示すればよい。
    """
    try:
        from src.data.jquants_client._client import get_client, is_available
    except Exception as exc:                                  # pragma: no cover
        return _na(f"import失敗: {type(exc).__name__}")
    if not is_available():
        return _na("J-Quants 未設定（JQUANTS_API_KEY）")
    try:
        client = get_client()
    except Exception as exc:
        return _na(f"クライアント初期化失敗 {type(exc).__name__}: {exc}")

    last_err = None
    for d in _candidate_dates(date_yyyymmdd, max_lookback):
        try:
            df = client.get_eq_bars_daily(date_yyyymmdd=d)
        except Exception as exc:
            return _na(f"取得失敗（{d}） {type(exc).__name__}: {exc}")
        if df is None or not len(df):
            last_err = f"{d} のバー未確定"
            continue          # 当日分が未確定 → 前営業日へ（#1）
        # MktCap の取れる行に分子分母を揃える（#4a）。レバETF等を両側から外す
        sub = df[df["MktCap"].notna()]
        if not len(sub):
            return _na(f"{d}: MktCap 列が全行 null（スキーマ変更の可能性）")
        stop_low = int((sub["LL"].astype(str) == "1").sum())
        turnover = float(sub["Va"].dropna().sum())
        mcap = float(sub["MktCap"].dropna().sum()) * 1e6      # 百万円 → 円
        out = evaluate_crash_buy_signal(stop_low, turnover, mcap)
        out["date"] = d
        out["rows_used"] = int(len(sub))
        out["rows_dropped_no_mktcap"] = int(len(df) - len(sub))
        return out
    return _na(last_err or f"直近{max_lookback}営業日にバーなし")
