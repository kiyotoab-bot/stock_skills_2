---
name: stock-skills
description: 投資アシスタント。自然言語の意図を判定し、7エージェント(screener/analyst/health-checker/researcher/strategist/risk-assessor/reviewer)に振り分ける。
user_invocable: true
---

# Stock Skills Orchestrator

ユーザーの自然言語入力を解釈し、適切なエージェントにルーティングする。

## Routing

1. `routing.yaml` を参照し、ユーザーの意図に最も近い example からエージェントを選定する
2. 単一エージェント（`agent`）→ そのエージェントをサブエージェントとして起動
3. 複数エージェント（`agents`）→ 配列の順序でサブエージェントを連鎖起動し、結果を統合
4. 該当パターンなし → `agents` セクションの `role` と `triggers` から柔軟に判定

## Intent Clarification

Routing後、Execution前に実行する。ユーザーの意図を正しく汲み取れているかを確認する仕組み。

### 文脈補完の優先順位

`routing.yaml` の `required_context` で定義された必須パラメータを、以下の順序で解決する:

1. **input_text** — ユーザーの入力テキストから直接抽出（「米国の高配当」→ region=us, theme=高配当）
2. **prior_output** — 直前エージェントの出力（「その株を分析して」→ symbol=直前銘柄）
3. **portfolio** — `data/portfolio.csv` の保有銘柄・地域構成から推測
4. **memory** — ユーザーの過去のフィードバック・傾向
5. **聞き返す** — 上記で解決できない場合のみ

### 解決ルール

- `optional: true` のキーは未解決でも `default` を適用し即実行する
- `optional: false` のキーが未解決の場合のみ、**最大1回** 聞き返す
- 複数の未解決キーがあっても、1メッセージにまとめて聞く

### 聞き返しフォーマット

推測を必ず付記し、Yes/No で答えられる形式にする:

```
曖昧+文脈なし:
  「日本株のバリュー系でスクリーニングしますね？（米国やテーマ指定があれば教えてください）」

曖昧+文脈あり（推測実行、質問なし）:
  → 直前のPF診断で日本株偏重と判明 → 米国・欧州株で自動スクリーニング

対象不明（optional: false）:
  「どの銘柄を分析しますか？」
```

### 聞かないケース

- 入力が明確（「7203.T分析して」「PF大丈夫？」）→ 即実行
- `required_context: []`（health-checker, risk-assessor, reviewer）→ 即実行
- `mode: routine-*`（朝サマリー/日次/週次/月次）→ 定型なので即実行

### ヘッダー表示

`routing.yaml` の `header` フィールドがある複数エージェント連鎖は、1行ヘッダーを表示してから即実行する（承認は不要）。`header` がない `agents` パターンは `[A → B → C] ～を実行します` の形式で自動生成する。

**ヘッダー記法:**
- `→` = 連鎖（A の結果を B に渡す）
- `+` = 並列（A と B を同時実行）
- `mode: routine-*` のパターンはヘッダーを表示しない（定型なので不要）

### Progressive表示

**agents が3つ以上**の連鎖には `progressive: true` を付与する。各Agent完了後に中間出力を表示する:

```
--- [1/3: risk-assessor 完了] ---
verdict: risk-on, ...
🔍 health-checker 実行中...
```

**付与基準:**
- 2エージェント以下 → 不要（短時間で完了）
- 3エージェント以上 → `progressive: true`（中間出力でUX向上）
- `mode: routine-*` → SKILL.md の「プログレッシブ表示（週次）」セクションで別途制御

### context_rules との関係

`routing.yaml` の `context_rules` は銘柄の省略補完など **具体的なヒューリスティック** を定義する。Intent Clarification は **パラメータの充足判定フレームワーク** であり、context_rules はその中の「prior_output」解決で活用される。両者は補完関係にあり、重複ではない。

## チェックリスト（必須・KIK-731）

`config/checklists.yaml` を参照する。**2026年8月3〜6日に発生した15件の見落とし・誤りを、
「どのチェックがあれば防げたか」に1対1で変換したもの**であり、精神論ではない。

| 場面 | 通すチェックリスト |
|:---|:---|
| 銘柄の評価・スクリーニング | `data_quality` `comparison` |
| 改訂率・前年比・進捗率・リターンの計算 | `comparison` |
| 売買可否・ストップ・配分の判定 | `rules` |
| WLチェック・日次/週次チェック・候補提示 | `reporting` `data_quality` |
| **発注指示書を出す直前** | **`pre_order`（6項目すべて）** |
| すべての場面 | `followthrough` |

### 機械的レビュー（必須・KIK-734）

チェックリストのうち**コードで判定できる12項目**は `src/data/checklist_review.py` で実行する。

**入口は `run_review()` ひとつ。**段階的に縮退しつつ、記録だけは必ず残る。

