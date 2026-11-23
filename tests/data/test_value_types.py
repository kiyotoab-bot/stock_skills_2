"""3類型バリューの式と機械チェックのテスト（KIK-786）."""

import pandas as pd
import pytest

from src.data import checklist_review as CR
from src.data import value_formulas as F
from src.data import value_types as V
from src.data.yahoo_client import _balance as B

M = 1e6  # 百万円
PASS, WARN, FAIL, NA = CR.PASS, CR.WARN, CR.FAIL, CR.NA


# 1926.T ライト工業 2026-03 期の実データ（百万円）。手計算の検算値を固定する。
# PER は yfinance info の TTM 値（11.673）。時価総額 ÷ 当期純利益（12.60）とは期間が違う。
# AV1 の PER≤12 はこの取り方に依存する境界ぎりぎりの値であることに注意
def _raito(**over):
    d = {
        "currency": "JPY",
        "market_cap": 157_377 * M,
        "price": 958.0,
        "per": 11.673,
        "pbr": 1.790,
        "psr": 1.115,
        "operating_margin": 0.1393,
        "equity_ratio": 0.7147,
        "net_income_stmt": 12_487 * M,
        "total_assets": 125_930 * M,
        "operating_cashflow": 13_662 * M,
        "investing_cashflow": -1_885 * M,
        "net_income_history": [12_487 * M, 9_919 * M, 8_181 * M, 9_489 * M],
        "cash_and_st_investments": 29_975 * M,
        "investment_securities": 10_026 * M,
        "accounts_receivable": 40_737 * M,
        "inventory": 2_278 * M,
        "net_ppe": 26_661 * M,
        "intangibles": 625 * M,
        "total_non_current_assets": 45_890 * M,
        "total_liabilities": 35_046 * M,
        "interest_bearing_debt": 1_744 * M,
        "balance_sheet_date": "2026-03-31",
    }
    d.update(over)
    return d


def _by_id(results):
    return {r["id"]: r for r in results}


def _status(fn, item, **over):
    return _by_id(fn({"X": _raito(**over)}))[item]["status"]


