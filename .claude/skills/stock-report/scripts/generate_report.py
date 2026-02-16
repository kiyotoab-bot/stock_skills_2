#!/usr/bin/env python3
"""Entry point for the stock-report skill."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from src.data.yahoo_client import get_stock_info, get_stock_detail
from src.core.indicators import calculate_value_score

try:
    from src.core.indicators import calculate_shareholder_return
    HAS_SHAREHOLDER_RETURN = True
except ImportError:
    HAS_SHAREHOLDER_RETURN = False

try:
    from src.data.history_store import save_report as history_save_report
    HAS_HISTORY = True
except ImportError:
    HAS_HISTORY = False


def main():
    if len(sys.argv) < 2:
        print("Usage: generate_report.py <ticker>")
        print("Example: generate_report.py 7203.T")
        sys.exit(1)

    symbol = sys.argv[1]
    data = get_stock_detail(symbol)
    if data is None:
        data = get_stock_info(symbol)

    if data is None:
        print(f"Error: {symbol} のデータを取得できませんでした。")
        sys.exit(1)

    thresholds = {"per_max": 15, "pbr_max": 1.0, "dividend_yield_min": 0.03, "roe_min": 0.08}
    score = calculate_value_score(data, thresholds)

    if score >= 70:
        verdict = "割安（買い検討）"
    elif score >= 50:
        verdict = "やや割安"
    elif score >= 30:
        verdict = "適正水準"
    else:
        verdict = "割高傾向"

    def fmt(val, pct=False):
        if val is None:
            return "-"
        return f"{val * 100:.2f}%" if pct else f"{val:.2f}"

    def fmt_int(val):
        if val is None:
            return "-"
        return f"{val:,.0f}"

    print(f"# {data.get('name', symbol)} ({symbol})")
    print()
    print(f"- **セクター**: {data.get('sector') or '-'}")
    print(f"- **業種**: {data.get('industry') or '-'}")
    print()
    print("## 株価情報")
    print(f"- **現在値**: {fmt_int(data.get('price'))}")
    print(f"- **時価総額**: {fmt_int(data.get('market_cap'))}")
    print()
    print("## バリュエーション")
    print(f"| 指標 | 値 |")
    print(f"|---:|:---|")
    print(f"| PER | {fmt(data.get('per'))} |")
    print(f"| PBR | {fmt(data.get('pbr'))} |")
    print(f"| 配当利回り | {fmt(data.get('dividend_yield'), pct=True)} |")
    print(f"| ROE | {fmt(data.get('roe'), pct=True)} |")
    print(f"| ROA | {fmt(data.get('roa'), pct=True)} |")
    print(f"| 利益成長率 | {fmt(data.get('revenue_growth'), pct=True)} |")
    print()
    print("## 割安度判定")
    print(f"- **スコア**: {score:.1f} / 100")
    print(f"- **判定**: {verdict}")

    # KIK-375: Shareholder return section
    if HAS_SHAREHOLDER_RETURN:
        sr = calculate_shareholder_return(data)
        total_rate = sr.get("total_return_rate")
        if total_rate is not None or sr.get("dividend_yield") is not None:
            print()
            print("## 株主還元")
            print("| 指標 | 値 |")
            print("|---:|:---|")
            print(f"| 配当利回り | {fmt(sr.get('dividend_yield'), pct=True)} |")
            print(f"| 自社株買い利回り | {fmt(sr.get('buyback_yield'), pct=True)} |")
            print(f"| **総株主還元率** | **{fmt(total_rate, pct=True)}** |")
            dp = sr.get("dividend_paid")
            br = sr.get("stock_repurchase")
            ta = sr.get("total_return_amount")
            if dp is not None or br is not None:
                print()
                print(f"- 配当総額: {fmt_int(dp)}")
                print(f"- 自社株買い額: {fmt_int(br)}")
                print(f"- 株主還元合計: {fmt_int(ta)}")

    if HAS_HISTORY:
        try:
            history_save_report(symbol, data, score, verdict)
        except Exception as e:
            print(f"Warning: 履歴保存失敗: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
