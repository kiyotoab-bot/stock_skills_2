"""EC6 の期末後の比較（KIK-788）のテスト.

5408.T 中山製鋼所（2026-11-25 実測）: J-Quants 2Q 短信（11/05 開示・9/30 時点）の流通株
54,250,204 株 / yfinance 59,912,320 株（10/07 に新株分が反映）→ +10.4%。
期末の発行済株数の系列は横ばいなので、従来の EC6 は PASS を返していた。
"""

import datetime

import pytest

from src.data import share_count as S
from src.data.checklist_review import check_dilution as reexported_check
from src.data.dilution import check_dilution

TODAY = datetime.date(2026, 11, 25)
FLAT = [("2024-11-08", 63_079_256), ("2025-11-07", 63_079_256), ("2026-11-05", 63_079_256)]
JQ_5408 = 63_079_256 - 8_829_052
YF_5408 = 59_912_320


def _post(base=JQ_5408, latest=YF_5408, disclosed="2026-11-05"):
    return {"base": base, "base_disclosed": disclosed, "latest": latest, "latest_source": "yfinance"}


class TestCheckDilutionPostPeriod:
    def test_5408_flat_history_but_post_period_issuance_warns(self):
        r = check_dilution({"5408.T": FLAT}, today=TODAY, post_period={"5408.T": _post()})[0]
        assert r["status"] == "WARN"
        assert "期末後 +10.4%" in r["detail"]
        assert "2026-11-05" in r["detail"] and "54.25M" in r["detail"] and "59.91M" in r["detail"]
        assert "形跡なし" not in r["detail"]

    def test_without_post_period_legacy_pass_but_says_not_checked(self):
        r = check_dilution({"5408.T": FLAT}, today=TODAY)[0]
        assert r["status"] == "PASS"
        assert "期末より後の増資は見ていない" in r["detail"]

    @pytest.mark.parametrize("latest", [JQ_5408 * 1.01, JQ_5408 * 0.95, JQ_5408 * 1.0499])
    def test_small_change_or_decrease_pass(self, latest):
        r = check_dilution({"7777.T": FLAT}, today=TODAY,
                           post_period={"7777.T": _post(latest=latest)})[0]
        assert r["status"] == "PASS"
        assert "期末後 +" not in r["detail"]

    def test_boundary_5pct_warns(self):
        r = check_dilution({"7777.T": FLAT}, today=TODAY,
                           post_period={"7777.T": _post(latest=JQ_5408 * 1.05)})[0]
        assert r["status"] == "WARN"

    def test_boundary_80pct_is_manual_check(self):
        r = check_dilution({"7777.T": FLAT}, today=TODAY,
                           post_period={"7777.T": _post(base=100e6, latest=180e6)})[0]
        assert "目視確認" in r["detail"] and "期末後 +80%" in r["detail"]

    def test_huge_increase_needs_manual_check(self):
        r = check_dilution({"7777.T": FLAT}, today=TODAY,
                           post_period={"7777.T": _post(latest=JQ_5408 * 2)})[0]
        assert r["status"] == "WARN"
        assert "目視確認" in r["detail"] and "分割か大規模希薄化" in r["detail"]

    @pytest.mark.parametrize("rec", [None, {}, _post(latest=None), _post(base=0), _post(base="x"),
                                     "bad", _post(base=float("inf")), _post(latest=float("inf")),
                                     _post(base=True), _post(latest=float("nan"))])
    def test_missing_latest_is_warn_not_silent_pass(self, rec):
        r = check_dilution({"7777.T": FLAT}, today=TODAY, post_period={"7777.T": rec})[0]
        assert r["status"] == "WARN"
        assert "期末より後は未確認" in r["detail"]
        assert "形跡なし: 7777.T" in r["detail"]  # 期末の系列は見られている

    def test_symbol_absent_from_post_period_is_unchecked(self):
        r = check_dilution({"7777.T": FLAT}, today=TODAY, post_period={})[0]
        assert r["status"] == "WARN" and "期末より後は未確認" in r["detail"]

    def test_history_and_post_period_both_reported(self):
        hist = [("2024-11-08", 100_000_000), ("2025-11-07", 115_000_000)]
        r = check_dilution({"9999.T": hist}, today=TODAY,
                           post_period={"9999.T": _post(base=100e6, latest=110e6)})[0]
        assert "2025-11-07 +15.0%" in r["detail"] and "期末後 +10.0%" in r["detail"]

    def test_post_period_still_checked_when_history_insufficient(self):
        r = check_dilution({"9999.T": [("2026-11-05", 63e6)]}, today=TODAY,
                           post_period={"9999.T": _post()})[0]
        assert r["status"] == "WARN"
        assert "期末後 +10.4%" in r["detail"]
        assert "データ不足" in r["detail"]

    def test_mixed_candidates_all_listed(self):
        r = check_dilution({"5408.T": FLAT, "7203.T": FLAT}, today=TODAY,
                           post_period={"5408.T": _post(), "7203.T": _post(latest=JQ_5408)})[0]
        assert "5408.T(期末後" in r["detail"] and "形跡なし: 7203.T" in r["detail"]

    def test_reexport_passes_post_period(self):
        r = reexported_check({"5408.T": FLAT}, today=TODAY, post_period={"5408.T": _post()})[0]
        assert r["status"] == "WARN" and "期末後 +10.4%" in r["detail"]


