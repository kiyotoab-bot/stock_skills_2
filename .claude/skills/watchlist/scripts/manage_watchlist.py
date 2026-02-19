#!/usr/bin/env python3
"""Entry point for the watchlist skill."""

import json
import sys
import os

WATCHLIST_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "data", "watchlists")


def _ensure_dir():
    os.makedirs(WATCHLIST_DIR, exist_ok=True)


def _path(name):
    return os.path.join(WATCHLIST_DIR, f"{name}.json")


def _load(name):
    path = _path(name)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def _save(name, symbols):
    _ensure_dir()
    symbols = sorted(set(symbols))
    with open(_path(name), "w") as f:
        json.dump(symbols, f, indent=2, ensure_ascii=False)
    # Sync to Neo4j (view) -- graceful degradation
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
        from src.data.graph_store import merge_watchlist, merge_stock
        from src.data.history_store import _build_embedding
        for sym in symbols:
            merge_stock(symbol=sym)
        sem_summary, emb = _build_embedding(
            "watchlist", name=name, symbols=symbols)
        merge_watchlist(name, symbols,
                        semantic_summary=sem_summary, embedding=emb)
    except Exception:
        pass


def cmd_list():
    _ensure_dir()
    files = [f.replace(".json", "") for f in os.listdir(WATCHLIST_DIR) if f.endswith(".json")]
    if not files:
        print("ウォッチリストはありません。")
        return
    print("## ウォッチリスト一覧\n")
    for name in sorted(files):
        symbols = _load(name)
        print(f"- **{name}** ({len(symbols)} 銘柄)")


def cmd_show(name):
    symbols = _load(name)
    if not symbols:
        print(f"ウォッチリスト '{name}' は空か存在しません。")
        return
    print(f"## {name} ({len(symbols)} 銘柄)\n")
    for s in symbols:
        print(f"- {s}")


def cmd_add(name, new_symbols):
    symbols = _load(name)
    symbols.extend(new_symbols)
    _save(name, symbols)
    print(f"'{name}' に {len(new_symbols)} 銘柄を追加しました: {', '.join(new_symbols)}")


def cmd_remove(name, remove_symbols):
    symbols = _load(name)
    removed = [s for s in remove_symbols if s in symbols]
    symbols = [s for s in symbols if s not in remove_symbols]
    _save(name, symbols)
    if removed:
        print(f"'{name}' から {len(removed)} 銘柄を削除しました: {', '.join(removed)}")
    else:
        print("該当する銘柄が見つかりませんでした。")


def main():
    args = sys.argv[1:]

    if not args or args[0] == "list":
        cmd_list()
    elif args[0] == "show" and len(args) >= 2:
        cmd_show(args[1])
    elif args[0] == "add" and len(args) >= 3:
        cmd_add(args[1], args[2:])
    elif args[0] == "remove" and len(args) >= 3:
        cmd_remove(args[1], args[2:])
    else:
        print("Usage:")
        print("  manage_watchlist.py list")
        print("  manage_watchlist.py show <name>")
        print("  manage_watchlist.py add <name> <symbol1> [symbol2] ...")
        print("  manage_watchlist.py remove <name> <symbol1> [symbol2] ...")


if __name__ == "__main__":
    main()
