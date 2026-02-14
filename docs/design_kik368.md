# KIK-368: データ蓄積基盤 + バックテスト 詳細設計書

## 1. history_store.py API仕様

ファイル: `src/data/history_store.py`

### 概要

スクリーニング結果・レポート・売買記録・ヘルスチェック結果を JSON ファイルとして蓄積する。
既存の `yahoo_client.py` のキャッシュパターン（`CACHE_DIR`, `_write_cache`, `_read_cache`）に倣い、
`data/history/` 配下にカテゴリ別サブディレクトリで保存する。

### ディレクトリ構造

```
data/history/
  screen/       # スクリーニング結果
  report/       # 個別銘柄レポート
  trade/        # 売買記録
  health/       # ヘルスチェック結果
```

### ファイル命名規則

```
{YYYY-MM-DD}_{identifier}.json
```

| カテゴリ | identifier | 例 |
|---------|-----------|-----|
| screen | `{region}_{preset}` | `2026-02-14_jp_value.json` |
| report | `{symbol}` (`"."` を `"_"` に置換) | `2026-02-14_7203_T.json` |
| trade | `{buy\|sell}_{symbol}` | `2026-02-14_buy_7203_T.json` |
| health | `health` | `2026-02-14_health.json` |

同日に同一 identifier の保存が複数回ある場合、上書きする（最新結果のみ保持）。

### 保存関数

```python
def save_screening(
    preset: str,
    region: str,
    results: list[dict],
    sector: str | None = None,
    base_dir: str = "data/history",
) -> str:
    """スクリーニング結果を保存する。

    Parameters
    ----------
    preset : str
        使用プリセット名 (value, high-dividend, etc.)
    region : str
        リージョンコード (jp, us, sg, etc.)
    results : list[dict]
        screener.screen() の戻り値。各 dict は symbol, name, price,
        per, pbr, dividend_yield, roe, value_score を含む。
    sector : str | None
        セクターフィルタ (指定時のみ)
    base_dir : str
        履歴保存ルートディレクトリ。テスト時に tmp_path を渡す。

    Returns
    -------
    str
        保存ファイルの絶対パス
    """
```

保存 JSON スキーマ:
```json
{
  "category": "screen",
  "date": "2026-02-14",
  "timestamp": "2026-02-14T10:30:00",
  "preset": "value",
  "region": "jp",
  "sector": null,
  "count": 10,
  "results": [
    {
      "symbol": "7203.T",
      "name": "Toyota Motor",
      "price": 2850,
      "per": 10.5,
      "pbr": 0.95,
      "dividend_yield": 0.032,
      "roe": 0.12,
      "value_score": 72.5
    }
  ]
}
```

---

```python
def save_report(
    symbol: str,
    data: dict,
    score: float,
    verdict: str,
    base_dir: str = "data/history",
) -> str:
    """個別銘柄レポートを保存する。

    Parameters
    ----------
    symbol : str
        ティッカーシンボル (例: "7203.T")
    data : dict
        get_stock_info() の戻り値
    score : float
        calculate_value_score() の算出スコア
    verdict : str
        判定文字列 ("割安（買い検討）", "やや割安", etc.)
    base_dir : str
        履歴保存ルートディレクトリ

    Returns
    -------
    str
        保存ファイルの絶対パス
    """
```

保存 JSON スキーマ:
```json
{
  "category": "report",
  "date": "2026-02-14",
  "timestamp": "2026-02-14T10:30:00",
  "symbol": "7203.T",
  "name": "Toyota Motor",
  "sector": "Consumer Cyclical",
  "industry": "Auto Manufacturers",
  "price": 2850,
  "per": 10.5,
  "pbr": 0.95,
  "dividend_yield": 0.032,
  "roe": 0.12,
  "roa": 0.05,
  "revenue_growth": 0.08,
  "market_cap": 35000000000000,
  "value_score": 72.5,
  "verdict": "割安（買い検討）"
}
```

---

```python
def save_trade(
    symbol: str,
    trade_type: str,
    shares: int,
    price: float,
    currency: str,
    date: str,
    memo: str = "",
    base_dir: str = "data/history",
) -> str:
    """売買記録を保存する。

    Parameters
    ----------
    symbol : str
        ティッカーシンボル
    trade_type : str
        "buy" または "sell"
    shares : int
        株数
    price : float
        取得/売却単価
    currency : str
        通貨コード (JPY, USD, etc.)
    date : str
        取引日 (YYYY-MM-DD)
    memo : str
        メモ（任意）
    base_dir : str
        履歴保存ルートディレクトリ

    Returns
    -------
    str
        保存ファイルの絶対パス
    """
```

