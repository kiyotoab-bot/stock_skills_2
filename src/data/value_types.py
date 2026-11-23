"""3類型バリュー（資産・収益・シクリカル）の機械チェック（KIK-786）.

式は ``src/data/value_formulas.py``（ここから re-export する）。出典は NotebookLM
「father-daughter-value-investin」、方針と決定は lesson note_2026-11-23_general_9ac8dd74。

機械チェックの判定（PASS/WARN/FAIL）まで。売買判断はエージェントが行う
（``src/data/dilution.py`` の EC6 と同じ位置づけ）。

入力は ``{symbol: get_stock_detail(symbol)}``。全銘柄を detail に載せ、取れないものは
WARN にする（SD1/EC6 と同じ方針。異常だけ出すと「表が無い＝見ていない」と区別がつかない）。

⚠️ 閾値（時価総額 300億/1000億 等）は円建て。日本株以外は WARN「対象外」にする。

株数（KIK-787）: 時価総額は yfinance の値ではなく、yfinance と J-Quants を照合して大きい方の
株数 × 株価で出す（``reconcile_shares``）。照合できない・食い違う銘柄は、時価総額で合否が
決まる行（AV2・EV6）の PASS を WARN に下げ、出所を行末に付ける。DQ9 ``check_share_count``。
"""

from __future__ import annotations

from typing import Literal, Optional

from src.data.value_formulas import (  # noqa: F401  (re-export)
    ASSET_EQUITY_RATIO_MIN,
    ASSET_PBR_MAX,
    ASSET_PER_MAX,
    CYC_PSR_MAX,
    CYC_TARGET_PER,
    EARN_MCAP_MAX,
    EARN_MCAP_UPPER,
    EARN_OP_MARGIN_MIN,
    EARN_OP_MARGIN_RELAXED,
    EARN_PBR_MAX,
    EARN_PER_MAX,
    EARN_PER_RELAXED,
    EARN_ROA_MIN,
    GRAHAM_MAX,
    LIQUIDATION_WEIGHTS,
    PEAK_YEARS_REQUIRED,
    PEAK_ZONE,
    SHARE_DIVERGENCE_WARN,
    SHARE_OVERRIDE_RANGE,
    book_fcf,
    compute_metrics,
    cyclical_target_price,
    dcf_bear,
    dcf_bull,
    depletion_years,
    graham_index,
    liquidation_value,
    net_cash,
    other_investments,
    peak_profile,
    reconcile_shares,
    reconciled_market_cap,
    roa,
    shares_outstanding,
)

_MARK = {"PASS": "🟢", "WARN": "🟡", "FAIL": "🔴", "N/A": "・"}
_TARGET_CURRENCY = "JPY"


def _oku(v: Optional[float]) -> str:
    return "-" if v is None else f"{v / 1e8:,.0f}億"


def _item(item_id: str, header: str, rows: list[tuple[str, str, str]]) -> dict:
    """銘柄ごとの (sym, status, text) を1件の結果にまとめる。最悪の status を採る.

    N/A（参考値の表示だけ）は PASS より弱い。全行 N/A なら N/A。
    """
    from src.data.checklist_review import FAIL, NA, PASS, WARN, _result

    if not rows:
        return _result(item_id, NA, header + "候補なし")
    statuses = {s for _, s, _ in rows}
    for s in (FAIL, WARN, PASS):
        if s in statuses:
            overall = s
            break
    else:
        overall = NA
    body = " | ".join(f"{_MARK.get(s, '')} {sym} {text}" for sym, s, text in rows)
    return _result(item_id, overall, header + body)


def _m(v: Optional[float]) -> str:
    return "-" if v is None else f"{v / 1e6:.1f}M"


#: 株数を照合できていない状態（KIK-787）。時価総額で合否を決める行は PASS を WARN に下げる
_UNSETTLED = ("diverged", "unverified", "missing", "override_suspect")


