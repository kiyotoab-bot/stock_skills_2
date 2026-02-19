"""Common utilities for skill scripts -- path setup and graceful imports."""

import sys
from pathlib import Path


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