# ---------------------------------------------------------------------------
# 式
# ---------------------------------------------------------------------------
class TestFormulas:
    def test_net_cash_matches_hand_calc(self):
        # 29,975 + 10,026 − (1,737 + 7) = 38,257
        assert F.net_cash(_raito()) == pytest.approx(38_257 * M)

    def test_liquidation_value_matches_hand_calc(self):
        # 29,975 + 10,026 + 0.85×40,737 + 0.5×2,278 + 0.5×8,578 + 0.5×26,661 − 35,046
        value, missing = F.liquidation_value(_raito())
        assert value == pytest.approx(58_339.95 * M)   # 0.85×40,737 = 34,626.45
        assert missing == []

    def test_other_investments_excludes_securities_and_floors_at_zero(self):
        assert F.other_investments(_raito()) == pytest.approx(8_578 * M)
        assert F.other_investments(_raito(total_non_current_assets=1 * M)) == 0.0

    @pytest.mark.parametrize("key", ["total_non_current_assets", "net_ppe", "intangibles"])
    def test_other_investments_none_when_component_missing(self, key):
        assert F.other_investments(_raito(**{key: None})) is None

    def test_missing_intangibles_does_not_raise_liquidation_value(self):
        # 無形（0%）が欠けたとき、のれんが投資等（50%）に流れ込まないこと（レビュー must）
        base, _ = F.liquidation_value(_raito())
        value, missing = F.liquidation_value(_raito(intangibles=None))
        assert value <= base
        assert value == pytest.approx(base - 0.5 * 8_578 * M)   # 投資等が 0 になる
        assert "other_investments" in missing and "intangibles" in missing

    def test_missing_net_ppe_is_conservative(self):
        base, _ = F.liquidation_value(_raito())
        value, missing = F.liquidation_value(_raito(net_ppe=None))
        # 有形 50%・投資等 50% の両方が 0 になる
        assert value == pytest.approx(base - 0.5 * 26_661 * M - 0.5 * 8_578 * M)
        assert {"net_ppe", "other_investments"} <= set(missing)

    def test_missing_securities_is_conservative(self):
        # 有価証券の欠損は 100% → 投資等 50% に下がるだけ
        base, _ = F.liquidation_value(_raito())
        value, missing = F.liquidation_value(_raito(investment_securities=None))
        assert value == pytest.approx(base - 10_026 * M + 0.5 * 10_026 * M)
        assert missing == ["investment_securities"]

    def test_net_cash_none_when_debt_or_cash_missing(self):
        # 有利子負債を 0 で埋めると過大になる → None
        assert F.net_cash(_raito(interest_bearing_debt=None)) is None
        assert F.net_cash(_raito(cash_and_st_investments=None)) is None
        assert F.net_cash(_raito(interest_bearing_debt=float("nan"))) is None

    def test_net_cash_treats_missing_securities_as_zero(self):
        assert F.net_cash(_raito(investment_securities=None)) == pytest.approx((29_975 - 1_744) * M)

    def test_liquidation_none_without_liabilities_or_cash(self):
        assert F.liquidation_value(_raito(total_liabilities=None)) == (None, [])
        assert F.liquidation_value(_raito(cash_and_st_investments=None)) == (None, [])

    def test_graham_index(self):
        assert F.graham_index(10, 2) == 20
        assert F.graham_index(-5, 1) is None
        assert F.graham_index(5, 0) is None
        assert F.graham_index(None, 1) is None
        assert F.graham_index("abc", 1) is None

    def test_book_fcf_is_ocf_minus_investing(self):
        assert F.book_fcf(_raito()) == pytest.approx(11_777 * M)
        assert F.book_fcf(_raito(investing_cashflow=None)) is None

    def test_dcf_bear(self):
        assert F.dcf_bear(100.0, 10.0) == pytest.approx(200.0)
        assert F.dcf_bear(None, 10.0) is None

    def test_dcf_bull(self):
        fcf, nc = 10.0, 0.0
        expected = sum(fcf * 1.2 ** t / 1.1 ** t for t in range(1, 6)) + fcf * 1.2 ** 5 / 0.1 / 1.1 ** 5
        assert F.dcf_bull(nc, fcf) == pytest.approx(expected)
        assert F.dcf_bull(nc, fcf) > F.dcf_bear(nc, fcf)

    @pytest.mark.parametrize("fcf", [-5.0, 0.0])
    def test_dcf_bull_none_for_non_positive_fcf(self, fcf):
        assert F.dcf_bull(100.0, fcf) is None

    def test_depletion_only_when_loss(self):
        assert F.depletion_years(_raito(), 100.0) is None
        d = _raito(net_income_stmt=-10.0, operating_cashflow=-25.0)
        assert F.depletion_years(d, 100.0) == pytest.approx(4.0)  # 大きい方の赤字で割る
        assert F.depletion_years(d, -50.0) == 0.0
        assert F.depletion_years(d, None) is None

    def test_roa_uses_net_income_over_assets(self):
        assert F.roa(_raito()) == pytest.approx(12_487 / 125_930)
        assert F.roa({"roa": 0.05}) == 0.05
        assert F.roa({"net_income_stmt": 5.0, "total_assets": 0, "roa": 0.03}) == 0.03

    def test_peak_profile(self):
        p = F.peak_profile([12.0, 9.0, 8.0, 9.0])
        assert p["years"] == 4 and p["latest_is_peak"] is True and p["has_loss"] is False
        assert p["in_peak_zone"] is True
        p = F.peak_profile([1.0, 40.0, -3.0])
        assert p["latest_is_peak"] is False and p["peak_to_latest"] == 40.0 and p["has_loss"]
        assert p["in_peak_zone"] is False
        assert F.peak_profile([])["years"] == 0
        assert F.peak_profile([float("nan"), 5.0])["years"] == 1
        assert F.peak_profile([0.0, 5.0])["peak_to_latest"] is None
        assert F.peak_profile([0.0, 0.0])["in_peak_zone"] is False

    def test_cyclical_target_price(self):
        # 最高純利益 12,487百万 ÷ (時価総額/株価) × 5
        shares = 157_377 * M / 958.0
        assert F.cyclical_target_price(_raito()) == pytest.approx(12_487 * M / shares * 5)
        assert F.cyclical_target_price(_raito(net_income_history=[-1.0, -2.0])) is None
        assert F.cyclical_target_price(_raito(price=None)) is None

    def test_compute_metrics_keys(self):
        m = F.compute_metrics(_raito())
        for key in ("graham_index", "net_cash", "liquidation_value", "book_fcf", "dcf_bear",
                    "dcf_bull", "depletion_years", "roa", "peak", "cyclical_target_price", "currency"):
            assert key in m

    def test_value_types_reexports_formulas(self):
        assert V.net_cash is F.net_cash and V.compute_metrics is F.compute_metrics


