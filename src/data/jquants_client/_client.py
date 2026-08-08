"""J-Quants API クライアント初期化・認証。"""

import os
import sys
from pathlib import Path
from typing import Optional

_client_cache: Optional[object] = None
_available: Optional[bool] = None
_env_loaded = False


def _ensure_env() -> None:
    """.env をこのモジュール自身が読み込む。

    従来は ``tools/jquants.py`` だけが ``load_dotenv`` を呼んでいたため、
    ``src/data/`` 側から直接 import した経路では認証情報が環境変数に載らず
    ``is_available()`` が常に False を返していた（2026-08-05 発見）。
    ``get_stock_info()`` は ``src/data/yahoo_client/`` にあるので、
    J-Quants を統合しても無言で無効化される状態だった。
    エントリポイントに依存しないよう、ここで自前に読む。
    """
    global _env_loaded
    if _env_loaded:
        return
    # テストは実際の .env の資格情報を拾ってはいけない。tests/conftest.py の
    # autouse フィクスチャがこのフラグを立てて .env 読込を無効化する。
    if os.environ.get("JQUANTS_SKIP_DOTENV"):
        _env_loaded = True
        return
    _env_loaded = True
    if os.environ.get("JQUANTS_API_KEY") or os.environ.get("JQUANTS_API_REFRESH_TOKEN"):
        return
    env_path = Path(__file__).resolve().parents[3] / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
        return
    except Exception:
        pass
    # dotenv が無い/失敗した場合の最小フォールバック
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass


def _make_client():
    """ClientV2 または Client (V1 fallback) を返す。"""
    _ensure_env()
    try:
        import jquantsapi
    except ImportError:
        raise ImportError("jquants-api-client not installed: pip install jquants-api-client")

    api_key = os.environ.get("JQUANTS_API_KEY", "")
    refresh_token = os.environ.get("JQUANTS_API_REFRESH_TOKEN", "")

    if api_key:
        return jquantsapi.ClientV2(api_key=api_key)
    if refresh_token:
        # V2 は api_key のみ受け付けるが、refresh_token でも動作確認済み
        client = jquantsapi.ClientV2(api_key=refresh_token)
        return client
    # 環境変数なし → jquantsapi デフォルト設定ファイルに fallback
    return jquantsapi.ClientV2()


def get_client():
    global _client_cache
    if _client_cache is None:
        _client_cache = _make_client()
    return _client_cache


def is_available() -> bool:
    """J-Quants APIキーが設定されているか確認。"""
    _ensure_env()
    try:
        import jquantsapi  # noqa: F401
    except ImportError:
        return False
    return bool(
        os.environ.get("JQUANTS_API_KEY")
        or os.environ.get("JQUANTS_API_REFRESH_TOKEN")
    )


def reset_client() -> None:
    """テスト用: クライアントキャッシュをリセット。"""
    global _client_cache, _env_loaded
    _client_cache = None
    _env_loaded = False