def _share_text(sh: dict) -> str:
    """株数の出所（KIK-787）。時価総額・株数を使う行の末尾に付ける."""
    st = sh["status"]
    if st == "override":
        note = f"・{sh['override_note']}" if sh.get("override_note") else ""
        return f"株数: 確認値 {_m(sh['shares'])}{note}"
    if st == "override_suspect":
        ref = max(x for x in (sh["yf_shares"], sh["jq_shares"]) if x)  # suspect は ref がある時だけ
        return (f"株数: 確認値 {_m(sh['shares'])} が機械の値 {_m(ref)} と"
                f" {sh['shares'] / ref:.2f}倍ずれる。単位（百万株で入れていないか）を確認")
    if st == "ok":
        return f"株数: 照合済 {_m(sh['shares'])}（乖離{sh['divergence_pct']:.1f}%）"
    if st == "diverged":
        date = f"・{sh['jq_date']}開示" if sh.get("jq_date") else ""
        return (f"株数: yf {_m(sh['yf_shares'])} / J-Quants {_m(sh['jq_shares'])}{date}"
                f" 乖離{sh['divergence_pct']:.1f}%→大きい方。適時開示を確認")
    if st == "unverified":
        src = "yfinance" if sh["source"] == "yfinance" else "J-Quants"
        return f"株数: 未照合（{src}のみ {_m(sh['shares'])}）"
    return "株数: 取得不可"


def _rows(details: dict[str, dict], judge,
          shares: Optional[Literal["gate", "note"]] = None) -> list[tuple[str, str, str]]:
    """銘柄ごとに judge を当てる.

    shares（KIK-787）: ``"gate"`` = 時価総額で合否が決まる行。株数が未照合・乖離なら PASS を
    WARN に下げ、出所を付ける。``"note"`` = 時価総額を参考表示に使うだけの行。出所だけ付ける。
    """
    from src.data.checklist_review import PASS, WARN

    out = []
    for sym in sorted(details or {}):
        m = compute_metrics(details[sym] or {})
        cur = m["currency"]
        if cur and cur != _TARGET_CURRENCY:
            # 閾値が円建て。比較の両辺の通貨が揃っている保証もない
            out.append((sym, WARN, f"対象外（日本株のみ・通貨 {cur}）"))
            continue
        status, text = judge(m)
        if shares:
            sh = m["shares"]
            if shares == "gate" and status == PASS and sh["status"] in _UNSETTLED:
                status = WARN
            text = f"{text}［{_share_text(sh)}］"
        out.append((sym, status, text))
    return out


# ---------------------------------------------------------------------------
# 資産バリュー
# ---------------------------------------------------------------------------
def check_asset_value(details: dict[str, dict]) -> list[dict]:
    """資産バリュー AV1-AV4."""
    from src.data.checklist_review import FAIL, PASS, WARN

    def av1(m):
        g, per = m["graham_index"], m["per"]
        if g is None or per is None:
            return WARN, "PER/PBR 取得不可（赤字含む）"
        ok = g <= GRAHAM_MAX and per <= ASSET_PER_MAX
        return (PASS if ok else FAIL), f"PER×PBR {g:.1f} / PER {per:.1f}"

    def av2(m):
        liq, mc = m["liquidation_value"], m["market_cap"]
        if not mc:
            return WARN, "時価総額 取得不可"
        if liq is None:
            return WARN, "清算価値 計算不可（現預金または総負債が無い）"
        miss = f"（0扱い: {','.join(m['liquidation_missing'])}）" if m["liquidation_missing"] else ""
        return (PASS if liq > mc else FAIL), f"清算価値 {_oku(liq)} / 時価総額 {_oku(mc)} = {liq / mc:.2f}倍{miss}"

    def av3(m):
        nc, mc = m["net_cash"], m["market_cap"]
        if nc is None:
            return WARN, "NC（父娘式）計算不可（現預金または有利子負債が無い）"
        ratio = f"（時価総額の {nc / mc * 100:.0f}%）" if mc else ""
        dep = f" 枯渇{m['depletion_years']:.1f}年" if m["depletion_years"] is not None else ""
        return (PASS if nc > 0 else FAIL), f"NC（父娘式）{_oku(nc)}{ratio}{dep}"

    def av4(m):
        eq, pbr = m["equity_ratio"], m["pbr"]
        if eq is None or pbr is None:
            return WARN, "自己資本比率/PBR 取得不可"
        ok = eq >= ASSET_EQUITY_RATIO_MIN and pbr <= ASSET_PBR_MAX
        # 小数1桁: 59.6% を「60%」と丸めて FAIL を出すと、満たしているように読める（8138.T）
        return (PASS if ok else FAIL), f"自己資本 {eq * 100:.1f}% / PBR {pbr:.2f}"

    return [
        _item("AV1", f"グレアム指数≤{GRAHAM_MAX} かつ PER≤{ASSET_PER_MAX:.0f}: ", _rows(details, av1)),
        _item("AV2", "清算価値（修正資産−総負債）＞時価総額: ", _rows(details, av2, "gate")),
        _item("AV3", "NC（父娘式: 現預金+有価証券−有利子負債。清原式とは別）＞0: ", _rows(details, av3, "note")),
        _item("AV4", f"自己資本比率≥{ASSET_EQUITY_RATIO_MIN * 100:.0f}% かつ PBR≤{ASSET_PBR_MAX}: ",
              _rows(details, av4)),
    ]


