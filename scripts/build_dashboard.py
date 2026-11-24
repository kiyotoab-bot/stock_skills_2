"""ダッシュボード（ローカル HTML）を作る（KIK-789）.

    python scripts/build_dashboard.py [--base DIR] [--no-prices]

data/dashboard/index.html に書き出し、ブラウザで開くパスを表示する。外部への通信はしない
（--no-prices を付けなければ株価の取得だけは yfinance キャッシュ経由で行う）。
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.dashboard import build_dashboard, default_price  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=".", help="data/ と config/ があるディレクトリ")
    ap.add_argument("--no-prices", action="store_true", help="株価を取らず取得単価で評価する")
    a = ap.parse_args()
    path = build_dashboard(base_dir=a.base, price_fn=None if a.no_prices else default_price)
    print(path.as_uri())


if __name__ == "__main__":
    main()
