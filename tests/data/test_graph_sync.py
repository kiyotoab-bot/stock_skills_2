"""Tests for src/data/graph_sync.py history coverage (KIK-735).

KIK-712 の sync_all() は portfolio と notes しか回しておらず、SKILL.md が
同期対象に挙げている trade / screen / report / research / health が
一度も同期されなかった。ここではその全カテゴリが実際に merge されることと、
実データに存在するキー名の揺れを吸収できることを検証する。
"""

import json
from unittest.mock import patch

import pytest

from src.data import graph_sync


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return tmp_path


class TestLoadRecords:
    """履歴ファイルは dict 形式と list 形式が混在している."""

    def test_list_format(self, tmp_path):
        p = tmp_path / "a.json"
        _write(p, [{"symbol": "MSFT"}, {"symbol": "AAPL"}])
        assert graph_sync._load_records(p) == [{"symbol": "MSFT"}, {"symbol": "AAPL"}]

    def test_dict_format(self, tmp_path):
        p = tmp_path / "a.json"
        _write(p, {"symbol": "MSFT"})
        assert graph_sync._load_records(p) == [{"symbol": "MSFT"}]

    def test_scalar_format_returns_empty(self, tmp_path):
        p = tmp_path / "a.json"
        _write(p, "broken")
        assert graph_sync._load_records(p) == []

    def test_non_dict_entries_dropped(self, tmp_path):
        p = tmp_path / "a.json"
        _write(p, [{"symbol": "MSFT"}, "junk", None])
        assert graph_sync._load_records(p) == [{"symbol": "MSFT"}]


class TestSyncTrade:
    """direction と実現損益はファイルによってキー名が違う."""

    def test_action_key_used(self):
        rec = {"symbol": "7203.T", "action": "sell", "date": "2026-05-19",
               "shares": 100, "price": 520, "currency": "JPY"}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            assert graph_sync._sync_trade(rec) is True
        assert m.call_args.kwargs["trade_type"] == "sell"
        assert m.call_args.kwargs["trade_date"] == "2026-05-19"

    def test_trade_type_key_fallback(self):
        rec = {"symbol": "7203.T", "trade_type": "buy", "trade_date": "2026-05-19",
               "shares": 100, "price": 520, "currency": "JPY"}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            graph_sync._sync_trade(rec)
        assert m.call_args.kwargs["trade_type"] == "buy"
        assert m.call_args.kwargs["trade_date"] == "2026-05-19"

    def test_action_wins_over_trade_type(self):
        """実データでは action が全件、trade_type は一部にしかない."""
        rec = {"symbol": "7203.T", "action": "sell", "trade_type": "buy",
               "date": "2026-05-19", "shares": 1, "price": 1, "currency": "JPY"}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            graph_sync._sync_trade(rec)
        assert m.call_args.kwargs["trade_type"] == "sell"

    @pytest.mark.parametrize("key", ["realized_pnl", "realized_pl", "pnl"])
    def test_realized_pnl_key_variants(self, key):
        rec = {"symbol": "7203.T", "action": "sell", "date": "2026-05-19",
               "shares": 100, "price": 520, "currency": "JPY", key: -114000}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            graph_sync._sync_trade(rec)
        assert m.call_args.kwargs["realized_pnl"] == -114000

    def test_uppercase_direction_normalized(self):
        rec = {"symbol": "7203.T", "action": "SELL", "date": "2026-05-19",
               "shares": 1, "price": 1, "currency": "JPY"}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            graph_sync._sync_trade(rec)
        assert m.call_args.kwargs["trade_type"] == "sell"

    def test_missing_required_field_returns_false(self):
        with patch("src.data.graph_store.merge_trade") as m:
            assert graph_sync._sync_trade({"symbol": "7203.T"}) is False
        m.assert_not_called()


