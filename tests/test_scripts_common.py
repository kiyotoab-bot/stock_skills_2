"""Tests for scripts/common.py -- try_import."""

from scripts.common import try_import


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
