"""Tests for J-REIT の評価指標 — KIK-760.

2026-08-15 に yfinance の PBR をそのまま提示して誤った:
8951.T は PBR 0.33 と出たが、時価総額÷純資産では 1.55。**割安に見える方向**に
4.7倍外れていた。J-Quants の決算短信（DocType に REIT を含む）から
BPS / TA / Eq / DivUnit を取れば正しく出る。

守りたい性質:
  1. NAV倍率 = 投資口価格 ÷ BPS（yfinance の PBR を使わない）
  2. 分配金は**半期**。年換算しないと利回りが半分に見える
  3. レコードは日付順に返らない。開示日で並べ直す
  4. 予想改訂レコードは BPS を持たない。本決算まで遡る
"""

import pytest

from src.data import reit_metrics as rm


def _row(disc, doctype="FYFinancialStatements_Consolidated_REIT",
         bps=84298, ta=1448831000000, eq=729181000000,
         div=2454, nxt=2460, st="2025-07-01", en="2025-12-31"):
    return {"DiscDate": disc, "DocType": doctype, "BPS": bps, "TA": ta, "Eq": eq,
            "DivUnit": div, "NxFDivUnit": nxt, "CurPerSt": st, "CurPerEn": en}


def _stub(monkeypatch, rows):
    monkeypatch.setattr(rm, "_fetch_summary", lambda code: sorted(
        rows, key=lambda r: str(r.get("DiscDate") or "")))