class TestSyncScreen:
    def test_symbols_extracted_from_results(self):
        rec = {"date": "2026-08-08", "preset": "value", "region": "jp", "count": 2,
               "results": [{"symbol": "7203.T", "name": "Toyota", "sector": "Auto"},
                           {"symbol": "6701.T"}]}
        with patch("src.data.graph_store.merge_screen", return_value=True) as ms, \
             patch("src.data.graph_store.merge_stock") as mst:
            assert graph_sync._sync_screen(rec) is True
        assert ms.call_args.kwargs["symbols"] == ["7203.T", "6701.T"]
        assert mst.call_count == 2

    def test_count_falls_back_to_symbol_count(self):
        rec = {"date": "2026-08-08", "results": [{"symbol": "7203.T"}]}
        with patch("src.data.graph_store.merge_screen", return_value=True) as ms, \
             patch("src.data.graph_store.merge_stock"):
            graph_sync._sync_screen(rec)
        assert ms.call_args.kwargs["count"] == 1

    def test_missing_date_returns_false(self):
        with patch("src.data.graph_store.merge_screen") as m:
            assert graph_sync._sync_screen({"preset": "value"}) is False
        m.assert_not_called()


class TestSyncReport:
    def test_value_score_mapped_to_score(self):
        rec = {"date": "2026-08-08", "symbol": "7203.T", "value_score": 72.5,
               "verdict": "buy", "price": 2000, "per": 10}
        with patch("src.data.graph_store.merge_report_full", return_value=True) as m, \
             patch("src.data.graph_store.merge_stock"):
            assert graph_sync._sync_report(rec) is True
        assert m.call_args.kwargs["score"] == 72.5
        assert m.call_args.kwargs["verdict"] == "buy"

    def test_none_numerics_become_zero(self):
        """payload の数値フィールドは None のまま保存されることがある."""
        rec = {"date": "2026-08-08", "symbol": "7203.T", "per": None, "roe": None}
        with patch("src.data.graph_store.merge_report_full", return_value=True) as m, \
             patch("src.data.graph_store.merge_stock"):
            graph_sync._sync_report(rec)
        assert m.call_args.kwargs["per"] == 0.0
        assert m.call_args.kwargs["roe"] == 0.0


class TestSyncResearch:
    def test_research_type_key_fallback(self):
        rec = {"date": "2026-08-08", "target": "半導体", "type": "theme"}
        with patch("src.data.graph_store.merge_research_full", return_value=True) as m:
            assert graph_sync._sync_research(rec) is True
        assert m.call_args.kwargs["research_type"] == "theme"

    def test_missing_target_returns_false(self):
        with patch("src.data.graph_store.merge_research_full") as m:
            assert graph_sync._sync_research({"date": "2026-08-08"}) is False
        m.assert_not_called()


class TestSyncHealth:
    def test_symbols_extracted_from_positions(self):
        rec = {"date": "2026-08-08", "summary": {"green": 3},
               "positions": [{"symbol": "7203.T"}, {"symbol": "6701.T"}, {}]}
        with patch("src.data.graph_store.merge_health", return_value=True) as m:
            assert graph_sync._sync_health(rec) is True
        assert m.call_args.kwargs["symbols"] == ["7203.T", "6701.T"]
        assert m.call_args.kwargs["summary"] == {"green": 3}


