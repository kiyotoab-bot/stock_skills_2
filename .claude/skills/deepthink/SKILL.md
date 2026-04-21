---
name: deepthink
description: DeepThinking — 自律的に足りない観点を補完し、シナリオ分岐で深掘り分析する。Evaluator-Optimizer パターン。
user_invocable: true
---

# DeepThink

Evaluator-Optimizer パターンで自律的に深掘り分析する。通常の stock-skills が1回のエージェント起動で回答するのに対し、DeepThink は **評価→改善のループを収束するまで続ける**。

## いつ使うか

- 「イラン停戦したらPFはどうなる？」→ シナリオ分岐 + PF影響計算
- 「再投資先を提案して」→ 候補選定 + RSI確認 + シナリオ検証 + PFターゲット照合
- 「6ヶ月後を見据えたPF設計」→ マクロシナリオ × セクターローテーション × 通貨配分

通常の stock-skills で十分な場合は使わない。**複数の不確実性が絡む判断** に使う。

## 実行フロー

### Step 0: 開始通知

ユーザーに以下を通知して承認を得る:
- 「DeepThinkingモードで分析します」
- 「評価→改善のループが収束するまで続きます」
- 「各ステップで中間結果を報告します」
- 深度: shallow / medium / deep（指定がなければ medium）

深度選択ガイド:
- **shallow**: 1回の追加調査。軽微な情報不足の補完（max 3 agents, 5 LLM calls）
- **medium**: 2-3回の評価→改善ループ。標準的な深掘り（max 6 agents, 12 LLM calls）
- **deep**: 最大5回のループ。徹底的な分析（max 10 agents, 20 LLM calls）

### Step 1: 初回分析

stock-skills のエージェント（Screener / Analyst / Health Checker / Researcher / Strategist）を通常通り起動。使用可能なエージェントは [stock-skills routing.yaml](../stock-skills/routing.yaml) を参照。

### Step 2: 評価（Evaluator）

初回分析の結果を以下の観点で自己評価する:

| 観点 | チェック内容 |
|:---|:---|
| 情報充足 | 必要なデータが揃っているか（RSI? 決算日? センチメント?） |
| シナリオ | 複数のシナリオが検討されているか（楽観/悲観/中立） |
| PF整合 | ユーザーのPF構成・ターゲットと照合されているか |
| 反論 | Devil's Advocate の視点があるか |
| lesson | 過去の lesson と矛盾していないか |

**評価結果**: 不足リストを作成。

**収束条件**（以下の全てを満たしたらループ終了 → Step 5 へ）:
1. 5つの評価観点が全て完了
2. 新たな不足が検出されない

**終了条件**（いずれかに該当したら強制終了 → 現時点の結果を提示）:
1. max_iterations に到達
2. max_llm_calls に到達
3. max_wall_time_minutes に到達
4. ユーザーが「ここで終了」を選択

### Step 3: 改善（Optimizer）

不足リストに基づき、追加のエージェント/ツールを **自律的に** 起動する。

```
不足: "RSI未確認" → Analyst 追加起動（code interpreter で RSI 計算）
不足: "地政学シナリオなし" → Researcher + Gemini(web_search) で並列調査
不足: "PFターゲット未照合" → Health Checker でPF構造確認
```

**マルチLLMの活用**（`config/llm_capabilities.yaml` を参照）:
- 事実収集: Gemini(web_search=True) + Grok(tools/grok.py) を並列
- シナリオ推論: GPT(reasoning='high') + Gemini-Pro を並列
- 統合: Claude（自身）

### Step 4: チェックポイント

改善結果をユーザーに中間報告する:

```
📊 Step 2/5 完了（LLM calls: 5/12）

中間結果:
- NVO: RSI 85.6（過熱圏）
- イラン停戦シナリオ: DVN -15%、CEG -8%
- 停戦長期化シナリオ: DVN +5%、CEG +12%

[続行] [方向修正] [ここで終了]
```

- **続行** → Step 2 に戻る（次の評価→改善ループ）
- **方向修正** → ユーザーが修正内容を指示（例: 「地政学リスクに絞って」「楽観シナリオだけ深掘り」）→ 指示を反映して Step 3
- **ここで終了** → Step 5 へ（現時点の結果で統合レポートを出力）

### Step 5: 統合レポート

全ステップの結果を統合し、最終レポートを出力する:
- 事実の整理
- シナリオ別の影響
- PFへの具体的な影響
- 推奨アクション（「何もしない」を含む）

## ハーネス制約

`deepthink_limits.yaml` に従い暴走を防止する:

- 上限到達時: ループ停止 → 現時点の結果を提示 → 続行にはユーザー承認が必要
- 進捗は各ステップで表示: 「Step 3/5, LLM calls 8/12, Agents 4/6」

## 進捗表示フォーマット

各ステップの開始・完了時に以下を表示:

```
🔍 DeepThink Step 2: シナリオ分析
   Gemini(grounding) でイラン停戦の影響を調査中...
   GPT(reasoning=high) で原油価格シナリオを分析中...
```

```
✅ DeepThink Step 2 完了 (45s)
   発見: 停戦シナリオで DVN -15%、CEG -8% の影響
   次のステップ: PFターゲットとの照合
```

## References

- ハーネス制約: [deepthink_limits.yaml](./deepthink_limits.yaml)
- LLM選択: [llm_capabilities.yaml](../../config/llm_capabilities.yaml)
- 通常モード: [stock-skills SKILL.md](../stock-skills/SKILL.md)
