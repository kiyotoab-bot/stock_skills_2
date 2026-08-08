"""Tests for graph_store portfolio sync functions (KIK-414).

Neo4j driver is mocked -- no real database connection needed.
"""

import pytest
from unittest.mock import MagicMock, patch, call

pytestmark = pytest.mark.no_auto_mock


# ===================================================================
# Fixtures
# ===================================================================

@pytest.fixture(autouse=True)
def reset_driver():
    """Reset global _driver before each test."""
    import src.data.graph_store as gs
    gs._driver = None
    yield
    gs._driver = None


@pytest.fixture
def mock_driver():
    """Provide a mock Neo4j driver with session context manager."""
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver, session


@pytest.fixture
def gs_with_driver(mock_driver):
    """Set up graph_store with a mock driver already injected."""
    import src.data.graph_store as gs
    driver, session = mock_driver
    gs._driver = driver
    return gs, driver, session


# ===================================================================
# sync_portfolio tests
# ===================================================================

class TestSyncPortfolio:
    def test_basic_sync(self, gs_with_driver):
        """Normal sync: creates Portfolio anchor, MERGE stock+HOLDS, deletes stale."""
        gs, _, session = gs_with_driver
        holdings = [
            {"symbol": "7203.T", "shares": 100, "cost_price": 2850,
             "cost_currency": "JPY", "purchase_date": "2026-01-01"},
            {"symbol": "AAPL", "shares": 10, "cost_price": 250,
             "cost_currency": "USD", "purchase_date": "2026-01-15"},
        ]
        with patch.object(gs, "_get_mode", return_value="full"):
            result = gs.sync_portfolio(holdings)
        assert result is True
        # Portfolio MERGE + 2 stock MERGEs + 2 HOLDS MERGEs + 1 stale DELETE = 6
        assert session.run.call_count == 6

    def test_skips_cash(self, gs_with_driver):
        """CASH positions should be skipped."""
        gs, _, session = gs_with_driver
        holdings = [
            {"symbol": "JPY.CASH", "shares": 1000000, "cost_price": 1},
            {"symbol": "7203.T", "shares": 100, "cost_price": 2850},
        ]
        with patch.object(gs, "_get_mode", return_value="full"):
            result = gs.sync_portfolio(holdings)
        assert result is True
        # Portfolio MERGE + 1 stock MERGE + 1 HOLDS MERGE + 1 stale DELETE = 4
        assert session.run.call_count == 4

    def test_empty_holdings(self, gs_with_driver):
        """Empty holdings should delete all HOLDS relationships."""
        gs, _, session = gs_with_driver
        with patch.object(gs, "_get_mode", return_value="full"):
            result = gs.sync_portfolio([])
        assert result is True
        # Portfolio MERGE + 1 delete-all-HOLDS = 2
        assert session.run.call_count == 2

    def test_no_driver(self):
        """Returns False when no driver available."""
        import src.data.graph_store as gs
        with patch("src.data.graph_store._get_driver", return_value=None):
            assert gs.sync_portfolio([{"symbol": "AAPL"}]) is False

    def test_mode_off(self, gs_with_driver):
        """Returns False when NEO4J_MODE is off."""
        gs, _, session = gs_with_driver
        with patch.object(gs, "_get_mode", return_value="off"):
            assert gs.sync_portfolio([{"symbol": "AAPL"}]) is False
        assert session.run.call_count == 0

    def test_error_handling(self, gs_with_driver):
        """Returns False on database error."""
        gs, driver, session = gs_with_driver
        session.run.side_effect = Exception("DB error")
        with patch.object(gs, "_get_mode", return_value="full"):
            assert gs.sync_portfolio([{"symbol": "AAPL"}]) is False


# ===================================================================
# is_held tests
# ===================================================================

class TestIsHeld:
    def test_held(self, gs_with_driver):
        """Returns True when stock is held."""
        gs, _, session = gs_with_driver
        mock_result = MagicMock()
        mock_result.single.return_value = {"cnt": 1}
        session.run.return_value = mock_result
        assert gs.is_held("7203.T") is True

    def test_not_held(self, gs_with_driver):
        """Returns False when stock is not held."""
        gs, _, session = gs_with_driver
        mock_result = MagicMock()
        mock_result.single.return_value = {"cnt": 0}
        session.run.return_value = mock_result
        assert gs.is_held("NVDA") is False

    def test_no_driver(self):
        """Returns False when no driver available."""
        import src.data.graph_store as gs
        with patch("src.data.graph_store._get_driver", return_value=None):
            assert gs.is_held("AAPL") is False

    def test_error_handling(self, gs_with_driver):
        """Returns False on database error."""
        gs, _, session = gs_with_driver
        session.run.side_effect = Exception("DB error")
        assert gs.is_held("AAPL") is False