class TestSyncHistory:
    """KIK-735 の本丸: 全カテゴリが回ること."""

    def test_all_categories_synced(self, root):
        _write(root / "data/history/trade/t.json",
               [{"symbol": "7203.T", "action": "buy", "date": "2026-08-08",
                 "shares": 100, "price": 2000, "currency": "JPY"}])
        _write(root / "data/history/screen/s.json",
               {"date": "2026-08-08", "preset": "value", "region": "jp",
                "results": [{"symbol": "7203.T"}]})
        _write(root / "data/history/report/r.json",
               {"date": "2026-08-08", "symbol": "7203.T", "value_score": 70})
        _write(root / "data/history/research/rs.json",
               {"date": "2026-08-08", "target": "半導体", "research_type": "theme"})
        _write(root / "data/history/health/h.json",
               {"date": "2026-08-08", "summary": {}, "positions": [{"symbol": "7203.T"}]})

        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_trade", return_value=True), \
             patch("src.data.graph_store.merge_screen", return_value=True), \
             patch("src.data.graph_store.merge_report_full", return_value=True), \
             patch("src.data.graph_store.merge_research_full", return_value=True), \
             patch("src.data.graph_store.merge_health", return_value=True), \
             patch("src.data.graph_store.merge_stock"):
            graph_sync._sync_history(root, result)

        joined = " ".join(result["synced"])
        for category in graph_sync.HISTORY_CATEGORIES:
            assert f"{category}(1件)" in joined, f"{category} not synced: {joined}"
        assert not result["failed"]

    def test_missing_directory_is_not_an_error(self, root):
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_history(root, result)
        assert result == {"synced": [], "failed": [], "skipped": []}

    def test_broken_file_does_not_stop_the_rest(self, root):
        (root / "data/history/trade").mkdir(parents=True)
        (root / "data/history/trade/bad.json").write_text("{not json", encoding="utf-8")
        _write(root / "data/history/trade/good.json",
               [{"symbol": "7203.T", "action": "buy", "date": "2026-08-08",
                 "shares": 1, "price": 1, "currency": "JPY"}])

        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_trade", return_value=True):
            graph_sync._sync_history(root, result)

        assert any("trade(1件)" in s for s in result["synced"])
        assert any("bad.json" in f for f in result["failed"])

    def test_files_present_but_none_written_is_reported(self, root):
        """全滅を「何もなかった」と区別できないと、また気づけない."""
        _write(root / "data/history/trade/t.json", [{"symbol": "7203.T"}])  # 必須欠落
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_history(root, result)
        assert any("trade" in s and "0件" in s for s in result["skipped"])
        assert not result["synced"]

    def test_history_categories_match_skill_md_table(self):
        assert set(graph_sync.HISTORY_CATEGORIES) == {
            "trade", "screen", "report", "research", "health"}


