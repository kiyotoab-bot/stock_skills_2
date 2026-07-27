"""Tests for src/data/edinet_client/."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.no_auto_mock

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# E22222 appears both as issuerEdinetCode (target in row0) and as a filer (row3)
# so observe() will populate the learned map with its name/secCode.
_DOC_LIST_RESPONSE = {
    "metadata": {
        "title": "提出書類一覧",
        "parameter": {"date": "2026-04-30", "type": "2"},
        "resultset": {"count": 4},
        "processDateTime": "2026-04-30 10:00:00",
        "status": "200",
        "message": "OK",
    },
    "results": [
        {
            "seqNumber": 1,
            "docID": "S100AAAA",
            "edinetCode": "E11111",
            "secCode": "8604",
            "filerName": "野村證券株式会社",
            "fundCode": None,
            "operatorDate": "2026-04-30",
            "submitDateTime": "2026-04-30 09:00:00",
            "docDescription": "大量保有報告書",
            "issuerEdinetCode": "E22222",
            "subjectEdinetCode": None,
            "withdrawalStatus": "0",
            "pdfFlag": "1",
            "xbrlFlag": "1",
            "csvFlag": "1",
        },
        {
            "seqNumber": 2,
            "docID": "S100BBBB",
            "edinetCode": "E33333",
            "secCode": None,
            "filerName": "テスト投資顧問",
            "fundCode": None,
            "operatorDate": "2026-04-30",
            "submitDateTime": "2026-04-30 10:00:00",
            "docDescription": "変更報告書",
            "issuerEdinetCode": "E44444",
            "subjectEdinetCode": None,
            "withdrawalStatus": "0",
            "pdfFlag": "1",
            "xbrlFlag": "0",
            "csvFlag": "0",
        },
        {
            "seqNumber": 3,
            "docID": "S100CCCC",
            "edinetCode": "E55555",
            "secCode": None,
            "filerName": "テスト有価証券",
            "fundCode": None,
            "operatorDate": "2026-04-30",
            "submitDateTime": "2026-04-30 11:00:00",
            "docDescription": "有価証券報告書",
            "issuerEdinetCode": "E66666",
            "subjectEdinetCode": None,
            "withdrawalStatus": "0",
            "pdfFlag": "1",
            "xbrlFlag": "1",
            "csvFlag": "0",
        },
        {
            # E22222 files its own report → observe() learns its name/secCode
            "seqNumber": 4,
            "docID": "S100DDDD",
            "edinetCode": "E22222",
            "secCode": "5401",
            "filerName": "日本製鉄株式会社",
            "fundCode": None,
            "operatorDate": "2026-04-30",
            "submitDateTime": "2026-04-30 08:00:00",
            "docDescription": "内部統制報告書",
            "issuerEdinetCode": None,
            "subjectEdinetCode": None,
            "withdrawalStatus": "0",
            "pdfFlag": "0",
            "xbrlFlag": "1",
            "csvFlag": "0",
        },
    ],
}


def _mock_requests_get(url, **kwargs):
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    if "documents.json" in url:
        mock_resp.json.return_value = _DOC_LIST_RESPONSE
    else:
        mock_resp.json.return_value = {}
        mock_resp.content = b""
    return mock_resp


def _reset_company_map():
    """テスト前に学習マップをリセット（ファイルI/Oをスキップ）。"""
    import src.data.edinet_client._company as cm
    cm._learned_map = {}
    cm._map_loaded = True
    cm._map_dirty = False


# ---------------------------------------------------------------------------
# TestIsAvailable
# ---------------------------------------------------------------------------

class TestIsAvailable:
    def test_available_with_key(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key-123")
        from src.data.edinet_client._common import is_available
        assert is_available() is True

    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("EDINET_API_KEY", raising=False)
        from src.data.edinet_client._common import is_available
        assert is_available() is False


# ---------------------------------------------------------------------------
# TestGetDocumentList
# ---------------------------------------------------------------------------

class TestGetDocumentList:
    def setup_method(self):
        _reset_company_map()

    def test_returns_results(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_document_list
            docs = get_document_list("2026-04-30")

        assert len(docs) == 4
        assert docs[0]["docID"] == "S100AAAA"

    def test_returns_empty_without_api_key(self, monkeypatch):
        monkeypatch.delenv("EDINET_API_KEY", raising=False)
        from src.data.edinet_client._cache import clear
        clear()

        from src.data.edinet_client.documents import get_document_list
        docs = get_document_list("2026-04-30")
        assert docs == []

    def test_cached_second_call(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        call_count = 0

        def counting_get(url, **kwargs):
            nonlocal call_count
            if "documents.json" in url:
                call_count += 1
            return _mock_requests_get(url, **kwargs)

        with patch("src.data.edinet_client._common.requests.get", side_effect=counting_get):
            from src.data.edinet_client.documents import get_document_list
            get_document_list("2026-04-30")
            get_document_list("2026-04-30")

        assert call_count == 1

    def test_returns_empty_on_error(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get",
                   side_effect=ConnectionError("offline")):
            from src.data.edinet_client.documents import get_document_list
            docs = get_document_list("2026-04-30")

        assert docs == []


# ---------------------------------------------------------------------------
# TestGetLargeShareholding
# ---------------------------------------------------------------------------

class TestGetLargeShareholding:
    def setup_method(self):
        _reset_company_map()

    def test_filters_large_shareholding(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_large_shareholding
            result = get_large_shareholding("2026-04-30")

        # 大量保有報告書 + 変更報告書 の2件のみ
        assert result["count"] == 2
        assert result["available"] is True
        assert result["error"] is None

    def test_filing_schema(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_large_shareholding
            result = get_large_shareholding("2026-04-30")

        filing = result["filings"][0]
        assert "doc_id" in filing
        assert "filer_edinet" in filing
        assert "target_edinet" in filing
        assert "submit_time" in filing
        assert "doc_type" in filing
        assert "pdf_flag" in filing

    def test_unavailable_without_key(self, monkeypatch):
        monkeypatch.delenv("EDINET_API_KEY", raising=False)
        from src.data.edinet_client._cache import clear
        clear()

        from src.data.edinet_client.documents import get_large_shareholding
        result = get_large_shareholding("2026-04-30")

        assert result["available"] is False
        assert result["count"] == 0
        assert "EDINET_API_KEY" in (result["error"] or "")

    def test_uses_today_when_no_date(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_large_shareholding
            result = get_large_shareholding()

        assert result["date"] is not None


# ---------------------------------------------------------------------------
# TestCompanyLookup
# ---------------------------------------------------------------------------

class TestCompanyLookup:
    def setup_method(self):
        _reset_company_map()

    def test_observe_and_lookup(self):
        from src.data.edinet_client._company import observe, lookup
        observe("E22222", "日本製鉄株式会社", "5401")
        info = lookup("E22222")
        assert info["name"] == "日本製鉄株式会社"
        assert info["securities_code"] == "5401"
        assert info["ticker"] == "5401.T"

    def test_lookup_unknown_code_returns_none(self):
        from src.data.edinet_client._company import lookup
        info = lookup("E99999")
        assert info["name"] is None
        assert info["ticker"] is None

    def test_lookup_none_returns_empty(self):
        from src.data.edinet_client._company import lookup
        info = lookup(None)
        assert info["name"] is None

    def test_filer_name_from_api_response(self, monkeypatch):
        """filer_name はAPIレスポンスのfilerNameフィールドから取得される。"""
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_large_shareholding
            result = get_large_shareholding("2026-04-30")

        first = result["filings"][0]
        # E11111 の filerName は API レスポンスから直接取得
        assert first["filer_name"] == "野村證券株式会社"
        # E22222 は同日に自社書類を提出したので learned map に登録済み
        assert first["target_name"] == "日本製鉄株式会社"
        assert first["target_ticker"] == "5401.T"


# ---------------------------------------------------------------------------
# TestGetDisclosures
# ---------------------------------------------------------------------------

class TestGetDisclosures:
    def setup_method(self):
        _reset_company_map()

    def test_keyword_filter(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_disclosures
            result = get_disclosures("2026-04-30", keyword="有価証券報告書")

        assert result["count"] == 1
        assert result["filings"][0]["doc_id"] == "S100CCCC"

    def test_ticker_filter(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_disclosures
            # 5401.T = E22222 が issuerEdinetCode の書類
            result = get_disclosures("2026-04-30", ticker="5401.T")

        assert result["count"] == 1
        assert result["filings"][0]["target_ticker"] == "5401.T"

    def test_no_filter_returns_all(self, monkeypatch):
        monkeypatch.setenv("EDINET_API_KEY", "test-key")
        from src.data.edinet_client._cache import clear
        clear()

        with patch("src.data.edinet_client._common.requests.get", side_effect=_mock_requests_get):
            from src.data.edinet_client.documents import get_disclosures
            result = get_disclosures("2026-04-30")

        assert result["count"] == 4
