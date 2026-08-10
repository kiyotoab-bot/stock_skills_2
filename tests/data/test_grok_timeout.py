"""Tests for the Grok timeout default and empty-response diagnostics — KIK-754.

2026-08-10 の日次で search_market が空の構造化フィールドを返し、
「JSON パースが壊れている」と診断した。実際はパースは正常で、
x_search/web_search 付きの呼び出しが実測 27〜30秒かかるのに
既定 timeout が 30 だったため境界上で落ちていた。

空で返るとき raw_response ごと消えるので、呼び出し側からは
「検索したが何も無かった」と区別できなかった。
"""

import inspect

import pytest

from src.data.grok_client import _common
from src.data.grok_client._common import _DEFAULT_TIMEOUT, _call_grok_api
from src.data.grok_client.market import search_market
from src.data.grok_client.stock import search_x_sentiment
from src.data.grok_client.industry import search_industry


class TestDefaultTimeout:
    def test_default_is_longer_than_observed_latency(self):
        """実測 27〜30秒。既定はそれを明確に上回ること。"""
        assert _DEFAULT_TIMEOUT >= 60

    def test_call_helper_uses_the_shared_default(self):
        assert inspect.signature(_call_grok_api).parameters["timeout"].default \
            == _DEFAULT_TIMEOUT

    @pytest.mark.parametrize("fn", [search_market, search_x_sentiment,
                                    search_industry])
    def test_search_functions_share_the_default(self, fn):
        """個別に 30 を書き戻すと、ここだけ再発する。"""
        assert inspect.signature(fn).parameters["timeout"].default == _DEFAULT_TIMEOUT

    def test_facade_defers_instead_of_redefining(self):
        """ファサードが独自の既定を持つと、下層を伸ばしても効かない。"""
        from tools.grok import search_market as facade
        assert inspect.signature(facade).parameters["timeout"].default is None


class TestEmptyResponseCarriesReason:
    def _stub_empty(self, monkeypatch, status):
        monkeypatch.setattr("src.data.grok_client.market._call_grok_api",
                            lambda *a, **k: "")
        monkeypatch.setattr("src.data.grok_client.market.get_error_status",
                            lambda: {"status": status, "status_code": None,
                                     "message": "stub"})

    def test_timeout_is_reported(self, monkeypatch):
        self._stub_empty(monkeypatch, "timeout")
        r = search_market("日経平均")
        assert r["error"]["status"] == "timeout"

    def test_ok_status_means_genuinely_no_data(self, monkeypatch):
        """タイムアウトと『検索したが何も無い』を呼び出し側が区別できること。"""
        self._stub_empty(monkeypatch, "ok")
        r = search_market("存在しない指数")
        assert r["error"]["status"] == "ok"
        assert r["price_action"] == ""

    def test_empty_result_keeps_the_schema(self, monkeypatch):
        self._stub_empty(monkeypatch, "timeout")
        r = search_market("日経平均")
        for key in ("price_action", "macro_factors", "sentiment",
                    "upcoming_events", "sector_rotation"):
            assert key in r


class TestParsingStillWorks:
    """パースは壊れていなかった（誤診の再発防止）。"""

    def test_json_after_prose_is_parsed(self, monkeypatch):
        raw = (
            "**日経平均（2026年8月10日）66,970.22円**\n\n"
            "前日比大幅上昇で反発。[[1]](https://example.com)\n\n"
            '{\n'
            '  "price_action": "66,970.22円（+2.08%）で大幅反発",\n'
            '  "macro_factors": ["米雇用統計が予想を下回る"],\n'
            '  "sentiment": {"score": 0.6, "summary": "強気優勢"},\n'
            '  "upcoming_events": ["米CPI"],\n'
            '  "sector_rotation": ["半導体へ資金集中"]\n'
            '}'
        )
        monkeypatch.setattr("src.data.grok_client.market._call_grok_api",
                            lambda *a, **k: raw)
        r = search_market("日経平均")
        assert "66,970.22" in r["price_action"]
        assert r["sentiment"]["score"] == 0.6
        assert r["macro_factors"] == ["米雇用統計が予想を下回る"]
        assert r["raw_response"] == raw

    def test_sentiment_score_is_clamped(self, monkeypatch):
        raw = '{"sentiment": {"score": 5.0, "summary": "x"}}'
        monkeypatch.setattr("src.data.grok_client.market._call_grok_api",
                            lambda *a, **k: raw)
        assert search_market("x")["sentiment"]["score"] == 1.0

    def test_prose_without_json_keeps_raw(self, monkeypatch):
        """JSON が無くても raw_response は残す。手で読めば使える。"""
        monkeypatch.setattr("src.data.grok_client.market._call_grok_api",
                            lambda *a, **k: "散文だけの応答")
        r = search_market("日経平均")
        assert r["raw_response"] == "散文だけの応答"
        assert r["price_action"] == ""
