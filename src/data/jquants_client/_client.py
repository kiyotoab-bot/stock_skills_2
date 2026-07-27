"""J-Quants API クライアント初期化・認証。"""

import os
import sys
from typing import Optional

_client_cache: Optional[object] = None
_available: Optional[bool] = None


def _make_client():
    """ClientV2 または Client (V1 fallback) を返す。"""
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
    global _client_cache
    _client_cache = None
