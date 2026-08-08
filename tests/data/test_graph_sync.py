"""Tests for src/data/graph_sync.py history coverage (KIK-735).

KIK-712 の sync_all() は portfolio と notes しか回しておらず、SKILL.md が
同期対象に挙げている trade / screen / report / research / health が
一度も同期されなかった。ここではその全カテゴリが実際に merge されることと、
実データに存在するキー名の揺れを吸収できることを検証する。
"""

import json
from contextlib import contextmanager
from datetime import datetime
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


@contextmanager
def _graph_up():
    """Neo4j が繋がっていて mode も off でない状態を作る.

    conftest の autouse フィクスチャが NEO4J_MODE=off を立てるため、
    get_mode() も一緒に上書きしないと sync_all が早期リターンする。
    """
    with patch("src.data.graph_store.get_mode", return_value="full"), \
         patch("src.data.graph_store.is_available", return_value=True):
        yield


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

    def test_all_scalar_args_forwarded(self):
        """数値・文字列引数を検証していないと 0株/0円が黙って通る (KIK-737)."""
        rec = {"symbol": "7203.T", "action": "sell", "date": "2026-05-19",
               "shares": 2000, "price": 520.5, "currency": "USD", "memo": "stop",
               "sell_price": 520, "hold_days": 233}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            graph_sync._sync_trade(rec)
        k = m.call_args.kwargs
        assert k["shares"] == 2000 and isinstance(k["shares"], int)
        assert k["price"] == 520.5
        assert k["currency"] == "USD"
        assert k["memo"] == "stop"
        assert k["sell_price"] == 520
        assert k["hold_days"] == 233

    @pytest.mark.parametrize("shares,expected", [
        (100, 100), ("100", 100), (100.9, 100),
        (None, None), ("abc", None), ("1,000", None), (True, None),
    ])
    def test_shares_type_handling(self, shares, expected):
        """欠落・カンマ区切り・bool を 0株として通すと壊れた取引が残る."""
        rec = {"symbol": "7203.T", "action": "buy", "date": "2026-05-19",
               "shares": shares, "price": 1, "currency": "JPY"}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            ok = graph_sync._sync_trade(rec)
        if expected is None:
            assert ok is False
            m.assert_not_called()
        else:
            assert m.call_args.kwargs["shares"] == expected

    def test_missing_price_returns_false(self):
        rec = {"symbol": "7203.T", "action": "buy", "date": "2026-05-19", "shares": 100}
        with patch("src.data.graph_store.merge_trade") as m:
            assert graph_sync._sync_trade(rec) is False
        m.assert_not_called()

    def test_non_iso_date_returns_false(self):
        rec = {"symbol": "7203.T", "action": "buy", "date": "2026/05/19",
               "shares": 1, "price": 1}
        with patch("src.data.graph_store.merge_trade") as m:
            assert graph_sync._sync_trade(rec) is False
        m.assert_not_called()

    def test_empty_action_falls_through_to_trade_type(self):
        """空文字を「有効値」と読むとレコードごと落ちる."""
        rec = {"symbol": "7203.T", "action": "", "trade_type": "sell",
               "date": "2026-05-19", "shares": 1, "price": 1}
        with patch("src.data.graph_store.merge_trade", return_value=True) as m:
            assert graph_sync._sync_trade(rec) is True
        assert m.call_args.kwargs["trade_type"] == "sell"


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

    def test_symbolless_and_non_dict_results_dropped(self):
        """symbol 無しを混ぜると merge_screen に None が渡る (KIK-737)."""
        rec = {"date": "2026-08-08",
               "results": [{"symbol": "7203.T"}, {"name": "no symbol"}, "junk", None]}
        with patch("src.data.graph_store.merge_screen", return_value=True) as ms, \
             patch("src.data.graph_store.merge_stock") as mst:
            graph_sync._sync_screen(rec)
        assert ms.call_args.kwargs["symbols"] == ["7203.T"]
        assert mst.call_count == 1

    def test_empty_results_still_syncs(self):
        rec = {"date": "2026-08-08", "preset": "value"}
        with patch("src.data.graph_store.merge_screen", return_value=True) as ms, \
             patch("src.data.graph_store.merge_stock"):
            assert graph_sync._sync_screen(rec) is True
        assert ms.call_args.kwargs["symbols"] == []
        assert ms.call_args.kwargs["count"] == 0

    def test_theme_tagged_like_save_screen(self):
        """save_screen.py と揃えないと sync 経由だけ Theme に繋がらない."""
        rec = {"date": "2026-08-08", "theme": "AI", "results": [{"symbol": "7203.T"}]}
        with patch("src.data.graph_store.merge_screen", return_value=True), \
             patch("src.data.graph_store.merge_stock"), \
             patch("src.data.graph_store.tag_theme") as mt:
            graph_sync._sync_screen(rec)
        mt.assert_called_once_with("7203.T", "AI")


