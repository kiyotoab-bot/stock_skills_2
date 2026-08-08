"""Tests for graph_store.check_schema (KIK-742).

`init_schema()` はベクトル索引の失敗を `try/except: pass` で握り潰すため、
1つも作られなくても True を返す。実際 2026-08-09 に調べたところ、このDBには
索引も制約も1つも無かった（Neo4j 既定の LOOKUP 2件のみ）。埋め込みを全ノードに
付けても索引が無ければ意味検索は動かない。その状態を検知できることを固定する。
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.no_auto_mock


@pytest.fixture(autouse=True)
def reset_driver():
    import src.data.graph_store as gs
    gs._driver = None
    yield
    gs._driver = None


def _driver(indexes, constraints):
    """SHOW INDEXES / SHOW CONSTRAINTS の戻りを差し替えたドライバを作る."""
    session = MagicMock()

    def run(q, *a, **k):
        res = MagicMock()
        res.data.return_value = indexes if "INDEXES" in q else constraints
        return res

    session.run.side_effect = run
    d = MagicMock()
    d.session.return_value.__enter__ = MagicMock(return_value=session)
    d.session.return_value.__exit__ = MagicMock(return_value=False)
    return d


def _all_present():
    import src.data.graph_store._common as C
    e = C._expected_schema()
    idx = ([{"name": n, "type": "RANGE", "state": "ONLINE"} for n in e["indexes"]]
           + [{"name": n, "type": "VECTOR", "state": "ONLINE"}
              for n in e["vector_indexes"]])
    con = [{"name": n} for n in e["constraints"]]
    return idx, con


class TestExpectedSchema:
    def test_names_are_parsed_from_the_ddl(self):
        import src.data.graph_store._common as C
        e = C._expected_schema()
        assert "note_embedding" in e["vector_indexes"]
        assert "stock_symbol" in e["constraints"]
        assert "trade_date" in e["indexes"]
        # DDL の本数と一致すること（片方だけ増える事故を防ぐ）
        assert len(e["vector_indexes"]) == len(C._VECTOR_INDEXES)
        assert len(e["constraints"]) == len(C._SCHEMA_CONSTRAINTS)
        assert len(e["indexes"]) == len(C._SCHEMA_INDEXES)


class TestCheckSchema:
    def test_all_present_is_ok(self):
        import src.data.graph_store as gs
        gs._driver = _driver(*_all_present())
        r = gs.check_schema()
        assert r["ok"] is True and r["alerts"] == []
        assert r["present"] == r["expected"]
        assert r["vector_online"] == len(r["expected"]["vector_indexes"] * 1) \
            if isinstance(r["expected"]["vector_indexes"], list) else True

    def test_empty_database_is_critical(self):
        """2026-08-09 に実際にこの状態だった（LOOKUP 2件のみ）."""
        import src.data.graph_store as gs
        gs._driver = _driver([{"name": "index_343aff4e", "type": "LOOKUP",
                               "state": "ONLINE"}], [])
        r = gs.check_schema()
        assert r["ok"] is False
        sev = {a["type"]: a["severity"] for a in r["alerts"]}
        assert sev["vector_index_missing"] == "CRITICAL"
        assert sev["constraint_missing"] == "WARN"
        assert sev["index_missing"] == "INFO"

    def test_missing_vector_index_only(self):
        """制約と索引は揃っていてもベクトル索引が無ければ意味検索は死ぬ."""
        import src.data.graph_store as gs
        idx, con = _all_present()
        idx = [i for i in idx if i["type"] != "VECTOR"]
        gs._driver = _driver(idx, con)
        r = gs.check_schema()
        assert r["ok"] is False
        assert [a["severity"] for a in r["alerts"]] == ["CRITICAL"]
        assert "note_embedding" in r["missing"]["vector_indexes"]

    def test_vector_index_present_but_not_online(self):
        """作られていても ONLINE でなければ引けない."""
        import src.data.graph_store as gs
        idx, con = _all_present()
        for i in idx:
            if i["name"] == "note_embedding":
                i["state"] = "POPULATING"
        gs._driver = _driver(idx, con)
        r = gs.check_schema()
        assert r["ok"] is False
        assert any(a["type"] == "vector_index_not_online" for a in r["alerts"])

    def test_no_driver_is_skipped_not_failed(self):
        import src.data.graph_store as gs
        with patch("src.data.graph_store._get_driver", return_value=None):
            r = gs.check_schema()
        assert r["ok"] is None and "Neo4j未接続" in r["skipped"]
        assert r["alerts"] == []

    def test_query_failure_is_skipped_not_failed(self):
        import src.data.graph_store as gs
        d = MagicMock()
        d.session.side_effect = RuntimeError("boom")
        gs._driver = d
        r = gs.check_schema()
        assert r["ok"] is None and "boom" in r["skipped"]


class TestCheckRoutineHealth:
    """Step 0 は鮮度とスキーマをまとめて見る (KIK-742)."""

    def test_combines_freshness_and_schema(self, tmp_path):
        from src.data.morning_summary import check_routine_health
        import datetime
        (tmp_path / "daily_20260809.md").write_text("x", encoding="utf-8")
        (tmp_path / "weekly_20260809.md").write_text("x", encoding="utf-8")
        (tmp_path / "monthly_20260809.md").write_text("x", encoding="utf-8")
        schema_alert = {"symbol": "SCHEMA", "type": "vector_index_missing",
                        "severity": "CRITICAL", "message": "索引なし", "value": []}
        with patch("src.data.graph_store.check_schema",
                   return_value={"alerts": [schema_alert]}):
            out = check_routine_health(str(tmp_path), datetime.date(2026, 8, 9))
        # 鮮度は全て新しいので、残るのはスキーマの1件だけ
        assert out == [schema_alert]

    def test_schema_failure_does_not_break_step0(self, tmp_path):
        """スキーマが読めなくても鮮度チェックは出す."""
        from src.data.morning_summary import check_routine_health
        import datetime
        with patch("src.data.graph_store.check_schema",
                   side_effect=RuntimeError("neo4j down")):
            out = check_routine_health(str(tmp_path), datetime.date(2026, 8, 9))
        assert [a["type"] for a in out].count("monthly_never_run") == 1
        assert all(a["symbol"] == "ROUTINE" for a in out)

    def test_no_neo4j_adds_nothing(self, tmp_path):
        from src.data.morning_summary import check_routine_health
        import datetime
        with patch("src.data.graph_store.check_schema",
                   return_value={"ok": None, "skipped": "Neo4j未接続", "alerts": []}):
            out = check_routine_health(str(tmp_path), datetime.date(2026, 8, 9))
        assert all(a["symbol"] == "ROUTINE" for a in out)