# ---------------------------------------------------------------------------
# チェック
# ---------------------------------------------------------------------------
class TestAggregation:
    def test_empty_is_na(self):
        for fn in (V.check_asset_value, V.check_earnings_value, V.check_cyclical_peak, V.check_peak_trap):
            assert all(r["status"] == NA for r in fn({}))

    @pytest.mark.parametrize("statuses,expected", [
        ([PASS, PASS], PASS), ([WARN, PASS], WARN), ([FAIL, PASS], FAIL),
        ([FAIL, WARN], FAIL), ([NA, PASS], PASS), ([NA, NA], NA),
    ])
    def test_item_worst_status_wins(self, statuses, expected):
        rows = [(f"S{i}", s, "t") for i, s in enumerate(statuses)]
        assert V._item("X1", "h: ", rows)["status"] == expected

    def test_all_symbols_listed_sorted(self):
        r = _by_id(V.check_asset_value({"9999.T": _raito(market_cap=1 * M), "1926.T": _raito()}))
        detail = r["AV2"]["detail"]
        assert r["AV2"]["status"] == FAIL
        assert detail.index("1926.T") < detail.index("9999.T")

    def test_none_detail_is_warn_everywhere(self):
        # get_stock_detail() は失敗すると None を返す
        for fn in (V.check_asset_value, V.check_earnings_value, V.check_cyclical_peak):
            assert all(r["status"] == WARN for r in fn({"X": None}))

    def test_non_jpy_is_out_of_scope(self):
        for fn in (V.check_asset_value, V.check_earnings_value, V.check_cyclical_peak):
            results = fn({"AAPL": _raito(currency="USD")})
            assert all(r["status"] == WARN and "対象外" in r["detail"] for r in results)