class TestSyncNotes:
    def test_all_records_in_a_file_are_synced(self, root):
        """旧実装は data[0] しか見ず、1ファイル複数ノートを取りこぼしていた."""
        _write(root / "data/notes/n.json", [
            {"id": "n1", "date": "2026-08-08", "type": "lesson", "content": "A"},
            {"id": "n2", "date": "2026-08-08", "type": "lesson", "content": "B"},
            {"id": "n3", "date": "2026-08-08", "type": "lesson", "content": "C"},
        ])
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note") as m:
            graph_sync._sync_notes(root, result)
        assert m.call_count == 3
        assert result["synced"] == ["notes(3件)"]

    def test_note_id_falls_back_to_filename(self, root):
        _write(root / "data/notes/fallback.json", {"date": "2026-08-08", "content": "X"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note") as m:
            graph_sync._sync_notes(root, result)
        assert m.call_args.kwargs["note_id"] == "fallback"


class TestSyncPortfolioPath:
    def test_csv_resolved_from_project_root(self, root):
        (root / "data" / "portfolio.csv").write_text("symbol\n7203.T\n", encoding="utf-8")
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.portfolio_io.load_portfolio",
                   return_value=[{"symbol": "7203.T"}]) as ml, \
             patch("src.data.graph_store.portfolio.sync_portfolio"):
            graph_sync._sync_portfolio(root, result)
        assert ml.call_args.args[0] == str(root / "data" / "portfolio.csv")
        assert result["synced"] == ["portfolio(1銘柄)"]

    def test_missing_csv_is_skipped_not_silent(self, root):
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_portfolio(root, result)
        assert any("portfolio" in s for s in result["skipped"])
        assert not result["synced"]


class TestSyncCash:
    """KIK-736: cash_balance.json は同期表にあるだけで呼び出し口が無かった."""

    REAL = {
        "JPY": 6296491,
        "updated_at": "2026-08-04T18:30:00",
        "balance_jpy": 6296491,
        "last_updated": "2026-08-04",
        "memo": "8/4寄付き一斉約定 7件目",
    }

    def test_portfolio_property_and_note_written(self, root):
        _write(root / "data/cash_balance.json", self.REAL)
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True) as mc, \
             patch("src.data.graph_store.note.merge_note") as mn:
            graph_sync._sync_cash(root, result)

        assert mc.call_args.args[0] == "2026-08-04"
        assert mn.call_args.kwargs["note_type"] == "cash"
        assert mn.call_args.kwargs["category"] == "portfolio"
        assert result["synced"] == ["cash(1通貨)"]

    def test_note_id_is_date_scoped_so_resync_does_not_duplicate(self, root):
        _write(root / "data/cash_balance.json", self.REAL)
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note") as mn:
            graph_sync._sync_cash(root, result)
            graph_sync._sync_cash(root, result)
        ids = {c.kwargs["note_id"] for c in mn.call_args_list}
        assert ids == {"cash_2026-08-04"}

    def test_last_updated_wins_over_updated_at(self, root):
        """updated_at は書き込み時刻、last_updated が残高の基準日."""
        _write(root / "data/cash_balance.json",
               {"JPY": 100, "updated_at": "2026-08-07T23:00:00",
                "last_updated": "2026-08-04"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True) as mc, \
             patch("src.data.graph_store.note.merge_note"):
            graph_sync._sync_cash(root, result)
        assert mc.call_args.args[0] == "2026-08-04"

    def test_updated_at_used_when_last_updated_missing(self, root):
        _write(root / "data/cash_balance.json",
               {"JPY": 100, "updated_at": "2026-08-07T23:00:00"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True) as mc, \
             patch("src.data.graph_store.note.merge_note"):
            graph_sync._sync_cash(root, result)
        assert mc.call_args.args[0] == "2026-08-07"

    def test_multi_currency_content(self, root):
        _write(root / "data/cash_balance.json",
               {"JPY": 6296491, "USD": 2996.9, "last_updated": "2026-08-04"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note") as mn:
            graph_sync._sync_cash(root, result)
        content = mn.call_args.kwargs["content"]
        assert "JPY 6,296,491" in content
        assert "USD 2,997" in content
        assert result["synced"] == ["cash(2通貨)"]

    def test_missing_file_is_silent(self, root):
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_cash(root, result)
        assert result == {"synced": [], "failed": [], "skipped": []}

    def test_no_currency_key_is_skipped(self, root):
        _write(root / "data/cash_balance.json",
               {"last_updated": "2026-08-04", "memo": "x"})
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_cash(root, result)
        assert any("cash" in s for s in result["skipped"])
        assert not result["synced"]

    def test_no_date_is_skipped(self, root):
        _write(root / "data/cash_balance.json", {"JPY": 100})
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_cash(root, result)
        assert any("基準日" in s for s in result["skipped"])

    def test_write_failure_reported(self, root):
        _write(root / "data/cash_balance.json", self.REAL)
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=False), \
             patch("src.data.graph_store.note.merge_note") as mn:
            graph_sync._sync_cash(root, result)
        assert any("cash" in f for f in result["failed"])
        mn.assert_not_called()

    def test_cash_included_in_sync_all(self, root):
        _write(root / "data/cash_balance.json", self.REAL)
        with patch("src.data.graph_store._common.is_available", return_value=True), \
             patch("src.data.portfolio_io.load_portfolio", return_value=[]), \
             patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note"):
            result = graph_sync.sync_all(str(root))
        assert any("cash" in s for s in result["synced"])


class TestSyncAllEntryPoint:
    def test_neo4j_unavailable_returns_skipped(self):
        with patch("src.data.graph_store._common.is_available", return_value=False):
            result = graph_sync.sync_all()
        assert result["skipped"] == ["Neo4j未接続"]
        assert not result["synced"]

    def test_history_included_in_sync_all(self, root):
        _write(root / "data/history/trade/t.json",
               [{"symbol": "7203.T", "action": "buy", "date": "2026-08-08",
                 "shares": 1, "price": 1, "currency": "JPY"}])
        with patch("src.data.graph_store._common.is_available", return_value=True), \
             patch("src.data.portfolio_io.load_portfolio", return_value=[]), \
             patch("src.data.graph_store.merge_trade", return_value=True):
            result = graph_sync.sync_all(str(root))
        assert any("trade(1件)" in s for s in result["synced"])

    def test_tools_facade_delegates(self, root):
        """tools/graphrag.py は薄いファサードで、_project_root を引き継ぐ."""
        import tools.graphrag as tg
        orig = tg._project_root
        try:
            tg._project_root = str(root)
            with patch("src.data.graph_sync.sync_all", return_value={"synced": ["ok"]}) as m:
                assert tg.sync_all() == {"synced": ["ok"]}
            m.assert_called_once_with(str(root))
        finally:
            tg._project_root = orig