```python
from src.data import checklist_review as CR

checks = (CR.check_data_quality(infos) + CR.check_pf_tier(total, usdjpy)
          + CR.check_stop_sigma(dist) + CR.check_followthrough(notes)
          + CR.check_cooldown(excluded_dates=...)
          + CR.check_order(sym, info, rev, margin, cap)
          + CR.check_review_coverage(notes, CR.latest_review_date()))

summary = CR.run_review(checks, llm_context=review_prompt)
# → level: "mechanical_plus_independent"（外部LLMが実際に使えた場合）
#           "mechanical_only"（使えなかった場合）
# → data/reviews/ への保存は run_review が必ず行う
```

| 段階 | 内容 | 条件 |
|:---|:---|:---|
| 1 | 機械的チェック（12項目） | **常に実行** |
| 2 | 外部LLMによる独立レビュー | 実際に叩いて使えたときだけ |
| 3 | `data/reviews/` への記録 | **1でも2でも必ず** |

個別の `check_*` / `save_review` を直接呼ぶ設計にしていたが、**呼ぶ側が組み立てる限り
組み立て忘れが起きる**。`auto_review` が一度も発火しなかったのと同じ構造なので、
単一の入口に畳み込み `save` を既定 True にした。「レビューしたが記録しなかった」を起こせない。

**なぜ機械化したか**: `orchestration.yaml` の `auto_review` は仕組みで強制されておらず、
2026-08-03〜06 に該当する判断が多数あったのに **Reviewer が一度も発火しなかった**
（`data/reviews/` の最新が 2026-04-26 のままだった）。目標・期限・配分・11銘柄の投入計画・
ルール改訂のすべてが未レビューで確定していた。

- `check_review_coverage()` が**未レビューの判断件数**を数える。5件以上で FAIL
- `save_review()` を呼ばない限りカウントは減らない。**発火したことが記録で検証できる**
- `llm_availability()` は環境変数ではなく**実際に叩いて**確認する
  （`is_provider_available()` は鍵の有無しか見ず、それを「使える」と誤読した実績がある）
- 外部LLMが使えないときは `independent=False` を明示する。
  **Claude が Claude の判断を見るのは独立レビューではない**

⚠️ 総合 PASS は「31項目すべて確認した」ではなく「**自動判定できた範囲で問題なし**」の意味しか持たない。

**`code` 欄があるチェックは必ず実行する**（目視確認で代替しない）。主なもの:

- `get_stock_info()` の `forecast_source` / `forecast_suspect` / `dividend_yield_suspect`
- `analyze_revisions()`（`get_forecast_history()` の隣接2件を直接比較しない）
- `src.data.yahoo_client._cache._cache_path()`（キャッシュパスを自分で組まない）
- `detect_alerts(stop_levels=get_stop_levels())`（ストップ距離は日次σ倍で判定）

とくに `followthrough.FT1` は毎回確認する。**過去に自分が「○日に再評価する」と書いた項目を
実行しないまま、その予定を前提に意思決定が進んだ**事例が実際に起きている
（7/28に「7259.Tを8/3に再評価」と記録 → 未実行のまま8/3に約定）。
`load_notes(note_type="target")` の `trigger` / `expected_action` を日付で洗うこと。

## Execution

エージェントは必ず **Agent ツールでサブエージェントとして起動**する。自分で agent.md を読んで直接実行してはならない。

```
Agent({
  description: "<エージェント名>: <タスク概要>",
  prompt: "<agent.md の内容> + <examples.yaml の内容> + <ユーザーの入力> + <コンテキスト>"
})
```

- サブエージェントの prompt に agent.md と examples.yaml の内容を含める
- サブエージェントは自律的にツール（tools/）を使ってデータ取得・判断・出力する

### 今日の日付の注入（必須）

**エージェント起動前に必ず以下を実行し、取得した日付を全エージェントの prompt 冒頭に含めること。**

```python
import datetime
today = datetime.date.today().isoformat()  # 例: "2026-05-27"
```

prompt に含める形式:
```
## 今日の日付: {today}
※ yfinance のキャッシュ日付と混同しないこと。レポートのファイル名・見出し・TODO の日付は必ずこの日付を使用する。
```

**なぜ必要か**: yfinance は24hキャッシュを持つため、取得した株価データの日付（キャッシュ日）と実行日が異なる場合がある。日次レポートのファイル名や「本日」「明日」の表現に実行日を使わないと、日付の混乱が生じる。

### Conviction 銘柄の強制注入

Strategist / Reviewer を起動する前に、`notes.load_notes(note_type="thesis")` で conviction（ユーザーが「売らない」と明言した銘柄）を抽出し、prompt に注入する:

```
⚠️ conviction銘柄（売却提案禁止）:
- 7751.T キヤノン: ホールド確定（ユーザー判断）
- AMZN: ホールド確定（トリムは可、全売却は不可）
売却提案は conviction 理由を覆す根拠がない限り禁止。
```

thesis の content に「ホールド確定」「うらない」「conviction」を含むものが対象。

### グロース枠スクリーニング時のリスク判定連動

グロース枠の銘柄探し（「グロース株探して」等）の場合、**Screener の前に Risk Assessor を実行**する。

#### Risk Assessor → Screener の連携フロー