保存 JSON スキーマ:
```json
{
  "category": "trade",
  "date": "2026-02-14",
  "timestamp": "2026-02-14T10:30:00",
  "symbol": "7203.T",
  "trade_type": "buy",
  "shares": 100,
  "price": 2850,
  "currency": "JPY",
  "memo": "割安判定でエントリー"
}
```

---

```python
def save_health(
    health_data: dict,
    base_dir: str = "data/history",
) -> str:
    """ヘルスチェック結果を保存する。

    Parameters
    ----------
    health_data : dict
        run_health_check() の戻り値。
        keys: positions, alerts, summary
    base_dir : str
        履歴保存ルートディレクトリ

    Returns
    -------
    str
        保存ファイルの絶対パス
    """
```

保存 JSON スキーマ:
```json
{
  "category": "health",
  "date": "2026-02-14",
  "timestamp": "2026-02-14T10:30:00",
  "summary": {
    "total": 5,
    "healthy": 3,
    "early_warning": 1,
    "caution": 1,
    "exit": 0
  },
  "positions": [
    {
      "symbol": "7203.T",
      "pnl_pct": 0.15,
      "trend": "上昇",
      "quality_label": "良好",
      "alert_level": "none"
    }
  ]
}
```

### 読み込み関数

```python
def load_history(
    category: str,
    days_back: int | None = None,
    base_dir: str = "data/history",
) -> list[dict]:
    """指定カテゴリの履歴を日付降順で返す。

    Parameters
    ----------
    category : str
        "screen", "report", "trade", "health" のいずれか
    days_back : int | None
        指定時、N日前までのファイルのみ返す。None で全件。
    base_dir : str
        履歴保存ルートディレクトリ

    Returns
    -------
    list[dict]
        JSON の中身をそのまま返す。日付降順（新しい順）。
    """
```

```python
def list_history_files(
    category: str,
    base_dir: str = "data/history",
) -> list[str]:
    """指定カテゴリの履歴ファイルパスを日付降順で返す。

    Parameters
    ----------
    category : str
        "screen", "report", "trade", "health" のいずれか
    base_dir : str
        履歴保存ルートディレクトリ

    Returns
    -------
    list[str]
        ファイルの絶対パスのリスト。日付降順。
    """
```

### 内部ヘルパー

```python
def _safe_filename(s: str) -> str:
    """シンボル中の "." を "_" に置換してファイル名安全な文字列にする。"""
    # yahoo_client.py L21 の _cache_path と同じパターン
    return s.replace(".", "_").replace("/", "_")

def _history_dir(category: str, base_dir: str) -> Path:
    """カテゴリ別のサブディレクトリパスを返す。存在しなければ作成。"""
    d = Path(base_dir) / category
    d.mkdir(parents=True, exist_ok=True)
    return d
```

### JSON シリアライズ

`results` リスト内の dict は yfinance 由来のデータで、`numpy.float64`, `numpy.int64`, `float('nan')`, `float('inf')` を含む可能性がある。`json.dumps` のデフォルトではこれらをシリアライズできないため、カスタムエンコーダを使用する。

```python
class _HistoryEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            if np.isnan(obj) or np.isinf(obj):
                return None
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)
```

---

## 2. backtest.py API仕様

ファイル: `src/core/backtest.py`

### 概要

`history_store` に蓄積されたスクリーニング結果を読み込み、各銘柄のスクリーニング時点の価格と現在価格を比較してリターンを検証する。ベンチマーク（日経225, S&P500）との比較でアルファを算出する。

### API