class TestAssetValue:
    def test_raito(self):
        r = _by_id(V.check_asset_value({"1926.T": _raito()}))
        assert r["AV1"]["status"] == PASS   # 20.9 ≤ 22.5, PER 11.7 ≤ 12
        assert r["AV2"]["status"] == FAIL and "0.37倍" in r["AV2"]["detail"]
        assert r["AV3"]["status"] == PASS and "時価総額の 24%" in r["AV3"]["detail"]
        assert "父娘式" in r["AV3"]["detail"]
        assert r["AV4"]["status"] == FAIL   # PBR 1.79

    def test_deep_value_passes(self):
        d = _raito(market_cap=20_000 * M, pbr=0.4, per=8.0)
        r = _by_id(V.check_asset_value({"9999.T": d}))
        assert all(r[k]["status"] == PASS for k in ("AV1", "AV2", "AV3", "AV4"))

    @pytest.mark.parametrize("per,pbr,expected", [
        (9.0, 2.5, PASS),     # 22.5 ちょうど
        (12.0, 1.0, PASS),    # PER 12 ちょうど
        (13.0, 1.0, FAIL),
        (10.0, 2.6, FAIL),
    ])
    def test_av1_boundaries(self, per, pbr, expected):
        assert _status(V.check_asset_value, "AV1", per=per, pbr=pbr) == expected

    def test_av2_equal_is_fail(self):
        liq, _ = F.liquidation_value(_raito())
        assert _status(V.check_asset_value, "AV2", market_cap=liq) == FAIL   # > は厳密

    def test_av2_missing_market_cap_reason(self):
        r = _by_id(V.check_asset_value({"X": _raito(market_cap=None)}))["AV2"]
        assert r["status"] == WARN and "時価総額" in r["detail"]

    def test_av2_reports_zeroed_items(self):
        r = _by_id(V.check_asset_value({"X": _raito(inventory=None)}))["AV2"]
        assert "0扱い: inventory" in r["detail"]

    def test_av3_zero_and_negative_fail(self):
        assert _status(V.check_asset_value, "AV3", interest_bearing_debt=(29_975 + 10_026) * M) == FAIL
        assert _status(V.check_asset_value, "AV3", interest_bearing_debt=90_000 * M) == FAIL

    def test_av3_depletion_shown_for_loss(self):
        r = _by_id(V.check_asset_value({"X": _raito(net_income_stmt=-1_000 * M)}))["AV3"]
        assert "枯渇" in r["detail"]

    @pytest.mark.parametrize("eq,pbr,expected", [(0.60, 0.5, PASS), (0.59, 0.4, FAIL), (0.7, 0.51, FAIL)])
    def test_av4_boundaries(self, eq, pbr, expected):
        assert _status(V.check_asset_value, "AV4", equity_ratio=eq, pbr=pbr) == expected

    def test_nan_and_string_are_warn(self):
        assert _status(V.check_asset_value, "AV1", per=float("nan")) == WARN
        assert _status(V.check_asset_value, "AV1", per="abc") == WARN
        assert _status(V.check_asset_value, "AV3", interest_bearing_debt=float("nan")) == WARN


class TestEarningsValue:
    def test_raito(self):
        r = _by_id(V.check_earnings_value({"1926.T": _raito()}))
        assert r["EV1"]["status"] == PASS
        assert r["EV2"]["status"] == WARN   # 11.7 は緩和
        assert r["EV3"]["status"] == FAIL   # PBR 1.79
        assert r["EV4"]["status"] == PASS
        assert r["EV5"]["status"] == PASS and "DCF弱気/時価総額 0.99倍" in r["EV5"]["detail"]
        assert "DCF強気" in r["EV5"]["detail"]
        assert r["EV6"]["status"] == WARN and "上限超" in r["EV6"]["detail"]

    @pytest.mark.parametrize("op,expected", [(0.12, PASS), (0.10, PASS), (0.085, WARN),
                                             (0.08, WARN), (0.05, FAIL), (None, WARN)])
    def test_ev1(self, op, expected):
        assert _status(V.check_earnings_value, "EV1", operating_margin=op) == expected

    @pytest.mark.parametrize("per,expected", [(8.0, PASS), (10.0, PASS), (15.0, WARN),
                                              (20.0, FAIL), (-3.0, WARN), (None, WARN)])
    def test_ev2(self, per, expected):
        assert _status(V.check_earnings_value, "EV2", per=per) == expected

    @pytest.mark.parametrize("pbr,expected", [(1.5, PASS), (0.8, PASS), (1.6, FAIL), (None, WARN)])
    def test_ev3(self, pbr, expected):
        assert _status(V.check_earnings_value, "EV3", pbr=pbr, per=10.0) == expected

    def test_ev4(self):
        assert _status(V.check_earnings_value, "EV4", net_income_stmt=7.0, total_assets=100.0) == PASS
        assert _status(V.check_earnings_value, "EV4", net_income_stmt=6.0, total_assets=100.0) == FAIL
        assert _status(V.check_earnings_value, "EV4", net_income_stmt=None, total_assets=None) == WARN

    def test_ev5(self):
        assert _status(V.check_earnings_value, "EV5", investing_cashflow=-13_662 * M) == FAIL   # FCF 0
        r = _by_id(V.check_earnings_value({"X": _raito(investing_cashflow=-20_000 * M)}))["EV5"]
        assert r["status"] == FAIL and "DCF強気" not in r["detail"]
        assert _status(V.check_earnings_value, "EV5", investing_cashflow=None) == WARN

    @pytest.mark.parametrize("mc,expected,word", [
        (200e8, PASS, "小型株枠"), (300e8, PASS, "小型株枠"),
        (800e8, WARN, "上限1000億以内"), (1000e8, WARN, "上限1000億以内"),
        (2000e8, WARN, "上限超"), (None, WARN, "取得不可"),
    ])
    def test_ev6_market_cap_bands(self, mc, expected, word):
        r = _by_id(V.check_earnings_value({"X": _raito(market_cap=mc)}))["EV6"]
        assert r["status"] == expected and word in r["detail"]