class TestIsReit:
    def test_reit_doctype_detected(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16")])
        assert rm.is_reit("8951.T") is True

    def test_equity_doctype_is_not_reit(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16", doctype="FYFinancialStatements_Consolidated_IFRS")])
        assert rm.is_reit("7751.T") is False

    def test_no_records_is_not_reit(self, monkeypatch):
        _stub(monkeypatch, [])
        assert rm.is_reit("7751.T") is False

    def test_fetch_error_is_not_reit(self, monkeypatch):
        def _boom(code):
            raise RuntimeError("network down")
        monkeypatch.setattr(rm, "_fetch_summary", _boom)
        assert rm.is_reit("8951.T") is False


class TestNavRatio:
    def test_nav_uses_bps_not_yfinance_pbr(self, monkeypatch):
        """yfinance の PBR 0.33 ではなく 128,400 / 84,298 = 1.52 になること。"""
        _stub(monkeypatch, [_row("2026-02-16")])
        r = rm.get_reit_metrics("8951.T", price=128400)
        assert r["nav_ratio"] == pytest.approx(1.523, abs=0.005)
        assert r["nav_signal"] == "rich"

    @pytest.mark.parametrize("price,signal", [
        (80000, "cheap"),     # 0.95
        (90000, "fair"),      # 1.07
        (120000, "rich"),     # 1.42
    ])
    def test_nav_signal_bands(self, monkeypatch, price, signal):
        _stub(monkeypatch, [_row("2026-02-16")])
        assert rm.get_reit_metrics("8951.T", price=price)["nav_signal"] == signal

    def test_nav_boundary_is_inclusive_at_cheap(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16", bps=100000)])
        assert rm.get_reit_metrics("x", price=100000)["nav_signal"] == "fair"
        assert rm.get_reit_metrics("x", price=99999)["nav_signal"] == "cheap"


class TestDistributionYield:
    def test_semiannual_is_annualised(self, monkeypatch):
        """半期 2,460円 × 2 ÷ 128,400 = 3.83%。年換算しないと 1.92% に見える。"""
        _stub(monkeypatch, [_row("2026-02-16")])
        r = rm.get_reit_metrics("8951.T", price=128400)
        assert r["months_in_period"] == 6
        assert r["dist_yield_forecast_pct"] == pytest.approx(3.83, abs=0.02)

    def test_annual_period_is_not_doubled(self, monkeypatch):
        """年次決算の REIT では2倍しない。"""
        _stub(monkeypatch, [_row("2026-02-16", st="2025-01-01", en="2025-12-31",
                                 nxt=5000)])
        r = rm.get_reit_metrics("x", price=100000)
        assert r["months_in_period"] == 12
        assert r["dist_yield_forecast_pct"] == pytest.approx(5.0, abs=0.05)

    def test_actual_and_forecast_are_separate(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16", div=2454, nxt=2460)])
        r = rm.get_reit_metrics("x", price=128400)
        assert r["dist_per_unit"] == 2454
        assert r["dist_forecast"] == 2460
        assert r["dist_yield_pct"] != r["dist_yield_forecast_pct"]


class TestLtv:
    def test_ltv_from_total_and_net_assets(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16")])
        r = rm.get_reit_metrics("8951.T", price=128400)
        assert r["ltv_pct"] == pytest.approx(49.7, abs=0.1)
        assert r["ltv_signal"] == "normal"

    @pytest.mark.parametrize("eq_ratio,signal", [
        (0.60, "conservative"),   # LTV 40%
        (0.50, "normal"),         # LTV 50%
        (0.43, "warn"),           # LTV 57%
        (0.38, "limit"),          # LTV 62%
    ])
    def test_ltv_bands(self, monkeypatch, eq_ratio, signal):
        ta = 1_000_000
        _stub(monkeypatch, [_row("2026-02-16", ta=ta, eq=ta * eq_ratio)])
        assert rm.get_reit_metrics("x", price=1000)["ltv_signal"] == signal


class TestRecordSelection:
    def test_records_are_sorted_by_disclosure(self, monkeypatch):
        """API は日付順に返さない。古いレコードを最新と誤認しない。"""
        _stub(monkeypatch, [
            _row("2026-02-16", bps=84298, nxt=2460),
            _row("2025-08-15", bps=70000, nxt=9999),
        ])
        r = rm.get_reit_metrics("8951.T", price=128400)
        assert r["bps"] == 84298

    def test_forecast_revision_without_bps_is_skipped(self, monkeypatch):
        """予想改訂レコードは BPS を持たない。本決算まで遡る。"""
        _stub(monkeypatch, [
            _row("2026-02-16", bps=84298),
            {"DiscDate": "2026-05-01", "DocType": "REITEarnForecastRevision",
             "BPS": None, "NxFDivUnit": 2500},
        ])
        r = rm.get_reit_metrics("8951.T", price=128400)
        assert r["bps"] == 84298
        assert r["nav_ratio"] is not None

    def test_forecast_falls_back_to_revision_record(self, monkeypatch):
        """本決算に予想が無ければ改訂レコードから拾う。"""
        _stub(monkeypatch, [
            _row("2026-02-16", nxt=None),
            {"DiscDate": "2026-05-01", "DocType": "REITEarnForecastRevision",
             "BPS": None, "NxFDivUnit": 2600},
        ])
        assert rm.get_reit_metrics("x", price=128400)["dist_forecast"] == 2600


class TestGuards:
    def test_non_reit_returns_flag_only(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16", doctype="FYFinancialStatements_Consolidated_JP")])
        r = rm.get_reit_metrics("7751.T", price=4656)
        assert r["is_reit"] is False
        assert r["nav_ratio"] is None

    def test_reit_without_bps_is_reported(self, monkeypatch):
        """REIT と分かっているのに算出できないことを黙らせない。"""
        _stub(monkeypatch, [{"DiscDate": "2026-02-16",
                             "DocType": "REITEarnForecastRevision", "BPS": None}])
        r = rm.get_reit_metrics("x", price=1000)
        assert r["is_reit"] is True
        assert r["nav_ratio"] is None
        assert "BPS" in r["label"]

    def test_missing_price_leaves_nav_none(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16")])
        monkeypatch.setattr("src.data.yahoo_client.history.get_price_history",
                            lambda *a, **k: None)
        r = rm.get_reit_metrics("8951.T")
        assert r["nav_ratio"] is None
        assert r["ltv_pct"] is not None      # LTV は価格に依存しない

    def test_string_numbers_are_parsed(self, monkeypatch):
        _stub(monkeypatch, [_row("2026-02-16", bps="84298", ta="1448831000000",
                                 eq="729181000000")])
        assert rm.get_reit_metrics("x", price=128400)["nav_ratio"] is not None

    def test_empty_string_is_not_zero(self, monkeypatch):
        """DivUnit が空文字のレコードがある。0 と誤認しない。"""
        _stub(monkeypatch, [_row("2026-02-16", div="", nxt="")])
        r = rm.get_reit_metrics("x", price=128400)
        assert r["dist_per_unit"] is None
        assert r["dist_yield_pct"] is None
