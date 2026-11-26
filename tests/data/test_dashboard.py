"""ローカル HTML ダッシュボード（KIK-789）."""

import re

import pytest

from src.data import dashboard as D
from src.data import dashboard_svg as S


def _ctx(**over):
    ctx = {
        "generated_at": "2026-11-24T21:00",
        "history": [{"date": "2026-05-06", "total": 8_400_000, "source": "report_text"},
                    {"date": "2026-08-05", "total": 7_900_000, "source": "report_text"},
                    {"date": "2026-11-24", "total": 8_000_000, "source": "daily"}],
        "trades": [{"date": "2026-05-19", "action": "sell", "symbol": "5401.T", "shares": 2000,
                    "price": 520, "realized_pnl": -114000, "memo": "stop <b>", "sleeve": "core"},
                   {"date": "2026-11-21", "action": "buy", "symbol": "1926.T", "shares": 100,
                    "price": 976, "realized_pnl": None, "memo": "", "sleeve": "core"}],
        "positions": [
            {"symbol": "7453.T", "shares": 100, "cost_price": 1199.0, "cost_currency": "JPY",
             "role": "growth", "memo": "良品計画", "price": 4926.0},
            {"symbol": "1926.T", "shares": 100, "cost_price": 976.0, "cost_currency": "JPY",
             "role": "", "memo": "<script>x</script>", "price": None},
            {"symbol": "AAPL", "shares": 10, "cost_price": 150.0, "cost_currency": "USD",
             "role": "growth", "memo": "", "price": 200.0},
        ],
        "cash": {"total_jpy": 5_000_000, "date": "2026-11-21"},
        "allocation": {"goal": {"amount": 10_000_000, "deadline": "2031-04-30", "required_equity_cagr": 6.74,
                                "basis": "管理分のみ"},
                       "role_targets": {"normal": {"income": [35, 45], "growth": [35, 45], "cash": [15, 25]}},
                       "concentration": {"single_stock": 15},
                       "unconditional_hold": {"7453.T": "無条件保有（全株）"}},
        "checklists": {"data_quality": {"apply_to": ["評価"], "items": [{"id": "DQ9", "check": "株数照合", "why": "古い"}]},
                       "unknown_section": {"items": [{"id": "ZZ1"}]}},
        "lessons": [{"date": "2026-11-23", "content": "【3類型】式\n詳細"}],
    }
    ctx.update(over)
    return ctx


