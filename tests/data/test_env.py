"""Tests for src.data.env (KIK-785).

.env を読む入口を1つにした。以前は linker.py が src/.env（存在しない）を読み、
graph_store の接続情報は import 順で値が変わっていた。
"""

import os

import pytest

from src.data import env as E


@pytest.fixture
def fresh(monkeypatch):
    """テストでは conftest が SKIP を立てるので、ここでは外して挙動を見る."""
    monkeypatch.delenv(E.SKIP_FLAG, raising=False)
    E.reset_for_tests()
    yield
    E.reset_for_tests()


def _write(tmp_path, text):
    p = tmp_path / ".env"
    p.write_text(text, encoding="utf-8")
    return p


def test_env_path_is_repo_root():
    import src.data.graph_sync as gs
    from pathlib import Path
    assert E.ENV_PATH == Path(gs.__file__).resolve().parents[2] / ".env"
    assert E.ENV_PATH.parent.name != "src"


def test_loads_values(tmp_path, fresh, monkeypatch):
    monkeypatch.delenv("KIK785_A", raising=False)
    p = _write(tmp_path, "KIK785_A=hello\n")
    assert E.load_project_env(p) is True
    assert os.environ["KIK785_A"] == "hello"
    monkeypatch.delenv("KIK785_A")


def test_does_not_override_shell(tmp_path, fresh, monkeypatch):
    monkeypatch.setenv("KIK785_B", "shell")
    p = _write(tmp_path, "KIK785_B=file\n")
    E.load_project_env(p)
    assert os.environ["KIK785_B"] == "shell"


def test_loads_once(tmp_path, fresh, monkeypatch):
    monkeypatch.delenv("KIK785_C", raising=False)
    p = _write(tmp_path, "KIK785_C=1\n")
    assert E.load_project_env(p) is True
    assert E.load_project_env(p) is False
    monkeypatch.delenv("KIK785_C")


def test_skip_flag(tmp_path, monkeypatch):
    E.reset_for_tests()
    monkeypatch.setenv(E.SKIP_FLAG, "1")
    monkeypatch.delenv("KIK785_D", raising=False)
    p = _write(tmp_path, "KIK785_D=1\n")
    assert E.load_project_env(p) is False
    assert "KIK785_D" not in os.environ
    E.reset_for_tests()


def test_missing_file(tmp_path, fresh):
    assert E.load_project_env(tmp_path / "nope.env") is False


def test_conftest_sets_skip_flag():
    """テスト中に本物の .env を読まない."""
    assert os.environ.get(E.SKIP_FLAG) == "1"


@pytest.mark.parametrize("line,expected", [
    ("A=full                # off / summary / full", "full"),
    ("A='quoted # not comment'", "quoted # not comment"),
    ('A="dq"', "dq"),
    ("A=", ""),
    ("A=x#y", "x#y"),
])
def test_minimal_parser(tmp_path, line, expected):
    p = _write(tmp_path, f"# comment\n\n{line}\n")
    assert E._parse_minimal(p) == {"A": expected}


def test_fallback_without_dotenv(tmp_path, fresh, monkeypatch):
    import builtins
    real = builtins.__import__

    def fake(name, *a, **k):
        if name == "dotenv":
            raise ImportError
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    monkeypatch.delenv("KIK785_E", raising=False)
    p = _write(tmp_path, "KIK785_E=v   # c\n")
    assert E.load_project_env(p) is True
    assert os.environ["KIK785_E"] == "v"
    monkeypatch.delenv("KIK785_E")


def test_no_module_loads_dotenv_directly():
    """入口を1つに保つ。load_dotenv を直接呼ぶ箇所が増えたら落とす（jquants は旧来の自前読込を残す）."""
    from pathlib import Path
    root = E.PROJECT_ROOT
    allowed = {root / "src/data/env.py", root / "src/data/jquants_client/_client.py"}
    offenders = []
    for base in ("src", "tools"):
        for f in (root / base).rglob("*.py"):
            if f in allowed:
                continue
            if "load_dotenv(" in f.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(f.relative_to(root)))
    assert offenders == []
