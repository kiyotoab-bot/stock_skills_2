---
name: market-research
description: "銘柄・業界・マーケットの深掘りリサーチ。Grok API (X/Web検索) と yfinance を統合して多角的な分析レポートを生成する。"
argument-hint: "[stock|industry|market] [対象]  例: stock 7203.T, industry 半導体, market 日経平均"
allowed-tools: Bash(python3 *)
---

# 深掘りリサーチスキル

$ARGUMENTS を解析してリサーチタイプと対象を判定し、以下のコマンドを実行してください。

## 実行コマンド

```bash
python3 /Users/kikuchihiroyuki/stock-skills/.claude/skills/market-research/scripts/run_research.py <command> <target>
```

## 引数の解釈ルール

### command（リサーチタイプ・必須）

| ユーザー入力 | command |
|:-----------|:--------|
| 銘柄名、ティッカーシンボル | stock |
| 業界名、テーマ | industry |
| マーケット名、指数名 | market |

### target（対象・必須）

| ユーザー入力例 | command | target |
|:-------------|:--------|:-------|
| `7203.T` | stock | 7203.T |
| `トヨタ` | stock | 7203.T（ティッカーに変換） |
| `AAPL` | stock | AAPL |
| `半導体` | industry | 半導体 |
| `AI / Machine Learning` | industry | "AI / Machine Learning" |
| `日経平均` | market | 日経平均 |
| `S&P500` | market | S&P500 |
| `米国株市場` | market | 米国株市場 |

## リサーチタイプ別の出力

### stock（銘柄リサーチ）
- 基本情報 + バリュエーション（yfinance）
- 最新ニュース（yfinance）
- Xセンチメント（Grok API）
- 深掘り分析: ニュース・業績材料・アナリスト見解・競合比較（Grok API）

### industry（業界リサーチ）
- トレンド・主要プレイヤー・成長ドライバー・リスク・規制動向（Grok API）

### market（マーケット概況）
- 値動き・マクロ要因・センチメント・注目イベント・セクターローテーション（Grok API）

## Grok API について
- XAI_API_KEY 環境変数が設定されている場合のみ Grok API を利用
- 未設定時は yfinance データのみでレポート生成（stock の場合）
- industry / market は Grok API 必須のため、未設定時はその旨を表示

## 出力の補足

スクリプトの出力をそのまま表示した後、Claudeが以下を補足してください:

### stock の場合
- ファンダメンタルズデータと Grok リサーチの整合性を確認
- バリュースコアと市場センチメントの乖離があれば指摘
- 投資判断に影響する追加コンテキストがあれば補足

### industry の場合
- 日本市場固有の事情を補足（規制環境、参入障壁等）
- 関連する銘柄スクリーニングの提案（/screen-stocks との連携）

### market の場合
- ポートフォリオへの影響を推定（/stock-portfolio との連携）
- 類似過去事例があれば言及

## 実行例

```bash
# 銘柄リサーチ
python3 .../run_research.py stock 7203.T
python3 .../run_research.py stock AAPL

# 業界リサーチ
python3 .../run_research.py industry 半導体
python3 .../run_research.py industry "Electric Vehicles"

# マーケットリサーチ
python3 .../run_research.py market 日経平均
python3 .../run_research.py market "S&P500"
```
