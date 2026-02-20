"""Formatter for GraphRAG screening context output (KIK-452).

Converts the context dict from screening_context.get_screening_graph_context()
into a human-readable markdown string appended after screening tables.
"""


_NOTE_TYPE_JP = {
    "concern": "懸念",
    "thesis": "テーゼ",
    "observation": "観察",
    "lesson": "学び",
    "review": "振り返り",
}


def format_screening_summary(context: dict, llm_text: str = "") -> str:
    """Format GraphRAG context as markdown for screening output.

    Parameters
    ----------
    context : dict
        Output from get_screening_graph_context().
    llm_text : str
        Optional LLM-generated summary sentence(s). Empty string to omit.

    Returns
    -------
    str
        Formatted markdown string. Empty string if nothing to show.
    """
    has_data = context.get("has_data", False)
    if not has_data and not llm_text:
        return ""

    lines = ["---", "### 📊 グラフコンテキスト（ナレッジグラフより）", ""]

    # --- Sector research ---
    for sector, data in context.get("sector_research", {}).items():
        lines.append(f"**{sector} セクタートレンド**")
        cats_pos = data.get("catalysts_pos", [])
        cats_neg = data.get("catalysts_neg", [])
        if cats_pos:
            pos_str = "、".join(cats_pos[:3])
            lines.append(f"- ポジティブ: {pos_str}")
        if cats_neg:
            neg_str = "、".join(cats_neg[:3])
            lines.append(f"- ネガティブ: {neg_str}")
        lines.append("")

    # --- Symbol themes ---
    themes_map = context.get("symbol_themes", {})
    if themes_map:
        for symbol, themes in themes_map.items():
            if themes:
                themes_str = "、".join(themes)
                lines.append(f"**テーマ（{symbol}）**: {themes_str}")
        lines.append("")

    # --- Symbol notes ---
    notes_map = context.get("symbol_notes", {})
    if notes_map:
        for symbol, notes in notes_map.items():
            for note in notes[:2]:
                note_type = _NOTE_TYPE_JP.get(
                    note.get("type", ""), note.get("type", "")
                )
                content = note.get("content", "")
                if len(content) > 80:
                    content = content[:77] + "..."
                date_str = note.get("date", "")
                date_part = f"（{date_str}）" if date_str else ""
                lines.append(
                    f"**投資メモ（{symbol}）**: {note_type} — {content}{date_part}"
                )
        lines.append("")

    # --- LLM summary ---
    if llm_text:
        lines.append(f"💡 **AI統合サマリー**: {llm_text.strip()}")
        lines.append("")

    return "\n".join(lines)
