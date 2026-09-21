"""増資（希薄化）履歴の判定 — EC6（2026-09-21 ユーザー指示）。

出典: NotebookLM「投資家の父から娘への教え」——
「苦しい時に増資で乗り切ろうとする会社の株は買わない。1株当たりの価値を
希薄化させて既存株主の利益を損なうため」。

2026-09-21 の父娘本監査で、EC1-EC5 / CY1-CY5 / PO のどこにも希薄化履歴を
見る工程が無いことが判明した。WL 登録・候補選別の段階で通す。

データは J-Quants 決算短信の ``ShOutFY``（期末発行済株数・自己株式込み）。
四半期ごとに開示されるので、隣接開示の比較で増加イベントの時期まで分かる。

⚠️ 限界を理解して使う:
- **株式分割・併合も株数を動かす**。分割は希薄化ではない。ただし日本株の
  分割は 1:1.2 / 1:1.5 など小比率も普通に行われる（EC4 の 8035.T は 1:5）。
  小比率分割は増資と同じ +5〜50% 帯に落ちるため機械では区別できず、
  「増資疑い」の WARN に含めて人間に確認を回す。+80% 以上（1:2 以上の
  分割で典型）と -30% 以下（併合の可能性）は別枠で目視確認を要求する。
  自動で分割と断定したい場合は J-Quants daily_quotes の AdjustmentFactor
  との突合が本筋（未実装）。
- 隣接開示の比較だけでは MSCB・新株予約権の分割行使のような
  **段階的希薄化**（毎四半期 +4% × 3年 = 累計 +60%）が素通りするため、
  分割・併合イベントで区切った区間ごとの累計増加も併せて判定する。
- 自己株の消却は株数を減らす。減少・微増（SO 行使等）は問題にしない。
  ただし大幅減は併合の可能性があるので目視確認に回す（併合直後の
  新株発行を差し引きで覆い隠すパターンがある）。
- ここで見えるのは「株数が動いた事実」だけ。増資の**理由**（苦しい時の
  穴埋めか、成長投資か）は開示資料を読んで人間が判断する。WARN は
  「買うな」ではなく「短信・適時開示で理由を確認せよ」の意味。
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

#: 隣接開示間でこの率以上の株数増加を「増資の疑い」として WARN にする。
#: ストックオプション行使・譲渡制限株式は年 1% 未満が普通で、5% を超える
#: 増加が SO だけで起きることはまず無い（小比率の株式分割は混入し得る）。
DILUTION_WARN_PCT = 5.0

#: 区間累計（分割・併合イベントで系列を区切った区間ごと）の増加がこの率
#: 以上なら、単発イベントが無くても WARN にする。MSCB 等の段階的希薄化
#: （隣接では毎回 WARN 閾値未満）を拾うため。
DILUTION_CUM_WARN_PCT = 10.0

#: この率以上の単発増加は株式分割の可能性が高い（1:2 で +100%）。
#: 自動で「分割だから無視」とはせず、分割か大規模希薄化かの目視確認を求める。
DILUTION_SPLIT_PCT = 80.0

#: この率以下の単発減少は株式併合の可能性。併合自体が株価低迷後の
#: corporate action であり、併合+新株発行の複合も実在するため目視確認を求める。
DILUTION_MERGE_PCT = -30.0

#: 検査対象の既定期間（年）。
DILUTION_LOOKBACK_YEARS = 3


def _num(value: Any) -> Optional[float]:
    """文字列混じりの API レスポンスを安全に float 化する（NaN は None）。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def get_share_count_history(symbol: str, limit: int = 16) -> list[tuple[str, float]]:
    """期末発行済株数（自己株込み）の履歴を **古い順** で返す。

    ⚠️ J-Quants の API は日付順に返さない（reit_metrics と同じ注意点）。
    全行から抽出 → 日付でソート → 新しい方から ``limit`` 件、の順で処理する。
    ソート前に行数で切ると最新の開示を取りこぼす。
    同一開示日が複数ある場合（訂正短信）は後の行を採用する。これは
    「API 応答順＝登録順」という仮定に依存する（日付順の保証とは別の話。
    厳密にやるなら DocType の訂正マーカー優先だが、同日訂正で株数が
    変わるのは稀なので割り切る）。
    開示日が ISO 日付でない行（NaT 等）は捨てる。NaT を通すと文字列
    ソートで「最新の開示」に化け、架空の増減イベントを作る。

    Returns
    -------
    list[tuple[str, float]]
        ``[(開示日 ISO, 株数), ...]``。取得できなければ空リスト。
    """
    from src.data.jquants_client._client import get_client, is_available
    from src.data.jquants_client.fin_summary import normalize_code

    if not is_available():
        return []
    try:
        df = get_client().get_fin_summary(code=normalize_code(symbol))
    except Exception:  # noqa: BLE001 - API 側の例外は種類が多い
        return []
    if df is None or len(df) == 0:
        return []

    by_date: dict[str, float] = {}
    for _, row in df.iterrows():
        date = str(row.get("DiscDate", ""))[:10]
        shares = _num(row.get("ShOutFY"))
        if shares is None or shares <= 0:
            continue
        try:
            # isoformat() との往復で YYYY-MM-DD 形式に限定する。
            # Python 3.11+ の fromisoformat は "20260510" も受理してしまい、
            # 区切り無し文字列は cutoff とのソート・比較を壊す
            if datetime.date.fromisoformat(date).isoformat() != date:
                continue
        except ValueError:
            continue  # NaT・非ISO は捨てる（fin_summary._fy_key と同じ方針）
        by_date[date] = shares  # 同日重複は後の行（訂正）で上書き

    out = sorted(by_date.items())
    return out[-limit:]


