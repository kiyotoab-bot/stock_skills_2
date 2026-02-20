#!/usr/bin/env python3
"""Proactive action suggestions based on accumulated knowledge graph (KIK-435).

Usage:
    python3 scripts/suggest.py
    python3 scripts/suggest.py --symbol 7203.T
    python3 scripts/suggest.py --sector Technology
    python3 scripts/suggest.py --symbol AAPL --sector Technology
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    parser = argparse.ArgumentParser(
        description="Suggest next actions from knowledge graph"
    )
    parser.add_argument("--context", default="", help="User context text")
    parser.add_argument("--symbol", default="", help="Current symbol in focus")
    parser.add_argument("--sector", default="", help="Current sector in focus")
    args = parser.parse_args()

    try:
        from src.core.proactive_engine import format_suggestions, get_suggestions

        suggestions = get_suggestions(
            context=args.context,
            symbol=args.symbol,
            sector=args.sector,
        )
        output = format_suggestions(suggestions)
        if output:
            print(output)
    except Exception:
        pass  # Graceful degradation — never crash


if __name__ == "__main__":
    main()