class TestSyncReport:
    def test_value_score_mapped_to_score(self):
        rec = {"date": "2026-08-08", "symbol": "7203.T", "value_score": 72.5,
               "verdict": "buy", "price": 2000, "per": 10}
        with patch("src.data.graph_store.merge_report_full", return_value=True) as m, \
             patch("src.data.graph_store.merge_stock"):
            assert graph_sync._sync_report(rec) is True
        assert m.call_args.kwargs["score"] == 72.5
        assert m.call_args.kwargs["verdict"] == "buy"

    def test_missing_symbol_returns_false(self):
        """ガードが無いと report_None_None のゴミノードが MERGE される (KIK-737)."""
        with patch("src.data.graph_store.merge_report_full") as m, \
             patch("src.data.graph_store.merge_stock") as ms:
            assert graph_sync._sync_report({"date": "2026-08-08"}) is False
        m.assert_not_called()
        ms.assert_not_called()

    def test_missing_date_returns_false(self):
        with patch("src.data.graph_store.merge_report_full") as m, \
             patch("src.data.graph_store.merge_stock"):
            assert graph_sync._sync_report({"symbol": "7203.T"}) is False
        m.assert_not_called()

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

    def test_missing_date_returns_false(self):
        """ガードが無いと health_None のゴミノードが MERGE される (KIK-737)."""
        with patch("src.data.graph_store.merge_health") as m:
            assert graph_sync._sync_health({"summary": {}}) is False
        m.assert_not_called()