def _cutoff(today: Optional[datetime.date], years: int) -> str:
    d = today or datetime.date.today()
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:  # 2/29
        return d.replace(year=d.year - years, day=28).isoformat()


def check_dilution(
    share_series: dict[str, list[tuple[str, float]]],
    today: Optional[datetime.date] = None,
    lookback_years: int = DILUTION_LOOKBACK_YEARS,
) -> list[dict]:
    """EC6 — 買い候補の発行株数履歴に増資（希薄化）の形跡が無いか。

    Parameters
    ----------
    share_series
        ``{symbol: get_share_count_history() の結果}``。**買い候補**を渡す。
    today
        判定基準日（テスト用）。省略時は今日。
    lookback_years
        遡る年数。既定 3 年。

    Returns
    -------
    list[dict]
        EC6 の1件。**全候補を detail に載せる**。異常だけ出すと
        「表が無い＝見ていない」と区別がつかない（SD1/RL6 と同じ方針）。
        データが取れなかった銘柄も WARN に含める（SD1/SD2 と同じ方針。
        「見られなかったのに総合 PASS」を作らない）。
    """
    from src.data.checklist_review import NA, PASS, WARN, _result

    header = (f"直近{lookback_years}年の期末発行済株数(自己株込み)。"
              f"閾値: 単発+{DILUTION_WARN_PCT:.0f}% 累計+{DILUTION_CUM_WARN_PCT:.0f}% "
              f"分割疑義+{DILUTION_SPLIT_PCT:.0f}% 併合疑義{DILUTION_MERGE_PCT:.0f}%。")

    if not share_series:
        return [_result("EC6", NA, header + "候補なし")]

    cutoff = _cutoff(today, lookback_years)
    suspects, verify, clean, unknown = [], [], [], []

    for sym in sorted(share_series):
        # 入口でも同日重複を後勝ちで解決する（get_share_count_history 経由なら
        # 解決済みだが、この関数は yaml がエージェントに直接呼ばせる公開関数で
        # 任意の系列を受ける。タプル全体ソートだと同日2点が架空イベントになる）
        dedup: dict[str, float] = {}
        for d, s in (share_series.get(sym) or ()):
            dedup[d] = s
        full = sorted(dedup.items())
        in_win = [p for p in full if p[0] >= cutoff]
        before = [p for p in full if p[0] < cutoff]
        # 窓の直前1点を基準点として残す。切り捨てると「窓の最初の開示に
        # 現れる増加」（d0 < cutoff <= d1）が評価されず盲点になる
        series = before[-1:] + in_win
        if len(series) < 2:
            unknown.append(sym)
            continue

        events_warn, events_verify = [], []
        for (d0, s0), (d1, s1) in zip(series, series[1:]):
            if s0 <= 0:
                continue
            pct = (s1 / s0 - 1) * 100
            if pct >= DILUTION_SPLIT_PCT:
                events_verify.append(f"{d1} +{pct:.0f}% 分割か大規模希薄化")
            elif pct >= DILUTION_WARN_PCT:
                events_warn.append(f"{d1} +{pct:.1f}%")
            elif pct <= DILUTION_MERGE_PCT:
                events_verify.append(f"{d1} {pct:.0f}% 併合の可能性")

        # 段階的希薄化: 単発では閾値未満でも累計で効いているケース（MSCB 等）。
        # 分割・併合をまたぐ累計は corporate action に汚染されるが、汚染されるのは
        # **またぐ区間だけ**。銘柄まるごと累計を捨てると「分割を確認して閉じる →
        # 分割後の段階的希薄化を見ずに終わる」という、単発側で elif を潰したのと
        # 同じ失敗モードが累計側に残る。イベント位置で系列を区切り、区間ごとに見る
        bounds = [0]
        for i, ((_, s0), (_, s1)) in enumerate(zip(series, series[1:])):
            pct = (s1 / s0 - 1) * 100 if s0 > 0 else 0.0
            if pct >= DILUTION_SPLIT_PCT or pct <= DILUTION_MERGE_PCT:
                bounds.append(i + 1)
        bounds.append(len(series))
        for a, b in zip(bounds, bounds[1:]):
            seg = series[a:b]
            if len(seg) >= 2 and seg[0][1] > 0:
                cum = (seg[-1][1] / seg[0][1] - 1) * 100
                if cum >= DILUTION_CUM_WARN_PCT:
                    label = ("累計" if a == 0 and b == len(series)
                             else f"累計({seg[0][0]}以降)")
                    events_warn.append(f"{label} +{cum:.1f}%")

        # 分割と増資の複合を落とさない: elif にせず両方を積む
        if events_warn:
            suspects.append(f"{sym}({', '.join(events_warn)})")
        if events_verify:
            verify.append(f"{sym}({', '.join(events_verify)})")
        if not events_warn and not events_verify:
            clean.append(sym)

    parts = []
    if suspects:
        parts.append("増資疑い(小比率分割の可能性もある。理由を短信・適時開示で確認): "
                     + " / ".join(suspects))
    if verify:
        parts.append("目視確認: " + " / ".join(verify))
    if clean:
        parts.append("形跡なし: " + ", ".join(clean))
    if unknown:
        parts.append("データ不足/窓内の開示なし(要目視): " + ", ".join(unknown))

    # 非空なら全銘柄が suspects/verify/clean/unknown のいずれかに入るので
    # NA には落ちない（NA は「候補なし」専用）。unknown も WARN に含めるのは
    # SD1/SD2 と同じ方針——「見られなかったのに総合 PASS」を作らない
    status = WARN if (suspects or verify or unknown) else PASS
    return [_result("EC6", status, header + " | ".join(parts))]
