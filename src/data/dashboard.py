"""戦略・選定条件・売買推移・資産推移を1枚のローカル HTML にする（KIK-789）.

2026-11-23 ユーザー依頼。保有銘柄・資産額は個人情報なので、PC の外に出さない:
外部 CDN・フォント・画像を読まない1ファイルの HTML（グラフは ``dashboard_svg`` の inline SVG）。
出力先は gitignore 済みの ``data/dashboard/index.html``。

``collect()`` がディスクから集め、``render()`` が HTML 文字列を作る（テストは render に dict を渡す）。
判断はしない。数値の再計算もしない（現在値は取得できた株価、無ければ取得単価で出し、そう明記する）。
"""

from __future__ import annotations

import datetime
import json
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Callable, Optional

import yaml

from src.data import dashboard_svg as svg

DEFAULT_OUT = "data/dashboard/index.html"

#: 無条件保有の表示は config/allocation.yaml の ``unconditional_hold``（ユーザー判断）から読む

#: checklists.yaml のセクション見出し
CHECKLIST_TITLES = {
    "data_quality": "データ品質（DQ）", "comparison": "比較・計算（CP）", "rules": "売買ルール（RL）",
    "followthrough": "やると言ったこと（FT）", "reporting": "報告（RP）", "pre_order": "発注前後（PO）",
    "entry_conditions": "WL登録・エントリー（EC）", "entry_conditions_cyclical": "シクリカル（CY）",
    "entry_conditions_asset": "資産バリュー（AV）", "entry_conditions_earnings": "収益バリュー（EV）",
}


def _yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def default_price(symbol: str) -> Optional[float]:
    try:
        from src.data.yahoo_client import get_stock_info
        info = get_stock_info(symbol) or {}
        p = info.get("price")
        return float(p) if p else None
    except Exception:  # noqa: BLE001 - 取れなければ取得単価で出す
        return None


def _safe(fn, default):
    """1つの材料が壊れていてもダッシュボード全体は出す（その部分は空で出る）."""
    try:
        return fn()
    except Exception:  # noqa: BLE001
        return default


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def collect(base_dir: str = ".", price_fn: Optional[Callable[[str], Optional[float]]] = default_price) -> dict:
    """ディスク（と任意で株価）から表示用の材料を集める."""
    from src.data.asset_history import load_asset_history
    from src.data.monthly_check import load_trades
    from src.data.note_manager import load_notes
    from src.data.portfolio_io import load_cash_balance, load_portfolio

    base = Path(base_dir)
    data = base / "data"
    positions = []
    for p in load_portfolio(str(data / "portfolio.csv")):
        price = price_fn(p["symbol"]) if price_fn else None
        positions.append({**p, "price": price})
    try:
        lessons = load_notes(note_type="lesson", base_dir=str(data / "notes"))
    except Exception:  # noqa: BLE001
        lessons = []
    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="minutes"),
        "history": load_asset_history(str(data / "history" / "assets.jsonl"), str(data / "reports")),
        "trades": load_trades(str(data / "history" / "trade")),
        "positions": positions,
        "cash": _safe(lambda: load_cash_balance(str(data / "cash_balance.json")), {}),
        "allocation": _yaml(base / "config" / "allocation.yaml"),
        "checklists": _yaml(base / "config" / "checklists.yaml"),
        "lessons": [n for n in lessons if n.get("persistence") == "permanent"],
    }


# ---------------------------------------------------------------------------
# 描画
# ---------------------------------------------------------------------------
def _yen(v) -> str:
    if v is None:
        return "-"
    return f"-¥{-v:,.0f}" if v < 0 else f"¥{v:,.0f}"


def _first_line(text: str, n: int = 90) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line if len(line) <= n else line[:n] + "…"


def _positions_view(ctx: dict) -> tuple[list[dict], float, float]:
    """保有の評価額（株価が無ければ取得単価）。日本円以外は換算しないので合計から外す."""
    rows, equity, cost_total = [], 0.0, 0.0
    for p in ctx.get("positions", []):
        shares = p.get("shares") or 0
        cost = p.get("cost_price") or 0
        price = p.get("price")
        jpy = (p.get("cost_currency") or "JPY") == "JPY"
        value = shares * (price if price else cost)
        if jpy:
            equity += value
            cost_total += shares * cost
        rows.append({**p, "value": value if jpy else None, "priced": bool(price),
                     "pnl": (shares * (price - cost)) if (price and jpy) else None})
    return rows, equity, cost_total