class TestSyncNewCategories:
    """KIK-737 で同期対象に加えた3カテゴリ."""

    def test_market_context(self):
        rec = {"date": "2026-08-08", "indices": [{"symbol": "^N225", "change": -0.12}],
               "grok_research": {"summary": "x"}}
        with patch("src.data.graph_store.merge_market_context_full", return_value=True) as m:
            assert graph_sync._sync_market_context(rec) is True
        assert m.call_args.kwargs["indices"] == [{"symbol": "^N225", "change": -0.12}]
        assert m.call_args.kwargs["grok_research"] == {"summary": "x"}

    def test_market_context_missing_date(self):
        with patch("src.data.graph_store.merge_market_context_full") as m:
            assert graph_sync._sync_market_context({"indices": []}) is False
        m.assert_not_called()

    def test_stress_test(self):
        rec = {"date": "2026-08-08", "scenario": "トリプル安", "symbols": ["7203.T"],
               "portfolio_impact": -12.5,
               "var_result": {"var_95_daily": -3.1, "var_99_daily": -5.2}}
        with patch("src.data.graph_store.merge_stress_test", return_value=True) as m, \
             patch("src.data.graph_store.merge_stock") as ms:
            assert graph_sync._sync_stress_test(rec) is True
        assert m.call_args.kwargs["scenario"] == "トリプル安"
        assert m.call_args.kwargs["var_95"] == -3.1
        assert m.call_args.kwargs["var_99"] == -5.2
        ms.assert_called_once_with(symbol="7203.T")

    def test_stress_test_missing_scenario(self):
        with patch("src.data.graph_store.merge_stress_test") as m, \
             patch("src.data.graph_store.merge_stock"):
            assert graph_sync._sync_stress_test({"date": "2026-08-08"}) is False
        m.assert_not_called()

    def test_forecast(self):
        rec = {"date": "2026-08-08",
               "portfolio": {"optimistic": 20.0, "base": 5.0, "pessimistic": -10.0},
               "positions": [{"symbol": "7203.T"}, {}], "total_value_jpy": 1646500}
        with patch("src.data.graph_store.merge_forecast", return_value=True) as m, \
             patch("src.data.graph_store.merge_stock"):
            assert graph_sync._sync_forecast(rec) is True
        k = m.call_args.kwargs
        assert (k["optimistic"], k["base"], k["pessimistic"]) == (20.0, 5.0, -10.0)
        assert k["symbols"] == ["7203.T"]
        assert k["total_value_jpy"] == 1646500

    def test_forecast_missing_date(self):
        with patch("src.data.graph_store.merge_forecast") as m, \
             patch("src.data.graph_store.merge_stock"):
            assert graph_sync._sync_forecast({"positions": []}) is False
        m.assert_not_called()


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
        # KIK-737 で追加した3カテゴリ
        _write(root / "data/history/market_context/m.json",
               {"date": "2026-08-08", "indices": [{"symbol": "^N225"}]})
        _write(root / "data/history/stress_test/st.json",
               {"date": "2026-08-08", "scenario": "トリプル安",
                "symbols": ["7203.T"], "portfolio_impact": -12.5})
        _write(root / "data/history/forecast/f.json",
               {"date": "2026-08-08", "portfolio": {"base": 5.0},
                "positions": [{"symbol": "7203.T"}]})

        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_trade", return_value=True), \
             patch("src.data.graph_store.merge_screen", return_value=True), \
             patch("src.data.graph_store.merge_report_full", return_value=True), \
             patch("src.data.graph_store.merge_research_full", return_value=True), \
             patch("src.data.graph_store.merge_health", return_value=True), \
             patch("src.data.graph_store.merge_market_context_full", return_value=True), \
             patch("src.data.graph_store.merge_stress_test", return_value=True), \
             patch("src.data.graph_store.merge_forecast", return_value=True), \
             patch("src.data.graph_store.link_research_supersedes"), \
             patch("src.data.graph_store.tag_theme"), \
             patch("src.data.graph_store.merge_stock"):
            graph_sync._sync_history(root, result)

        joined = " ".join(result["synced"])
        for category in graph_sync.HISTORY_CATEGORIES:
            assert f"{category}(1/1件)" in joined, f"{category} not synced: {joined}"
        assert not result["failed"]

    def test_missing_directory_is_not_an_error(self, root):
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_history(root, result)
        assert result == {"synced": [], "failed": [], "skipped": []}

    def test_empty_category_dir_is_not_reported(self, root):
        """ディレクトリだけあって json 0件を「0件同期」と報告すると狼少年になる."""
        (root / "data/history/trade").mkdir(parents=True)
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

        assert any("trade(1/1件)" in s for s in result["synced"])
        assert any("bad.json" in f for f in result["failed"])
        # 例外の内容を落とすと JSON 破損か Neo4j 障害か切り分けられない
        assert any("Expecting" in f or "line" in f for f in result["failed"])

    def test_partial_failure_is_reported(self, root):
        """1件成功・1件失敗を「1件同期」だけで済ませない (KIK-737)."""
        _write(root / "data/history/trade/t.json", [
            {"symbol": "7203.T", "action": "buy", "date": "2026-08-08",
             "shares": 1, "price": 1, "currency": "JPY"},
            {"symbol": "6701.T", "action": "buy", "date": "2026-08-08"},  # shares/price 欠落
        ])
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_trade", return_value=True):
            graph_sync._sync_history(root, result)
        assert any("trade(1/2件)" in s for s in result["synced"])
        assert any("#1" in f for f in result["failed"])

    def test_files_present_but_none_written_is_a_failure(self, root):
        """全滅は skipped（＝対象が無かった）ではなく failed (KIK-737).

        Neo4j 障害で全 writer が False を返したとき skipped に入ると、
        failed が空なのでリトライ判断ができない。
        """
        _write(root / "data/history/trade/t.json", [{"symbol": "7203.T"}])  # 必須欠落
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_trade") as m:
            graph_sync._sync_history(root, result)
        m.assert_not_called()
        assert any("trade" in f and "0件" in f for f in result["failed"])
        assert not result["synced"]

    def test_every_saved_category_has_a_writer(self):
        """`save_*.py` が作るカテゴリを全て同期対象にする (KIK-737).

        旧テストは名前が `..._match_skill_md_table` なのに SKILL.md も
        save_*.py も読まず、リテラル集合と比べるだけだった。そのため
        market_context / stress_test / forecast が漏れたまま緑になり、
        「表と揃っている」という誤った安心を与えていた。
        ここでは `_history_dir("...")` の実引数をソースから拾って突き合わせる。
        """
        import re
        from pathlib import Path

        save_dir = Path(graph_sync.__file__).resolve().parent / "history"
        saved = set()
        for py in save_dir.glob("save_*.py"):
            saved |= set(re.findall(r'_history_dir\(\s*"([a-z_]+)"',
                                    py.read_text(encoding="utf-8")))
        assert saved, "save_*.py からカテゴリを検出できていない（正規表現が古い）"
        missing = saved - set(graph_sync.HISTORY_CATEGORIES)
        assert not missing, (
            f"save_*.py が書くのに同期されないカテゴリ: {sorted(missing)}. "
            "_WRITERS と SKILL.md の同期対象表に追加すること"
        )

    def test_history_categories_derives_from_writers(self):
        """2つを別々に並べると片方だけ増える。導出であることを固定する."""
        assert graph_sync.HISTORY_CATEGORIES == tuple(graph_sync._WRITERS)