```python
def run_backtest(
    yahoo_client_module,
    category: str = "screen",
    preset: str | None = None,
    region: str | None = None,
    days_back: int = 90,
    base_dir: str = "data/history",
) -> dict:
    """蓄積データからリターン検証を実行する。

    Parameters
    ----------
    yahoo_client_module
        yahoo_client モジュール。get_stock_info(symbol) を使用して
        現在価格を取得する。
    category : str
        検証対象カテゴリ。現在は "screen" のみ対応。
    preset : str | None
        フィルタ: 指定プリセットの結果のみ対象。None で全プリセット。
    region : str | None
        フィルタ: 指定リージョンの結果のみ対象。None で全リージョン。
    days_back : int
        何日前までの履歴を対象にするか。デフォルト 90日。
    base_dir : str
        履歴保存ルートディレクトリ。テスト時に tmp_path を渡す。

    Returns
    -------
    dict
        バックテスト結果。以下の構造:
        {
            "period": {"start": "2025-11-16", "end": "2026-02-14"},
            "total_screens": 5,
            "total_stocks": 42,
            "stocks": [
                {
                    "symbol": "7203.T",
                    "name": "Toyota Motor",
                    "screen_date": "2026-01-15",
                    "score_at_screen": 72.5,
                    "price_at_screen": 2850,
                    "price_now": 3100,
                    "return_pct": 0.0877
                }
            ],
            "avg_return": 0.065,
            "median_return": 0.058,
            "win_rate": 0.714,
            "benchmark": {
                "nikkei": 0.032,
                "sp500": 0.045
            },
            "alpha_nikkei": 0.033,
            "alpha_sp500": 0.020
        }
    """
```

### 内部処理フロー

1. `load_history("screen", days_back, base_dir)` で対象期間の履歴を取得
2. `preset` / `region` でフィルタリング
3. 各結果の `results` リストから銘柄を展開
4. 同一銘柄が複数回出現する場合、最古の記録を採用（最初にスクリーニングされた時点のリターンを計測）
5. `yahoo_client_module.get_stock_info(symbol)` で現在価格を取得
6. `return_pct = (price_now - price_at_screen) / price_at_screen` を算出
7. ベンチマーク取得: `get_stock_info("^N225")`, `get_stock_info("^GSPC")` で期間開始日から現在までのリターンを近似
8. アルファ = `avg_return - benchmark_return`

### ベンチマークリターン算出

ベンチマークの期間リターンは `yahoo_client_module.get_price_history(symbol, period)` を使用する。対象期間の始点と終点の終値から算出する。

```python
def _get_benchmark_return(yahoo_client_module, symbol: str, start_date: str) -> float | None:
    """ベンチマークの期間リターンを算出する。"""
```

ベンチマークシンボル:
- 日経225: `^N225`
- S&P500: `^GSPC`

---

## 3. 各スクリプトへの組み込み箇所

### 3.1 run_screen.py (screen-stocks)

**ファイル**: `.claude/skills/screen-stocks/scripts/run_screen.py`

**組み込み箇所 (1): import + HAS_HISTORY フラグ**
- 行14付近（既存 import の直後）に追加:

```python
try:
    from src.data.history_store import save_screening
    HAS_HISTORY = True
except ImportError:
    HAS_HISTORY = False
```

**組み込み箇所 (2): run_query_mode 内のスクリーニング結果保存**
- 行103-106（pullback preset の結果表示後）:

```python
# 既存: print(format_pullback_markdown(results))
# 追加:
if HAS_HISTORY and results:
    save_screening(preset="pullback", region=region_code, results=results)
```

- 行116-119（alpha preset の結果表示後）:

```python
# 既存: print(format_alpha_markdown(results))
# 追加:
if HAS_HISTORY and results:
    save_screening(preset="alpha", region=region_code, results=results)
```

- 行140-148（QueryScreener の結果表示後、with_pullback / 通常の両方）:

```python
# 既存: print(format_pullback_markdown(results)) or print(format_query_markdown(results))
# 追加（各 print の後）:
if HAS_HISTORY and results:
    save_screening(preset=args.preset, region=region_code, results=results, sector=args.sector)
```

**組み込み箇所 (3): run_legacy_mode 内**
- 行181-184（ValueScreener の結果表示後）:

```python
# 既存: print(format_markdown(results))
# 追加:
if HAS_HISTORY and results:
    save_screening(preset=args.preset, region=market_name, results=results)
```

### 3.2 generate_report.py (stock-report)

**ファイル**: `.claude/skills/stock-report/scripts/generate_report.py`

**組み込み箇所 (1): import + HAS_HISTORY フラグ**
- 行9付近（既存 import の直後）:

```python
try:
    from src.data.history_store import save_report
    HAS_HISTORY = True
except ImportError:
    HAS_HISTORY = False
```

**組み込み箇所 (2): main() のレポート出力後**
- 行69（判定表示の直後、関数末尾）:

