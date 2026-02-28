#!/usr/bin/env python3
"""Entry point for the graph-query skill (KIK-409).

Migrated to BaseSkillCommand (KIK-518).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from scripts.cli_framework import BaseSkillCommand


class GraphQueryCommand(BaseSkillCommand):
    name = "graph-query"
    description = "ナレッジグラフ自然言語クエリ"

    def configure_parser(self, parser):
        parser.add_argument(
            "query_words",
            nargs="+",
            help="自然言語クエリ (例: 7203.Tの前回レポートは？)",
        )

    def context_input(self, args):
        # graph-query does not use print_context (it IS the context query)
        return ""

    def run(self, args):
        from src.data.graph_nl_query import query

        user_input = " ".join(args.query_words)
        result = query(user_input)

        if result is None:
            print("クエリに一致するデータが見つかりませんでした。")
            print("\n対応クエリ例:")
            print("  - 「7203.T の前回レポートは？」")
            print("  - 「繰り返し候補に上がってる銘柄は？」")
            print("  - 「AAPL のリサーチ履歴」")
            print("  - 「最近の市況は？」")
            print("  - 「7203.T の取引履歴」")
            return

        print(result["formatted"])

    def suggestion_kwargs(self, args):
        user_input = " ".join(args.query_words)
        return {"context_summary": f"グラフクエリ: {user_input[:60]}"}


def main():
    GraphQueryCommand().execute()


if __name__ == "__main__":
    main()
