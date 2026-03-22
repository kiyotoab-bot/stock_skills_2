"""Markdown formatting for graph context output (KIK-411/427/428).

Converts raw graph history dicts into human-readable markdown with
freshness labels, community info, and action directives.
"""

from src.data.context.freshness import (
    _action_directive,
    _best_freshness,
    freshness_action,
    freshness_label,
)


def _format_context(symbol: str, history: dict, skill: str, reason: str,
                    relationship: str) -> str:
    """Format graph context as markdown with freshness labels (KIK-427/428)."""
    lines = [f"## 過去の経緯: {symbol} ({relationship})"]

    # Track freshness by data type for summary
    freshness_map: dict[str, str] = {}  # data_type -> label

    # Screens
    for s in history.get("screens", [])[:3]:
        d = s.get("date", "?")
        fl = freshness_label(d)
        lines.append(f"- [{fl}] {d} {s.get('preset', '')} "
                     f"スクリーニング ({s.get('region', '')})")
        freshness_map.setdefault("スクリーニング", fl)

    # Reports
    for r in history.get("reports", [])[:2]:
        d = r.get("date", "?")
        fl = freshness_label(d)
        verdict = r.get("verdict", "")
        score = r.get("score", "")
        lines.append(f"- [{fl}] {d} レポート: スコア {score}, {verdict}")
        freshness_map.setdefault("レポート", fl)

    # Trades
    for t in history.get("trades", [])[:3]:
        d = t.get("date", "?")
        fl = freshness_label(d)
        action = "購入" if t.get("type") == "buy" else "売却"
        lines.append(f"- [{fl}] {d} {action}: "
                     f"{t.get('shares', '')}株 @ {t.get('price', '')}")
        freshness_map.setdefault("取引", fl)

    # Health checks
    for h in history.get("health_checks", [])[:1]:
        d = h.get("date", "?")
        fl = freshness_label(d)
        lines.append(f"- [{fl}] {d} ヘルスチェック実施")
        freshness_map.setdefault("ヘルスチェック", fl)

    # Notes
    for n in history.get("notes", [])[:3]:
        content = (n.get("content", "") or "")[:50]
        lines.append(f"- メモ({n.get('type', '')}): {content}")

    # Themes
    themes = history.get("themes", [])
    if themes:
        lines.append(f"- テーマ: {', '.join(themes[:5])}")

    # Community (KIK-549)
    try:
        from src.data.graph_query.community import get_stock_community
        comm = get_stock_community(symbol)
        if comm:
            peers = comm.get("peers", [])[:5]
            lines.append(f"- コミュニティ: {comm['name']} ({comm['size']}銘柄)")
            if peers:
                lines.append(f"  同一クラスタ: {', '.join(peers)}")
    except Exception:
        pass

    # Researches
    for r in history.get("researches", [])[:2]:
        d = r.get("date", "?")
        fl = freshness_label(d)
        summary = (r.get("summary", "") or "")[:50]
        lines.append(f"- [{fl}] {d} リサーチ({r.get('research_type', '')}): "
                     f"{summary}")
        freshness_map.setdefault("リサーチ", fl)

    if len(lines) == 1:
        lines.append("- (過去データなし)")

    # Freshness summary (KIK-427)
    if freshness_map:
        lines.append("")
        lines.append("### 鮮度サマリー")
        for dtype, fl in freshness_map.items():
            lines.append(f"- {dtype}: [{fl}] → {freshness_action(fl)}")

    # KIK-428: Prepend action directive based on overall freshness
    overall = _best_freshness(list(freshness_map.values())) if freshness_map else "NONE"
    lines.insert(0, _action_directive(overall) + "\n")

    lines.append(f"\n**推奨**: {skill} ({reason})")
    return "\n".join(lines)


def _format_market_context(mc: dict) -> str:
    """Format market context as markdown with freshness label (KIK-427/428)."""
    d = mc.get("date", "?")
    fl = freshness_label(d)
    lines = [_action_directive(fl) + "\n"]
    lines.append(f"## 直近の市況コンテキスト [{fl}]")
    lines.append(f"- 取得日: {d} → {freshness_action(fl)}")
    for idx in mc.get("indices", [])[:5]:
        if isinstance(idx, dict):
            name = idx.get("name", idx.get("symbol", "?"))
            price = idx.get("price", idx.get("close", "?"))
            lines.append(f"- {name}: {price}")
    lines.append("\n**推奨**: market-research (市況照会)")
    return "\n".join(lines)