```python
# 既存: print(f"- **判定**: {verdict}")
# 追加:
if HAS_HISTORY:
    save_report(symbol, data, score, verdict)
```

### 3.3 run_portfolio.py (stock-portfolio)

**ファイル**: `.claude/skills/stock-portfolio/scripts/run_portfolio.py`

**組み込み箇所 (1): import + HAS_HISTORY フラグ**
- 行76付近（既存の HAS_* import ブロックの直後）:

```python
try:
    from src.data.history_store import save_trade, save_health
    HAS_HISTORY = True
except ImportError:
    HAS_HISTORY = False
```

**組み込み箇所 (2): cmd_buy() 内**
- 行332付近（`format_trade_result` 後の return 前）と 行359付近（fallback 出力後）:

```python
# buy 成功後に追加:
if HAS_HISTORY:
    save_trade(symbol, "buy", shares, price, currency, purchase_date, memo)
```

**組み込み箇所 (3): cmd_sell() 内**
- 行376-378付近（sell 成功後）:

```python
# sell 成功後に追加:
if HAS_HISTORY:
    save_trade(symbol, "sell", shares, 0.0, "", date.today().isoformat())
```

注: sell 時は price=0.0, currency="" で記録する。売却価格は別途取得が必要だが、初期実装では記録のみ。

**組み込み箇所 (4): cmd_health() 内**
- 行514付近（format_health_check 出力後）:

```python
# health 結果表示後に追加:
if HAS_HISTORY:
    save_health(health_data)
```

### 3.4 .gitignore

`data/history/` を追加:

```
data/history/
```

---

## 4. JSONスキーマ（各カテゴリ）

### 4.1 screen (スクリーニング結果)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["category", "date", "timestamp", "preset", "region", "count", "results"],
  "properties": {
    "category": {"type": "string", "const": "screen"},
    "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "timestamp": {"type": "string", "format": "date-time"},
    "preset": {"type": "string"},
    "region": {"type": "string"},
    "sector": {"type": ["string", "null"]},
    "count": {"type": "integer", "minimum": 0},
    "results": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["symbol", "value_score"],
        "properties": {
          "symbol": {"type": "string"},
          "name": {"type": ["string", "null"]},
          "price": {"type": ["number", "null"]},
          "per": {"type": ["number", "null"]},
          "pbr": {"type": ["number", "null"]},
          "dividend_yield": {"type": ["number", "null"]},
          "roe": {"type": ["number", "null"]},
          "value_score": {"type": "number"}
        }
      }
    }
  }
}
```

### 4.2 report (個別銘柄レポート)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["category", "date", "timestamp", "symbol", "value_score", "verdict"],
  "properties": {
    "category": {"type": "string", "const": "report"},
    "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "timestamp": {"type": "string", "format": "date-time"},
    "symbol": {"type": "string"},
    "name": {"type": ["string", "null"]},
    "sector": {"type": ["string", "null"]},
    "industry": {"type": ["string", "null"]},
    "price": {"type": ["number", "null"]},
    "per": {"type": ["number", "null"]},
    "pbr": {"type": ["number", "null"]},
    "dividend_yield": {"type": ["number", "null"]},
    "roe": {"type": ["number", "null"]},
    "roa": {"type": ["number", "null"]},
    "revenue_growth": {"type": ["number", "null"]},
    "market_cap": {"type": ["number", "null"]},
    "value_score": {"type": "number"},
    "verdict": {"type": "string"}
  }
}
```

### 4.3 trade (売買記録)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["category", "date", "timestamp", "symbol", "trade_type", "shares", "price", "currency"],
  "properties": {
    "category": {"type": "string", "const": "trade"},
    "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "timestamp": {"type": "string", "format": "date-time"},
    "symbol": {"type": "string"},
    "trade_type": {"type": "string", "enum": ["buy", "sell"]},
    "shares": {"type": "integer", "minimum": 1},
    "price": {"type": "number", "minimum": 0},
    "currency": {"type": "string"},
    "memo": {"type": "string"}
  }
}
```

### 4.4 health (ヘルスチェック結果)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["category", "date", "timestamp", "summary", "positions"],
  "properties": {
    "category": {"type": "string", "const": "health"},
    "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "timestamp": {"type": "string", "format": "date-time"},
    "summary": {
      "type": "object",
      "properties": {
        "total": {"type": "integer"},
        "healthy": {"type": "integer"},
        "early_warning": {"type": "integer"},
        "caution": {"type": "integer"},
        "exit": {"type": "integer"}
      }
    },
    "positions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["symbol"],
        "properties": {
          "symbol": {"type": "string"},
          "pnl_pct": {"type": ["number", "null"]},
          "trend": {"type": "string"},
          "quality_label": {"type": "string"},
          "alert_level": {"type": "string", "enum": ["none", "early_warning", "caution", "exit"]}
        }
      }
    }
  }
}
```