1. Risk Assessor が verdict + sector_signal + 「やらないチェック」を出力
2. オーケストレーターが結果を読み、以下を判断:

| 判定 | Screener mode | sector_signal の扱い |
|:---|:---|:---|
| normal | momentum / trending | sector_signal の favorable セクターを優先フィルタに |
| risk-off | **買わない** | Screener を起動しない |

3. 「やらないチェック」に該当した場合:
   - 理由を説明し「何もしないのが最善」と提案
   - ユーザーが「それでもやりたい」→ 実行する（ユーザーの意思を尊重）

#### sector_signal → Screener への注入

Risk Assessor の sector_signal を Screener の prompt に含める:
- favorable セクターを theme パラメータとして優先使用
- unfavorable セクターは結果に含めるが ⚠️ 警告タグ付与
- インカム枠 → 総還元4%超 + Beta0.5以下を追加条件
- グロース枠 → EPS成長プラス + テーゼ明確を追加条件

### Screener 起動時の追加コンテキスト（KIK-670）

Screener を起動する前に `tools/portfolio_io.py` の `load_portfolio()` で保有銘柄リストを取得し、prompt に含める。

```
# Screener の prompt に渡す情報
1. agent.md + examples.yaml の内容
2. ユーザーの入力
3. 前段エージェントの結果（連鎖時：投資テーゼ・文脈・除外理由を含む）
4. 既保有銘柄リスト（以下の銘柄は結果から除外すること）
```

保有銘柄リストの取得が失敗した場合（CSV なし等）は除外なしで続行する。

### 連鎖 vs 並列の判断基準（KIK-672）

#### エージェント間の並列判断

`agents: [A, B]` は原則 **順序付き連鎖** であり、A の結果を B の prompt に渡す。

| パターン | 判断 | 例 |
|:---|:---|:---|
| A の出力が B の入力に影響する | **連鎖** | researcher → screener（テーマ特定→テーマ別スクリーニング） |
| A と B が独立した観点で同じ対象を調査する | **並列** | health-checker + researcher（定量+定性で市況チェック） |

並列起動してよいのは、routing.yaml に明示的に独立と判断できる場合のみ。迷ったら連鎖を選ぶ。

#### オーケストレーター主導の並列化（KIK-673）

**サブエージェントに並列を指示しても逐次実行される。** オーケストレーター自身が複数の Agent ツールを1つのメッセージで同時発行して強制的に並列化する。

##### Screener の並列化

テーマ×地域の組み合わせごとに独立した Screener サブエージェントを起動する:

```
# NG: 1つのScreenerに全テーマを任せる（逐次実行される）
Agent(screener, prompt="4テーマ全部やれ")

# OK: テーマごとに独立したScreenerを同時発行（並列実行される）
Agent(screener-ai-jp, prompt="AIテーマ日本株")     ─┐
Agent(screener-defense, prompt="防衛テーマ米国株")  ─┤ 同時発行
Agent(screener-ev, prompt="EVテーマ日本株")        ─┘
→ 全結果を受け取ってからオーケストレーターがマージ・ランキング
```

##### Reviewer の並列化

3レビュアーを独立したサブエージェントとして起動する:

```
# NG: 1つのReviewerに3 LLM全部を任せる（逐次実行される）
Agent(reviewer, prompt="GPT/Gemini/Claude全部やれ")

# OK: レビュアーごとに独立したサブエージェントを同時発行
Agent(risk-reviewer, prompt="GPTでリスクレビュー: call_llm('gpt', ...)")   ─┐
Agent(logic-reviewer, prompt="Geminiでロジックレビュー: call_llm('gemini', ...)") ─┤ 同時発行
データレビュー: オーケストレーター自身が実行（Claude = 自分）           ─┘
→ 全結果を受け取ってからオーケストレーターが統合判断（PASS/WARN/FAIL）
```

##### 単一テーマ・単一レビューの場合

テーマが1つだけ、またはレビューが軽量な場合は、従来通り1つのサブエージェントに任せてよい。並列化は複数の独立タスクがある場合のみ適用する。

### 定常業務（Routine Execution）（KIK-724）

routing.yaml で `mode: routine-daily` / `routine-weekly` / `routine-monthly` にマッチした場合、以下のフローをオーケストレーターが制御する。

#### レベル判定

| レベル | トリガー | 所要時間 |
|:---|:---|:---|
| daily | 定常業務, まとめてチェック, 日次チェック, ルーティン | 3-4分 |
| weekly | フルチェック, 週次レビュー, しっかり見たい | 8-13分 |
| **monthly** | **月次チェック, 月次レビュー, 今月の発注どうする, 月初チェック** | **5-7分** |
| デフォルト（未指定時） | daily | — |

⚠️ **monthly は weekly の上位互換ではない。** 見る対象が違う。
weekly は「相場と PF の現状」、monthly は「**今月の売買1回をどう使うか**」。
片方を回しても他方は埋まらない。

#### 日次フロー（routine-daily）

