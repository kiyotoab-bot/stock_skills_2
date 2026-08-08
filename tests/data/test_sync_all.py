"""Tests for tools/graphrag.py の sync_all ファサード (KIK-712 / KIK-737).

同期の中身は `src/data/graph_sync.py` に移ったので、検証も
`tests/data/test_graph_sync.py` に寄せてある。ここはファサードとしての
責務——`_project_root` を渡して委譲すること——だけを見る。
二重に中身を検証すると、仕様変更のたびに2ファイル直すことになる。
"""

from unittest.mock import patch


class TestSyncAllFacade:
    def test_delegates_with_project_root(self, tmp_path):
        import tools.graphrag as tg
        orig = tg._project_root
        try:
            tg._project_root = str(tmp_path)
            with patch("src.data.graph_sync.sync_all",
                       return_value={"synced": ["ok"], "failed": [], "skipped": []}) as m:
                result = tg.sync_all()
            m.assert_called_once_with(str(tmp_path))
            assert result["synced"] == ["ok"]
        finally:
            tg._project_root = orig

    def test_project_root_is_the_repository_root(self):
        """tools/ から見て2階層上。graph_sync の既定値と一致していること."""
        from pathlib import Path

        import tools.graphrag as tg
        from src.data import graph_sync

        assert Path(tg._project_root) == Path(graph_sync.__file__).resolve().parents[2]

    def test_returns_the_standard_shape(self, tmp_path):
        """Neo4j 未接続でも synced/failed/skipped の3キーが揃う."""
        import tools.graphrag as tg
        orig = tg._project_root
        try:
            tg._project_root = str(tmp_path)
            with patch("src.data.graph_store.get_mode", return_value="full"), \
                 patch("src.data.graph_store.is_available", return_value=False):
                result = tg.sync_all()
        finally:
            tg._project_root = orig
        assert set(result) == {"synced", "failed", "skipped"}
        assert all(isinstance(v, list) for v in result.values())
        assert not result["synced"]
