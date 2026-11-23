"""株数の照合（KIK-787）のテスト.

5408.T 中山製鋼所（2026-11-23 実測）: yfinance 59,912,320 株 / J-Quants 2Q 短信
（11/05 開示・9/30 時点）発行済 63,079,256 − 自己株 8,829,052 = 54,250,204 株 /
正解（10/02 第三者割当後・適時開示から手計算）67,304,204 株。
"""

import pandas as pd
import pytest

from src.data import checklist_review as CR
from src.data import share_count as S
from src.data import value_formulas as F
from src.data import value_types as V

PASS, WARN, FAIL, NA = CR.PASS, CR.WARN, CR.FAIL, CR.NA

YF_5408 = 59_912_320
JQ_5408 = 63_079_256 - 8_829_052
TRUE_5408 = 67_304_204
PX_5408 = 482.0


def _d(yf=None, jq=None, price=100.0, **over):
    d = {"currency": "JPY", "price": price,
         "market_cap": (yf * price) if (yf and price) else None}
    if jq is not None:
        d[S.JQ_SHARES_KEY] = jq
        d[S.JQ_SHARES_DATE_KEY] = "2026-11-05"
    d.update(over)
    return d


def _nakayama(**over):
    """5408.T の資産バリュー判定に効く値（百万円単位の概数・2026-09-30 BS）."""
    M = 1e6
    d = _d(YF_5408, JQ_5408, PX_5408,
           per=7.5, pbr=0.27, equity_ratio=0.74,
           cash_and_st_investments=30_000 * M, investment_securities=3_000 * M,
           accounts_receivable=15_000 * M, inventory=20_000 * M, net_ppe=40_000 * M,
           intangibles=500 * M, total_non_current_assets=45_000 * M,
           total_liabilities=25_000 * M, interest_bearing_debt=5_600 * M)
    d.update(over)
    return d


def _by_id(results):
    return {r["id"]: r for r in results}


# ---------------------------------------------------------------------------
# reconcile_shares
# ---------------------------------------------------------------------------
class TestReconcile:
    def test_5408_diverged_takes_larger(self):
        sh = F.reconcile_shares(_d(YF_5408, JQ_5408, PX_5408))
        assert sh["status"] == "diverged"
        assert sh["shares"] == pytest.approx(YF_5408)
        assert sh["source"] == "yfinance"
        assert sh["divergence_pct"] == pytest.approx((YF_5408 / JQ_5408 - 1) * 100)  # 約10.4%

    def test_jquants_larger_is_taken(self):
        sh = F.reconcile_shares(_d(100e6, 110e6))
        assert sh["shares"] == pytest.approx(110e6) and sh["source"] == "jquants"

    @pytest.mark.parametrize("jq,expected", [
        (103e6, "ok"),            # 3% ちょうどは乖離にしない
        (103.01e6, "diverged"),
        (100e6, "ok"),
        (97.1e6, "ok"),           # 小さい方を分母にする: 100/97.1 = +2.99%
        (97e6, "diverged"),       # 100/97 = +3.09%
    ])
    def test_divergence_boundary(self, jq, expected):
        assert F.reconcile_shares(_d(100e6, jq))["status"] == expected

    def test_override_wins(self):
        sh = F.reconcile_shares(_d(YF_5408, JQ_5408, PX_5408, shares_override=TRUE_5408,
                                   shares_override_note="10/02 第三者割当後"))
        assert sh["status"] == "override" and sh["shares"] == TRUE_5408
        assert sh["divergence_pct"] is not None   # 乖離の事実は残す
        assert sh["override_note"] == "10/02 第三者割当後"

    @pytest.mark.parametrize("bad", [0, -1, None, "abc"])
    def test_invalid_override_ignored(self, bad):
        assert F.reconcile_shares(_d(100e6, 100e6, shares_override=bad))["status"] == "ok"

    def test_yf_only_unverified(self):
        sh = F.reconcile_shares(_d(100e6))
        assert sh["status"] == "unverified" and sh["source"] == "yfinance"

    def test_jq_only_unverified(self):
        sh = F.reconcile_shares(_d(None, 100e6))
        assert sh["status"] == "unverified" and sh["shares"] == 100e6 and sh["source"] == "jquants"

    @pytest.mark.parametrize("jq", [0, -5, None])
    def test_nonpositive_jq_ignored(self, jq):
        d = _d(100e6)
        d[S.JQ_SHARES_KEY] = jq
        assert F.reconcile_shares(d)["status"] == "unverified"

    def test_missing(self):
        sh = F.reconcile_shares({"price": 100.0})
        assert sh["status"] == "missing" and sh["shares"] is None

    def test_zero_price_falls_back_to_jq(self):
        # 株価0では yfinance 株数を出せない。J-Quants だけで未照合
        d = _d(None, 100e6, price=0.0, market_cap=5e9)
        assert F.reconcile_shares(d)["status"] == "unverified"


