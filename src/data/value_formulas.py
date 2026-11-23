"""3類型バリュー（資産・収益・シクリカル）の式（KIK-786）.

出典: NotebookLM「father-daughter-value-investin」
（『50万円を50億円に増やした 投資家の父から娘への教え』）。式は原文どおり。
方針と決定は lesson note_2026-11-23_general_9ac8dd74。チェック（PASS/WARN/FAIL）は
``src/data/value_types.py``。

入力は ``get_stock_detail()`` の dict（KIK-786 で決算書の項目を追加済み）。取得はしない。

⚠️ ここで言う「ネットキャッシュ」は**父娘式**（現預金 + 有価証券 − 有利子負債）。
清原式（ネットキャッシュ比率・NotebookLM の清原ノート）とは別の式。出力では「NC（父娘式）」と書く。

欠損の扱い（判定を甘くする方向に倒さない）:
  - 有利子負債・現預金が取れない → ネットキャッシュは None（0 で埋めると過大になる）
  - 投資有価証券・売掛金・棚卸資産・有形固定資産が取れない → 0 として足す
    （資産が小さく出る＝保守的。何を欠いたかは ``missing`` に残す）
  - 有形・無形・固定資産合計のどれかが取れない → 投資等を 0 にする。差し引きで出す値なので、
    無形（掛目0%）が欠けると、のれんが投資等（50%）に流れ込んで清算価値が甘くなる
  - 総負債が取れない → 清算価値は None
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# 閾値（原文の数値）
# ---------------------------------------------------------------------------
GRAHAM_MAX = 22.5            # PER × PBR
ASSET_PBR_MAX = 0.5
ASSET_EQUITY_RATIO_MIN = 0.60
ASSET_PER_MAX = 12.0

EARN_OP_MARGIN_MIN = 0.10    # 緩和 8〜9%
EARN_OP_MARGIN_RELAXED = 0.08
EARN_PER_MAX = 10.0          # 上昇相場は 15 まで
EARN_PER_RELAXED = 15.0
EARN_PBR_MAX = 1.5
EARN_ROA_MIN = 0.07
EARN_MCAP_MAX = 300e8        # 300億円
EARN_MCAP_UPPER = 1000e8     # 上限でも 1000億円（= 当システムの小型株の境界）

CYC_PSR_MAX = 0.5
CYC_TARGET_PER = 5.0         # 逆算PER（名村造船所の例）

DCF_DISCOUNT = 0.10          # 割引率 R
DCF_BULL_GROWTH = 0.20       # 強気: 5年間 年20%成長
DCF_BULL_YEARS = 5

PEAK_YEARS_REQUIRED = 10     # 本は過去10〜20年の最高益と比べる
#: 直近が最高益のこの割合以上なら「最高益圏」とみなす（KIK-786 レビュー。
#: 99% でも等号で判定すると PASS になり、「今業績が好調な会社は買わない」に対して甘い）
PEAK_ZONE = 0.80

#: 清算価値の掛目（修正資産）
LIQUIDATION_WEIGHTS = {
    "cash_and_st_investments": 1.00,   # 現金及び預金
    "investment_securities": 1.00,     # 有価証券
    "accounts_receivable": 0.85,       # 受取手形及び売掛金
    "inventory": 0.50,                 # 棚卸資産
    "other_investments": 0.50,         # 投資等
    "net_ppe": 0.50,                   # 有形固定資産
    "intangibles": 0.00,               # 無形固定資産
}


def _num(x) -> Optional[float]:
    """float にできて NaN でなければその値（負値も通す）。それ以外は None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ---------------------------------------------------------------------------
# 式
# ---------------------------------------------------------------------------
def graham_index(per, pbr) -> Optional[float]:
    """PER × PBR。赤字（PER<=0）や PBR<=0 では意味を持たないので None."""
    per, pbr = _num(per), _num(pbr)
    if per is None or pbr is None or per <= 0 or pbr <= 0:
        return None
    return per * pbr


def net_cash(d: dict) -> Optional[float]:
    """NC（父娘式）= 現預金 + 有価証券 − 有利子負債。現預金か有利子負債が無ければ None."""
    cash = _num(d.get("cash_and_st_investments"))
    debt = _num(d.get("interest_bearing_debt"))
    if cash is None or debt is None:
        return None
    return cash + (_num(d.get("investment_securities")) or 0.0) - debt


def other_investments(d: dict) -> Optional[float]:
    """投資等 = 固定資産合計 − 有形 − 無形 − 投資有価証券（下限0）.

    投資有価証券は掛目100%で別に数えるので、ここから引いて二重計上を避ける。
    固定資産合計・有形・無形のどれかが取れなければ None（呼び出し側で 0 として扱う）。
    差し引きで出す値なので、欠けた項目がそのまま投資等（50%）に流れ込むのを防ぐ。
    投資有価証券の欠損は 100%→50% に下がるだけ（保守的）なので 0 として引く。
    """
    total = _num(d.get("total_non_current_assets"))
    ppe, intang = _num(d.get("net_ppe")), _num(d.get("intangibles"))
    if total is None or ppe is None or intang is None:
        return None
    rest = total - ppe - intang - (_num(d.get("investment_securities")) or 0.0)
    return max(rest, 0.0)


def liquidation_value(d: dict) -> tuple[Optional[float], list[str]]:
    """清算価値 = 修正資産 − 総負債。戻り値は (値, 0 として扱った項目)."""
    liabilities = _num(d.get("total_liabilities"))
    if _num(d.get("cash_and_st_investments")) is None or liabilities is None:
        return None, []
    missing = []
    adjusted = 0.0
    for key, w in LIQUIDATION_WEIGHTS.items():
        v = other_investments(d) if key == "other_investments" else _num(d.get(key))
        if v is None:
            missing.append(key)
            v = 0.0
        adjusted += v * w
    return adjusted - liabilities, missing


