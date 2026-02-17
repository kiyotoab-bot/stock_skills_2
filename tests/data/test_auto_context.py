"""Tests for src.data.auto_context module (KIK-411).

All graph_store/graph_query functions are mocked — no Neo4j dependency.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.data.auto_context import (
    _check_bookmarked,
    _days_since,
    _extract_symbol,
    _format_context,
    _format_market_context,
    _has_bought_not_sold,
    _has_concern_notes,
    _has_exit_alert,
    _has_recent_research,
    _is_market_query,
    _is_portfolio_query,
    _recommend_skill,
    _resolve_symbol,
    _screening_count,
    _thesis_needs_review,
    get_context,
)


# ===================================================================
# Symbol extraction tests
# ===================================================================

class TestExtractSymbol:
    def test_jp_ticker(self):
        assert _extract_symbol("7203.Tってどう？") == "7203.T"

    def test_us_ticker(self):
        assert _extract_symbol("AAPLを調べて") == "AAPL"

    def test_sg_ticker(self):
        assert _extract_symbol("D05.SIの状況は？") == "D05.SI"

    def test_no_symbol(self):
        assert _extract_symbol("トヨタの状況は？") is None

    def test_embedded_in_sentence(self):
        assert _extract_symbol("最近の7203.Tはどうなっている？") == "7203.T"


# ===================================================================
# Keyword detection tests
# ===================================================================

class TestKeywordDetection:
    def test_market_query_jp(self):
        assert _is_market_query("今日の相場は？") is True

    def test_market_query_en(self):
        assert _is_market_query("market overview") is True

    def test_market_query_negative(self):
        assert _is_market_query("トヨタってどう？") is False

    def test_portfolio_query_jp(self):
        assert _is_portfolio_query("ポートフォリオ大丈夫？") is True

    def test_portfolio_query_short(self):
        assert _is_portfolio_query("PF確認して") is True

    def test_portfolio_query_negative(self):
        assert _is_portfolio_query("AAPLを調べて") is False


# ===================================================================
# Graph state analysis helpers
# ===================================================================

class TestDaysSince:
    def test_today(self):
        assert _days_since(date.today().isoformat()) == 0

    def test_yesterday(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        assert _days_since(yesterday) == 1

    def test_invalid_date(self):
        assert _days_since("not-a-date") == 9999

    def test_none(self):
        assert _days_since(None) == 9999


class TestHasBoughtNotSold:
    def test_bought_only(self):
        history = {"trades": [{"type": "buy", "shares": 100}]}
        assert _has_bought_not_sold(history) is True

    def test_bought_and_sold_equal(self):
        history = {"trades": [
            {"type": "buy", "shares": 100},
            {"type": "sell", "shares": 100},
        ]}
        assert _has_bought_not_sold(history) is False

    def test_no_trades(self):
        assert _has_bought_not_sold({}) is False
        assert _has_bought_not_sold({"trades": []}) is False

    def test_multiple_buys_partial_sell(self):
        history = {"trades": [
            {"type": "buy", "shares": 100},
            {"type": "buy", "shares": 200},
            {"type": "sell", "shares": 100},
        ]}
        assert _has_bought_not_sold(history) is True


class TestScreeningCount:
    def test_zero(self):
        assert _screening_count({}) == 0
        assert _screening_count({"screens": []}) == 0

    def test_multiple(self):
        history = {"screens": [
            {"date": "2026-01-01"},
            {"date": "2026-01-15"},
            {"date": "2026-02-01"},
        ]}
        assert _screening_count(history) == 3


class TestHasRecentResearch:
    def test_recent(self):
        today = date.today().isoformat()
        history = {"researches": [{"date": today, "research_type": "stock"}]}
        assert _has_recent_research(history, 7) is True

    def test_old(self):
        old_date = (date.today() - timedelta(days=30)).isoformat()
        history = {"researches": [{"date": old_date}]}
        assert _has_recent_research(history, 7) is False

    def test_empty(self):
        assert _has_recent_research({}, 7) is False


class TestHasExitAlert:
    def test_no_health_checks(self):
        assert _has_exit_alert({}) is False
        assert _has_exit_alert({"health_checks": []}) is False

    def test_health_check_with_recent_lesson(self):
        today = date.today().isoformat()
        history = {
            "health_checks": [{"date": today}],
            "notes": [{"type": "lesson", "date": today}],
        }
        assert _has_exit_alert(history) is True

    def test_health_check_without_lesson(self):
        today = date.today().isoformat()
        history = {
            "health_checks": [{"date": today}],
            "notes": [],
        }
        assert _has_exit_alert(history) is False


class TestThesisNeedsReview:
    def test_old_thesis(self):
        old_date = (date.today() - timedelta(days=100)).isoformat()
        history = {"notes": [{"type": "thesis", "date": old_date}]}
        assert _thesis_needs_review(history, 90) is True

    def test_recent_thesis(self):
        recent_date = (date.today() - timedelta(days=30)).isoformat()
        history = {"notes": [{"type": "thesis", "date": recent_date}]}
        assert _thesis_needs_review(history, 90) is False

    def test_no_thesis(self):
        history = {"notes": [{"type": "observation", "date": "2026-01-01"}]}
        assert _thesis_needs_review(history, 90) is False


class TestHasConcernNotes:
    def test_has_concern(self):
        history = {"notes": [{"type": "concern", "content": "PER低すぎ"}]}
        assert _has_concern_notes(history) is True

    def test_no_concern(self):
        history = {"notes": [{"type": "thesis"}]}
        assert _has_concern_notes(history) is False

    def test_empty(self):
        assert _has_concern_notes({}) is False


# ===================================================================
# Skill recommendation tests
# ===================================================================

class TestRecommendSkill:
    def test_holding_stock(self):
        """保有銘柄 → health 推奨"""
        history = {"trades": [{"type": "buy", "shares": 100}]}
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "health"
        assert rel == "保有"

    def test_holding_with_old_thesis(self):
        """保有 + テーゼ3ヶ月経過 → health + レビュー促し"""
        old_date = (date.today() - timedelta(days=100)).isoformat()
        history = {
            "trades": [{"type": "buy", "shares": 100}],
            "notes": [{"type": "thesis", "date": old_date}],
        }
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "health"
        assert "レビュー" in reason

    def test_exit_alert(self):
        """EXIT判定 → screen_alternative"""
        today = date.today().isoformat()
        history = {
            "health_checks": [{"date": today}],
            "notes": [{"type": "lesson", "date": today}],
        }
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "screen_alternative"

    def test_bookmarked(self):
        """ウォッチ中 → report"""
        history = {}
        skill, reason, rel = _recommend_skill(history, True)
        assert skill == "report"
        assert rel == "ウォッチ中"

    def test_frequent_screening(self):
        """3回以上スクリーニング → report + 注目"""
        history = {"screens": [
            {"date": "2026-01-01"},
            {"date": "2026-01-15"},
            {"date": "2026-02-01"},
        ]}
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "report"
        assert rel == "注目"

    def test_recent_research(self):
        """直近リサーチ済み → report_diff"""
        today = date.today().isoformat()
        history = {"researches": [{"date": today}]}
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "report_diff"
        assert rel == "リサーチ済"

    def test_concern_notes(self):
        """懸念メモあり → report"""
        history = {"notes": [{"type": "concern"}]}
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "report"
        assert rel == "懸念あり"

    def test_known_stock(self):
        """過去データあり → report"""
        history = {"reports": [{"date": "2026-01-01"}]}
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "report"
        assert rel == "既知"

    def test_unknown_stock(self):
        """未知の銘柄 → report"""
        history = {}
        skill, reason, rel = _recommend_skill(history, False)
        assert skill == "report"
        assert rel == "未知"


# ===================================================================
# Context formatting tests
# ===================================================================

class TestFormatContext:
    def test_with_data(self):
        """履歴あり → screens/reports/trades が含まれる"""
        history = {
            "screens": [{"date": "2026-02-14", "preset": "alpha", "region": "jp"}],
            "reports": [{"date": "2026-02-16", "score": 75, "verdict": "割安"}],
            "trades": [{"date": "2026-02-16", "type": "buy", "shares": 100, "price": 2850}],
            "health_checks": [],
            "notes": [],
            "themes": ["EV", "自動車"],
            "researches": [],
        }
        md = _format_context("7203.T", history, "health", "保有", "保有")
        assert "7203.T" in md
        assert "alpha" in md
        assert "スコア 75" in md
        assert "購入" in md
        assert "EV" in md

    def test_empty_history(self):
        """空の履歴 → 過去データなし"""
        history = {}
        md = _format_context("AAPL", history, "report", "未知", "未知")
        assert "AAPL" in md
        assert "過去データなし" in md

    def test_notes_truncated(self):
        """長いメモ → 50文字に切り詰め"""
        history = {"notes": [{"type": "thesis", "content": "A" * 100}]}
        md = _format_context("7203.T", history, "report", "既知", "既知")
        assert "A" * 50 in md
        assert "A" * 51 not in md


class TestFormatMarketContext:
    def test_basic(self):
        mc = {
            "date": "2026-02-17",
            "indices": [
                {"name": "日経225", "price": 38500},
                {"name": "S&P 500", "price": 5200},
            ],
        }
        md = _format_market_context(mc)
        assert "市況コンテキスト" in md
        assert "日経225" in md
        assert "38500" in md

    def test_empty_indices(self):
        mc = {"date": "2026-02-17", "indices": []}
        md = _format_market_context(mc)
        assert "2026-02-17" in md


# ===================================================================
# Resolve symbol (with Neo4j mock)
# ===================================================================

class TestResolveSymbol:
    def test_direct_ticker(self):
        """ティッカーパターンがあれば Neo4j 照会不要"""
        assert _resolve_symbol("7203.Tってどう？") == "7203.T"

    @patch("src.data.auto_context.graph_store")
    def test_name_lookup_found(self, mock_gs):
        """企業名 → Neo4j 逆引きで見つかる"""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_record = {"symbol": "7203.T"}
        mock_session.run.return_value.single.return_value = mock_record
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_gs._get_driver.return_value = mock_driver

        result = _resolve_symbol("トヨタの状況は？")
        assert result == "7203.T"

    @patch("src.data.auto_context.graph_store")
    def test_name_lookup_not_found(self, mock_gs):
        """企業名 → Neo4j に無い → None"""
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = None
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_gs._get_driver.return_value = mock_driver

        result = _resolve_symbol("謎の会社の状況は？")
        assert result is None

    @patch("src.data.auto_context.graph_store")
    def test_neo4j_unavailable(self, mock_gs):
        """Neo4j 未接続 → None"""
        mock_gs._get_driver.return_value = None
        result = _resolve_symbol("トヨタの状況は？")
        assert result is None


# ===================================================================
# Check bookmarked (with Neo4j mock)
# ===================================================================

class TestCheckBookmarked:
    @patch("src.data.auto_context.graph_store")
    def test_bookmarked(self, mock_gs):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = {"cnt": 1}
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_gs._get_driver.return_value = mock_driver

        assert _check_bookmarked("7203.T") is True

    @patch("src.data.auto_context.graph_store")
    def test_not_bookmarked(self, mock_gs):
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_session.run.return_value.single.return_value = {"cnt": 0}
        mock_driver.session.return_value.__enter__ = lambda s: mock_session
        mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)
        mock_gs._get_driver.return_value = mock_driver

        assert _check_bookmarked("7203.T") is False

    @patch("src.data.auto_context.graph_store")
    def test_neo4j_unavailable(self, mock_gs):
        mock_gs._get_driver.return_value = None
        assert _check_bookmarked("7203.T") is False


# ===================================================================
# get_context integration tests (all mocked)
# ===================================================================

class TestGetContext:
    @patch("src.data.auto_context.graph_query")
    def test_market_query(self, mock_gq):
        """市況クエリ → market-research 推奨"""
        mock_gq.get_recent_market_context.return_value = {
            "date": "2026-02-17",
            "indices": [{"name": "日経225", "price": 38500}],
        }
        result = get_context("今日の相場は？")
        assert result is not None
        assert result["recommended_skill"] == "market-research"
        assert result["relationship"] == "市況"
        assert "日経225" in result["context_markdown"]

    @patch("src.data.auto_context.graph_query")
    def test_market_query_no_data(self, mock_gq):
        """市況クエリ + データなし → None"""
        mock_gq.get_recent_market_context.return_value = None
        result = get_context("相場どう？")
        assert result is None

    @patch("src.data.auto_context.graph_query")
    def test_portfolio_query(self, mock_gq):
        """PFクエリ → health 推奨"""
        mock_gq.get_recent_market_context.return_value = {
            "date": "2026-02-17",
        }
        result = get_context("PF大丈夫？")
        assert result is not None
        assert result["recommended_skill"] == "health"
        assert result["relationship"] == "PF"

    @patch("src.data.auto_context._check_bookmarked")
    @patch("src.data.auto_context.graph_store")
    def test_symbol_query_holding(self, mock_gs, mock_bookmark):
        """保有銘柄のクエリ → health 推奨"""
        mock_gs.is_available.return_value = True
        mock_gs.get_stock_history.return_value = {
            "trades": [{"type": "buy", "shares": 100}],
        }
        mock_bookmark.return_value = False

        result = get_context("7203.Tってどう？")
        assert result is not None
        assert result["symbol"] == "7203.T"
        assert result["recommended_skill"] == "health"
        assert result["relationship"] == "保有"

    @patch("src.data.auto_context._check_bookmarked")
    @patch("src.data.auto_context.graph_store")
    def test_symbol_query_unknown(self, mock_gs, mock_bookmark):
        """未知銘柄 → report 推奨"""
        mock_gs.is_available.return_value = True
        mock_gs.get_stock_history.return_value = {}
        mock_bookmark.return_value = False

        result = get_context("AAPLを調べて")
        assert result is not None
        assert result["symbol"] == "AAPL"
        assert result["recommended_skill"] == "report"
        assert result["relationship"] == "未知"

    def test_no_symbol_detected(self):
        """シンボル検出できない → None (Neo4j 照会もスキップ)"""
        # _lookup_symbol_by_name will try Neo4j but it's not available
        with patch("src.data.auto_context.graph_store") as mock_gs:
            mock_gs._get_driver.return_value = None
            result = get_context("今日はいい天気だ")
        assert result is None

    @patch("src.data.auto_context._check_bookmarked")
    @patch("src.data.auto_context.graph_store")
    def test_neo4j_unavailable(self, mock_gs, mock_bookmark):
        """Neo4j 未接続 → None"""
        mock_gs._get_driver.return_value = None  # for _resolve_symbol
        mock_gs.is_available.return_value = False

        result = get_context("7203.Tってどう？")
        # _extract_symbol finds the ticker, but is_available returns False
        assert result is None

    @patch("src.data.auto_context._check_bookmarked")
    @patch("src.data.auto_context.graph_store")
    def test_bookmarked_stock(self, mock_gs, mock_bookmark):
        """ウォッチ中 → report + ウォッチ中"""
        mock_gs.is_available.return_value = True
        mock_gs.get_stock_history.return_value = {}
        mock_bookmark.return_value = True

        result = get_context("7203.Tってどう？")
        assert result is not None
        assert result["recommended_skill"] == "report"
        assert result["relationship"] == "ウォッチ中"

    @patch("src.data.auto_context._check_bookmarked")
    @patch("src.data.auto_context.graph_store")
    def test_context_includes_all_fields(self, mock_gs, mock_bookmark):
        """返り値に必要な全フィールドが含まれる"""
        mock_gs.is_available.return_value = True
        mock_gs.get_stock_history.return_value = {}
        mock_bookmark.return_value = False

        result = get_context("AAPLの状況")
        assert result is not None
        assert "symbol" in result
        assert "context_markdown" in result
        assert "recommended_skill" in result
        assert "recommendation_reason" in result
        assert "relationship" in result
