---
name: investment-note
description: 投資メモの管理。投資テーゼ・懸念・学びなどをノートとして記録・参照・削除。
argument-hint: "[save|list|delete] [--symbol SYMBOL] [--category CATEGORY] [--type TYPE] [--content TEXT] [--id NOTE_ID]"
allowed-tools: Bash(python3 *)
---

# 投資メモ管理スキル

$ARGUMENTS を解析し、以下のコマンドを実行してください。

## 実行コマンド

```bash
python3 /Users/kikuchihiroyuki/stock-skills/.claude/skills/investment-note/scripts/manage_note.py $ARGUMENTS
```

結果をそのまま表示してください。

## コマンド一覧

### save -- メモ保存

```bash
# 銘柄メモ（従来通り）
python3 .../manage_note.py save --symbol 7203.T --type thesis --content "EV普及で部品需要増"

# PF全体メモ（KIK-429: symbolオプション化）
python3 .../manage_note.py save --category portfolio --type review --content "セクター偏重を改善"

# 市況メモ
python3 .../manage_note.py save --category market --type observation --content "日銀利上げ観測"
```

`--symbol` と `--category` のいずれかは必須。`--symbol` 指定時はカテゴリは自動で `stock`。

### list -- メモ一覧

```bash
python3 .../manage_note.py list [--symbol 7203.T] [--type concern] [--category portfolio]
```

### delete -- メモ削除

```bash
python3 .../manage_note.py delete --id note_2025-02-17_7203_T_abc12345
```

## ノートタイプ

| タイプ | 意味 | 使い方例 |
|:---|:---|:---|
| thesis | 投資テーゼ | 「EV普及で部品需要増」 |
| observation | 気づき | 「3回連続スクリーニング上位」 |
| concern | 懸念 | 「中国市場の減速リスク」 |
| review | 振り返り | 「3ヶ月保有、テーゼ通り推移」 |
| target | 目標・出口 | 「PER 15 で利確」 |
| lesson | 学び | 「バリュートラップだった」 |

## カテゴリ (KIK-429)

| カテゴリ | 意味 | 使い方 |
|:---|:---|:---|
| stock | 個別銘柄メモ | `--symbol` 指定時に自動設定 |
| portfolio | PF全体メモ | `--category portfolio`（PF振り返り、リバランス理由等） |
| market | 市況メモ | `--category market`（マクロ動向、金利等） |
| general | 汎用メモ | `--category general`（未分類、デフォルト） |

## 引数の解釈ルール（自然言語対応）

| ユーザー入力 | コマンド |
|:-----------|:--------|
| 「トヨタについてメモ: EV需要が...」 | save --symbol 7203.T --type observation --content "..." |
| 「AAPLの懸念: 中国売上の減速」 | save --symbol AAPL --type concern --content "中国売上の減速" |
| 「バリュートラップの学び」 | save --type lesson --content "..." |
| 「PF全体のメモ」「ポートフォリオの振り返り」 | save --category portfolio --type review --content "..." |
| 「市況メモ」「マクロの気づき」 | save --category market --type observation --content "..." |
| 「メモ一覧」「ノート見せて」 | list |
| 「トヨタのメモ」 | list --symbol 7203.T |
| 「PFのメモ」 | list --category portfolio |
| 「メモを削除」 | delete --id ... |

タイプの自動判定:
- 投資テーマ/買う理由/論拠 → thesis
- 観察/気づき/メモ → observation
- 懸念/リスク/心配 → concern
- レビュー/振り返り/反省 → review
- 目標価格/買い増し/利確 → target
- 学び/教訓/失敗から → lesson