def _section_assets(ctx: dict) -> str:
    goal = (ctx.get("allocation") or {}).get("goal") or {}
    markers = [{"date": t.get("date"), "kind": t.get("action"), "label": f"{t.get('action', '')} {t.get('symbol', '')}"}
               for t in ctx.get("trades", [])]
    chart = svg.line_chart(ctx.get("history", []), _num(goal.get("amount")), str(goal.get("deadline") or ""),
                           _num(goal.get("required_equity_cagr")), markers)
    hist = ctx.get("history", [])
    summary = ""
    if hist:
        first, last = hist[0], hist[-1]
        chg = last["total"] / first["total"] - 1 if first["total"] else 0
        amount = _num(goal.get("amount"))
        to_goal = f" / 目標まで {_yen(amount - last['total'])}" if amount else ""
        summary = (f'<p class="kpi"><b>{_yen(last["total"])}</b>（{escape(last["date"])}）'
                   f' / {escape(first["date"])} から {chg * 100:+.1f}%{to_goal}</p>')
    return f"<section><h2>資産推移</h2>{summary}{chart}</section>"


def _section_allocation(ctx: dict) -> str:
    rows, equity, cost_total = _positions_view(ctx)
    cash = _num((ctx.get("cash") or {}).get("total_jpy")) or 0.0
    total = equity + cash
    by_role: dict[str, float] = defaultdict(float)
    for r in rows:
        if r["value"] is not None:
            by_role[r.get("role") or "未分類"] += r["value"]
    by_role["cash"] += cash
    targets = ((ctx.get("allocation") or {}).get("role_targets") or {}).get("normal") or {}
    bars = []
    for role in sorted(set(by_role) | set(targets)):
        pct = max(by_role.get(role, 0) / total * 100, 0.0) if total > 0 else 0.0
        rng = targets.get(role)
        # style 属性に入るので数値だけを通す（yaml の値をそのまま埋め込まない）
        lo, hi = (rng[0], rng[1]) if (isinstance(rng, list) and len(rng) >= 2 and all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in rng[:2])) else (None, None)
        band = (f'<span class="band" style="left:{lo}%;width:{hi - lo}%"></span>' if lo is not None else "")
        tgt = f"{lo}〜{hi}%" if lo is not None else "目標なし"
        bars.append(f'<div class="alloc"><span class="role">{escape(role)}</span>'
                    f'<span class="track">{band}<span class="fill" style="width:{min(pct, 100):.1f}%"></span></span>'
                    f'<span class="pct">{pct:.1f}%（目標 {tgt}）</span></div>')
    trs = []
    for r in rows:
        uh = (ctx.get("allocation") or {}).get("unconditional_hold") or {}
        tag = str(uh.get(r["symbol"], "")) if isinstance(uh, dict) else ""
        ccy = str(r.get("cost_currency") or "JPY")
        money = _yen if ccy == "JPY" else (lambda v, c=ccy: "-" if v is None else f"{v:,.2f} {escape(c)}")
        price = money(r["price"]) if r["priced"] else "取得単価で代用"
        trs.append(f"<tr><td>{escape(r['symbol'])}</td><td>{escape(str(r.get('memo') or '')[:40])}</td>"
                   f"<td>{escape(r.get('role') or '未分類')}</td><td class='n'>{r['shares']:,}</td>"
                   f"<td class='n'>{money(r['cost_price'])}</td><td class='n'>{price}</td>"
                   f"<td class='n'>{_yen(r['value'])}</td><td class='n'>{_yen(r['pnl'])}</td>"
                   f"<td>{escape(tag)}</td></tr>")
    unpriced = sum(1 for r in rows if not r["priced"])
    note = (f'<p class="note">株価が取れなかった {unpriced} 銘柄は取得単価で評価しています。</p>' if unpriced else "")
    foreign = [r["symbol"] for r in rows if r["value"] is None]
    if foreign:
        note += (f'<p class="note">⚠ 円以外の銘柄（{escape(", ".join(map(str, foreign)))}）は換算していないため、'
                 "総資産・株式・配分の合計に含めていません。</p>")
    return (f'<section><h2>現在の配分</h2><p class="kpi">総資産 <b>{_yen(total)}</b> = 株式 {_yen(equity)}'
            f' + 現金 {_yen(cash)}（現金の基準日 {escape(str((ctx.get("cash") or {}).get("date", "-")))}）'
            f' / 含み損益 {_yen(equity - cost_total)}</p>{"".join(bars)}'
            '<table><thead><tr><th>銘柄</th><th>メモ</th><th>枠</th><th>株数</th><th>取得単価</th>'
            f'<th>現値</th><th>評価額</th><th>含み損益</th><th>扱い</th></tr></thead><tbody>{"".join(trs)}'
            f"</tbody></table>{note}</section>")