**Step 0（必須）: ルーティンの鮮度チェック**

```python
from src.data.morning_summary import latest_routine_dates, check_routine_freshness
check_routine_freshness(latest_routine_dates())
```

週次にしか含まれない項目（リスク判定・アクションプラン・レビュー・需給）は、
**週次を回さないと誰も気づかないまま抜け続ける**。実際 2026-07-27 から 08-06 まで
10日間 週次が未実行で、その間リスク判定・Reviewer・需給がすべて抜けていた
（需給はユーザーの指摘で発覚した）。日次の冒頭で必ず確認し、
`weekly_stale`（7日でWARN / 14日でCRITICAL）が出たら**週次の実行を促す**。

```
Step 1: detect_alerts（異常検知）
  ↓ CRITICAL 銘柄を Step 2 に注入
Step 2: HC — PFヘルスチェック（損益・RSI・クロス）
Step 3a: HC — 市況定量        ─┐ 並列（Agent同時発行）
Step 3b: researcher — ニュース ─┘
Step 4: HC — ターゲット乖離（config/allocation.yaml照合）+ WLアラート
```

- Step 3a/3b はオーケストレーターが Agent を同時発行して並列化する
- Step 4 で全 green の場合、ターゲット乖離セクションを省略する
- **出力分岐**: 異常あり → 全テーブル / 異常なし → 軽量3行（評価額+変動+一言）

#### 週次フロー（routine-weekly）

```
[日次 Step 1-4（ただし Step 3 は 3c を追加）]
  Step 3a: HC — 市況定量        ─┐
  Step 3b: researcher — ニュース ─┤ 並列（Agent同時発行）
  Step 3c: HC — 需給動向        ─┘  ← 週次のみ追加
  ↓
Step 5: risk-assessor（フルリスク判定 — 12ステップ全実行）
  ↓
Step 6: strategist（課題特定 + アクションプラン）
  ↓ 課題あり（exit-rule/乖離red/バリュートラップ）
Step 7: screener（条件付き — strategist指定のテーマ×地域でTop3+3軸スコア）
  ⚠️ screener は「探す」だけ。「買う」判断は別。
  strategist の「やらないチェック」は「今月は買わない」であり「探さない」ではない。
  → やらないチェック該当でも screener は起動し、候補をウォッチリスト候補として提示する。
  ↓ risk-off + 逆張りなし → Step 6 スキップ。Step 7 はターゲット乖離redがあれば起動（ヘッジ/インカム補強候補を探す）、乖離なしならスキップ
Step 8: reviewer（auto_review で自動挿入）
  ↓ Step 6 スキップ → Step 8 もスキップ
```

- Step 3c（需給）は `jpx.get_demand_supply()` を呼び出す。`available=False` の場合は `（需給: データ取得失敗）` を1行付記してスキップ
- Step 3c の出力項目: 信用倍率（market）/ 外国人純買い / 個人純買い / 投信純買い。判断コメントは付けず数値のみ
- Step 7 のスクリーニングは、ターゲット乖離red / exit-rule到達 / バリュートラップ疑いがある場合に起動
- **「やらないチェック」はscreener起動を阻害しない。** 「やらないチェック」該当時は結果に「📋 WL候補（買い保留）」ラベルを付与
- 課題なし → 「現状維持が最善」と出力し、Step 7 をスキップ
- 週次の Step 4 ターゲット乖離は全 green でも表示する（網羅的に見る目的）

#### 月次フロー（routine-monthly）（KIK-738）

**なぜ月次が要るか**: 冷却期間は買付から4週、月次上限は売買1回、投入計画も月1銘柄。
**発注は月1回しか起きないのに、その1回を判断する枠が無かった。**
結果、月に紐づく宿題（翌月枠の銘柄未定・conviction 未認定）が週次のたびに持ち越されていた。

**Step 0（値の用意）**: `equity_value` / `cash` は health-checker に
**数値だけ**を出させる（銘柄テーブル・RSI・市況は出さない。それは日次と週次の仕事）。
あるいは `portfolio_io.load_portfolio()` と `cash_balance.load_cash_balance()` から
オーケストレーターが直接組む。

```python
from src.data.monthly_check import build_monthly_context
ctx = build_monthly_context(
    load_notes(), load_portfolio(), equity_value, cash,
    excluded_dates={"2026-08-04", "2026-08-03"},   # 枠から外すが損益は残る日
    stop_levels=get_stop_levels(),                 # conviction の CV3 判定に要る
)
# 目標額・期限は省略すると config/allocation.yaml の goal: から読む
```

**入口は `build_monthly_context()` ひとつ。** 個別に呼ぶ設計にすると組み立て忘れが起きる。

```
Step 1: budget      — 冷却期間の残り / 月次上限の残り / 今月買えるか + 塞がっている理由
Step 2: slots       — 当月〜3ヶ月先の枠。「枠あり銘柄未定」を必ず出す
Step 3: conviction  — 予定銘柄の CV1-CV3。記録が無ければ未認定として出す
Step 4: goal        — 目標進捗と必要年率（現状維持 / 投入完了後 の2本）
Step 5: realized    — 今月と先月の確定売買・実現損益
  ↓
Step 6: strategist  — 今月の1回をどう使うか。発注する / 見送る / 枠を埋める作業をする
Step 7: reviewer    — auto_review で自動挿入
```