def book_fcf(d: dict) -> Optional[float]:
    """本の FCF = 営業CF − 投資CF（投資CF は通常マイナスなので足し算になる）.

    既存の ``fcf``（yfinance の Free Cash Flow = 営業CF − 設備投資）とは別物。直近1期だけ。
    """
    ocf, icf = _num(d.get("operating_cashflow")), _num(d.get("investing_cashflow"))
    if ocf is None or icf is None:
        return None
    return ocf + icf   # icf は符号付き（支出がマイナス）


def dcf_bear(nc: Optional[float], fcf: Optional[float]) -> Optional[float]:
    """弱気: ネットキャッシュ + FCF ÷ R（成長なし）."""
    if nc is None or fcf is None:
        return None
    return nc + fcf / DCF_DISCOUNT


def dcf_bull(nc: Optional[float], fcf: Optional[float]) -> Optional[float]:
    """強気: ネットキャッシュ + 5年間 年20%成長の FCF の現在価値 + 6年目以降 FCF ÷ R.

    FCF が 0 以下のときは「マイナスが20%ずつ増える」計算になり意味を持たないので None。
    """
    if nc is None or fcf is None or fcf <= 0:
        return None
    r, g, n = DCF_DISCOUNT, DCF_BULL_GROWTH, DCF_BULL_YEARS
    pv = sum(fcf * (1 + g) ** t / (1 + r) ** t for t in range(1, n + 1))
    terminal = fcf * (1 + g) ** n / r / (1 + r) ** n
    return nc + pv + terminal


def depletion_years(d: dict, nc: Optional[float]) -> Optional[float]:
    """枯渇年数 = ネットキャッシュ ÷ 年間赤字。赤字（純損失 or 営業CF マイナス）のときだけ.

    両方マイナスなら大きい方の赤字で割る（保守的）。
    """
    if nc is None:
        return None
    losses = [-v for v in (_num(d.get("net_income_stmt")), _num(d.get("operating_cashflow")))
              if v is not None and v < 0]
    if not losses:
        return None
    return max(nc, 0.0) / max(losses)


def roa(d: dict) -> Optional[float]:
    """ROA = 当期純利益 ÷ 総資産（本の定義）。取れなければ yfinance の roa."""
    ni, ta = _num(d.get("net_income_stmt")), _num(d.get("total_assets"))
    if ni is not None and ta:
        return ni / ta
    return _num(d.get("roa"))


def peak_profile(net_income_history) -> dict:
    """純利益の履歴（新しい順）から、直近が最高益（圏）かを見る.

    ⚠️ yfinance の履歴は4年程度しかない。本は過去10〜20年の最高益と比べる。
    ``years`` を必ず返し、足りないことを出力で隠さない。
    """
    hist = [v for v in (_num(x) for x in (net_income_history or [])) if v is not None]
    if not hist:
        return {"years": 0, "latest": None, "peak": None, "latest_is_peak": None,
                "in_peak_zone": None, "peak_to_latest": None, "has_loss": None}
    latest, peak = hist[0], max(hist)
    return {
        "years": len(hist),
        "latest": latest,
        "peak": peak,
        "latest_is_peak": latest >= peak,
        "in_peak_zone": peak > 0 and latest >= peak * PEAK_ZONE,
        "peak_to_latest": (peak / latest) if latest > 0 else None,
        "has_loss": min(hist) < 0,
    }


def shares_outstanding(d: dict) -> Optional[float]:
    mc, px = _num(d.get("market_cap")), _num(d.get("price"))
    if not mc or not px:
        return None
    return mc / px


def cyclical_target_price(d: dict, target_per: float = CYC_TARGET_PER) -> Optional[float]:
    """目標株価 = 想定ピークEPS × 逆算PER（既定 5）.

    想定ピークEPS は、見られる履歴の最高純利益 ÷ 発行済株式数で近似する。
    ⚠️ 本は「ピーク時に出せる利益を数量×価格で試算する」。履歴の最高値は代用にすぎない。
    """
    prof = peak_profile(d.get("net_income_history"))
    shares = shares_outstanding(d)
    if not prof["peak"] or prof["peak"] <= 0 or not shares:
        return None
    return prof["peak"] / shares * target_per


def compute_metrics(d: dict) -> dict:
    """1銘柄の式をまとめて計算する（判定はしない）."""
    nc = net_cash(d)
    liq, liq_missing = liquidation_value(d)
    fcf = book_fcf(d)
    return {
        "currency": d.get("currency"),
        "market_cap": _num(d.get("market_cap")),
        "price": _num(d.get("price")),
        "per": _num(d.get("per")),
        "pbr": _num(d.get("pbr")),
        "psr": _num(d.get("psr")),
        "operating_margin": _num(d.get("operating_margin")),
        "equity_ratio": _num(d.get("equity_ratio")),
        "graham_index": graham_index(d.get("per"), d.get("pbr")),
        "net_cash": nc,
        "liquidation_value": liq,
        "liquidation_missing": liq_missing,
        "book_fcf": fcf,
        "dcf_bear": dcf_bear(nc, fcf),
        "dcf_bull": dcf_bull(nc, fcf),
        "depletion_years": depletion_years(d, nc),
        "roa": roa(d),
        "peak": peak_profile(d.get("net_income_history")),
        "cyclical_target_price": cyclical_target_price(d),
        "balance_sheet_date": d.get("balance_sheet_date"),
    }