def _section_trades(ctx: dict) -> str:
    trades = sorted(ctx.get("trades", []), key=lambda t: str(t.get("date") or ""), reverse=True)
    monthly: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for t in trades:
        m = str(t.get("date") or "")[:7] or "不明"
        counts[m] += 1
        if isinstance(t.get("realized_pnl"), (int, float)):
            monthly[m] += t["realized_pnl"]
    months = sorted(counts)
    chart = svg.bar_chart([(m, monthly.get(m, 0.0)) for m in months], "月別の実現損益")
    cnt = " / ".join(f"{m}: {counts[m]}件" for m in months[-6:])
    trs = "".join(
        f"<tr><td>{escape(str(t.get('date', '')))}</td><td>{escape(str(t.get('symbol', '')))}</td>"
        f"<td class='{'buy' if t['action'] == 'buy' else 'sell'}'>{escape(t['action'])}</td>"
        f"<td class='n'>{escape(str(t['shares'])) if t.get('shares') is not None else '-'}</td>"
        f"<td class='n'>{_yen(t['price']) if isinstance(t['price'], (int, float)) else '-'}</td>"
        f"<td class='n'>{_yen(t['realized_pnl']) if isinstance(t.get('realized_pnl'), (int, float)) else ''}</td>"
        f"<td>{escape(t.get('sleeve') or '')}</td><td class='memo'>{escape(str(t.get('memo') or ''))}</td></tr>"
        for t in trades)
    empty = "" if trades else '<p class="empty">取引の記録がありません。</p>'
    return (f"<section><h2>売買の推移</h2><h3>月別の実現損益</h3>{chart}"
            f'<p class="note">直近の件数: {escape(cnt) or "-"}（月次上限は売りも数える）</p>'
            "<details open><summary>取引の一覧（新しい順）</summary><table><thead><tr><th>日付</th><th>銘柄</th>"
            "<th>売買</th><th>株数</th><th>価格</th><th>実現損益</th><th>枠</th><th>メモ</th></tr></thead>"
            f"<tbody>{trs}</tbody></table></details>{empty}</section>")


def _kv(d: dict) -> str:
    return "".join(f"<tr><th>{escape(str(k))}</th><td>{escape(json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v))}</td></tr>"
                   for k, v in d.items())


def _section_strategy(ctx: dict) -> str:
    a = ctx.get("allocation") or {}
    goal = a.get("goal") or {}
    rt = a.get("role_targets") or {}
    regimes = "".join(
        f"<tr><th>{escape(name)}</th>"
        + "".join(f"<td>{escape(str(r))} {escape(str(v[0]))}〜{escape(str(v[-1]))}%</td>" for r, v in t.items() if isinstance(v, list) and v)
        + "</tr>"
        for name, t in rt.items() if isinstance(t, dict))
    lessons = "".join(
        f"<li><span class='date'>{escape(str(n.get('date', '')))}</span> {escape(_first_line(n.get('content', '')))}</li>"
        for n in sorted(ctx.get("lessons", []), key=lambda n: n.get("date", ""), reverse=True))
    return ("<section><h2>戦略</h2>"
            f"<p class='kpi'>目標 <b>{_yen(_num(goal.get('amount')))}</b>（期限 {escape(str(goal.get('deadline', '-')))}・"
            f"必要な株式年率 {escape(str(goal.get('required_equity_cagr', '-')))}%）</p>"
            f"<p class='note'>{escape(str(goal.get('basis', '')))}</p>"
            f"<h3>役割別ターゲット</h3><table>{regimes}</table>"
            "<details><summary>集中・小型株・短期枠の制約</summary><table>"
            + _kv({k: a[k] for k in ("concentration", "cap_size", "tactical") if k in a})
            + "</table></details>"
            f"<h3>恒久ルール（lesson・permanent）{len(ctx.get('lessons', []))}件</h3>"
            f"<ul class='lessons'>{lessons or '<li>なし</li>'}</ul></section>")


def _section_criteria(ctx: dict) -> str:
    c = ctx.get("checklists") or {}
    blocks = []
    for key, title in CHECKLIST_TITLES.items():
        sec = c.get(key)
        if not isinstance(sec, dict):
            continue
        items = "".join(
            f"<tr><td class='id'>{escape(str(it.get('id', '')))}</td><td>{escape(str(it.get('check', '')))}</td>"
            f"<td class='why'>{escape(str(it.get('why', '')))}</td></tr>"
            for it in (sec.get("items") or []) if isinstance(it, dict))
        apply_to = "・".join(map(str, sec.get("apply_to") or []))
        blocks.append(f"<details><summary>{escape(title)}（{len(sec.get('items') or [])}項目）"
                      f"<span class='apply'>{escape(apply_to)}</span></summary>"
                      f"<table><thead><tr><th>ID</th><th>確認すること</th><th>理由</th></tr></thead>"
                      f"<tbody>{items}</tbody></table></details>")
    return "<section><h2>選定条件・チェックリスト</h2>" + ("".join(blocks) or '<p class="empty">なし</p>') + "</section>"


