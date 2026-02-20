"""Common utilities for skill scripts -- path setup and graceful imports."""

import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Human-readable error messages (KIK-443)
# ---------------------------------------------------------------------------

_ERROR_MESSAGES: dict[str, dict[str, str]] = {
    "neo4j_unavailable": {
        "title": "Neo4jに接続できません",
        "cause": "Dockerコンテナが起動していない可能性があります",
        "fix": "docker compose up -d を実行してください",
        "fallback": "Neo4jなしで続行します（コンテキストなし）",
    },
    "grok_not_configured": {
        "title": "Grok APIキーが設定されていません",
        "cause": "XAI_API_KEY 環境変数が未設定です",
        "fix": "export XAI_API_KEY=your_key を設定してください",
        "fallback": "yfinanceデータのみで実行します",
    },
    "grok_auth_error": {
        "title": "Grok API認証エラー",
        "cause": "APIキーが無効または期限切れの可能性があります",
        "fix": "xai.com でAPIキーを確認・再発行してください",
        "fallback": "yfinanceデータのみで実行します",
    },
    "grok_rate_limited": {
        "title": "Grok APIのレート制限に達しました",
        "cause": "短時間に多くのリクエストが送信されました",
        "fix": "しばらく待ってから再試行してください（通常1〜2分）",
        "fallback": "yfinanceデータのみで実行します",
    },
    "yahoo_timeout": {
        "title": "Yahoo Financeへの接続がタイムアウトしました",
        "cause": "ネットワーク接続が不安定、またはYahoo Financeが一時的に応答していません",
        "fix": "ネットワーク接続を確認し、再試行してください",
        "fallback": "該当銘柄のデータを取得できませんでした",
    },
    "portfolio_not_found": {
        "title": "ポートフォリオデータが見つかりません",
        "cause": "portfolio.csv がまだ作成されていません",
        "fix": "まず buy コマンドで銘柄を追加してください（例: run_portfolio.py buy --symbol 7203.T --shares 100 --price 2800）",
        "fallback": None,
    },
}


def format_user_error(error_type: str, context: str = "") -> str:
    """Format a human-readable error message for the given error type.

    Args:
        error_type: One of neo4j_unavailable, grok_not_configured,
                    grok_auth_error, grok_rate_limited,
                    yahoo_timeout, portfolio_not_found.
        context: Optional extra context (e.g. symbol name).

    Returns:
        Formatted multi-line string suitable for printing to the user.
    """
    msg = _ERROR_MESSAGES.get(error_type)
    if msg is None:
        return f"⚠️  エラーが発生しました: {error_type}" + (f" ({context})" if context else "")

    lines = [f"⚠️  {msg['title']}"]
    if context:
        lines.append(f"    対象: {context}")
    lines.append(f"    原因: {msg['cause']}")
    lines.append(f"    対処: {msg['fix']}")
    if msg.get("fallback"):
        lines.append(f"    → {msg['fallback']}")
    return "\n".join(lines)


def setup_project_path(script_file: str, depth: int = 4) -> str:
    """Add project root to sys.path.

    Args:
        script_file: __file__ of the calling script
        depth: directory levels from script to project root
               4 for .claude/skills/*/scripts/*.py
               2 for scripts/*.py

    Returns:
        Project root path as string.
    """
    root = str(Path(script_file).resolve().parents[depth - 1])
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


def try_import(module_path: str, *names: str):
    """Import names from a module with graceful degradation.

    Args:
        module_path: Dotted module path (e.g. "src.data.history_store")
        *names: Names to import from the module

    Returns:
        tuple: (success: bool, imports: dict)
               imports maps each name to the imported object or None.

    Example:
        ok, imports = try_import("src.data.history_store", "save_screening")
        save_screening = imports["save_screening"]
        if ok:
            save_screening(...)
    """
    result = {n: None for n in names}
    try:
        mod = __import__(module_path, fromlist=list(names))
        for name in names:
            result[name] = getattr(mod, name)
        return True, result
    except (ImportError, AttributeError):
        return False, result