class TestRender:
    def test_sections_and_no_external_urls(self):
        html = D.render(_ctx())
        for h in ("資産推移", "現在の配分", "売買の推移", "戦略", "選定条件・チェックリスト"):
            assert f"<h2>{h}</h2>" in html
        assert not re.search(r"(src|href)=['\"]?(https?:)?//", html)
        assert "https://" not in html and "http://" not in html
        assert "url(" not in html and "@import" not in html and "<link" not in html and "<script" not in html
        assert [f'id="s{i}"' in html for i in range(1, 6)] == [True] * 5

    def test_escaping(self):
        html = D.render(_ctx())
        assert "<script>x</script>" not in html and "&lt;script&gt;" in html
        assert "stop <b>" not in html and "stop &lt;b&gt;" in html

    @pytest.mark.parametrize("mutate", [
        lambda c: c["trades"][0].update(symbol="<x>", action="<x>", sleeve="<x>"),
        lambda c: c["positions"][0].update(symbol="<x>", role="<x>"),
        lambda c: c["lessons"][0].update(content="<x>", date="<x>"),
        lambda c: c["checklists"]["data_quality"].update(apply_to=["<x>"], items=[{"id": "<x>", "check": "<x>", "why": "<x>"}]),
        lambda c: c["allocation"]["goal"].update(deadline="<x>", basis="<x>", required_equity_cagr="<x>"),
        lambda c: c["allocation"]["role_targets"].update({"<x>": {"<x>": ["<x>", "<x>"]}}),
        lambda c: c["allocation"]["role_targets"]["normal"].update(growth=["<x>", "<x>"]),
        lambda c: c["cash"].update(date="<x>"),
        lambda c: c.update(generated_at="<x>"),
        lambda c: c["history"][-1].update(date="2026-11-24<x>"),
    ])
    def test_every_field_escaped(self, mutate):
        ctx = _ctx()
        mutate(ctx)
        try:
            html = D.render(ctx)
        except ValueError:
            return   # 日付として読めない値は描画前に弾かれる（それも可）
        assert "<x>" not in html

    def test_long_memo_cut_before_escape(self):
        ctx = _ctx()
        ctx["positions"][0]["memo"] = "a" * 39 + "<b>"
        html = D.render(ctx)
        assert "a" * 39 + "&lt;" in html and "&l<" not in html and "&lt</td>" not in html
    def test_unconditional_marked(self):
        html = D.render(_ctx())
        assert "無条件保有（全株）" in html

    def test_totals_exclude_non_jpy_and_use_cost_when_unpriced(self):
        html = D.render(_ctx())
        # 株式 = 7453: 492,600 + 1926: 97,600（取得単価）。AAPL は換算しない
        assert "株式 ¥590,200" in html and "現金 ¥5,000,000" in html
        assert "1 銘柄は取得単価で評価" in html

    def test_non_jpy_noted(self):
        html = D.render(_ctx())
        assert "円以外の銘柄（AAPL）" in html and "200.00 USD" in html

    def test_broken_inputs_do_not_crash(self):
        ctx = _ctx(cash={"total_jpy": "abc"})
        ctx["trades"].append({"date": None, "action": "buy", "symbol": 7203, "shares": "<x>", "price": None})
        ctx["checklists"]["data_quality"]["items"] = None
        ctx["allocation"]["role_targets"]["normal"]["income"] = [35]
        ctx["allocation"]["unconditional_hold"] = ["bad"]
        html = D.render(ctx)
        assert "<x>" not in html

    def test_negative_yen_format(self):
        assert D._yen(-900) == "-¥900" and D._yen(None) == "-" and D._yen(0) == "¥0"

    def test_zero_total_with_targets(self):
        html = D.render(_ctx(positions=[], cash={"total_jpy": 0}))
        assert "0.0%（目標 35〜45%）" in html

    def test_currency_none_is_jpy_and_zero_price_unpriced(self):
        ctx = _ctx(positions=[{"symbol": "X.T", "shares": 100, "cost_price": 10.0, "cost_currency": None,
                               "role": "income", "memo": "", "price": 0}])
        html = D.render(ctx)
        assert "株式 ¥1,000" in html and "取得単価で代用" in html

    def test_empty_everything(self):
        html = D.render({"generated_at": "x"})
        assert "資産推移のデータがまだありません" in html and "取引の記録がありません" in html

    def test_checklists_sections(self):
        html = D.render(_ctx())
        assert "DQ9" in html and "ZZ1" not in html   # 見出しの無いセクションは出さない

    def test_lesson_first_line(self):
        assert D._first_line("【3類型】式" + chr(10) + "詳細") == "【3類型】式"
        assert D._first_line("  " + chr(10)) == "" and D._first_line(None) == ""
        assert D._first_line("あ" * 100, n=10) == "あ" * 10 + "…"