---

## 5. テストケース一覧

テストファイル: `tests/data/test_history_store.py`, `tests/core/test_backtest.py`

### 5.1 history_store テスト

| # | テスト名 | 内容 |
|---|---------|------|
| 1 | `test_save_screening_creates_file` | `save_screening()` が正しいパスにJSONを生成する |
| 2 | `test_save_screening_json_schema` | 保存JSONが必須フィールド (category, date, timestamp, preset, region, count, results) を含む |
| 3 | `test_save_screening_with_sector` | sector 指定時に JSON に sector フィールドが含まれる |
| 4 | `test_save_screening_overwrites_same_day` | 同日・同 identifier の2回目保存で上書きされる |
| 5 | `test_save_report_creates_file` | `save_report()` が正しいパスにJSONを生成する |
| 6 | `test_save_report_json_schema` | 保存JSONが symbol, value_score, verdict を含む |
| 7 | `test_save_trade_buy` | buy の trade JSON が正しく保存される |
| 8 | `test_save_trade_sell` | sell の trade JSON が正しく保存される |
| 9 | `test_save_health_creates_file` | `save_health()` が正しいパスにJSONを生成する |
| 10 | `test_save_health_json_schema` | 保存JSONが summary, positions を含む |
| 11 | `test_load_history_returns_sorted` | `load_history()` が日付降順で返す |
| 12 | `test_load_history_with_days_back` | `days_back` 指定で古いファイルが除外される |
| 13 | `test_load_history_empty_dir` | 空ディレクトリで空リストを返す |
| 14 | `test_load_history_invalid_json` | 壊れたJSONファイルをスキップする |
| 15 | `test_list_history_files` | ファイルパスのリストが日付降順で返る |
| 16 | `test_safe_filename` | `_safe_filename()` が `.` と `/` を `_` に置換する |
| 17 | `test_numpy_serialization` | numpy.float64, numpy.int64, NaN, inf が正しくシリアライズされる |
| 18 | `test_base_dir_parameter` | `base_dir` に tmp_path を渡した場合に正しいディレクトリに保存される |

### 5.2 backtest テスト

| # | テスト名 | 内容 |
|---|---------|------|
| 1 | `test_run_backtest_basic` | 基本的なバックテストが正しい構造の dict を返す |
| 2 | `test_run_backtest_return_calculation` | `return_pct` が `(price_now - price_at_screen) / price_at_screen` で正しく算出される |
| 3 | `test_run_backtest_filters_preset` | `preset` フィルタが正しく適用される |
| 4 | `test_run_backtest_filters_region` | `region` フィルタが正しく適用される |
| 5 | `test_run_backtest_deduplicates_symbols` | 同一銘柄の複数出現で最古の記録が採用される |
| 6 | `test_run_backtest_benchmark_alpha` | ベンチマーク比較のアルファが正しく算出される |
| 7 | `test_run_backtest_win_rate` | 勝率 (return_pct > 0 の割合) が正しく算出される |
| 8 | `test_run_backtest_empty_history` | 履歴が空の場合に適切なデフォルト値を返す |
| 9 | `test_run_backtest_missing_price` | 現在価格が取得できない銘柄がスキップされる |
| 10 | `test_run_backtest_days_back` | `days_back` パラメータで期間が正しく制限される |
| 11 | `test_benchmark_return_calculation` | `_get_benchmark_return()` が期間リターンを正しく算出する |
| 12 | `test_benchmark_return_unavailable` | ベンチマークデータ取得失敗時に None を返す |

### 5.3 テスト共通方針

- 全テストで `base_dir=tmp_path` を使用し、実ファイルシステムへの副作用を防ぐ
- `yahoo_client_module` は monkeypatch でモック（既存 `tests/conftest.py` の `mock_yahoo_client` パターンに準拠）
- バックテストの `get_stock_info` モックは `price` フィールドを含む dict を返す
- ベンチマーク取得の `get_price_history` モックは DataFrame (Close カラム付き) を返す
