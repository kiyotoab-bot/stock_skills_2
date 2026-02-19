"""Tests for scripts/common.py -- setup_project_path and try_import."""

import sys

from scripts.common import setup_project_path, try_import


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
