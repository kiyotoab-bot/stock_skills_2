"""Tests for 日本語社名の取得 — KIK-758.

yfinance は英語表記しか返さない（"CANON INC" / "TOSO CO LTD"）。
レポートの日本語名は手で書いていたが、それでは書き間違えても誰も気づかない
（実際「日立」と書いていたが正しくは「日立製作所」だった）。
J-Quants の上場銘柄一覧を一次情報にする。
"""

import pytest

from src.data.jquants_client import listed


@pytest.fixture(autouse=True)
def _clear_cache():
    listed.reset_cache()
    yield
    listed.reset_cache()


def _stub_master(monkeypatch, rows):
    class _DF:
        def __init__(self, rows):
            self._rows = rows

        def to_dict(self, orient):
            return self._rows

    class _Client:
        def get_list(self):
            return _DF(rows)

    monkeypatch.setattr("src.data.jquants_client._client.get_client", lambda: _Client())


_ROWS = [
    {"Code": "77510", "CoName": "キヤノン", "CoNameEn": "CANON INC",
     "S33Nm": "電気機器", "S17Nm": "電機・精密", "MktNm": "プライム",
     "ScaleCat": "TOPIX Large70"},
    {"Code": "59560", "CoName": "トーソー", "CoNameEn": "TOSO CO LTD",
     "S33Nm": "金属製品", "S17Nm": "鉄鋼・非鉄", "MktNm": "スタンダード",
     "ScaleCat": "-"},
]


class TestCompanyNames:
    def test_returns_japanese_name(self, monkeypatch):
        _stub_master(monkeypatch, _ROWS)
        assert listed.get_company_name("7751.T") == "キヤノン"

    @pytest.mark.parametrize("symbol", ["7751.T", "7751", "77510"])
    def test_symbol_forms_are_normalised(self, monkeypatch, symbol):
        _stub_master(monkeypatch, _ROWS)
        assert listed.get_company_name(symbol) == "キヤノン"

    def test_batch_lookup(self, monkeypatch):
        _stub_master(monkeypatch, _ROWS)
        got = listed.get_company_names(["7751.T", "5956.T"])
        assert got == {"7751.T": "キヤノン", "5956.T": "トーソー"}

    def test_unknown_symbol_falls_back_to_symbol(self, monkeypatch):
        """空文字を返すと銘柄名が消えたレポートが出る。symbol で識別は残す。"""
        _stub_master(monkeypatch, _ROWS)
        assert listed.get_company_name("AAPL") == "AAPL"
        assert listed.get_company_names(["9999.T"]) == {"9999.T": "9999.T"}

    def test_keys_are_the_input_symbols(self, monkeypatch):
        """呼び出し側は元の symbol で引く。正規化後のコードでは引けない。"""
        _stub_master(monkeypatch, _ROWS)
        got = listed.get_company_names(["7751.T"])
        assert "7751.T" in got and "7751" not in got


class TestListedInfo:
    def test_full_record(self, monkeypatch):
        _stub_master(monkeypatch, _ROWS)
        i = listed.get_listed_info("7751.T")
        assert i["name_ja"] == "キヤノン"
        assert i["name_en"] == "CANON INC"
        assert i["sector33"] == "電気機器"
        assert i["market"] == "プライム"
        assert i["scale"] == "TOPIX Large70"

    def test_unknown_returns_empty_dict(self, monkeypatch):
        _stub_master(monkeypatch, _ROWS)
        assert listed.get_listed_info("9999.T") == {}

    def test_returned_dict_is_a_copy(self, monkeypatch):
        """呼び出し側が書き換えてもキャッシュを壊さない。"""
        _stub_master(monkeypatch, _ROWS)
        first = listed.get_listed_info("7751.T")
        first["name_ja"] = "書き換え"
        assert listed.get_listed_info("7751.T")["name_ja"] == "キヤノン"


class TestGracefulDegradation:
    def test_client_unavailable_falls_back(self, monkeypatch):
        """J-Quants 未設定でもレポートは出す。"""
        monkeypatch.setattr("src.data.jquants_client._client.get_client", lambda: None)
        assert listed.get_company_name("7751.T") == "7751.T"

    def test_api_error_falls_back(self, monkeypatch):
        def _boom():
            raise RuntimeError("network down")
        monkeypatch.setattr("src.data.jquants_client._client.get_client", _boom)
        assert listed.get_company_names(["7751.T"]) == {"7751.T": "7751.T"}

    def test_missing_code_column_is_skipped(self, monkeypatch):
        _stub_master(monkeypatch, [{"CoName": "コード無し"}] + _ROWS)
        assert listed.get_company_name("7751.T") == "キヤノン"


class TestCaching:
    def test_master_is_fetched_once(self, monkeypatch):
        """4,443銘柄を毎回引かない。"""
        calls = []

        class _DF:
            def to_dict(self, orient):
                return _ROWS

        class _Client:
            def get_list(self):
                calls.append(1)
                return _DF()

        monkeypatch.setattr("src.data.jquants_client._client.get_client",
                            lambda: _Client())
        listed.get_company_name("7751.T")
        listed.get_company_name("5956.T")
        listed.get_listed_info("7751.T")
        assert len(calls) == 1

    def test_reset_cache_refetches(self, monkeypatch):
        calls = []

        class _DF:
            def to_dict(self, orient):
                return _ROWS

        class _Client:
            def get_list(self):
                calls.append(1)
                return _DF()

        monkeypatch.setattr("src.data.jquants_client._client.get_client",
                            lambda: _Client())
        listed.get_company_name("7751.T")
        listed.reset_cache()
        listed.get_company_name("7751.T")
        assert len(calls) == 2
