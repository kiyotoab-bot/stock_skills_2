"""Tests for scripts/common.py -- setup_project_path and try_import."""

import sys

from scripts.common import format_user_error, setup_project_path, try_import


class TestSetupProjectPath:
    def test_adds_to_sys_path(self, tmp_path):
        fake_script = tmp_path / "a" / "b" / "c" / "d" / "script.py"
        fake_script.parent.mkdir(parents=True)
        fake_script.touch()

        root = setup_project_path(str(fake_script), depth=4)
        # depth=4 means parents[3] → tmp_path / "a"
        assert root == str((tmp_path / "a").resolve())
        assert root in sys.path

    def test_idempotent(self, tmp_path):
        fake_script = tmp_path / "a" / "b" / "script.py"
        fake_script.parent.mkdir(parents=True)
        fake_script.touch()

        root = setup_project_path(str(fake_script), depth=2)
        count_before = sys.path.count(root)
        setup_project_path(str(fake_script), depth=2)
        assert sys.path.count(root) == count_before

    def test_depth_2(self, tmp_path):
        fake_script = tmp_path / "scripts" / "tool.py"
        fake_script.parent.mkdir(parents=True)
        fake_script.touch()

        root = setup_project_path(str(fake_script), depth=2)
        assert root == str(tmp_path.resolve())


class TestTryImport:
    def test_success(self):
        ok, imports = try_import("os.path", "join", "exists")
        assert ok is True
        assert imports["join"] is not None
        assert imports["exists"] is not None
        # Verify they are the actual functions
        import os.path
        assert imports["join"] is os.path.join
        assert imports["exists"] is os.path.exists

    def test_failure_bad_module(self):
        ok, imports = try_import("nonexistent.module.xyz", "foo")
        assert ok is False
        assert imports["foo"] is None

    def test_failure_bad_name(self):
        ok, imports = try_import("os.path", "nonexistent_function_xyz")
        assert ok is False
        assert imports["nonexistent_function_xyz"] is None

    def test_multiple_names(self):
        ok, imports = try_import("os.path", "join", "dirname", "basename")
        assert ok is True
        assert len(imports) == 3
        assert all(v is not None for v in imports.values())


class TestFormatUserError:
    """Tests for format_user_error() (KIK-443)."""

    def test_neo4j_unavailable(self):
        msg = format_user_error("neo4j_unavailable")
        assert "⚠️" in msg
        assert "Neo4j" in msg
        assert "docker compose" in msg
        assert "Neo4jなしで続行" in msg

    def test_grok_not_configured(self):
        msg = format_user_error("grok_not_configured")
        assert "⚠️" in msg
        assert "XAI_API_KEY" in msg
        assert "export" in msg
        assert "yfinance" in msg

    def test_grok_auth_error(self):
        msg = format_user_error("grok_auth_error")
        assert "⚠️" in msg
        assert "認証" in msg
        assert "xai.com" in msg

    def test_grok_rate_limited(self):
        msg = format_user_error("grok_rate_limited")
        assert "⚠️" in msg
        assert "レート制限" in msg
        assert "再試行" in msg

    def test_yahoo_timeout(self):
        msg = format_user_error("yahoo_timeout")
        assert "⚠️" in msg
        assert "タイムアウト" in msg
        assert "ネットワーク" in msg

    def test_portfolio_not_found(self):
        msg = format_user_error("portfolio_not_found")
        assert "⚠️" in msg
        assert "portfolio.csv" in msg
        assert "buy" in msg

    def test_with_context(self):
        msg = format_user_error("yahoo_timeout", context="7203.T")
        assert "7203.T" in msg

    def test_unknown_error_type(self):
        msg = format_user_error("totally_unknown_error")
        assert "⚠️" in msg
        assert "totally_unknown_error" in msg

    def test_all_error_types_start_with_warning(self):
        error_types = [
            "neo4j_unavailable", "grok_not_configured", "grok_auth_error",
            "grok_rate_limited", "yahoo_timeout", "portfolio_not_found",
        ]
        for err_type in error_types:
            msg = format_user_error(err_type)
            assert msg.startswith("⚠️"), f"{err_type} should start with warning emoji"