class TestSvg:
    def test_line_chart_segments_and_markers(self):
        svg = S.line_chart(_ctx()["history"], 1e7, "2031-04-30", 6.74,
                           [{"date": "2026-05-19", "kind": "sell", "label": "<x>"},
                            {"date": "2020-01-01", "kind": "buy"}, {"bad": 1}])
        assert 'class="line-est"' in svg and 'class="line-rec"' in svg
        assert svg.count('class="mk-sell"') == 1 and 'class="mk-buy"' not in svg   # 範囲外は描かない
        assert "&lt;x&gt;" in svg and 'class="req"' in svg

    def test_single_point(self):
        svg = S.line_chart([{"date": "2026-11-24", "total": 8e6, "source": "daily"}])
        assert "<svg" in svg and "nan" not in svg.lower()

    def test_flat_values(self):
        pts = [{"date": f"2026-11-{d:02d}", "total": 8e6, "source": "daily"} for d in (1, 2, 3)]
        assert "nan" not in S.line_chart(pts).lower()

    def test_all_zero_bars(self):
        assert "nan" not in S.bar_chart([("2026-05", 0.0), ("2026-06", 0.0)], "x").lower()

    def test_single_point_with_target(self):
        svg = S.line_chart([{"date": "2026-11-24", "total": 8e6, "source": "daily"}], 1e7, "2031-04-30", 6.74)
        assert "nan" not in svg.lower() and "inf" not in svg.lower()

    def test_zero_total_points(self):
        pts = [{"date": "2026-11-01", "total": 0, "source": "daily"}, {"date": "2026-11-02", "total": 0, "source": "daily"}]
        assert "nan" not in S.line_chart(pts).lower()

    def test_bar_chart(self):
        svg = S.bar_chart([("2026-05", -114000.0), ("2026-08", 300000.0), ("2026-09", 0.0)], "x")
        assert 'class="bar-neg"' in svg and 'class="bar-pos"' in svg and "-11万" in svg and "30万" in svg
        assert "-1.2万" in S.bar_chart([("2026-10", -12000.0)], "x")
        assert S.bar_chart([], "x").startswith("<p")


class TestBuild:
    def test_build_from_files(self, tmp_path):
        (tmp_path / "data" / "history" / "trade").mkdir(parents=True)
        (tmp_path / "data" / "reports").mkdir()
        (tmp_path / "config").mkdir()
        (tmp_path / "data" / "portfolio.csv").write_text(
            "symbol,shares,cost_price,cost_currency,purchase_date,memo,role\n7203.T,100,2000,JPY,2026-01-01,トヨタ,income\n",
            encoding="utf-8")
        (tmp_path / "data" / "reports" / "daily_20261124.md").write_text("総資産 ¥8,000,000", encoding="utf-8")
        (tmp_path / "config" / "allocation.yaml").write_text("goal: {amount: 10000000}\n", encoding="utf-8")
        (tmp_path / "config" / "checklists.yaml").write_text(": broken yaml [", encoding="utf-8")
        path = D.build_dashboard(base_dir=str(tmp_path), price_fn=lambda s: 2500.0)
        html = path.read_text(encoding="utf-8")
        assert path.name == "index.html" and "7203.T" in html and "¥250,000" in html
        assert "¥8,000,000" in html

    def test_price_fn_none(self, tmp_path):
        (tmp_path / "data").mkdir()
        path = D.build_dashboard(out=str(tmp_path / "o.html"), base_dir=str(tmp_path), price_fn=None)
        assert path.exists()

    def test_facade(self):
        from tools import dashboard as T
        assert T.build_dashboard is D.build_dashboard

    def test_open_dashboard(self, tmp_path):
        f = tmp_path / "index.html"
        f.write_text("<html></html>", encoding="utf-8")
        seen = []
        assert D.open_dashboard(f, opener=lambda u: seen.append(u) or True) is True
        assert seen == [f.resolve().as_uri()] and seen[0].startswith("file://")

    def test_open_dashboard_missing_or_failing(self, tmp_path):
        assert D.open_dashboard(tmp_path / "nope.html", opener=lambda u: True) is False
        f = tmp_path / "index.html"
        f.write_text("x", encoding="utf-8")

        def boom(u):
            raise RuntimeError("no browser")
        assert D.open_dashboard(f, opener=boom) is False
        assert D.open_dashboard(f, opener=lambda u: False) is False

    def test_open_facade(self):
        from tools import dashboard as T
        assert T.open_dashboard is D.open_dashboard
