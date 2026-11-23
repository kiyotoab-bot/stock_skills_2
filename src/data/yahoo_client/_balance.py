"""3類型バリューの式に要る決算書の項目を取り出す（KIK-786）.

資産バリュー（ネットキャッシュ・清算価値）と収益バリュー（本の FCF = 営業CF − 投資CF）は、
既存の stock_detail が持っていない貸借対照表・キャッシュフローの行を使う。
detail.py は既に大きいので、行名の対応表とその取り出しだけをここに置く。

⚠️ 計算はしない（``src/data/value_types.py`` の仕事）。取れなかった項目は None で返し、
計算側が「データ不足」として扱う。0 で埋めると、たとえば有利子負債が取れなかった銘柄の
ネットキャッシュが過大になり、資産バリューの判定を誤らせる。
"""

from __future__ import annotations

from typing import Any, Optional

from src.data.yahoo_client._frames import _try_get_field as _field


def _sum_present(*values: Optional[float]) -> Optional[float]:
    """取れた値だけ足す。1つも取れなければ None（0 にしない）."""
    got = [v for v in values if v is not None]
    return sum(got) if got else None


def _period_date(df: Any) -> Optional[str]:
    try:
        if df is None or df.empty:
            return None
        return str(df.columns[0])[:10]
    except Exception:
        return None


def _interest_bearing_debt(bs: Any) -> Optional[float]:
    """有利子負債 = 短期借入金 + 長期借入金（本の定義。リース債務は除く）.

    判定を甘くしない向きに倒す（KIK-786 レビュー）:
      - 短期・長期の**両方**が取れたときだけ和を候補にする。片方だけの和は長期借入金を
        落としてネットキャッシュを過大にする（実例: 7427.T は Long Term Debt 行が無い）
      - Total Debt − リース債務 も候補にし、取れた候補の**大きい方**を採る
      - どちらも無ければ None（0 で埋めない）
    無借金の銘柄は行が 0 で返る（8138.T: Total Debt 0 / Current Debt 0）ので None にはならない。
    """
    current = _field(bs, ["Current Debt"])
    long_term = _field(bs, ["Long Term Debt"])
    candidates = []
    if current is not None and long_term is not None:
        candidates.append(current + long_term)
    total = _field(bs, ["Total Debt"])
    if total is not None:
        lease = _field(bs, ["Capital Lease Obligations"]) or 0.0
        candidates.append(max(total - lease, 0.0))
    return max(candidates) if candidates else None


def extract_value_items(bs: Any, cf: Any) -> dict:
    """最新期の貸借対照表 ``bs`` とキャッシュフロー計算書 ``cf`` から項目を取り出す.

    Returns
    -------
    dict
        cash_and_st_investments : 現預金 + 短期投資（本の「現預金」）
        investment_securities   : 投資有価証券（関連会社株式を含む。本の「有価証券」）
        accounts_receivable     : 受取手形及び売掛金
        inventory               : 棚卸資産
        net_ppe                 : 有形固定資産（純額）
        intangibles             : 無形固定資産（のれん含む）
        total_non_current_assets: 固定資産合計
        total_liabilities       : 負債合計（非支配株主持分を除く）
        interest_bearing_debt   : 有利子負債 = 短期借入金 + 長期借入金（リース債務は除く）
        investing_cashflow      : 投資活動によるキャッシュフロー
        balance_sheet_date      : 貸借対照表の期末日（YYYY-MM-DD）
    """
    cash = _field(bs, ["Cash Cash Equivalents And Short Term Investments"])
    if cash is None:
        cash = _sum_present(
            _field(bs, ["Cash And Cash Equivalents", "Cash"]),
            _field(bs, ["Other Short Term Investments", "Short Term Investments"]),
        )

    # 子行（金融資産 + 持分法投資）だけを足す。親行 Investments And Advances は
    # 投資不動産・長期貸付金（Other Investments）を含みうるので使わない（KIK-786 レビュー。
    # 8031.T は Investment Properties 1,853億・Other Investments 2.8兆を別行で持つ）
    securities = _sum_present(
        _field(bs, ["Investmentin Financial Assets", "Available For Sale Securities"]),
        _field(bs, ["Long Term Equity Investment"]),
    )

    receivable = _sum_present(
        _field(bs, ["Accounts Receivable", "Gross Accounts Receivable"]),
        _field(bs, ["Notes Receivable"]),
    )

    intangibles = _field(bs, ["Goodwill And Other Intangible Assets"])
    if intangibles is None:
        intangibles = _sum_present(
            _field(bs, ["Goodwill"]),
            _field(bs, ["Other Intangible Assets"]),
        )

    return {
        "cash_and_st_investments": cash,
        "investment_securities": securities,
        "accounts_receivable": receivable,
        "inventory": _field(bs, ["Inventory"]),
        "net_ppe": _field(bs, ["Net PPE"]),
        "intangibles": intangibles,
        "total_non_current_assets": _field(bs, ["Total Non Current Assets"]),
        "total_liabilities": _field(bs, [
            "Total Liabilities Net Minority Interest",
            "Total Liab",
        ]),
        "interest_bearing_debt": _interest_bearing_debt(bs),
        "investing_cashflow": _field(cf, [
            "Investing Cash Flow",
            "Cash Flow From Continuing Investing Activities",
            "Total Cashflows From Investing Activities",
        ]),
        "balance_sheet_date": _period_date(bs),
    }


#: detail の result に必ず入れるキー（取得に失敗しても None で揃える）
VALUE_ITEM_KEYS = tuple(extract_value_items(None, None))