class TestCyclical:
    def test_peak_trap_raito(self):
        r = _by_id(V.check_peak_trap({"X": _raito()}))["CY0"]
        assert r["status"] == WARN
        assert "4年分" in r["detail"] and "10〜20年" in r["detail"]

    def test_near_peak_is_warn(self):
        # 最高益の 90%（等号でないが最高益圏）
        r = _by_id(V.check_peak_trap({"X": _raito(net_income_history=[9.0, 10.0, 5.0])}))["CY0"]
        assert r["status"] == WARN and "最高益圏" in r["detail"]

    def test_trough_and_loss_pass(self):
        r = _by_id(V.check_peak_trap({"X": _raito(net_income_history=[2.0, 40.0, 20.0])}))["CY0"]
        assert r["status"] == PASS and "最高益の 5%" in r["detail"]
        r = _by_id(V.check_peak_trap({"X": _raito(net_income_history=[-5.0, 10.0])}))["CY0"]
        assert r["status"] == PASS and "赤字" in r["detail"]

    def test_no_history_is_warn(self):
        assert _status(V.check_peak_trap, "CY0", net_income_history=[]) == WARN

    def test_cyclical_peak_includes_cy0(self):
        ids = [r["id"] for r in V.check_cyclical_peak({"X": _raito()})]
        assert ids == ["CY0", "CY2", "CY5"]

    @pytest.mark.parametrize("psr,expected", [(0.5, PASS), (0.3, PASS), (1.115, FAIL), (None, WARN)])
    def test_cy2(self, psr, expected):
        assert _status(V.check_cyclical_peak, "CY2", psr=psr) == expected

    def test_cy5_is_reference_value(self):
        r = _by_id(V.check_cyclical_peak({"X": _raito()}))["CY5"]
        assert r["status"] == NA
        assert "¥380" in r["detail"] and "0.40倍" in r["detail"] and "数量×価格" in r["detail"]

    def test_cy5_warn_when_not_computable(self):
        r = _by_id(V.check_cyclical_peak({"X": _raito(price=None)}))["CY5"]
        assert r["status"] == WARN and "株価" in r["detail"]
        r = _by_id(V.check_cyclical_peak({"X": _raito(net_income_history=[-1.0])}))["CY5"]
        assert r["status"] == WARN and "黒字の履歴" in r["detail"]


class TestWiring:
    def test_checklist_review_delegates(self):
        details = {"1926.T": _raito()}
        assert CR.check_asset_value(details) == V.check_asset_value(details)
        assert CR.check_earnings_value(details) == V.check_earnings_value(details)
        assert CR.check_peak_trap(details) == V.check_peak_trap(details)
        assert CR.check_cyclical_peak(details) == V.check_cyclical_peak(details)

    def test_facade_reexports(self):
        from tools import value_types as T
        assert T.check_asset_value is V.check_asset_value
        assert T.check_peak_trap is V.check_peak_trap
        assert T.compute_metrics is F.compute_metrics


# ---------------------------------------------------------------------------
# 決算書の取り出し（yahoo_client/_balance.py）
# ---------------------------------------------------------------------------
def _df(rows: dict, date="2026-03-31"):
    return pd.DataFrame({pd.Timestamp(date): rows, pd.Timestamp("2025-03-31"): {k: 1.0 for k in rows}})