# ---------------------------------------------------------------------------
# compute_metrics / 時価総額
# ---------------------------------------------------------------------------
class TestMetrics:
    def test_market_cap_uses_reconciled_shares(self):
        m = F.compute_metrics(_d(YF_5408, JQ_5408, PX_5408))
        assert m["market_cap"] == pytest.approx(YF_5408 * PX_5408)
        assert m["market_cap_yf"] == pytest.approx(YF_5408 * PX_5408)

    def test_market_cap_raised_when_jq_larger(self):
        m = F.compute_metrics(_d(100e6, 110e6, 100.0))
        assert m["market_cap"] == pytest.approx(110e8)
        assert m["market_cap_yf"] == pytest.approx(100e8)

    def test_override_5408_gives_324oku(self):
        m = F.compute_metrics(_d(YF_5408, JQ_5408, PX_5408, shares_override=TRUE_5408))
        assert m["market_cap"] / 1e8 == pytest.approx(324.4, abs=0.1)

    def test_no_price_keeps_yf_market_cap(self):
        d = {"market_cap": 5e9, "price": None, S.JQ_SHARES_KEY: 100e6}
        assert F.compute_metrics(d)["market_cap"] == 5e9

    def test_cyclical_target_uses_reconciled_shares(self):
        d = _d(100e6, 125e6, 100.0, net_income_history=[1e9, 2.5e9])
        # ピーク 25億 ÷ 1.25億株 × 5 = 100円（yfinance の株数なら 125円）
        assert F.cyclical_target_price(d) == pytest.approx(100.0)
        assert F.cyclical_target_price(_d(100e6, 100e6, 100.0, net_income_history=[2.5e9])) == pytest.approx(125.0)


