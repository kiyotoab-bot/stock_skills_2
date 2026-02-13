# stock-skills

割安株スクリーニングシステム。Yahoo Finance API（yfinance）を使って60+地域から割安銘柄をスクリーニングする。[Claude Code](https://claude.ai/code) Skills として動作。

## セットアップ

```bash
pip install -r requirements.txt
```

Python 3.10+ が必要。依存: yfinance, pyyaml, numpy, pytest

Grok API（Xセンチメント分析）を利用する場合:
```bash
export XAI_API_KEY=xai-xxxxxxxxxxxxx
```

## スキル一覧

### `/screen-stocks` — 割安株スクリーニング

EquityQuery で日本株・米国株・ASEAN株等から割安銘柄を検索。7つのプリセットと60+地域に対応。

```bash
# 基本
/screen-stocks japan value        # 日本株バリュー
/screen-stocks us high-dividend   # 米国高配当
/screen-stocks asean growth-value # ASEAN成長割安

# プリセット一覧
# value / high-dividend / growth-value / deep-value / quality / pullback / alpha

# オプション
/screen-stocks japan value --sector Technology  # セクター指定
/screen-stocks japan value --with-pullback      # 押し目フィルタ追加
```

### `/stock-report` — 個別銘柄レポート

ティッカーシンボルを指定して財務分析レポートを生成。

```bash
/stock-report 7203.T    # トヨタ
/stock-report AAPL      # Apple
```

### `/watchlist` — ウォッチリスト管理

銘柄の追加・削除・一覧表示。

```bash
/watchlist list
/watchlist add my-list 7203.T AAPL
/watchlist show my-list
```

### `/stress-test` — ストレステスト

ポートフォリオのショック感応度・シナリオ分析・相関分析・VaR・推奨アクション。8つの事前定義シナリオ（トリプル安、テック暴落、円高ドル安等）。

```bash
/stress-test 7203.T,AAPL,D05.SI
/stress-test 7203.T,9984.T --scenario トリプル安
```

### `/stock-portfolio` — ポートフォリオ管理

保有銘柄の売買記録・損益表示・構造分析・ヘルスチェック・推定利回り。多通貨対応（JPY換算）。

```bash
/stock-portfolio snapshot   # 現在の損益
/stock-portfolio buy 7203.T 100 2850 JPY
/stock-portfolio sell AAPL 5
/stock-portfolio analyze    # HHI集中度分析
/stock-portfolio health     # 投資仮説ベースのヘルスチェック（3段階アラート）
/stock-portfolio forecast   # 推定利回り（楽観/ベース/悲観 + ニュース）
```

## アーキテクチャ

```
Skills (.claude/skills/*/SKILL.md → scripts/*.py)
  │
  ▼
Core (src/core/)
  screener.py ─ 4つのスクリーナー (Query/Value/Pullback/Alpha)
  indicators.py ─ バリュースコア (100点)
  alpha.py ─ 変化スコア (100点)
  technicals.py ─ 押し目判定
  health_check.py ─ ヘルスチェック (3段階アラート)
  return_estimate.py ─ 推定利回り (3シナリオ)
  concentration.py ─ HHI集中度分析
  correlation.py ─ 相関分析・ファクター分解・VaR
  shock_sensitivity.py ─ ショック感応度
  scenario_analysis.py ─ シナリオ分析 (8シナリオ)
  recommender.py ─ 推奨アクション
  portfolio_manager.py ─ ポートフォリオ管理
  │
  ├─ Markets (src/markets/) ─ japan/us/asean
  ├─ Data (src/data/)
  │    yahoo_client.py ─ 24h JSONキャッシュ
  │    grok_client.py ─ Grok API (Xセンチメント分析)
  ├─ Output (src/output/) ─ Markdown フォーマッタ
  └─ Config (config/) ─ プリセット・取引所定義
```

詳細は [CLAUDE.md](CLAUDE.md) を参照。

## テスト

```bash
pytest tests/           # 全640テスト (< 1秒)
pytest tests/core/ -v   # コアモジュール
```

## ライセンス

Private
