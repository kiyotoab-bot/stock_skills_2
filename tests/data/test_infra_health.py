"""Tests for src.data.infra_health (KIK-784).

Neo4j / TEI のコンテナが約2ヶ月止まっていたのに、日次 Step 0 は毎日
「異常なし」を返していた。止まっていたら WARN が出ることを固定する。
"""

import datetime
from pathlib import Path

import pytest

from src.data import infra_health as IH

TODAY = datetime.date(2026, 11, 6)


@pytest.fixture
def live_mode(monkeypatch):
    """conftest は NEO4J_MODE=off を入れるので、本番相当の自動判定に戻す."""
    monkeypatch.delenv("NEO4J_MODE", raising=False)


def _status(tmp_path, last_sync):
    p = tmp_path / "sync_status.yaml"
    p.write_text(f"last_sync: '{last_sync}'\n", encoding="utf-8")
    return str(p)


def _types(alerts):
    return [a["type"] for a in alerts]


class TestCheckInfraHealth:
    def test_explicit_off_is_silent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("NEO4J_MODE", "off")
        assert IH.check_infra_health(str(tmp_path / "none.yaml"), TODAY) == []

    @pytest.mark.parametrize("mode", [" OFF ", "Off"])
    def test_off_is_case_and_space_insensitive(self, tmp_path, monkeypatch, mode):
        monkeypatch.setenv("NEO4J_MODE", mode)
        assert IH.check_infra_health(str(tmp_path / "none.yaml"), TODAY) == []

    @pytest.mark.parametrize("mode", ["summary", "full"])
    def test_explicit_on_modes_still_check(self, tmp_path, monkeypatch, mode):
        """summary / full を明示したなら Neo4j は居るはず → 落ちていれば出す."""
        monkeypatch.setenv("NEO4J_MODE", mode)
        monkeypatch.setattr("src.data.graph_store.is_available", lambda: False)
        monkeypatch.setattr("src.data.embedding_client.is_available", lambda: True)
        out = IH.check_infra_health(_status(tmp_path, "2026-11-06"), TODAY)
        assert _types(out) == ["neo4j_unavailable"]

    def test_neo4j_down_warns(self, tmp_path, live_mode, monkeypatch):
        """2026-11-06 の再現: コンテナ停止 → 以前は [] だった."""
        monkeypatch.setattr("src.data.graph_store.is_available", lambda: False)
        monkeypatch.setattr("src.data.embedding_client.is_available", lambda: True)
        out = IH.check_infra_health(_status(tmp_path, "2026-11-05T10:00:00"), TODAY)
        assert _types(out) == ["neo4j_unavailable"]
        assert out[0]["severity"] == "WARN"
        assert "docker compose up -d" in out[0]["message"]
        assert out[0]["symbol"] == "INFRA"

    def test_tei_down_warns(self, tmp_path, live_mode, monkeypatch):
        monkeypatch.setattr("src.data.graph_store.is_available", lambda: True)
        monkeypatch.setattr("src.data.embedding_client.is_available", lambda: False)
        out = IH.check_infra_health(_status(tmp_path, "2026-11-05T10:00:00"), TODAY)
        assert _types(out) == ["tei_unavailable"]

    def test_all_up_and_fresh_is_clean(self, tmp_path, live_mode, monkeypatch):
        monkeypatch.setattr("src.data.graph_store.is_available", lambda: True)
        monkeypatch.setattr("src.data.embedding_client.is_available", lambda: True)
        assert IH.check_infra_health(_status(tmp_path, "2026-11-06T00:00:22"), TODAY) == []

    def test_check_exception_counts_as_down(self, tmp_path, live_mode, monkeypatch):
        """確認できないことを黙らない."""
        def boom():
            raise RuntimeError("driver exploded")
        monkeypatch.setattr("src.data.graph_store.is_available", boom)
        monkeypatch.setattr("src.data.embedding_client.is_available", boom)
        out = IH.check_infra_health(_status(tmp_path, "2026-11-06"), TODAY)
        assert _types(out) == ["neo4j_unavailable", "tei_unavailable"]

    def test_real_incident_shape(self, tmp_path, live_mode, monkeypatch):
        """両方停止 + last_sync 2026-08-09（89日前）→ WARN 2件 + CRITICAL."""
        monkeypatch.setattr("src.data.graph_store.is_available", lambda: False)
        monkeypatch.setattr("src.data.embedding_client.is_available", lambda: False)
        out = IH.check_infra_health(_status(tmp_path, "2026-08-09T00:02:44.277720"), TODAY)
        assert _types(out) == ["neo4j_unavailable", "tei_unavailable", "sync_stale"]
        assert out[2]["severity"] == "CRITICAL" and out[2]["value"] == 89