_CSS = """
:root{--bg:#fff;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--c-line:#0969da;--c-req:#9a6700;
--c-buy:#1a7f37;--c-sell:#cf222e;--c-band:rgba(9,105,218,.15);--c-fill:#0969da;--card:#f6f8fa}
@media (prefers-color-scheme:dark){:root{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;--line:#30363d;
--c-line:#4493f8;--c-req:#d29922;--c-buy:#3fb950;--c-sell:#f85149;--c-band:rgba(68,147,248,.2);
--c-fill:#4493f8;--card:#161b22}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 system-ui,-apple-system,"Segoe UI","Hiragino Sans","Yu Gothic UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 64px}
header h1{font-size:20px;margin:0}header p{color:var(--muted);margin:4px 0 0}
nav{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 0;margin:12px 0 8px;z-index:1}
nav a{color:var(--c-line);margin-right:14px;text-decoration:none}
section{margin:28px 0}h2{font-size:17px;border-bottom:1px solid var(--line);padding-bottom:4px}h3{font-size:14px;margin:16px 0 6px}
.kpi b{font-size:18px}.note,.empty{color:var(--muted);font-size:12px}
.chart{width:100%;height:auto;background:var(--card);border-radius:6px}
.grid{stroke:var(--line);stroke-width:1}.axis{fill:var(--muted);font-size:11px}
.line-rec,.line-est{fill:none;stroke:var(--c-line);stroke-width:2}.line-est{stroke-dasharray:5 4}
.req{stroke:var(--c-req);stroke-width:1.5;stroke-dasharray:2 4}.dot{fill:var(--c-line)}
.mk-buy{stroke:var(--c-buy);stroke-width:2}.mk-sell{stroke:var(--c-sell);stroke-width:2}
.bar-pos{fill:var(--c-buy)}.bar-neg{fill:var(--c-sell)}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}td.id{white-space:nowrap;font-weight:600}
td.why,td.memo{color:var(--muted);font-size:12px}td.buy{color:var(--c-buy)}td.sell{color:var(--c-sell)}
.alloc{display:grid;grid-template-columns:90px 1fr 210px;gap:8px;align-items:center;margin:4px 0}
.track{position:relative;height:12px;background:var(--card);border-radius:6px;overflow:hidden}
.band{position:absolute;top:0;bottom:0;background:var(--c-band)}
.fill{position:absolute;left:0;top:3px;height:6px;background:var(--c-fill);border-radius:3px}
.pct{font-variant-numeric:tabular-nums;font-size:12px}
details{margin:6px 0;border:1px solid var(--line);border-radius:6px;padding:4px 10px}
summary{cursor:pointer;font-weight:600}.apply{color:var(--muted);font-weight:400;font-size:12px;margin-left:8px}
.lessons{padding-left:18px}.lessons .date{color:var(--muted);font-size:12px;margin-right:6px}
"""


def render(ctx: dict) -> str:
    """表示用の材料（``collect()`` の戻り値）から HTML を作る."""
    body = (_section_assets(ctx) + _section_allocation(ctx) + _section_trades(ctx)
            + _section_strategy(ctx) + _section_criteria(ctx))
    nav = "".join(f'<a href="#s{i}">{t}</a>' for i, t in enumerate(
        ("資産推移", "現在の配分", "売買の推移", "戦略", "選定条件"), 1))
    # セクションにアンカーを振る
    for i in range(1, 6):
        body = body.replace("<section>", f'<section id="s{i}">', 1)
    return ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='referrer' content='no-referrer'>"
            "<title>stock-skills ダッシュボード</title>"
            f"<style>{_CSS}</style></head><body><main><header><h1>stock-skills ダッシュボード</h1>"
            f"<p>生成 {escape(ctx.get('generated_at', ''))}・このファイルは PC の中だけで開きます（外部への通信なし）</p>"
            f"</header><nav>{nav}</nav>{body}</main></body></html>")


def build_dashboard(out: str = DEFAULT_OUT, base_dir: str = ".", price_fn=default_price) -> Path:
    """材料を集めて HTML を書き出し、そのパスを返す."""
    html = render(collect(base_dir, price_fn))
    path = Path(base_dir) / out if not Path(out).is_absolute() else Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path.resolve()