# ===================================================================
# get_held_symbols tests
# ===================================================================

class TestGetHeldSymbols:
    def test_success(self, gs_with_driver):
        """Returns list of held symbols."""
        gs, _, session = gs_with_driver
        session.run.return_value = [
            {"symbol": "7203.T"},
            {"symbol": "AAPL"},
        ]
        result = gs.get_held_symbols()
        assert result == ["7203.T", "AAPL"]

    def test_no_driver(self):
        """Returns empty list when no driver available."""
        import src.data.graph_store as gs
        with patch("src.data.graph_store._get_driver", return_value=None):
            assert gs.get_held_symbols() == []

    def test_error_handling(self, gs_with_driver):
        """Returns empty list on database error."""
        gs, _, session = gs_with_driver
        session.run.side_effect = Exception("DB error")
        assert gs.get_held_symbols() == []


# ===================================================================
# extract_cash_currencies / merge_cash_balance tests (KIK-736)
# ===================================================================

class TestExtractCashCurrencies:
    """cash_balance.json は通貨・メタデータ・派生値が同じ階層に混ざっている."""

    def test_real_file_shape(self):
        import src.data.graph_store as gs
        balances = {
            "JPY": 6296491,
            "updated_at": "2026-08-04T18:30:00",
            "balance_jpy": 6296491,
            "last_updated": "2026-08-04",
            "memo": "8/4寄付き一斉約定 7件目",
        }
        assert gs.extract_cash_currencies(balances) == {"JPY": 6296491.0}

    def test_balance_jpy_is_not_a_currency(self):
        """balance_jpy は JPY の重複。通貨として数えると二重計上になる."""
        import src.data.graph_store as gs
        assert "balance_jpy" not in gs.extract_cash_currencies({"balance_jpy": 100})

    def test_multi_currency(self):
        import src.data.graph_store as gs
        result = gs.extract_cash_currencies({"JPY": 100, "USD": 2996.9, "EUR": "50"})
        assert result == {"JPY": 100.0, "USD": 2996.9, "EUR": 50.0}

    def test_lowercase_and_wrong_length_keys_ignored(self):
        import src.data.graph_store as gs
        assert gs.extract_cash_currencies({"jpy": 1, "JPYY": 2, "JP": 3}) == {}

    def test_non_numeric_value_dropped(self):
        import src.data.graph_store as gs
        assert gs.extract_cash_currencies({"JPY": "n/a", "USD": 5}) == {"USD": 5.0}


