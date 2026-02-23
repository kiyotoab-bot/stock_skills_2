"""Action item detector for proactive suggestions (KIK-472).

Converts proactive engine suggestions and health check data into structured
action items suitable for Linear issue creation and Neo4j storage.
"""

from datetime import date


# Keyword → trigger mapping
_TRIGGER_MAP: list[tuple[list[str], str, int, str]] = [
    # (keywords, trigger_type, linear_priority, title_format)
    (["撤退", "EXIT", "exit"], "exit", 2, "[Action] {symbol} 売却検討"),
    (["決算", "earnings", "Earnings"], "earnings", 2, "[Action] {symbol} 決算前チェック"),
    (["テーゼ", "thesis", "投資テーゼ"], "thesis_review", 3, "[Action] {symbol} テーゼ見直し"),
    (["懸念", "concern", "リスク確認"], "concern", 3, "[Action] {symbol} 懸念再確認"),
]


def _match_trigger(text: str) -> tuple[str, int, str] | None:
    """Match text against trigger patterns.

    Returns (trigger_type, priority, title_format) or None.
    """
    for keywords, trigger_type, priority, title_fmt in _TRIGGER_MAP:
        for kw in keywords:
            if kw in text:
                return trigger_type, priority, title_fmt
    return None


def detect_action_items(
    suggestions: list[dict],
    health_data: dict | None = None,
    context: dict | None = None,
) -> list[dict]:
    """Convert proactive suggestions into structured action items.

    Args:
        suggestions: Output from proactive_engine.get_suggestions().
        health_data: Output from health_check.run_health_check() (optional).
        context: Graph context dict (optional, reserved for future use).

    Returns:
        List of action item dicts:
        [{trigger_type, title, description, symbol, priority, urgency, action_id}]
    """
    items: list[dict] = []
    today = date.today().isoformat()
    seen_keys: set[str] = set()

    # 1. Extract from suggestions
    for s in suggestions:
        title_text = s.get("title", "")
        reason = s.get("reason", "")
        urgency = s.get("urgency", "medium")
        combined = f"{title_text} {reason}"

        match = _match_trigger(combined)
        if not match:
            continue

        trigger_type, priority, title_fmt = match

        # Extract symbol from suggestion (heuristic: first word of title after emoji)
        symbol = _extract_symbol_from_suggestion(s)
        title = title_fmt.format(symbol=symbol or "銘柄")
        action_id = f"action_{today}_{trigger_type}_{symbol or 'unknown'}"

        if action_id in seen_keys:
            continue
        seen_keys.add(action_id)

        items.append({
            "trigger_type": trigger_type,
            "title": title,
            "description": reason,
            "symbol": symbol,
            "priority": priority,
            "urgency": urgency,
            "action_id": action_id,
        })

    # 2. Extract EXIT alerts directly from health_data (supplements suggestions)
    if health_data:
        for pos in health_data.get("positions", []):
            alert = pos.get("alert", {})
            if not isinstance(alert, dict):
                continue
            level = alert.get("level", "")
            if level != "exit":
                continue
            symbol = pos.get("symbol", "")
            if not symbol:
                continue
            action_id = f"action_{today}_exit_{symbol}"
            if action_id in seen_keys:
                continue
            seen_keys.add(action_id)
            items.append({
                "trigger_type": "exit",
                "title": f"[Action] {symbol} 売却検討",
                "description": alert.get("message", "EXIT判定"),
                "symbol": symbol,
                "priority": 2,
                "urgency": "high",
                "action_id": action_id,
            })

    return items


def _extract_symbol_from_suggestion(suggestion: dict) -> str:
    """Try to extract a ticker symbol from a suggestion dict."""
    # Check command_hint for symbol
    hint = suggestion.get("command_hint", "")
    parts = hint.split()
    for part in parts:
        if "." in part and any(c.isdigit() for c in part):
            return part  # e.g. "7203.T"
        if part.isupper() and len(part) >= 2 and part.isalpha():
            return part  # e.g. "AAPL"

    # Check title for known patterns
    title = suggestion.get("title", "")
    for word in title.split():
        if "." in word and any(c.isdigit() for c in word):
            return word
        # Match patterns like "7203.Tの" (with Japanese suffix)
        cleaned = word.rstrip("のをがはにで")
        if "." in cleaned and any(c.isdigit() for c in cleaned):
            return cleaned

    return ""