**出力の必須項目**（省略禁止）:

- `budget.blockers` — 買えない理由を**全部**出す。冷却と月次上限が同時に塞がることがある
- `slots` の「枠あり銘柄未定」 — これが月次を作った直接の理由。**未定のまま月末を迎えさせない**
- `conviction` で `qualified=False` の予定銘柄 — 発注日までに認定作業が要る
- `goal.required_cagr_as_is` と `required_cagr_fully_invested` の**両方**
- `tier_rules.tier_mismatch` — 規模ティアと運用ティアが違うとき。**自動では緩めない**
- `conviction` の `exempt=True` — ユーザーが免除した銘柄。認定作業を促さない

⚠️ **必要年率は2本を取り違えない。** `as_is`（現金を寝かせたまま）は高く出るが、
これは達成不能という意味ではなく**未投入の帰結**でしかない。判断は
`fully_invested`（投入完了後の株式額ベース）を見る。片方だけ見せると誤読する。

⚠️ `slots` / `conviction` は**自然文のノートからの抽出**なので完全ではない。
根拠行（`lines` / `evidence`）を必ず添えて、エージェントが検証できるようにする。
`conviction` は CV1-CV3 と明示された記述のみを根拠にし、
「ストップ」「テーゼ」等のキーワードから充足を**推測しない**（全銘柄 3/3 になり警告が死ぬ）。

#### プログレッシブ表示（週次）

Phase 完了ごとに中間結果を出力し、体感の待ち時間を短縮する:

```
[Step 1-4完了 ~3min] → 日次データ先行表示
[Step 5完了 ~5min]   → リスク判定結果表示
[Step 6-7完了 ~8min] → アクションプラン+候補表示
[Step 8完了 ~10min]  → レビュー結果表示
```

**省略禁止項目**: Phase 要約時に以下は絶対に省略しない:
- TODO / ターゲットリマインド（target ノートの件数+内容）
- CRITICAL / EXIT 判定
- conviction 銘柄の警告（thesis に conviction_override がある銘柄）

#### 朝サマリーとの違い

| | 朝サマリー | 日次チェック | 週次レビュー |
|:---|:---|:---|:---|
| 所要時間 | 30秒 | 3-4分 | 8-13分 |
| 異常検知 | detect_alerts のみ | + HC全銘柄 | + HC全銘柄 |
| PF損益 | なし | 全銘柄テーブル | 全銘柄テーブル |
| 市況 | なし | 主要6指標+ニュース | 主要6指標+ニュース |
| 需給動向 | なし | なし | 信用倍率+外国人/個人/投信 |
| 乖離チェック | なし | yellow/red のみ | 全項目 |
| リスク判定 | なし | なし | フル(12ステップ) |
| アクション提案 | なし | なし | What-If付き |
| スクリーニング | なし | なし | 条件付きTop3 |
| レビュー | なし | なし | 自動レビュー |

#### データ保存

結果は `data/session_logs/routine/` に自動保存する:
- `daily_YYYYMMDD.json` / `weekly_YYYYMMDD.json` / `monthly_YYYYMMDD.json`

### Reviewer 自動挿入（KIK-659）

エージェント実行後、`orchestration.yaml` の `auto_review` ルールに従い Reviewer の要否を **自動判定** する。
判定は仕組みで強制されるため、オーケストレーターが意識的に判断する必要はない。

**トリガー条件**（いずれかに該当 → Reviewer を自動起動）:
1. 実行エージェントに `strategist` が含まれる
2. 実行エージェントに `screener` が含まれる（スクリーニング結果も投資判断の入口）
3. routing.yaml の該当パターンに `review: true` フラグがある
4. 出力に投資判断キーワード（売却/購入/入替/リバランス等）が含まれる

**二重実行防止**: 同一セッションで既に Reviewer が実行済みの場合はスキップする。

### Reviewer 起動時の lesson 注入

Reviewer を起動する前に `tools/notes.py` の `load_notes(note_type="lesson")` でローカルの lesson を取得し、prompt に含める。
get_context() が Neo4j 未接続で None を返す場合でも、lesson は data/notes/ から直接読めるため確実にレビューに反映される。

```
# Reviewer の prompt に渡す情報
1. agent.md + examples.yaml の内容
2. レビュー対象（前段エージェントの出力全文）
3. ユーザーの入力（元の意図）
4. 過去の lesson 一覧（load_notes(note_type="lesson") で取得）
```

## Direct Actions（記録系操作）

routing.yaml で `action: direct` に分類される操作はエージェント不要。オーケストレーターが直接実行する。

### 書く