class TestMergeCashBalance:
    def test_sets_prefixed_properties_on_portfolio(self, gs_with_driver):
        gs, _, session = gs_with_driver
        with patch.object(gs, "_get_mode", return_value="full"):
            assert gs.merge_cash_balance("2026-08-04", {"JPY": 6296491, "USD": 2996.9}) is True
        props = session.run.call_args.kwargs["props"]
        assert props == {"cash_jpy": 6296491.0, "cash_usd": 2996.9,
                         "cash_updated_at": "2026-08-04"}

    def test_merges_portfolio_anchor(self, gs_with_driver):
        """Portfolio ノードが無い状態でも作られる（MERGE）."""
        gs, _, session = gs_with_driver
        session.run.return_value.single.return_value = {"ks": []}
        with patch.object(gs, "_get_mode", return_value="full"):
            gs.merge_cash_balance("2026-08-04", {"JPY": 1})
        cyphers = [c.args[0] for c in session.run.call_args_list]
        assert any("MERGE (p:Portfolio {name: 'default'})" in c for c in cyphers)
        assert any("SET p += $props" in c for c in cyphers)

    def test_stale_currency_property_removed(self, gs_with_driver):
        """USD を使い切って JSON から消しても cash_usd が残ると過大計上する (KIK-737)."""
        gs, _, session = gs_with_driver
        session.run.return_value.single.return_value = {
            "ks": ["cash_jpy", "cash_usd", "cash_updated_at"]
        }
        with patch.object(gs, "_get_mode", return_value="full"):
            assert gs.merge_cash_balance("2026-08-04", {"JPY": 100}) is True
        removes = [c.args[0] for c in session.run.call_args_list if "REMOVE" in c.args[0]]
        assert len(removes) == 1
        assert "cash_usd" in removes[0]
        # 今回書き直すキーは消さない
        assert "cash_jpy" not in removes[0]
        assert "cash_updated_at" not in removes[0]

    def test_no_stale_property_means_no_remove_query(self, gs_with_driver):
        gs, _, session = gs_with_driver
        session.run.return_value.single.return_value = {"ks": ["cash_jpy"]}
        with patch.object(gs, "_get_mode", return_value="full"):
            gs.merge_cash_balance("2026-08-04", {"JPY": 100})
        assert not [c for c in session.run.call_args_list if "REMOVE" in c.args[0]]

    def test_only_cash_prefixed_properties_are_scanned(self, gs_with_driver):
        """name など cash_ 以外を巻き込むと Portfolio ノードが壊れる."""
        gs, _, session = gs_with_driver
        session.run.return_value.single.return_value = {"ks": ["cash_usd"]}
        with patch.object(gs, "_get_mode", return_value="full"):
            gs.merge_cash_balance("2026-08-04", {"JPY": 100})
        joined = " ".join(c.args[0] for c in session.run.call_args_list)
        assert "STARTS WITH 'cash_'" in joined
        removes = [c.args[0] for c in session.run.call_args_list if "REMOVE" in c.args[0]]
        # REMOVE 句に載るのは cash_ 始まりだけ（`{name: 'default'}` は MATCH 側なので
        # 素朴に "name" を探すと必ず引っかかる。プロパティ参照の形で見る）
        assert removes
        removed_props = removes[0].split("REMOVE", 1)[1]
        assert "p.`name`" not in removed_props
        assert "p.`cash_usd`" in removed_props

    def test_injection_shaped_property_name_is_ignored(self, gs_with_driver):
        """keys(p) 由来でもプロパティ名を素で埋め込むので形を検証する."""
        gs, _, session = gs_with_driver
        session.run.return_value.single.return_value = {
            "ks": ["cash_usd", "cash_x` DETACH DELETE p //"]
        }
        with patch.object(gs, "_get_mode", return_value="full"):
            gs.merge_cash_balance("2026-08-04", {"JPY": 100})
        removes = [c.args[0] for c in session.run.call_args_list if "REMOVE" in c.args[0]]
        assert removes and "DETACH DELETE" not in removes[0]
        assert "cash_usd" in removes[0]

    def test_no_currency_returns_false_without_writing(self, gs_with_driver):
        gs, _, session = gs_with_driver
        with patch.object(gs, "_get_mode", return_value="full"):
            assert gs.merge_cash_balance("2026-08-04", {"memo": "x"}) is False
        session.run.assert_not_called()

    def test_mode_off(self, gs_with_driver):
        gs, _, _ = gs_with_driver
        with patch.object(gs, "_get_mode", return_value="off"):
            assert gs.merge_cash_balance("2026-08-04", {"JPY": 1}) is False

    def test_no_driver(self):
        import src.data.graph_store as gs
        with patch.object(gs, "_get_mode", return_value="full"), \
             patch("src.data.graph_store._get_driver", return_value=None):
            assert gs.merge_cash_balance("2026-08-04", {"JPY": 1}) is False

    def test_error_handling(self, gs_with_driver):
        gs, _, session = gs_with_driver
        session.run.side_effect = Exception("DB error")
        with patch.object(gs, "_get_mode", return_value="full"):
            assert gs.merge_cash_balance("2026-08-04", {"JPY": 1}) is False


class TestSyncStockFullDelegatesTrades:
    """取引レコード → Trade の変換を1箇所に寄せた (KIK-740)."""

    def test_delegates_to_graph_sync(self, tmp_path, monkeypatch):
        import json as _json

        d = tmp_path / "data" / "history" / "trade"
        d.mkdir(parents=True)
        (d / "t.json").write_text(_json.dumps(
            [{"date": "2026-08-01", "action": "buy", "symbol": "7203.T",
              "shares": 100, "price": 2000},
             {"date": "2026-08-02", "action": "buy", "symbol": "OTHER",
              "shares": 1, "price": 1}]), encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        import src.data.graph_store as gs
        client = MagicMock()
        client.get_stock_info.return_value = None      # 1. の yfinance をスキップ
        with patch("src.data.graph_sync._sync_trade", return_value=True) as m, \
             patch.object(gs, "_get_mode", return_value="full"), \
             patch("src.data.graph_query.community.update_stock_community",
                   return_value=None):
            result = gs.sync_stock_full("7203.T", client=client)
        # 対象銘柄のレコードだけを委譲する
        assert m.call_count == 1
        assert m.call_args.args[0]["symbol"] == "7203.T"
        assert result["trades"] == 1
