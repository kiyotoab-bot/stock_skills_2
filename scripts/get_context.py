#!/usr/bin/env python3
"""CLI wrapper for auto graph context injection (KIK-411).

Usage:
    python3 scripts/get_context.py "7203.Tってどう？"
    python3 scripts/get_context.py "トヨタの状況は？"
    python3 scripts/get_context.py "PF大丈夫？"
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.auto_context import get_context  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/get_context.py <user_input>")
        sys.exit(1)

    user_input = " ".join(sys.argv[1:])
    result = get_context(user_input)

    if result:
        print(result["context_markdown"])
    else:
        print("コンテキストなし")


if __name__ == "__main__":
    main()
