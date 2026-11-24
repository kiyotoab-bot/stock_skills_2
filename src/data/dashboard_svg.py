"""ダッシュボード用の inline SVG グラフ（KIK-789）.

外部ライブラリ・CDN を使わない。ファイルを開くだけで描け、データはどこにも送らない。
色は CSS 変数（--c-*）で指定し、ライト/ダークの両方で読めるようにする。
"""

from __future__ import annotations

import datetime
from html import escape
from typing import Optional

W, H = 880, 300
PAD_L, PAD_R, PAD_T, PAD_B = 70, 20, 20, 36


def _d(s: str) -> datetime.date:
    return datetime.date.fromisoformat(s[:10])


def _yen_short(v: float) -> str:
    return f"{v / 1e4:,.1f}万" if abs(v) < 1e5 else f"{v / 1e4:,.0f}万"


def line_chart(points: list[dict], target: Optional[float] = None,
               target_date: Optional[str] = None, required_cagr: Optional[float] = None,
               markers: Optional[list[dict]] = None) -> str:
    """総資産の折れ線。推計点（report_text）は破線、日次の記録は実線.

    required_cagr があれば「最初の点から必要年率で伸ばした線」を重ねる（目標額は表示範囲の外なので注記で出す）。
    ⚠️ 必要年率は**株式部分**に必要な年率（allocation.yaml の required_equity_cagr）。現金込みの総資産に
    当てているので、厳密な到達線ではなく「この傾きより上なら計画以上」の目安。
    markers は売買（{date, label, kind: buy/sell}）。
    """
    if not points:
        return '<p class="empty">資産推移のデータがまだありません。</p>'
    xs = [_d(p["date"]) for p in points]
    x0, x1 = xs[0], xs[-1]
    if x1 == x0:
        x1 = x0 + datetime.timedelta(days=1)
    vals = [p["total"] for p in points]
    lo, hi = min(vals), max(vals)
    # 必要年率の線（最初の点から伸ばす）は、表示期間の終わりまでだけ描く
    req = None
    if required_cagr:
        days = (x1 - x0).days
        req = (vals[0], vals[0] * (1 + required_cagr / 100) ** (days / 365.25))
        lo, hi = min(lo, *req), max(hi, *req)
    span = (hi - lo) or abs(hi) * 0.05 or 1
    lo, hi = lo - span * 0.08, hi + span * 0.08

    def sx(d: datetime.date) -> float:
        return PAD_L + (d - x0).days / (x1 - x0).days * (W - PAD_L - PAD_R)

    def sy(v: float) -> float:
        return PAD_T + (hi - v) / (hi - lo) * (H - PAD_T - PAD_B)

    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="総資産の推移" class="chart">']
    # 横グリッドと目盛り（4本）
    for i in range(5):
        v = lo + (hi - lo) * i / 4
        y = sy(v)
        parts.append(f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{PAD_L - 6}" y="{y + 4:.1f}" class="axis" text-anchor="end">{_yen_short(v)}</text>')
    # x 目盛り: 最初・中間・最後
    for d, anchor in ((x0, "start"), (x0 + (x1 - x0) / 2, "middle"), (x1, "end")):
        parts.append(f'<text x="{sx(d):.1f}" y="{H - 12}" class="axis" text-anchor="{anchor}">{d.isoformat()}</text>')
    if req:
        parts.append(f'<line x1="{sx(x0):.1f}" y1="{sy(req[0]):.1f}" x2="{sx(x1):.1f}" y2="{sy(req[1]):.1f}" '
                     f'class="req"><title>必要年率 {escape(str(required_cagr))}% の線</title></line>')
    # 線: 連続する同じ source ごとに区切る
    seg: list[tuple[float, float]] = []
    seg_src = None
    for p, d in zip(points, xs):
        src = "est" if p.get("source") == "report_text" else "rec"
        if seg_src is not None and src != seg_src:
            parts.append(_poly(seg, seg_src))
            seg = seg[-1:]
        seg.append((sx(d), sy(p["total"])))
        seg_src = src
    parts.append(_poly(seg, seg_src))
    for m in markers or []:
        try:
            d = _d(m["date"])
        except (KeyError, ValueError, TypeError):
            continue
        if not (x0 <= d <= x1):
            continue
        cls = "mk-buy" if m.get("kind") == "buy" else "mk-sell"
        parts.append(f'<line x1="{sx(d):.1f}" x2="{sx(d):.1f}" y1="{H - PAD_B}" y2="{H - PAD_B - 10}" class="{cls}">'
                     f'<title>{escape(m["date"])} {escape(str(m.get("label", "")))}</title></line>')
    last = points[-1]
    parts.append(f'<circle cx="{sx(xs[-1]):.1f}" cy="{sy(last["total"]):.1f}" r="4" class="dot">'
                 f'<title>{escape(last["date"])} ¥{last["total"]:,.0f}</title></circle>')
    parts.append("</svg>")
    note = ""
    if target and target_date:
        note = (f'<p class="note">目標 ¥{target:,.0f}（{escape(target_date)}）。'
                f'斜めの点線は最初の点から年率 {escape(str(required_cagr))}%（株式部分に必要な年率を、現金込みの総資産に当てた目安）で伸ばした線。'
                '破線はレポート本文から抜いた推計、実線は日次の記録。下の目盛りの短い線は売買の日。</p>')
    return "".join(parts) + note


def _poly(seg: list[tuple[float, float]], src: Optional[str]) -> str:
    if len(seg) < 2:
        return ""
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in seg)
    return f'<polyline points="{pts}" class="line-{src}"/>'


def bar_chart(rows: list[tuple[str, float]], label: str) -> str:
    """月別の棒グラフ（正は上・負は下）。rows = [(YYYY-MM, 値), ...]."""
    if not rows:
        return '<p class="empty">データがありません。</p>'
    h, pad = 220, 30
    vmax = max(abs(v) for _, v in rows) or 1
    bw = min(48, (W - PAD_L - PAD_R) / len(rows) * 0.7)
    step = (W - PAD_L - PAD_R) / len(rows)
    mid = pad + (h - 2 * pad) / 2
    scale = (h - 2 * pad) / 2 / vmax
    parts = [f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{escape(label)}" class="chart">',
             f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{mid}" y2="{mid}" class="grid"/>']
    for i, (k, v) in enumerate(rows):
        x = PAD_L + step * i + (step - bw) / 2
        bh = abs(v) * scale
        y = mid - bh if v >= 0 else mid
        cls = "bar-pos" if v >= 0 else "bar-neg"
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{max(bh, 0.5):.1f}" class="{cls}">'
                     f'<title>{escape(k)} ¥{v:,.0f}</title></rect>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{h - 8}" class="axis" text-anchor="middle">{escape(k[2:])}</text>')
        if v:
            ty = (y - 4) if v >= 0 else (y + bh + 12)
            parts.append(f'<text x="{x + bw / 2:.1f}" y="{ty:.1f}" class="axis" text-anchor="middle">{_yen_short(v)}</text>')
    parts.append("</svg>")
    return "".join(parts)
