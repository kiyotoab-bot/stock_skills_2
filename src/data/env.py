"""リポジトリ直下の .env を読み込む唯一の入口（KIK-785）.

以前は各モジュールが自分で ``load_dotenv(Path(__file__).parents[N] / ".env")``
を呼んでいた。そのため:

- ``graph_store/linker.py`` は ``parents[2]``（= ``src/.env``、存在しない）を指していた。
  KIK-517 の再編でファイルが1階層深くなり、ずれたまま気づかれなかった
- ``graph_store/_common.py`` は import 時に ``NEO4J_URI`` などを読むが、
  .env を読む ``tools/llm.py`` / ``grok_client`` が**先に** import されたかどうかで
  値が変わっていた（import 順に依存）。今動いているのは既定値が .env と
  たまたま同じだから

ここに寄せ、環境変数を読むモジュールは**読む前に** ``load_project_env()`` を呼ぶ。

- 既存の環境変数は上書きしない（``override=False``）。シェルで明示した値が勝つ
- 何度呼んでも1回しか読まない
- ``STOCK_SKILLS_SKIP_DOTENV`` が立っていれば読まない。テストは本物の .env
  （API 鍵・NEO4J_MODE）を拾ってはいけないので、``tests/conftest.py`` が
  モジュール読込時に立てる
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
SKIP_FLAG = "STOCK_SKILLS_SKIP_DOTENV"

_loaded = False


def _parse_minimal(path: Path) -> dict[str, str]:
    """python-dotenv が無いときの最小パーサ（KEY=VALUE、行末の ``  # コメント`` を落とす）."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in ("'", '"'):
            q = value[0]
            end = value.find(q, 1)
            value = value[1:end] if end > 0 else value[1:]
        else:
            # dotenv と同じく「空白 + #」以降をコメントとして落とす
            for sep in (" #", "\t#"):
                i = value.find(sep)
                if i >= 0:
                    value = value[:i]
            value = value.strip()
        out[key.strip()] = value
    return out


def load_project_env(path: Path | None = None, force: bool = False) -> bool:
    """リポジトリ直下の .env を環境変数に読み込む。

    Returns
    -------
    bool
        今回の呼び出しで読み込んだら True。読み込み済み・スキップ・ファイル無しは False。
    """
    global _loaded
    if _loaded and not force:
        return False
    if os.environ.get(SKIP_FLAG):
        _loaded = True
        return False
    p = path or ENV_PATH
    _loaded = True
    if not p.exists():
        return False
    try:
        from dotenv import load_dotenv
        load_dotenv(p, override=False)
        return True
    except ImportError:
        pass
    try:
        for k, v in _parse_minimal(p).items():
            os.environ.setdefault(k, v)
        return True
    except OSError:
        return False


def reset_for_tests() -> None:
    """テスト用: 読み込み済みフラグを戻す."""
    global _loaded
    _loaded = False