class TestGetPostPeriodShares:
    def _latest(self, outstanding=JQ_5408):
        return lambda sym: {"outstanding": outstanding, "disclosed": "2026-11-05"}

    def _info(self, shares=YF_5408, price=482.0):
        return lambda sym: {"price": price, "market_cap": shares * price if shares else None}

    def test_normal(self):
        rec = S.get_post_period_shares("5408.T", latest_fn=self._latest(), info_fn=self._info())
        assert rec["base"] == JQ_5408 and rec["base_disclosed"] == "2026-11-05"
        assert rec["latest"] == pytest.approx(YF_5408)
        assert rec["latest_source"] == "yfinance"

    @pytest.mark.parametrize("latest_fn", [lambda s: None, lambda s: {"outstanding": None},
                                           lambda s: {"outstanding": 0}])
    def test_no_jquants_is_none(self, latest_fn):
        assert S.get_post_period_shares("5408.T", latest_fn=latest_fn, info_fn=self._info()) is None

    @pytest.mark.parametrize("info_fn", [lambda s: None, lambda s: {"price": 482.0},
                                         lambda s: {"price": None, "market_cap": 1e10}])
    def test_no_yfinance_is_none(self, info_fn):
        assert S.get_post_period_shares("5408.T", latest_fn=self._latest(), info_fn=info_fn) is None

    def test_non_dict_latest_is_none(self):
        assert S.get_post_period_shares("5408.T", latest_fn=lambda s: "bad", info_fn=self._info()) is None

    def test_exceptions_are_none(self):
        def boom(sym):
            raise RuntimeError("api")
        assert S.get_post_period_shares("5408.T", latest_fn=boom, info_fn=self._info()) is None
        assert S.get_post_period_shares("5408.T", latest_fn=self._latest(), info_fn=boom) is None


class TestCollectDilutionInputs:
    def test_shape_and_non_japanese_gets_none(self):
        calls = []
        series, post = S.collect_dilution_inputs(
            ["5408.T", "AAPL"], history_fn=lambda s: FLAT,
            post_fn=lambda s: calls.append(s) or _post())
        assert series == {"5408.T": FLAT, "AAPL": FLAT}
        assert post["5408.T"]["latest"] == YF_5408 and post["AAPL"] is None
        assert calls == ["5408.T"]  # 日本株以外は取りに行かない

    def test_end_to_end_with_check(self):
        series, post = S.collect_dilution_inputs(["5408.T"], history_fn=lambda s: FLAT,
                                                 post_fn=lambda s: _post())
        r = check_dilution(series, post_period=post, today=TODAY)[0]
        assert r["status"] == "WARN" and "期末後 +10.4%" in r["detail"]

    def test_empty(self):
        assert S.collect_dilution_inputs([]) == ({}, {})


def test_checklists_yaml_ec6_code_resolves():
    """yaml の code が指す関数が実在する（エージェントがこの1行で EC6 を回す）."""
    import importlib
    import pathlib

    import yaml

    data = yaml.safe_load(pathlib.Path("config/checklists.yaml").read_text(encoding="utf-8"))
    ec6 = [i for i in data["entry_conditions"]["items"] if i["id"] == "EC6"][0]
    assert "collect_dilution_inputs" in ec6["code"]
    for dotted in ("src.data.checklist_review.check_dilution",
                   "src.data.share_count.collect_dilution_inputs"):
        mod, name = dotted.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(mod), name))