class TestExtractValueItems:
    def test_extracts_latest_period(self):
        bs = _df({
            "Cash Cash Equivalents And Short Term Investments": 300.0,
            "Investmentin Financial Assets": 100.0,
            "Accounts Receivable": 50.0,
            "Inventory": 20.0,
            "Net PPE": 80.0,
            "Goodwill And Other Intangible Assets": 5.0,
            "Total Non Current Assets": 200.0,
            "Total Liabilities Net Minority Interest": 150.0,
            "Current Debt": 10.0,
            "Long Term Debt": 7.0,
        })
        cf = _df({"Investing Cash Flow": -40.0})
        out = B.extract_value_items(bs, cf)
        assert out == {
            "cash_and_st_investments": 300.0,
            "investment_securities": 100.0,
            "accounts_receivable": 50.0,
            "inventory": 20.0,
            "net_ppe": 80.0,
            "intangibles": 5.0,
            "total_non_current_assets": 200.0,
            "total_liabilities": 150.0,
            "interest_bearing_debt": 17.0,
            "investing_cashflow": -40.0,
            "balance_sheet_date": "2026-03-31",
        }

    def test_fallbacks(self):
        bs = _df({
            "Cash And Cash Equivalents": 100.0,
            "Other Short Term Investments": 20.0,
            "Investmentin Financial Assets": 30.0,
            "Long Term Equity Investment": 5.0,
            "Goodwill": 2.0,
            "Other Intangible Assets": 3.0,
            "Total Debt": 50.0,
            "Capital Lease Obligations": 8.0,
            "Accounts Receivable": 10.0,
            "Notes Receivable": 4.0,
        })
        out = B.extract_value_items(bs, None)
        assert out["cash_and_st_investments"] == 120.0
        assert out["investment_securities"] == 35.0      # 子の合計
        assert out["intangibles"] == 5.0
        assert out["interest_bearing_debt"] == 42.0      # Total Debt − リース
        assert out["accounts_receivable"] == 14.0
        assert out["investing_cashflow"] is None

    def test_alternative_row_names(self):
        bs = _df({"Cash": 9.0, "Available For Sale Securities": 4.0, "Gross Accounts Receivable": 3.0,
                  "Total Liab": 70.0})
        cf = _df({"Cash Flow From Continuing Investing Activities": -6.0})
        out = B.extract_value_items(bs, cf)
        assert out["cash_and_st_investments"] == 9.0
        assert out["investment_securities"] == 4.0
        assert out["accounts_receivable"] == 3.0
        assert out["total_liabilities"] == 70.0
        assert out["investing_cashflow"] == -6.0

    def test_parent_investments_row_is_not_used(self):
        # 親行は投資不動産・長期貸付金を含みうる（8031.T）。子行だけを足す
        bs = _df({"Investments And Advances": 999.0, "Investmentin Financial Assets": 30.0,
                  "Long Term Equity Investment": 5.0})
        assert B.extract_value_items(bs, None)["investment_securities"] == 35.0
        assert B.extract_value_items(_df({"Investments And Advances": 999.0}), None)["investment_securities"] is None

    @pytest.mark.parametrize("rows,expected", [
        # 短期だけ + Total Debt → Total Debt 側（長期借入金を落とさない・7427.T 型）
        ({"Current Debt": 10.0, "Total Debt": 60.0}, 60.0),
        # 両方 + Total Debt（リース込み）→ 大きい方
        ({"Current Debt": 10.0, "Long Term Debt": 30.0, "Total Debt": 52.0,
          "Capital Lease Obligations": 12.0}, 40.0),
        ({"Current Debt": 10.0, "Long Term Debt": 30.0, "Total Debt": 60.0,
          "Capital Lease Obligations": 5.0}, 55.0),
        # 片方だけで Total Debt も無い → None（過大な NC を出さない）
        ({"Current Debt": 10.0}, None),
        # 無借金（行が 0 で返る・8138.T 型）
        ({"Current Debt": 0.0, "Total Debt": 0.0}, 0.0),
        # リースが Total Debt より大きい → 0 に丸める
        ({"Total Debt": 5.0, "Capital Lease Obligations": 9.0}, 0.0),
    ])
    def test_interest_bearing_debt(self, rows, expected):
        assert B.extract_value_items(_df(rows), None)["interest_bearing_debt"] == expected

    def test_nan_and_missing_rows_are_none(self):
        bs = _df({"Inventory": float("nan"), "Net PPE": 1.0})
        out = B.extract_value_items(bs, None)
        assert out["inventory"] is None
        assert out["interest_bearing_debt"] is None  # 0 で埋めない
        assert out["cash_and_st_investments"] is None

    def test_empty_inputs(self):
        out = B.extract_value_items(pd.DataFrame(), None)
        assert set(out) == set(B.VALUE_ITEM_KEYS)
        assert all(v is None for v in out.values())