# ---------------------------------------------------------------------------
# 判定への反映
# ---------------------------------------------------------------------------
class TestChecks:
    def test_5408_av2_pass_downgraded_to_warn(self):
        r = _by_id(V.check_asset_value({"5408.T": _nakayama()}))
        av2 = r["AV2"]
        assert av2["status"] == WARN                # 清算価値 > 時価総額 だが株数が未確定
        assert "乖離10.4%" in av2["detail"] and "適時開示" in av2["detail"]
        assert "J-Quants 54.3M" in av2["detail"] and "yf 59.9M" in av2["detail"]

    def test_5408_override_restores_pass(self):
        r = _by_id(V.check_asset_value({"5408.T": _nakayama(shares_override=TRUE_5408)}))
        assert r["AV2"]["status"] == PASS
        assert "確認値 67.3M" in r["AV2"]["detail"]

    def test_fail_stays_fail(self):
        # 清算価値 < 時価総額 は株数に関係なく FAIL
        r = _by_id(V.check_asset_value({"X": _nakayama(total_liabilities=200_000e6)}))
        assert r["AV2"]["status"] == FAIL

    def test_av3_not_gated(self):
        # NC>0 は株数に依存しない。出所だけ付ける
        r = _by_id(V.check_asset_value({"5408.T": _nakayama()}))
        assert r["AV3"]["status"] == PASS and "株数:" in r["AV3"]["detail"]

    def test_av1_av4_untouched(self):
        r = _by_id(V.check_asset_value({"5408.T": _nakayama()}))
        assert "株数:" not in r["AV1"]["detail"] and "株数:" not in r["AV4"]["detail"]

    def test_ev6_gated_and_ev5_noted(self):
        d = _nakayama(operating_cashflow=5e9, investing_cashflow=-1e9)
        r = _by_id(V.check_earnings_value({"5408.T": d}))
        assert r["EV6"]["status"] == WARN and "乖離" in r["EV6"]["detail"]   # 289億 ≤ 300億 でも WARN
        assert r["EV5"]["status"] == PASS and "株数:" in r["EV5"]["detail"]

    def test_ev6_override_moves_band(self):
        # 正しい株数では 324億 → 300億超で「上限1000億以内」の WARN
        r = _by_id(V.check_earnings_value({"5408.T": _nakayama(shares_override=TRUE_5408)}))
        assert "324億" in r["EV6"]["detail"] and "上限1000億以内" in r["EV6"]["detail"]

    def test_unverified_downgrades(self):
        d = _nakayama()
        del d[S.JQ_SHARES_KEY]
        r = _by_id(V.check_asset_value({"5408.T": d}))
        assert r["AV2"]["status"] == WARN and "未照合" in r["AV2"]["detail"]

    def test_cy5_note_only(self):
        d = _nakayama(net_income_history=[1e9, 3e9])
        r = _by_id(V.check_cyclical_peak({"5408.T": d}))
        assert r["CY5"]["status"] == NA and "株数:" in r["CY5"]["detail"]

    def test_non_jpy_still_out_of_scope(self):
        r = _by_id(V.check_asset_value({"AAPL": _nakayama(currency="USD")}))
        assert r["AV2"]["status"] == WARN and "対象外" in r["AV2"]["detail"]
        assert "株数:" not in r["AV2"]["detail"]


class TestDQ9:
    @pytest.mark.parametrize("d,expected,word", [
        (_d(100e6, 100e6), PASS, "照合済"),
        (_d(YF_5408, JQ_5408, PX_5408), WARN, "乖離10.4%"),
        (_d(100e6), WARN, "未照合（yfinanceのみ"),
        (_d(None, 100e6), WARN, "未照合（J-Quantsのみ"),
        ({"currency": "JPY"}, WARN, "取得不可"),
        (_d(YF_5408, JQ_5408, PX_5408, shares_override=TRUE_5408), PASS, "確認値"),
    ])
    def test_statuses(self, d, expected, word):
        r = V.check_share_count({"X.T": d})[0]
        assert r["id"] == "DQ9" and r["status"] == expected and word in r["detail"]

    def test_empty_is_na(self):
        assert V.check_share_count({})[0]["status"] == NA

    def test_all_symbols_listed(self):
        r = V.check_share_count({"B.T": _d(100e6, 100e6), "A.T": _d(100e6)})[0]
        assert r["status"] == WARN and r["detail"].index("A.T") < r["detail"].index("B.T")

    def test_delegated_from_tools(self):
        from tools import value_types as T
        assert T.check_share_count is V.check_share_count
        assert T.attach_share_counts is S.attach_share_counts