class TestSyncFreshness:
    @pytest.mark.parametrize("last,expected", [
        ("2026-10-30", None),          # 7日ちょうど → まだ出さない
        ("2026-10-29", "WARN"),        # 8日
        ("2026-10-07", "WARN"),        # 30日ちょうど
        ("2026-10-06", "CRITICAL"),    # 31日
    ])
    def test_thresholds(self, last, expected):
        out = IH.check_sync_freshness(last, TODAY)
        if expected is None:
            assert out == []
        else:
            assert out[0]["type"] == "sync_stale" and out[0]["severity"] == expected

    def test_never_synced(self):
        out = IH.check_sync_freshness(None, TODAY)
        assert _types(out) == ["sync_never_run"]


class TestReadLastSync:
    def test_iso_string(self, tmp_path):
        assert IH.read_last_sync(_status(tmp_path, "2026-08-09T00:02:44.277720")) == "2026-08-09"

    def test_missing_file(self, tmp_path):
        assert IH.read_last_sync(str(tmp_path / "nope.yaml")) is None

    def test_yaml_datetime_value(self, tmp_path):
        """クォート無しだと YAML が datetime に読む."""
        p = tmp_path / "s.yaml"
        p.write_text("last_sync: 2026-11-06 00:00:22\n", encoding="utf-8")
        assert IH.read_last_sync(str(p)) == "2026-11-06"

    def test_broken_yaml_is_unreadable_not_missing(self, tmp_path):
        """記録はあるが読めない → sync_never_run と混ぜない."""
        p = tmp_path / "s.yaml"
        p.write_text("last_sync: [unclosed\n", encoding="utf-8")
        assert IH.read_last_sync(str(p)) == "unreadable"
        out = IH.check_sync_freshness(IH.read_last_sync(str(p)), TODAY)
        assert _types(out) == ["sync_status_unreadable"]

    def test_bad_date_is_unreadable(self, tmp_path):
        assert IH.read_last_sync(_status(tmp_path, "yesterday")) == "unreadable"

    def test_empty_file_is_missing(self, tmp_path):
        p = tmp_path / "s.yaml"
        p.write_text("", encoding="utf-8")
        assert IH.read_last_sync(str(p)) is None

    def test_default_path_is_repo_root(self):
        """cwd ではなくリポジトリ直下の data/ を見る（graph_sync と同じ場所）."""
        import src.data.graph_sync as gsync
        repo = Path(gsync.__file__).resolve().parents[2]
        assert IH._default_status_path() == repo / "data" / "sync_status.yaml"


class TestRoutineHealthIntegration:
    def test_routine_health_includes_infra(self, tmp_path, live_mode, monkeypatch):
        from src.data.morning_summary import check_routine_health
        for k in ("daily", "weekly", "monthly"):
            (tmp_path / f"{k}_20261106.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr("src.data.graph_store.is_available", lambda: False)
        monkeypatch.setattr("src.data.embedding_client.is_available", lambda: True)
        out = check_routine_health(str(tmp_path), TODAY,
                                   sync_status_path=_status(tmp_path, "2026-11-06"))
        assert _types(out) == ["neo4j_unavailable"]

    def test_infra_check_crash_is_reported(self, tmp_path, live_mode, monkeypatch):
        from src.data.morning_summary import check_routine_health
        def boom(*a, **k):
            raise RuntimeError("x")
        for k in ("daily", "weekly", "monthly"):
            (tmp_path / f"{k}_20261106.md").write_text("x", encoding="utf-8")
        monkeypatch.setattr("src.data.infra_health.check_infra_health", boom)
        out = check_routine_health(str(tmp_path), TODAY)
        assert _types(out) == ["infra_check_failed"]