# ---------------------------------------------------------------------------
# 収益バリュー
# ---------------------------------------------------------------------------
def check_earnings_value(details: dict[str, dict]) -> list[dict]:
    """収益バリュー EV1-EV6."""
    from src.data.checklist_review import FAIL, PASS, WARN

    def ev1(m):
        op = m["operating_margin"]
        if op is None:
            return WARN, "営業利益率 取得不可"
        s = PASS if op >= EARN_OP_MARGIN_MIN else WARN if op >= EARN_OP_MARGIN_RELAXED else FAIL
        return s, f"{op * 100:.1f}%" + ("（緩和）" if s == WARN else "")

    def ev2(m):
        per = m["per"]
        if per is None or per <= 0:
            return WARN, "PER 取得不可（赤字含む）"
        s = PASS if per <= EARN_PER_MAX else WARN if per <= EARN_PER_RELAXED else FAIL
        return s, f"PER {per:.1f}" + ("（緩和・上昇相場のみ）" if s == WARN else "")

    def ev3(m):
        pbr, g = m["pbr"], m["graham_index"]
        if pbr is None or g is None:
            return WARN, "PBR/グレアム指数 取得不可"
        ok = pbr <= EARN_PBR_MAX and g <= GRAHAM_MAX
        return (PASS if ok else FAIL), f"PBR {pbr:.2f} / PER×PBR {g:.1f}"

    def ev4(m):
        r = m["roa"]
        if r is None:
            return WARN, "ROA 取得不可"
        return (PASS if r >= EARN_ROA_MIN else FAIL), f"ROA {r * 100:.1f}%"

    def ev5(m):
        fcf, mc = m["book_fcf"], m["market_cap"]
        if fcf is None:
            return WARN, "FCF（営業CF−投資CF）計算不可"
        ref = []
        for label, v in (("DCF弱気", m["dcf_bear"]), ("DCF強気", m["dcf_bull"])):
            if v is not None and mc:
                ref.append(f"{label}/時価総額 {v / mc:.2f}倍")
        tail = f"（{' / '.join(ref)}）" if ref else ""
        return (PASS if fcf > 0 else FAIL), f"FCF {_oku(fcf)}{tail}"

    def ev6(m):
        mc = m["market_cap"]
        if not mc:
            return WARN, "時価総額 取得不可"
        if mc <= EARN_MCAP_MAX:
            return PASS, f"{_oku(mc)}（小型株枠: 1銘柄3%・合計10%）"
        if mc <= EARN_MCAP_UPPER:
            return WARN, f"{_oku(mc)}（本の上限1000億以内・小型株枠: 1銘柄3%・合計10%）"
        # 決定3: 当システムの上限（小型株枠・1銘柄15/25%）は守る。本の上限を超える銘柄は
        # 除外せず「緩和基準」と明記して比較表に残す
        return WARN, f"{_oku(mc)}（本の上限超・緩和基準として扱う）"

    return [
        _item("EV1", f"営業利益率≥{EARN_OP_MARGIN_MIN * 100:.0f}%（緩和{EARN_OP_MARGIN_RELAXED * 100:.0f}%）: ",
              _rows(details, ev1)),
        _item("EV2", f"PER≤{EARN_PER_MAX:.0f}（緩和{EARN_PER_RELAXED:.0f}）: ", _rows(details, ev2)),
        _item("EV3", f"PBR≤{EARN_PBR_MAX} かつ グレアム指数≤{GRAHAM_MAX}: ", _rows(details, ev3)),
        _item("EV4", f"ROA（純利益÷総資産）≥{EARN_ROA_MIN * 100:.0f}%: ", _rows(details, ev4)),
        _item("EV5", "FCF（営業CF−投資CF・直近期）＞0: ", _rows(details, ev5, "note")),
        _item("EV6", "時価総額≤300億（上限1000億）: ", _rows(details, ev6, "gate")),
    ]


