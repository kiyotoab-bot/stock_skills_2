"""Session-start state reconciliation (KIK-738 後追い).

`reconcile_session_state()` is a thin facade that loads the disk state AI
must read before making any PF / cash / holdings-related claim. The AI is
required (per stock-skills SKILL.md) to call this at session start or
before any PF assertion.

This is the same pattern as `tools/preflight.run_preflight()`: a tiny
facade so the SKILL.md can stay short and the call site is testable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from src.data import session_state as _impl  # internal logic


def reconcile_session_state(
    notes_window_days: int = 7,
    trade_window_days: int = 7,
    cash_stale_days: int = 3,
    base_dir: str = ".",
) -> dict[str, Any]:
    """Read all disk state required before talking about PF / cash / holdings.

    Returns
    -------
    dict with keys:
        portfolio          : list[dict]   — current holdings (CSV master)
        cash_balance       : dict | None  — cash_balance.json
        cash_stale         : bool         — True if cash date is too old
        recent_notes       : list[dict]   — notes within window_days
        recent_trades      : list[str]    — trade JSON filenames within window
        warnings           : list[str]    — human-readable warnings to surface
    """
    return _impl.reconcile_session_state(
        notes_window_days=notes_window_days,
        trade_window_days=trade_window_days,
        cash_stale_days=cash_stale_days,
        base_dir=base_dir,
    )


__all__ = ["reconcile_session_state"]