# ---------------------------------------------------------------------------
# get_stock_detail への組み込み
# ---------------------------------------------------------------------------
class _FakeTicker:
    def __init__(self, bs, cf):
        self.balance_sheet = bs
        self.cashflow = cf
        self.income_stmt = pd.DataFrame()
        self.info = {}

    def history(self, period="2y"):
        return pd.DataFrame()


@pytest.fixture
def detail_env(monkeypatch):
    from src.data.yahoo_client import detail as DT

    bs = _df({"Cash And Cash Equivalents": 100.0, "Current Debt": 10.0, "Long Term Debt": 0.0,
              "Total Liabilities Net Minority Interest": 60.0, "Total Assets": 400.0,
              "Stockholders Equity": 300.0})
    cf = _df({"Operating Cash Flow": 30.0, "Investing Cash Flow": -12.0})
    calls = {"ticker": 0}

    def fake_ticker(s):
        calls["ticker"] += 1
        return _FakeTicker(bs, cf)

    monkeypatch.setattr(DT, "get_stock_info", lambda s: {"symbol": s, "price": 100.0})
    monkeypatch.setattr(DT, "_read_detail_cache", lambda s: None)
    monkeypatch.setattr(DT, "_write_detail_cache", lambda s, d: None)
    monkeypatch.setattr(DT.stock_detail_cache, "get", lambda s: None)
    monkeypatch.setattr(DT.stock_detail_cache, "set", lambda s, d: None)
    monkeypatch.setattr(DT.time, "sleep", lambda s: None)
    monkeypatch.setattr(DT.yf, "Ticker", fake_ticker)
    return DT, calls


class TestDetailIntegration:
    def test_detail_contains_value_items(self, detail_env):
        DT, _ = detail_env
        d = DT.get_stock_detail("9999.T")
        assert d is not None
        for key in B.VALUE_ITEM_KEYS:
            assert key in d
        assert d["cash_and_st_investments"] == 100.0
        assert d["interest_bearing_debt"] == 10.0
        assert d["investing_cashflow"] == -12.0
        assert d["balance_sheet_date"] == "2026-03-31"
        assert F.book_fcf(d) == pytest.approx(18.0)

    def test_extraction_failure_keeps_keys_as_none(self, detail_env, monkeypatch):
        DT, _ = detail_env

        def boom(bs, cf):
            raise RuntimeError("bad frame")

        monkeypatch.setattr(DT, "extract_value_items", boom)
        d = DT.get_stock_detail("9999.T")
        assert d is not None
        assert all(d[k] is None for k in B.VALUE_ITEM_KEYS)

    def test_old_cache_without_value_items_is_refetched(self, detail_env, monkeypatch):
        # KIK-786 より前のキャッシュ（キーが無い）は返さずに取り直す
        DT, calls = detail_env
        monkeypatch.setattr(DT, "_read_detail_cache", lambda s: {"symbol": s, "per": 10.0})
        d = DT.get_stock_detail("9999.T")
        assert calls["ticker"] == 1
        assert d["cash_and_st_investments"] == 100.0

    def test_new_cache_is_used(self, detail_env, monkeypatch):
        DT, calls = detail_env
        cached = {"symbol": "9999.T", **dict.fromkeys(B.VALUE_ITEM_KEYS)}
        monkeypatch.setattr(DT, "_read_detail_cache", lambda s: cached)
        assert DT.get_stock_detail("9999.T") is cached
        assert calls["ticker"] == 0
