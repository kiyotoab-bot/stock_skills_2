"""Tests for src.data.session_state.reconcile_session_state (KIK-738 後追い)."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.data.session_state import reconcile_session_state


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def fake_repo(tmp_path):
    """Build a minimal data/ tree under tmp_path."""
    (tmp_path / "data").mkdir()
    return tmp_path


class TestReconcileSessionState:
    def test_empty_repo(self, fake_repo):
        out = reconcile_session_state(base_dir=str(fake_repo))
        assert out["portfolio"] == []
        assert out["cash_balance"] is None
        assert out["recent_notes"] == []
        assert out["recent_trades"] == []
        assert any("cash_balance" in w for w in out["warnings"])

    def test_fresh_cash_no_warning(self, fake_repo):
        today = date.today().isoformat()
        _write_json(
            fake_repo / "data" / "cash_balance.json",
            {"date": today, "total_jpy": 100000, "breakdown": {}},
        )
        out = reconcile_session_state(base_dir=str(fake_repo))
        assert out["cash_stale"] is False
        assert not any("cash_balance" in w for w in out["warnings"])

    def test_stale_cash_warns(self, fake_repo):
        old = (date.today() - timedelta(days=10)).isoformat()
        _write_json(
            fake_repo / "data" / "cash_balance.json",
            {"date": old, "total_jpy": 100000, "breakdown": {}},
        )
        out = reconcile_session_state(base_dir=str(fake_repo), cash_stale_days=3)
        assert out["cash_stale"] is True
        assert out["cash_missing"] is False
        assert any("10日前" in w or "乖離" in w for w in out["warnings"])

    def test_missing_cash_distinguished_from_stale(self, fake_repo):
        # No cash_balance.json at all — should set cash_missing, not cash_stale
        out = reconcile_session_state(base_dir=str(fake_repo))
        assert out["cash_missing"] is True
        assert out["cash_stale"] is False  # ← KIK-738 後追い: missing != stale

    def test_unparseable_cash_date_treated_as_stale(self, fake_repo):
        _write_json(
            fake_repo / "data" / "cash_balance.json",
            {"date": "garbage", "total_jpy": 0, "breakdown": {}},
        )
        out = reconcile_session_state(base_dir=str(fake_repo))
        assert out["cash_stale"] is True  # 保守側: 読めない時は stale 扱い
        assert out["cash_missing"] is False

    def test_recent_notes_loaded(self, fake_repo):
        today = date.today().isoformat()
        _write_json(
            fake_repo / "data" / "notes" / "recent.json",
            {"id": "n1", "date": today, "type": "journal", "content": "x"},
        )
        out = reconcile_session_state(base_dir=str(fake_repo))
        assert any(n.get("id") == "n1" for n in out["recent_notes"])

    def test_old_notes_excluded(self, fake_repo):
        old = (date.today() - timedelta(days=30)).isoformat()
        _write_json(
            fake_repo / "data" / "notes" / "old.json",
            {"id": "old1", "date": old, "type": "thesis", "content": "x"},
        )
        out = reconcile_session_state(base_dir=str(fake_repo), notes_window_days=7)
        assert all(n.get("id") != "old1" for n in out["recent_notes"])

    def test_recent_trades_listed(self, fake_repo):
        today = date.today().isoformat()
        _write_json(
            fake_repo / "data" / "history" / "trade" / "today_buy_X.json",
            {"id": "t1", "trade_date": today, "type": "buy", "symbol": "X"},
        )
        out = reconcile_session_state(base_dir=str(fake_repo))
        assert "today_buy_X.json" in out["recent_trades"]

    def test_old_trades_excluded(self, fake_repo):
        old = (date.today() - timedelta(days=30)).isoformat()
        _write_json(
            fake_repo / "data" / "history" / "trade" / "old_buy_X.json",
            {"id": "t1", "trade_date": old, "type": "buy", "symbol": "X"},
        )
        out = reconcile_session_state(base_dir=str(fake_repo), trade_window_days=7)
        assert "old_buy_X.json" not in out["recent_trades"]

    def test_corrupt_files_skipped(self, fake_repo):
        bad = fake_repo / "data" / "notes" / "bad.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{ this is not json", encoding="utf-8")
        out = reconcile_session_state(base_dir=str(fake_repo))
        # Should not raise
        assert out["recent_notes"] == []

    def test_notes_sorted_newer_first(self, fake_repo):
        d1 = (date.today() - timedelta(days=2)).isoformat()
        d2 = (date.today() - timedelta(days=5)).isoformat()
        _write_json(
            fake_repo / "data" / "notes" / "a.json",
            {"id": "older", "date": d2, "type": "journal"},
        )
        _write_json(
            fake_repo / "data" / "notes" / "b.json",
            {"id": "newer", "date": d1, "type": "journal"},
        )
        out = reconcile_session_state(base_dir=str(fake_repo))
        ids = [n["id"] for n in out["recent_notes"]]
        assert ids.index("newer") < ids.index("older")

    def test_warnings_when_no_recent_notes(self, fake_repo):
        # No notes dir
        out = reconcile_session_state(base_dir=str(fake_repo))
        assert any("新規 note なし" in w for w in out["warnings"])

    def test_checked_at_iso(self, fake_repo):
        out = reconcile_session_state(base_dir=str(fake_repo))
        # Just ensure it parses as iso date
        from datetime import date as _date
        _date.fromisoformat(out["checked_at"])