| 操作 | ツール | データ保存先 |
|:---|:---|:---|
| 投資メモ保存（thesis/concern/lesson/observation/review/target/journal） | `tools/graphrag.py` merge_note | CSV(master) + Neo4j(view) |
| ウォッチリスト追加・削除 | CSV 直接読み書き | CSV(master) + Neo4j(view) |
| 売買記録（buy/sell） | `tools/graphrag.py` merge_trade | CSV(master) + Neo4j(view) |
| キャッシュ残高更新 | JSON 直接読み書き | data/cash_balance.json |

判断不要のデータ操作なのでエージェントは起動しない。

### 読む（各エージェントが GraphRAG 経由で取得）

| データ | 読むエージェント | 活用方法 |
|:---|:---|:---|
| 投資メモ | Analyst, Strategist | 過去の分析・テーゼとの比較 |
| lesson | Strategist, Reviewer | 判断前の制約条件、バイアス補正 |
| ウォッチリスト | Screener | 候補と重複チェック |
| 売買記録 | Health Checker, Analyst | PF診断、保有者視点の分析 |
| キャッシュ残高 | Health Checker, Strategist | PF全体像の把握、購入予算の参照 |

### データ同期（KIK-676/677）

「sync して」「データを同期して」「整合性チェック」でローカル→GraphRAG の差分検出・同期を実行する。

**同期フロー**:
1. `data/sync_status.yaml` の last_sync を確認し、前回同期日をユーザーに伝える
2. `sync_all()` を実行（**毎回フルスキャン**。差分同期は実装していない）
3. 戻り値の synced / failed / skipped を件数まで提示する
4. `data/sync_status.yaml` の last_sync が更新される

⚠️ **差分同期は存在しない。** 以前ここには「last_sync より新しいファイルを差分として
検出し、差分テーブルを提示してから同期」と書いてあったが、そのような API は無く、
`sync_all()` は毎回全件を MERGE する（冪等なので不整合は出ないが、ファイルが増えると
線形に重くなる）。差分の提示が必要なら呼び出し側でファイルの mtime を見ること。

**実体は `src/data/graph_sync.py` の `sync_all()`**（`tools/graphrag.py` は薄いファサード）。
レコード → ノードの変換は **`src/data/graph_writers.py` ひとつ**で、
`save_*()` が保存時に書くときも同じ関数を通る（KIK-741）。
`save_*()` が JSON に書く **payload がそのままインターフェース**なので、
保存と同時に書いても、後から同じファイルを読んで sync しても結果は一致する。
下表の history カテゴリは `_WRITERS` から導出される（`HISTORY_CATEGORIES = tuple(_WRITERS)`）。
**`save_*()` を追加してカテゴリが増えたら `_WRITERS` に足すこと。**
`tests/data/test_graph_sync.py::test_every_saved_category_has_a_writer` が
`save_*.py` の `_history_dir("...")` を走査して漏れを検出する（テストが落ちる）。

**同期対象**:

| data/ | GraphRAG ノード | 同期関数 |
|:---|:---|:---|
| data/notes/*.json | Note | merge_note() |
| data/history/trade/*.json | Trade + BOUGHT/SOLD | merge_trade() |
| data/history/screen/*.json | Screen + SURFACED | merge_screen() + tag_theme() |
| data/history/report/*.json | Report + ANALYZED | merge_report_full() |
| data/history/research/*.json | Research | merge_research_full() + link_research_supersedes() |
| data/history/health/*.json | HealthCheck | merge_health() |
| data/history/market_context/*.json | MarketContext | merge_market_context_full() |
| data/history/stress_test/*.json | StressTest + STRESSED | merge_stress_test() |
| data/history/forecast/*.json | Forecast | merge_forecast() |
| data/portfolio.csv | Portfolio + HOLDS | sync_portfolio() |
| data/cash_balance.json | Portfolio.cash_* + Note(type=cash) | merge_cash_balance() |

**同期方向は常にローカル → GraphRAG**（一方向）。
**重複防止**: graph_store の全関数が MERGE を使用。同じ id は上書きされ二重登録されない。

**現金の持たせ方**: 現金は銘柄ではないので HOLDS を張れない（`sync_portfolio` も
`*.CASH` を除外する）。Portfolio アンカーの `cash_jpy` / `cash_usd` … と
`cash_updated_at` プロパティに入れ、基準日ごとの `Note(type=cash)` で履歴を残す。
Note の id は基準日で切ってあるので、再 sync しても増えず上書きされる。
`cash_balance.json` は通貨・メタデータ（`updated_at` / `memo`）・派生値（`balance_jpy`）が
同じ階層に混ざっているため、**3文字大文字キーだけを通貨とみなす**（`balance_jpy` を
通貨として数えると JPY が二重計上になる）。

⚠️ **KIK-735/736/737 まで、この表の大半が実際には回っていなかった**（2026-08-08 発見）。
`save_*()` が保存時に dual-write するため平常時は表面化せず、
**Neo4j が落ちている間に保存したデータだけが永久に取り残される**という形で漏れていた。
現金に至っては呼び出し口自体が無く、総資産の79%がグラフに存在しなかった。
notes は1ファイル目のレコードしか読んでおらず36件が毎回落ちていた。
KIK-735 で5カテゴリを足した後も market_context / stress_test / forecast が漏れており、
「表に無い＝忘れた」を検知する仕組みが無いことが原因だった。

**結果は件数まで見る。**「synced」と出ただけでは足りない:
- `synced` の history は `{category}({成功}/{全体}件)` 形式。分母と分子が違えば取りこぼしがある
- `failed` に `{category}: {N}件中0件同期` → **障害**（Neo4j が落ちた等）。リトライする
- `skipped` に `cash: 通貨として認識できないキー [...]` → `update_currency()` に
  通貨コードでない文字列が渡っている
- `skipped` に `NEO4J_MODE=off` → データではなく設定の問題

**ベクトル埋め込みは sync 経路でも生成される**（KIK-740）。save 経路と同じ
`history/_helpers._build_embedding` を使うので、Neo4j 停止中に保存したデータを
後から sync しても `embedding` / `semantic_summary` が付く。
TEI（`src/data/embedding_client.py`）が未起動なら埋め込みなしで書かれる（graceful degradation）。

⚠️ KIK-739 まで sync 経路は埋め込みを生成しておらず、**そのノードだけベクトル検索から
永久に漏れていた**。ノードは作られ件数も合うので出力からは検知できない。
実測では Note 172件中165件 → sync 後 169件に増えた（残り3件は 2026-04 の
ソースファイルが存在しない残骸）。

### データ保存原則

- マスター: data/ (JSON/CSV) — **常に保存。GraphRAG の有無に関わらない**
- ビュー: GraphRAG / Neo4j（dual-write、接続時のみ）
- GraphRAG がなくても動作する（graceful degradation）

## Orchestration（自律修正ループ）

`orchestration.yaml` に従い、エージェント実行後の自動リトライ・エスカレーションを制御する。

- スクリーニング0件 → 条件緩和して自律リトライ（最大2回）
- Reviewer PASS/WARN → そのまま出力（自律）
- **Reviewer FAIL → FAIL理由と修正方針案をユーザーに提示 → 承認後リトライ**（最大2回）
- 再試行上限到達 → 現時点の結果をそのまま提示

## Post-Action

### 1. 結果をユーザーに提示

エージェントの出力をユーザーに提示する。Reviewer の自動挿入は `orchestration.yaml` の `auto_review` で制御。

### 2. データ保存（自律実行）（KIK-674）

エージェント実行後、結果を以下に保存する。**ユーザーの指示を待たず自律的に実行する。**

| エージェント | data/ ローカル保存 |
|:---|:---|
| Screener | data/screening_results/{preset}_{date}.json |
| Analyst | data/reports/{symbol}_{date}.json |
| Researcher | data/research/{topic}_{date}.json |
| Health Checker | data/session_logs/{date}.json |
| Strategist | data/session_logs/{date}.json |
| Reviewer | data/reviews/{date}.json |

#### Markdown レポート保存（routine のみ）

`mode: routine-daily` / `routine-weekly` / `routine-monthly` の実行後、**チャットに出力したレポート全文を Markdown ファイルとして保存する**。

⚠️ **月次も必ず md を保存する。** 鮮度判定（`latest_routine_dates`）は
`data/reports/*.md` の日付しか見ないので、JSON だけ保存しても
`monthly_never_run` が毎日の日次チェックで出続ける。

| モード | 保存先 |
|:---|:---|
| routine-daily | `data/reports/daily_YYYYMMDD.md` |
| routine-weekly | `data/reports/weekly_YYYYMMDD.md` |

**Markdown フォーマット**:

```markdown
# 日次チェック — YYYY-MM-DD
<!-- または「# 週次レビュー — YYYY-MM-DD」 -->

## 概要
- 総資産: ¥X,XXX,XXX（PF: ¥X,XXX,XXX / キャッシュ: ¥X,XXX,XXX（XX%））
- Risk判定: risk-on / neutral / risk-off（スコアXX）
- Reviewer: PASS / WARN / FAIL

## ヘルスチェック
<!-- HC の出力そのまま（銘柄テーブル・RSI・クロス等） -->

## 市況
<!-- 市況テーブルそのまま -->

## リスク判定（週次のみ）
<!-- Risk Assessor の出力そのまま -->

## アクションプラン（週次のみ）
<!-- Strategist の出力そのまま -->

## スクリーニング結果（週次・条件付き）
<!-- Screener の出力そのまま -->

## レビュー
<!-- Reviewer の判定と理由 -->

## 確定アクション
<!-- 優先度付きアクションリスト -->
```

**月次レポートのセクション**（`# 月次チェック — YYYY-MM` の下に置く）:

```markdown
## 売買枠
<!-- 冷却期間の残り / 月次上限の残り / 今月買えるか。blockers は全部書く -->
<!-- tier_mismatch があれば必ず書く（規模は medium だが運用は small 等） -->

## 今月の発注
<!-- 予定銘柄と pre_order 6項目の結果。発注が起きるのは月次だけなのでここで通す -->

## 枠の確定状況
<!-- 当月〜3ヶ月先 + horizon 外の計画月。「枠あり銘柄未定」は省略禁止 -->

## conviction 認定
<!-- 予定銘柄の tier。qualified=False は発注日までの作業として書く -->
<!-- exempt=True（conviction_override）は免除なので認定作業を促さない -->

## 目標進捗
<!-- 総資産 / 目標 / 残り年数 / 必要年率（as_is と fully_invested の両方） -->

## 実現損益
<!-- 今月・先月の確定売買。excluded_pnl は別枠で示す -->
```

**保存方法**: `save_routine_report()` で Markdown と JSON を**1呼び出しで**保存する。

```python
from src.data.morning_summary import save_routine_report
save_routine_report("daily", markdown_text, data_dict)   # または "weekly"
```

Markdown と JSON を別々に書く手順だったため、2026-08-06 に日次を3回実行しながら
**保存を1度もしなかった**。`check_routine_freshness()` は保存されたレポートの日付を
見るので、この抜けは最大3日間検知されない。1呼び出しにまとめて書き忘れの余地を減らす。

**保存タイミング**: 全ステップ完了後、チャット出力と同一内容を保存する。
**内容の一致を保証**: チャットに表示した内容と Markdown の内容を一致させる。要約・省略不可。

**データ保存原則**:
- **data/ (JSON/CSV) は常に保存する。** これが唯一の自動保存先
- **GraphRAG への書き込みは自動実行しない。** ユーザーが「sync して」と指示した場合のみ実行する
- **保存の最終責任はオーケストレーターが持つ。** サブエージェントが「保存済み」と報告しても、オーケストレーターは必ず自分でファイルの存在を確認（ls or read）し、存在しなければ自分で保存する。サブエージェントの報告を鵜呑みにしない（保存処理が失敗している可能性がある）

**保存ステータス表示**:

データ保存後、以下のステータスをユーザーに必ず表示する:

```
💾 data/screening_results/trending_us_20260420.json
💾 data/reports/weekly_20260506.md
```

**sync 提案（Neo4j 接続時のみ）**:

データ保存後、Neo4j が接続中であれば「sync しますか？」とユーザーに確認する。
Neo4j 未接続時は提案しない（graceful degradation）。

```python
# Neo4j 接続判定
from src.data.graph_store._common import is_available
if is_available():
    # → 「💾 保存しました。sync しますか？」と提案
```

ユーザーが承認した場合のみ、下記「3. データ同期」を実行する。

### 3. データ同期（sync）

ユーザーから「sync して」「GraphRAG と同期」と指示された場合、または上記の sync 提案をユーザーが承認した場合、data/ → GraphRAG の一方向同期を実行する。

**sync 対象**: 上記「データ同期（KIK-676/677）」の表と同一。実体は
`src/data/graph_sync.py` の `sync_all()` ひとつで、`tools/graphrag.py` から呼ぶ。

```python
from tools.graphrag import sync_all
r = sync_all()   # {"synced": [...], "failed": [...], "skipped": [...]}
```

**結果は件数まで見る。** `skipped` に `"{category}: Nファイル中0件同期"` が出ていたら、
ファイルはあるのに1件も書けていない（必須フィールド欠落など）。`synced` が空でないことだけを
見て「同期できた」と報告しない。

**sync 状態管理**: `data/sync_status.yaml` で最終同期日時と同期済みファイル一覧を管理。ファイルの更新日時が last_sync より新しければ未同期と判定。

**重複防止**: graph_store の全関数が Neo4j の MERGE を使用。同じ id のデータは上書きされるため、初回 full sync でも二重登録されない。

### 4. 学びの記録提案

エージェント実行後、結果に学び・教訓・気づきがあると判断できる場合、ユーザーに「記録しますか？」と提案する。

**提案条件**（いずれかに該当）:
- Reviewer が WARN/FAIL を出した（失敗パターンの記録価値あり）
- 過去の lesson と矛盾する結果が出た
- ユーザーが意外な反応をした（想定外の判断・確信）
- スクリーニングで新しいテーマ・観点が出た

**提案フォーマット**:
```
📝 学びを記録しますか？
例: 「防衛株は地政学イベントで必ず上がるわけではない」
```

**保存フロー**:
1. ユーザーが承認 → `tools/notes.py` の `save_note(note_type="lesson")` で `data/notes/` に保存
2. Neo4j 接続中 → 保存後そのまま GraphRAG にも sync（`merge_note()`）
3. Neo4j 未接続 → data/ のみ保存（次回 sync 時に反映）

**記録しない場合**: ユーザーが不要と判断すればスキップ。強制しない。

### 5. 次のアクションを提案

- 次の自然なアクションを1-2個提案する
- 直前の会話で扱った銘柄・結果を引き継ぎ、省略された情報を補完する

## References

- ルーティング few-shot: [routing.yaml](./routing.yaml)
- 自律修正ループ: [orchestration.yaml](./orchestration.yaml)
