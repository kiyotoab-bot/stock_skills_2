"""save 経路と sync 経路が同じ書き込みをすること (KIK-741).

同じ「レコード → ノード」変換が3箇所にあり、既に食い違っていた:
screen の tag_theme、research の SUPERSEDES と merge_stock、trade のキー名
吸収が片方にしか無かった。`save_*()` が JSON に書く payload の形が、そのまま
graph_writers の入力になっている——**payload がインターフェース**である。
"""

import datetime
from unittest.mock import patch

import pytest

from src.data.common import load_json_records
from src.data.graph_writers import _WRITERS
from src.data.history import save_health, save_screening, save_trade

_TARGETS = ["merge_screen", "merge_stock", "tag_theme", "merge_trade",
            "merge_health", "merge_report_full", "merge_research_full",
            "link_research_supersedes"]


def _recorder(sink):
    def make(name):
        def call(*args, **kwargs):
            # 埋め込みは TEI の有無で変わるので比較から外す
            kwargs.pop("embedding", None)
            kwargs.pop("semantic_summary", None)
            sink.append((name, tuple(map(str, args)),
                         {k: str(v)[:80] for k, v in sorted(kwargs.items())}))
            return True
        return call
    return make


def _capture(fn):
    sink = []
    make = _recorder(sink)
    with patch.multiple("src.data.graph_store", **{t: make(t) for t in _TARGETS}):
        result = fn()
    return sink, result


def _replay(path, category):
    sink = []
    make = _recorder(sink)
    for rec in load_json_records(path):
        with patch.multiple("src.data.graph_store", **{t: make(t) for t in _TARGETS}):
            _WRITERS[category](rec)
    return sink


class TestSaveAndSyncAgree:
    """保存と同時に書いても、後から payload を読んで書いても同じ結果になる."""

    def test_screen(self, tmp_path):
        saved, path = _capture(lambda: save_screening(
            "value", "jp", [{"symbol": "7203.T", "name": "T", "sector": "Auto"}],
            theme="ai", base_dir=str(tmp_path)))
        assert saved == _replay(path, "screen")
        # tag_theme は sync 側に無かった。落ちていないことを明示する
        assert any(c[0] == "tag_theme" for c in saved)

    def test_trade(self, tmp_path):
        today = datetime.date.today().isoformat()
        saved, path = _capture(lambda: save_trade(
            "7203.T", "buy", 100, 2000.0, "JPY", today, memo="m",
            base_dir=str(tmp_path)))
        assert saved == _replay(path, "trade")

    def test_health(self, tmp_path):
        saved, path = _capture(lambda: save_health(
            {"summary": {"green": 1}, "positions": [{"symbol": "7203.T"}]},
            base_dir=str(tmp_path)))
        assert saved == _replay(path, "health")


class TestWriterRegistry:
    def test_every_category_has_exactly_one_writer(self):
        assert set(_WRITERS) == {"trade", "screen", "report", "research",
                                 "health", "market_context", "stress_test",
                                 "forecast"}

    @pytest.mark.parametrize("category", list(_WRITERS))
    def test_writers_reject_records_missing_required_fields(self, category):
        """必須が欠けたら False。壊れたノードを作らない."""
        with patch.multiple("src.data.graph_store",
                            **{t: _recorder([])(t) for t in _TARGETS}):
            assert _WRITERS[category]({}) is False

    def test_research_creates_the_stock_node(self):
        """save_research と同じ。落とすと Stock が作られない."""
        rec = {"date": "2026-08-08", "target": "7203.T", "research_type": "stock",
               "fundamentals": {"sector": "Auto"}, "summary": "s"}
        with patch("src.data.graph_store.merge_research_full", return_value=True), \
             patch("src.data.graph_store.link_research_supersedes"), \
             patch("src.data.graph_store.merge_stock") as m:
            assert _WRITERS["research"](rec) is True
        m.assert_called_once_with(symbol="7203.T", name="", sector="Auto")

    def test_research_summary_falls_back_to_the_builder(self):
        """payload に summary が無ければ本文から組み立てる（空で書かない）."""
        rec = {"date": "2026-08-08", "target": "半導体", "research_type": "theme"}
        with patch("src.data.graph_store.merge_research_full", return_value=True) as m, \
             patch("src.data.graph_store.link_research_supersedes"), \
             patch("src.data.graph_store.merge_stock"), \
             patch("src.data.history.save_research._build_research_summary",
                   return_value="組み立てた要約") as b:
            _WRITERS["research"](rec)
        b.assert_called_once_with("theme", rec)
        assert m.call_args.kwargs["summary"] == "組み立てた要約"

    def test_research_summary_in_the_payload_wins(self):
        rec = {"date": "2026-08-08", "target": "半導体", "research_type": "theme",
               "summary": "保存済みの要約"}
        with patch("src.data.graph_store.merge_research_full", return_value=True) as m, \
             patch("src.data.graph_store.link_research_supersedes"), \
             patch("src.data.graph_store.merge_stock"), \
             patch("src.data.history.save_research._build_research_summary") as b:
            _WRITERS["research"](rec)
        b.assert_not_called()
        assert m.call_args.kwargs["summary"] == "保存済みの要約"