class TestSyncNotes:
    def test_all_records_in_a_file_are_synced(self, root):
        """旧実装は data[0] しか見ず、1ファイル複数ノートを取りこぼしていた."""
        _write(root / "data/notes/n.json", [
            {"id": "n1", "date": "2026-08-08", "type": "lesson", "content": "A"},
            {"id": "n2", "date": "2026-08-08", "type": "lesson", "content": "B"},
            {"id": "n3", "date": "2026-08-08", "type": "lesson", "content": "C"},
        ])
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note", return_value=True) as m:
            graph_sync._sync_notes(root, result)
        assert m.call_count == 3
        assert result["synced"] == ["notes(3件)"]

    def test_note_id_falls_back_to_filename(self, root):
        _write(root / "data/notes/fallback.json", {"date": "2026-08-08", "content": "X"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note", return_value=True) as m:
            graph_sync._sync_notes(root, result)
        assert m.call_args.kwargs["note_id"] == "fallback"

    def test_write_failures_are_counted_not_claimed(self, root):
        """merge_note の戻り値を見ないと「159件同期」と出しながら0件になる (KIK-737)."""
        _write(root / "data/notes/n.json", [
            {"id": "n1", "date": "2026-08-08", "content": "A"},
            {"id": "n2", "date": "2026-08-08", "content": "B"},
        ])
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note", side_effect=[True, False]):
            graph_sync._sync_notes(root, result)
        assert result["synced"] == ["notes(1件)"]
        assert any("#1" in f for f in result["failed"])

    def test_all_failed_is_reported(self, root):
        _write(root / "data/notes/n.json", {"id": "n1", "date": "2026-08-08"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note", return_value=False):
            graph_sync._sync_notes(root, result)
        assert not result["synced"]
        assert any("0件同期" in s for s in result["skipped"])

    def test_broken_file_reported_with_reason_and_others_continue(self, root):
        (root / "data/notes").mkdir(parents=True)
        (root / "data/notes/bad.json").write_text("{not json", encoding="utf-8")
        _write(root / "data/notes/good.json", {"id": "g", "date": "2026-08-08"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note", return_value=True):
            graph_sync._sync_notes(root, result)
        assert result["synced"] == ["notes(1件)"]
        assert any("bad.json" in f for f in result["failed"])

    def test_one_bad_record_does_not_skip_the_rest_of_the_file(self, root):
        """try がループ全体を囲っていると3件目が試行されない (KIK-737)."""
        _write(root / "data/notes/n.json", [
            {"id": "n1", "date": "2026-08-08"},
            {"id": "n2", "date": "2026-08-08"},
            {"id": "n3", "date": "2026-08-08"},
        ])
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.note.merge_note",
                   side_effect=[True, RuntimeError("boom"), True]) as m:
            graph_sync._sync_notes(root, result)
        assert m.call_count == 3
        assert result["synced"] == ["notes(2件)"]
        assert any("boom" in f for f in result["failed"])


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


class TestWriteStatus:
    """sync_status.yaml は「最後にいつ sync したか」の唯一の記録 (KIK-737)."""

    def test_last_sync_is_iso_and_reported(self, root):
        import yaml
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._write_status(root, result)
        loaded = yaml.safe_load((root / "data/sync_status.yaml").read_text(encoding="utf-8"))
        datetime.fromisoformat(loaded["last_sync"])   # パースできなければ例外
        assert "sync_status更新" in result["synced"]

    def test_other_keys_are_preserved(self, root):
        """全上書きすると last_sync 以外のキーが次の sync で消える."""
        import yaml
        (root / "data").mkdir(parents=True, exist_ok=True)
        (root / "data/sync_status.yaml").write_text(
            yaml.dump({"last_sync": "2020-01-01T00:00:00", "note": "keep me"}),
            encoding="utf-8")
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._write_status(root, result)
        loaded = yaml.safe_load((root / "data/sync_status.yaml").read_text(encoding="utf-8"))
        assert loaded["note"] == "keep me"
        assert loaded["last_sync"] != "2020-01-01T00:00:00"

    def test_write_failure_is_visible(self, root):
        """握り潰すと「sync した」と誤認したまま鮮度チェックが狂う."""
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("builtins.open", side_effect=OSError("read-only")):
            graph_sync._write_status(root, result)
        assert any("sync_status" in s for s in result["skipped"])
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
             patch("src.data.graph_store.note.merge_note", return_value=True) as mn:
            graph_sync._sync_cash(root, result)

        assert mc.call_args.args[0] == "2026-08-04"
        assert mn.call_args.kwargs["note_type"] == "cash"
        assert mn.call_args.kwargs["category"] == "portfolio"
        assert result["synced"] == ["cash(1通貨)"]

    def test_note_id_is_date_scoped_so_resync_does_not_duplicate(self, root):
        _write(root / "data/cash_balance.json", self.REAL)
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note", return_value=True) as mn:
            graph_sync._sync_cash(root, result)
            graph_sync._sync_cash(root, result)
        ids = {c.kwargs["note_id"] for c in mn.call_args_list}
        assert ids == {"cash_2026-08-04"}

    def test_updated_at_wins_over_last_updated(self, root):
        """KIK-737: 優先順が逆だと残高更新のたびに過去日の履歴が壊れる.

        `tools/cash_balance.py` の save_cash_balance() が更新するのは
        `updated_at` だけで、`last_updated` は手で書かれた値が残り続ける。
        last_updated を優先すると、8/10 に残高を更新しても Note の id が
        `cash_2026-08-04` になり、8/4 の履歴が 8/10 の残高で上書きされる。
        """
        _write(root / "data/cash_balance.json",
               {"JPY": 7000000, "updated_at": "2026-08-10T09:00:00",
                "last_updated": "2026-08-04"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True) as mc, \
             patch("src.data.graph_store.note.merge_note", return_value=True) as mn:
            graph_sync._sync_cash(root, result)
        assert mc.call_args.args[0] == "2026-08-10"
        assert mn.call_args.kwargs["note_id"] == "cash_2026-08-10"

    def test_last_updated_used_when_updated_at_missing(self, root):
        _write(root / "data/cash_balance.json",
               {"JPY": 100, "last_updated": "2026-08-04"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True) as mc, \
             patch("src.data.graph_store.note.merge_note", return_value=True):
            graph_sync._sync_cash(root, result)
        assert mc.call_args.args[0] == "2026-08-04"

    def test_non_iso_date_is_skipped(self, root):
        """`[:10]` だけだと "Aug 4, 202" が id になって静かに汚染される."""
        _write(root / "data/cash_balance.json",
               {"JPY": 100, "updated_at": "Aug 4, 2026"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance") as mc:
            graph_sync._sync_cash(root, result)
        mc.assert_not_called()
        assert any("基準日" in s for s in result["skipped"])

    def test_unrecognized_currency_key_is_reported(self, root):
        """update_currency("usdt", ...) が黙って消えると気づけない."""
        _write(root / "data/cash_balance.json",
               {"JPY": 100, "usdt": 500, "updated_at": "2026-08-04"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note", return_value=True):
            graph_sync._sync_cash(root, result)
        assert any("usdt" in s for s in result["skipped"])
        assert any("cash(1通貨)" in s for s in result["synced"])

    def test_empty_file_is_skipped(self, root):
        _write(root / "data/cash_balance.json", [])
        result = {"synced": [], "failed": [], "skipped": []}
        graph_sync._sync_cash(root, result)
        assert any("空" in s for s in result["skipped"])

    def test_note_write_failure_is_reported(self, root):
        """Note が書けなければ履歴が残らない。成功として数えない."""
        _write(root / "data/cash_balance.json", self.REAL)
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note", return_value=False):
            graph_sync._sync_cash(root, result)
        assert any("Note" in f for f in result["failed"])
        assert not result["synced"]

    def test_multi_currency_content(self, root):
        _write(root / "data/cash_balance.json",
               {"JPY": 6296491, "USD": 2996.9, "last_updated": "2026-08-04"})
        result = {"synced": [], "failed": [], "skipped": []}
        with patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note", return_value=True) as mn:
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
             patch("src.data.graph_store.note.merge_note", return_value=True) as mn:
            graph_sync._sync_cash(root, result)
        assert any("cash" in f for f in result["failed"])
        mn.assert_not_called()

    def test_cash_included_in_sync_all(self, root):
        _write(root / "data/cash_balance.json", self.REAL)
        with _graph_up(), \
             patch("src.data.portfolio_io.load_portfolio", return_value=[]), \
             patch("src.data.graph_store.merge_cash_balance", return_value=True), \
             patch("src.data.graph_store.note.merge_note", return_value=True):
            result = graph_sync.sync_all(str(root))
        assert any("cash" in s for s in result["synced"])


class TestSyncAllEntryPoint:
    def test_neo4j_unavailable_returns_skipped(self, root):
        with patch("src.data.graph_store.get_mode", return_value="full"), \
             patch("src.data.graph_store.is_available", return_value=False):
            result = graph_sync.sync_all(str(root))
        assert result["skipped"] == ["Neo4j未接続"]
        assert not result["synced"]

    def test_mode_off_is_distinguished_from_data_problems(self, root):
        """NEO4J_MODE=off だと接続できても全 merge_* が False を返す (KIK-737).

        早期リターンしないと「N件中0件同期」が並び、設定ミスをデータ不良と
        誤診させる。
        """
        _write(root / "data/history/trade/t.json",
               [{"symbol": "7203.T", "action": "buy", "date": "2026-08-08",
                 "shares": 1, "price": 1}])
        with patch("src.data.graph_store.get_mode", return_value="off"), \
             patch("src.data.graph_store.is_available", return_value=True):
            result = graph_sync.sync_all(str(root))
        assert result["skipped"] == ["NEO4J_MODE=off"]
        assert not result["synced"] and not result["failed"]

    def test_graph_store_not_installed(self, root):
        """graph_store 未導入の環境でクラッシュしないこと."""
        import builtins
        real_import = builtins.__import__

        def fake(name, *a, **kw):
            if name == "src.data.graph_store":
                raise ImportError("no graph_store")
            return real_import(name, *a, **kw)

        with patch("builtins.__import__", side_effect=fake):
            result = graph_sync.sync_all(str(root))
        assert result["skipped"] == ["graph_store未インストール"]
        assert not result["synced"]

    def test_history_included_in_sync_all(self, root):
        _write(root / "data/history/trade/t.json",
               [{"symbol": "7203.T", "action": "buy", "date": "2026-08-08",
                 "shares": 1, "price": 1, "currency": "JPY"}])
        with _graph_up(), \
             patch("src.data.portfolio_io.load_portfolio", return_value=[]), \
             patch("src.data.graph_store.merge_trade", return_value=True):
            result = graph_sync.sync_all(str(root))
        assert any("trade(1/1件)" in s for s in result["synced"])

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
