"""Proactive action suggestions based on accumulated knowledge graph (KIK-435).

Rule-based triggers — no LLM required.
Graceful degradation: returns empty list when Neo4j unavailable or any exception occurs.

Trigger categories:
  Time:        thesis note >90d old, last health check >14d ago, earnings within 7d
  State:       recurring screening picks, concern notes, held stock w/ new report
  Contextual:  research sector matches held stocks
"""

from datetime import date

_THESIS_REVIEW_DAYS = 90   # thesis note older than this → suggest review
_HEALTH_STALE_DAYS  = 14   # no health check for N days → suggest check
_HEALTH_HIGH_DAYS   = 30   # > this → urgency=high
_EARNINGS_WARN_DAYS = 7    # upcoming earnings within N days → warn
_RECURRING_MIN      = 3    # screened N+ times → suggest deeper report


class ProactiveEngine:
    """Generate proactive next-action suggestions from the knowledge graph."""

    def get_suggestions(
        self,
        context: str = "",
        symbol: str = "",
        sector: str = "",
    ) -> list[dict]:
        """Return up to 3 suggestions sorted by urgency (high > medium > low).

        Each item: {emoji, title, reason, command_hint, urgency}
        """
        suggestions: list[dict] = []
        suggestions += self._check_time_triggers()
        suggestions += self._check_state_triggers(symbol)
        suggestions += self._check_contextual_triggers(sector)

        # Sort by urgency, deduplicate by title
        _order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda s: _order.get(s.get("urgency", "low"), 2))
        seen: set[str] = set()
        result: list[dict] = []
        for s in suggestions:
            key = s.get("title", "")
            if key not in seen:
                seen.add(key)
                result.append(s)
        return result[:3]

    # ------------------------------------------------------------------
    # Time triggers
    # ------------------------------------------------------------------

    def _check_time_triggers(self) -> list[dict]:
        out: list[dict] = []

        # Health check staleness
        try:
            from src.data.graph_query import get_last_health_check_date
            last_hc = get_last_health_check_date()
            if last_hc is None:
                out.append({
                    "emoji": "📋",
                    "title": "ヘルスチェックの実施",
                    "reason": "ヘルスチェックの記録がありません",
                    "command_hint": "portfolio health",
                    "urgency": "medium",
                })
            else:
                delta = (date.today() - date.fromisoformat(last_hc)).days
                if delta >= _HEALTH_STALE_DAYS:
                    out.append({
                        "emoji": "📋",
                        "title": "ヘルスチェックの実施",
                        "reason": f"最終チェックから{delta}日経過",
                        "command_hint": "portfolio health",
                        "urgency": "high" if delta >= _HEALTH_HIGH_DAYS else "medium",
                    })
        except Exception:
            pass

        # Old thesis notes
        try:
            from src.data.graph_query import get_old_thesis_notes
            old_theses = get_old_thesis_notes(older_than_days=_THESIS_REVIEW_DAYS)
            for note in old_theses[:1]:
                sym = note.get("symbol") or "保有銘柄"
                days = note.get("days_old", _THESIS_REVIEW_DAYS)
                out.append({
                    "emoji": "🔄",
                    "title": f"{sym}の投資テーゼを見直す",
                    "reason": f"テーゼ記録から{days}日経過（要再検証）",
                    "command_hint": (
                        f"investment-note list --symbol {sym}"
                        if sym != "保有銘柄" else "investment-note list --type thesis"
                    ),
                    "urgency": "medium",
                })
        except Exception:
            pass

        # Upcoming earnings events
        try:
            from src.data.graph_query import get_upcoming_events
            events = get_upcoming_events(within_days=_EARNINGS_WARN_DAYS)
            for ev in events[:1]:
                ev_date = ev.get("date", "")
                ev_text = str(ev.get("text", ""))[:60]
                out.append({
                    "emoji": "📅",
                    "title": "決算イベントが近い",
                    "reason": f"{ev_date} に予定: {ev_text} — 直前のレポート確認を推奨",
                    "command_hint": "market-research market",
                    "urgency": "high",
                })
        except Exception:
            pass

        return out

    # ------------------------------------------------------------------
    # State triggers
    # ------------------------------------------------------------------

    def _check_state_triggers(self, symbol: str = "") -> list[dict]:
        out: list[dict] = []

        # Recurring screening picks
        try:
            from src.data.graph_query import get_recurring_picks
            picks = get_recurring_picks(min_count=_RECURRING_MIN)
            for pick in picks[:1]:
                sym = pick.get("symbol", "")
                cnt = pick.get("count", _RECURRING_MIN)
                out.append({
                    "emoji": "🔍",
                    "title": f"{sym}の詳細分析",
                    "reason": f"スクリーニングで{cnt}回上位にランクイン",
                    "command_hint": f"stock-report {sym}",
                    "urgency": "medium",
                })
        except Exception:
            pass

        # Concern notes
        try:
            from src.data.graph_query import get_concern_notes
            concerns = get_concern_notes(limit=1)
            for c in concerns:
                sym = c.get("symbol") or ""
                days = c.get("days_old", 0)
                sym_display = sym if sym else "銘柄"
                out.append({
                    "emoji": "⚠️",
                    "title": f"{sym_display}の懸念メモを再確認",
                    "reason": f"{days}日前に懸念を記録済み — 状況変化を確認",
                    "command_hint": (
                        f"investment-note list --symbol {sym}"
                        if sym else "investment-note list --type concern"
                    ),
                    "urgency": "medium",
                })
        except Exception:
            pass

        return out

    # ------------------------------------------------------------------
    # Contextual triggers
    # ------------------------------------------------------------------

    def _check_contextual_triggers(self, sector: str = "") -> list[dict]:
        out: list[dict] = []
        if not sector:
            return out
        try:
            from src.data.graph_query import get_current_holdings, get_industry_research_for_linking
            research = get_industry_research_for_linking(sector, days=14, limit=1)
            if not research:
                return out
            holdings = get_current_holdings()
            held_sectors = {h.get("sector", "") for h in holdings}
            if sector in held_sectors:
                out.append({
                    "emoji": "💡",
                    "title": f"{sector}セクターの最新リサーチがあります",
                    "reason": "保有銘柄のセクターに関連する直近リサーチを検出",
                    "command_hint": f"market-research industry {sector}",
                    "urgency": "low",
                })
        except Exception:
            pass
        return out


# ---------------------------------------------------------------------------
# Public convenience functions
# ---------------------------------------------------------------------------

def get_suggestions(
    context: str = "",
    symbol: str = "",
    sector: str = "",
) -> list[dict]:
    """Return proactive suggestions from the knowledge graph (KIK-435)."""
    return ProactiveEngine().get_suggestions(
        context=context, symbol=symbol, sector=sector
    )


def format_suggestions(suggestions: list[dict]) -> str:
    """Format suggestion list as markdown for display after skill output."""
    if not suggestions:
        return ""
    lines = [f"\n---\n💡 **次のアクション提案** ({len(suggestions)}件)\n"]
    for i, s in enumerate(suggestions, 1):
        emoji = s.get("emoji", "💡")
        title = s.get("title", "")
        reason = s.get("reason", "")
        cmd = s.get("command_hint", "")
        lines.append(f"{i}. {emoji} **{title}**")
        lines.append(f"   {reason}")
        if cmd:
            lines.append(f"   → `{cmd}` を実行してください")
        lines.append("")
    return "\n".join(lines)