# ---------------------------------------------------------------------------
# シクリカル
# ---------------------------------------------------------------------------
def check_peak_trap(details: dict[str, dict]) -> list[dict]:
    """CY0 最高益の罠だけを返す。型に関係なく、低PERを割安と言う前に通す."""
    from src.data.checklist_review import PASS, WARN

    def cy0(m):
        p = m["peak"]
        if not p["years"]:
            return WARN, "純利益の履歴なし"
        span = f"{p['years']}年分（本は{PEAK_YEARS_REQUIRED}〜20年）"
        if p["latest"] < 0:
            return PASS, f"直近赤字（谷側）・{span}"
        if p["latest_is_peak"]:
            return WARN, f"直近=最高益（ピークの安さの疑い）・{span}"
        pct = f"{p['latest'] / p['peak'] * 100:.0f}%"
        if p["in_peak_zone"]:
            return WARN, f"最高益の {pct}（最高益圏）・{span}"
        return PASS, f"最高益の {pct}・{span}"

    return [_item("CY0", f"最高益の罠（直近が最高益の{PEAK_ZONE * 100:.0f}%以上か）: ", _rows(details, cy0))]


def check_cyclical_peak(details: dict[str, dict]) -> list[dict]:
    """シクリカルの機械判定: CY0 最高益の罠 / CY2 PSR / CY5 逆算目標株価（参考値）."""
    from src.data.checklist_review import FAIL, NA, PASS, WARN

    def cy2(m):
        psr = m["psr"]
        if psr is None:
            return WARN, "PSR 取得不可"
        return (PASS if psr <= CYC_PSR_MAX else FAIL), f"PSR {psr:.2f}"

    def cy5(m):
        tp, px = m["cyclical_target_price"], m["price"]
        if not px:
            return WARN, "逆算目標株価 計算不可（株価が無い）"
        if tp is None:
            return WARN, "逆算目標株価 計算不可（黒字の履歴または時価総額が無い）"
        # 参考値なので N/A（満たした/満たさないの判定ではない）
        return NA, (f"参考: 履歴最高益EPS×{CYC_TARGET_PER:.0f} = ¥{tp:,.0f}（現値比 {tp / px:.2f}倍）"
                    "※ピーク利益は数量×価格で試算し直すこと")

    return check_peak_trap(details) + [
        _item("CY2", f"PSR≤{CYC_PSR_MAX}: ", _rows(details, cy2)),
        _item("CY5", f"逆算目標株価（ピークEPS×PER{CYC_TARGET_PER:.0f}）: ", _rows(details, cy5, "note")),
    ]


# ---------------------------------------------------------------------------
# 株数照合（KIK-787）
# ---------------------------------------------------------------------------
def check_share_count(details: dict[str, dict]) -> list[dict]:
    """DQ9 株数照合: yfinance と J-Quants（最新短信の発行済−自己株）の株数が合っているか.

    先に ``share_count.attach_share_counts(details)`` を呼ぶ（呼ばないと全銘柄が未照合で WARN）。
    WARN なら適時開示（第三者割当・公募・自己株処分・消却）を見て、確認した株数を
    detail の ``shares_override`` に入れて判定し直す。
    ⚠️ 照合済（ok）でも、期末より後の増資は両方の出所に出てこないことがある。
    """
    from src.data.checklist_review import PASS, WARN

    def dq9(m):
        sh = m["shares"]
        status = WARN if sh["status"] in _UNSETTLED else PASS
        return status, _share_text(sh)

    return [_item("DQ9", f"株数照合（yfinance と J-Quants の差 ≤{SHARE_DIVERGENCE_WARN * 100:.0f}%（小さい方比）・"
                         "大きい方で時価総額を計算）: ", _rows(details, dq9))]