# ---------------------------------------------------------------------------
# 取得: get_latest_share_count / attach_share_counts
# ---------------------------------------------------------------------------
class TestFetch:
    def _patch(self, monkeypatch, df=None, available=True, exc=None):
        class _C:
            def get_fin_summary(self, code):
                if exc:
                    raise exc
                return df
        monkeypatch.setattr("src.data.jquants_client._client.is_available", lambda: available)
        monkeypatch.setattr("src.data.jquants_client._client.get_client", lambda: _C())

    def test_latest_row_even_if_shuffled(self, monkeypatch):
        df = pd.DataFrame([
            {"DiscDate": "2026-11-05", "CurPerType": "2Q", "ShOutFY": 63_079_256, "TrShFY": 8_829_052},
            {"DiscDate": "2026-02-05", "CurPerType": "3Q", "ShOutFY": 63_079_256, "TrShFY": 8_863_762},
            {"DiscDate": "2026-08-07", "CurPerType": "1Q", "ShOutFY": 63_079_256, "TrShFY": 8_863_936},
        ])
        self._patch(monkeypatch, df)
        rec = S.get_latest_share_count("5408.T")
        assert rec["disclosed"] == "2026-11-05" and rec["period_type"] == "2Q"
        assert rec["outstanding"] == JQ_5408

    def test_same_day_correction_uses_later_row(self, monkeypatch):
        df = pd.DataFrame([
            {"DiscDate": "2026-05-10", "ShOutFY": 100, "TrShFY": 10},
            {"DiscDate": "2026-05-10", "ShOutFY": 100, "TrShFY": 20},
        ])
        self._patch(monkeypatch, df)
        assert S.get_latest_share_count("9999.T")["outstanding"] == 80

    def test_nat_and_nonpositive_skipped(self, monkeypatch):
        df = pd.DataFrame([
            {"DiscDate": "NaT", "ShOutFY": 999, "TrShFY": 0},
            {"DiscDate": "2027-01-01", "ShOutFY": 0, "TrShFY": 0},
            {"DiscDate": "2026-05-10", "ShOutFY": 100, "TrShFY": 10},
        ])
        self._patch(monkeypatch, df)
        assert S.get_latest_share_count("9999.T")["disclosed"] == "2026-05-10"

    @pytest.mark.parametrize("treasury", [None, float("nan"), -1, 100, 150])
    def test_bad_treasury_gives_no_outstanding(self, monkeypatch, treasury):
        df = pd.DataFrame([{"DiscDate": "2026-05-10", "ShOutFY": 100, "TrShFY": treasury}])
        self._patch(monkeypatch, df)
        rec = S.get_latest_share_count("9999.T")
        assert rec["outstanding"] is None and rec["issued"] == 100

    def test_zero_treasury_ok(self, monkeypatch):
        self._patch(monkeypatch, pd.DataFrame([{"DiscDate": "2026-05-10", "ShOutFY": 100, "TrShFY": 0}]))
        assert S.get_latest_share_count("9999.T")["outstanding"] == 100

    def test_unavailable_exception_empty(self, monkeypatch):
        self._patch(monkeypatch, available=False)
        assert S.get_latest_share_count("9999.T") is None
        self._patch(monkeypatch, exc=RuntimeError("boom"))
        assert S.get_latest_share_count("9999.T") is None
        self._patch(monkeypatch, df=pd.DataFrame())
        assert S.get_latest_share_count("9999.T") is None
        self._patch(monkeypatch, df=pd.DataFrame([{"DiscDate": "NaT", "ShOutFY": 1, "TrShFY": 0}]))
        assert S.get_latest_share_count("9999.T") is None

    def test_attach_only_japanese(self):
        calls = []

        def fetch(sym):
            calls.append(sym)
            return {"outstanding": 54_250_204, "disclosed": "2026-11-05"}

        details = {"5408.T": {}, "AAPL": {}, "X.T": None}
        S.attach_share_counts(details, fetch=fetch)
        assert calls == ["5408.T"]
        assert details["5408.T"] == {S.JQ_SHARES_KEY: 54_250_204, S.JQ_SHARES_DATE_KEY: "2026-11-05"}
        assert details["AAPL"] == {}

    @pytest.mark.parametrize("rec", [None, {}, {"outstanding": None, "disclosed": "2026-11-05"}])
    def test_attach_missing_adds_nothing(self, rec):
        details = {"5408.T": {"price": 1.0}}
        S.attach_share_counts(details, fetch=lambda s: rec)
        assert details["5408.T"] == {"price": 1.0}

    def test_attach_empty(self):
        assert S.attach_share_counts({}) == {}
        assert S.attach_share_counts(None) is None


class TestReviewFixes:
    def test_reattach_failure_clears_stale_values(self):
        details = {"5408.T": {S.JQ_SHARES_KEY: 1.0, S.JQ_SHARES_DATE_KEY: "2026-01-01"}}
        S.attach_share_counts(details, fetch=lambda s: None)
        assert details["5408.T"] == {}

    def test_keys_defined_in_pure_layer(self):
        assert S.JQ_SHARES_KEY is F.JQ_SHARES_KEY and S.JQ_SHARES_DATE_KEY is F.JQ_SHARES_DATE_KEY


class TestReviewFixes2:
    @pytest.mark.parametrize("bad", [True, False, float("nan")])
    def test_bool_nan_override_ignored(self, bad):
        assert F.reconcile_shares(_d(100e6, 100e6, shares_override=bad))["status"] == "ok"

    @pytest.mark.parametrize("ov,expected", [
        (67.3, "override_suspect"),          # 百万株で入れた
        (TRUE_5408, "override"),             # 59.9M 比 1.12倍
        (YF_5408 * 0.5, "override"), (YF_5408 * 2.0, "override"),
        (YF_5408 * 0.49, "override_suspect"), (YF_5408 * 2.01, "override_suspect"),
    ])
    def test_override_range(self, ov, expected):
        assert F.reconcile_shares(_d(YF_5408, JQ_5408, PX_5408, shares_override=ov))["status"] == expected

    def test_suspect_override_gates_pass(self):
        r = _by_id(V.check_asset_value({"5408.T": _nakayama(shares_override=67.3)}))
        assert r["AV2"]["status"] == WARN and "単位" in r["AV2"]["detail"]
        assert V.check_share_count({"5408.T": _nakayama(shares_override=67.3)})[0]["status"] == WARN

    def test_override_without_sources(self):
        sh = F.reconcile_shares({"price": 100.0, "shares_override": 1e6})
        assert sh["status"] == "override" and sh["shares"] == 1e6
        assert V.check_share_count({"X.T": {"currency": "JPY", "price": 100.0, "shares_override": 1e6}})[0]["status"] == PASS

    def test_dq9_non_jpy(self):
        r = V.check_share_count({"AAPL": _d(100e6, currency="USD")})[0]
        assert r["status"] == WARN and "対象外" in r["detail"]

    def test_ok_keeps_pass(self):
        r = _by_id(V.check_asset_value({"5408.T": _nakayama(**{S.JQ_SHARES_KEY: YF_5408})}))
        assert r["AV2"]["status"] == PASS and "照合済" in r["AV2"]["detail"]

    def test_ev6_exact_boundary_from_shares(self):
        # 300億ちょうど = 3億株 × 100円（株数×株価で作る）
        r = _by_id(V.check_earnings_value({"X.T": _d(3e8, 3e8, 100.0)}))
        assert r["EV6"]["status"] == PASS

    def test_diverged_without_date(self):
        d = _d(YF_5408, JQ_5408, PX_5408)
        del d[S.JQ_SHARES_DATE_KEY]
        txt = V.check_share_count({"5408.T": d})[0]["detail"]
        assert "開示 乖離" not in txt and "54.3M 乖離10.4%" in txt

    def test_latest_nan_shares_uses_older_row(self, monkeypatch):
        TestFetch()._patch(monkeypatch, pd.DataFrame([
            {"DiscDate": "2026-11-05", "ShOutFY": float("nan"), "TrShFY": 1},
            {"DiscDate": "2026-08-07", "ShOutFY": 100, "TrShFY": 10},
        ]))
        rec = S.get_latest_share_count("9999.T")
        assert rec["disclosed"] == "2026-08-07" and rec["outstanding"] == 90
