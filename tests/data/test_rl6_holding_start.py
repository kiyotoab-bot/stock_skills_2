"""RL6 は今の保有を始めた日より後のバーだけを判定する（KIK-778・KIK-777 のレビュー指摘）.

1. 売って14日以内に買い直すと、前の保有のカーソルから保有していない期間を今の
   ストップで判定し、偽の抵触で FAIL になっていた
2. 01:05 の実行で cursor_last=9/29、9/30 の場中に購入、23:50 に再実行すると
   購入日 9/30 のバー（買う前の安値）を判定していた
3. 履歴が止まった銘柄は14日後に黙って起点を戻され、止まっていた間を見落としていた
"""

import json

from src.data.checklist_review import check_stop_breach
from src.data.note_manager import _position_starts, get_stop_levels


def _rl6(stops, histories, since):
    prices = {s: h[-1][1] for s, h in histories.items() if h}
    prices.update({s: 150.0 for s, h in histories.items() if not h})
    return check_stop_breach(prices, stops, histories=histories, since=since)[0]


class TestRebuyWithinStaleWindow:
    def test_old_cursor_dropped_by_purchase_date(self):
        """9/20 に売り（カーソル 9/20）、9/28 に高いストップで買い直し。9/21-27 は見ない."""
        stops = {"A": {"stop": 130.0, "opened_on": "2026-09-28", "reopened": True},
                 "B": {"stop": 10.0}}
        h = {"A": [("2026-09-20", 100.0, 99.0), ("2026-09-24", 110.0, 105.0),
                   ("2026-09-29", 150.0, 145.0), ("2026-09-30", 152.0, 148.0)],
             "B": [("2026-09-30", 20.0, 20.0)]}
        cur = {"A": {"date": "2026-09-20", "stop": 90.0},
               "B": {"date": "2026-09-29", "stop": 10.0}}
        r = _rl6(stops, h, cur)
        assert r["status"] == "PASS", r["detail"]
        assert "購入日に合わせた A（前回 2026-09-20・購入 2026-09-28）" in r["detail"]
        assert r["stop_cursor"]["A"] == {"date": "2026-09-30", "stop": 130.0}

    def test_breach_after_rebuy_is_still_caught(self):
        stops = {"A": {"stop": 130.0, "opened_on": "2026-09-28", "reopened": True}}
        h = {"A": [("2026-09-24", 110.0, 105.0), ("2026-09-29", 125.0, 120.0),
                   ("2026-09-30", 150.0, 148.0)]}
        r = _rl6(stops, h, {"A": {"date": "2026-09-20", "stop": 90.0}})
        assert r["status"] == "FAIL" and "2026-09-29" in r["detail"]

    def test_cursor_from_current_holding_is_kept(self):
        """購入日以降のカーソルは今の保有のもの。従来どおりカーソルの日から見る."""
        stops = {"A": {"stop": 100.0, "opened_on": "2026-09-01"}}
        h = {"A": [("2026-09-29", 99.0, 98.0), ("2026-09-30", 150.0, 148.0)]}
        r = _rl6(stops, h, {"A": {"date": "2026-09-29", "stop": 100.0}})
        assert r["status"] == "FAIL", r["detail"]


class TestPurchaseDayBar:
    def test_same_day_rerun_skips_purchase_day_bar(self):
        """01:05 で cursor_last=9/29、9/30 場中に購入、23:50 再実行。9/30 の買う前の安値で発動扱いしない."""
        stops = {"OLD": {"stop": 10.0}, "NEW": {"stop": 100.0, "opened_on": "2026-09-30"}}
        h = {"OLD": [("2026-09-30", 20.0, 20.0)],
             "NEW": [("2026-09-29", 105.0, 104.0), ("2026-09-30", 120.0, 95.0)]}
        r = _rl6(stops, h, {"OLD": {"date": "2026-09-29", "stop": 10.0}})
        assert r["status"] == "PASS", r["detail"]

    def test_no_cursor_written_on_purchase_day(self):
        """購入日のバーにカーソルを書かない。書くと次の実行でそのバーを見直す（再レビュー指摘 1）."""
        stops = {"OLD": {"stop": 10.0}, "NEW": {"stop": 100.0, "opened_on": "2026-09-30"}}
        h = {"OLD": [("2026-09-30", 20.0, 20.0)],
             "NEW": [("2026-09-29", 105.0, 104.0), ("2026-09-30", 120.0, 95.0)]}
        cur = {"OLD": {"date": "2026-09-29", "stop": 10.0}}
        r1 = _rl6(stops, h, cur)
        assert "NEW" not in r1["stop_cursor"]
        # 3回目（翌朝 10/1 バー前）。カーソルを引き継いでも 9/30 は見ない
        cur2 = {**cur, **r1["stop_cursor"]}
        r2 = _rl6(stops, h, cur2)
        assert r2["status"] == "PASS", r2["detail"]

    def test_rebuy_cursor_on_purchase_day_is_dropped(self):
        """買い直しの購入日にカーソルが残っていても（修正前の記録）、購入日のバーは見ない."""
        stops = {"NEW": {"stop": 100.0, "opened_on": "2026-09-30", "reopened": True}}
        h = {"NEW": [("2026-09-30", 120.0, 95.0)]}
        r = _rl6(stops, h, {"NEW": {"date": "2026-09-30", "stop": 100.0}})
        assert r["status"] == "PASS", r["detail"]

    def test_next_bar_after_purchase_is_judged(self):
        stops = {"OLD": {"stop": 10.0}, "NEW": {"stop": 100.0, "opened_on": "2026-09-30"}}
        h = {"OLD": [("2026-10-01", 20.0, 20.0)],
             "NEW": [("2026-09-30", 120.0, 95.0), ("2026-10-01", 120.0, 99.0)]}
        r = _rl6(stops, h, {"OLD": {"date": "2026-09-29", "stop": 10.0}})
        assert r["status"] == "FAIL" and "NEW 2026-10-01" in r["detail"]

    def test_date_string_since_also_respects_purchase_date(self):
        stops = {"NEW": {"stop": 100.0, "opened_on": "2026-09-30"}}
        h = {"NEW": [("2026-09-30", 120.0, 95.0)]}
        assert _rl6(stops, h, "2026-09-29")["status"] == "PASS"


class TestStalledHistory:
    def test_continuous_holding_is_not_reset_and_gap_hit_is_warned(self):
        """記録上は持ち続けている。間の抵触は拾うが、記録に無い売り（逆指値の約定）と区別できない
        ので FAIL にせず WARN で確認を促す（再々々レビュー指摘）."""
        stops = {"A": {"stop": 100.0}, "B": {"stop": 100.0, "opened_on": "2026-06-01"}}
        h = {"A": [("2026-09-30", 150.0, 150.0)],
             "B": [("2026-07-15", 95.0, 94.0), ("2026-09-30", 150.0, 150.0)]}
        cur = {"A": {"date": "2026-09-29", "stop": 100.0},
               "B": {"date": "2026-06-30", "stop": 100.0}}
        r = _rl6(stops, h, cur)
        assert r["status"] == "WARN", r["detail"]
        assert "間に 2026-07-15" in r["detail"] and "約定一覧" in r["detail"]
        assert "新規保有扱い" not in r["detail"]
        assert r["stop_cursor"]["B"] == {"date": "2026-09-30", "stop": 100.0}

    def test_unlogged_sell_does_not_fail_on_unheld_bars(self):
        """逆指値が約定したが売りを記録していない。保有していない間のバーで「執行せよ」と出さない."""
        stops = {"Y": {"stop": 100.0}, "X": {"stop": 100.0, "opened_on": "2026-06-01"}}
        h = {"Y": [("2026-09-30", 150.0, 150.0)],
             "X": [("2026-09-02", 90.0, 88.0), ("2026-09-10", 95.0, 94.0),
                   ("2026-09-30", 150.0, 149.0)]}
        cur = {"X": {"date": "2026-09-01", "stop": 100.0},
               "Y": {"date": "2026-09-30", "stop": 100.0}}
        r = _rl6(stops, h, cur)
        assert r["status"] == "WARN", r["detail"]
        assert "見逃し抵触" not in r["detail"] and "トリガー到達" not in r["detail"]

    def test_stalled_latest_bar_below_stop_still_fails(self):
        stops = {"A": {"stop": 100.0}, "B": {"stop": 100.0, "opened_on": "2026-06-01"}}
        h = {"A": [("2026-09-30", 150.0, 150.0)],
             "B": [("2026-07-15", 140.0, 135.0), ("2026-09-30", 98.0, 97.0)]}
        cur = {"A": {"date": "2026-09-29", "stop": 100.0},
               "B": {"date": "2026-06-30", "stop": 100.0}}
        assert _rl6(stops, h, cur)["status"] == "FAIL"

    def test_gap_without_breach_is_warned(self):
        stops = {"A": {"stop": 100.0}, "B": {"stop": 100.0, "opened_on": "2026-06-01"}}
        h = {"A": [("2026-09-30", 150.0, 150.0)],
             "B": [("2026-07-15", 140.0, 135.0), ("2026-09-30", 150.0, 150.0)]}
        cur = {"A": {"date": "2026-09-29", "stop": 100.0},
               "B": {"date": "2026-06-30", "stop": 100.0}}
        r = _rl6(stops, h, cur)
        assert r["status"] == "WARN" and "判定が途切れていた B" in r["detail"]

    def test_missing_history_this_run_is_warned(self):
        stops = {"A": {"stop": 100.0}, "B": {"stop": 100.0}}
        h = {"A": [("2026-09-30", 150.0, 150.0)], "B": []}
        cur = {"A": {"date": "2026-09-29", "stop": 100.0},
               "B": {"date": "2026-09-29", "stop": 100.0}}
        r = _rl6(stops, h, cur)
        assert r["status"] == "WARN" and "価格履歴なし B" in r["detail"]
        assert "B" not in r["stop_cursor"]           # 見ていないので起点は進めない

    def test_no_history_warning_when_histories_not_given(self):
        r = check_stop_breach({"A": 150.0}, {"A": {"stop": 100.0}}, since="2026-09-29")[0]
        assert r["status"] == "PASS", r["detail"]


class TestPositionStarts:
    def _td(self, tmp_path, rows):
        d = tmp_path / "trades"
        d.mkdir(exist_ok=True)
        (d / "t.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return str(d)

    def test_rebuy_starts_at_first_buy_after_selling_out(self, tmp_path):
        td = self._td(tmp_path, [
            {"date": "2026-09-28", "action": "buy", "symbol": "A", "shares": 100},
            {"date": "2026-07-01", "action": "buy", "symbol": "A", "shares": 100},   # 順不同
            {"date": "2026-09-20", "action": "sell", "symbol": "A", "shares": 100},
            {"date": "2026-09-29", "action": "buy", "symbol": "A", "shares": 100},   # 買い増し
        ])
        assert _position_starts(td) == {"A": {"date": "2026-09-28", "reopened": True}}

    def test_partial_sell_keeps_original_start(self, tmp_path):
        td = self._td(tmp_path, [
            {"date": "2026-07-01", "action": "buy", "symbol": "A", "shares": 200},
            {"date": "2026-08-04", "action": "sell", "symbol": "A", "shares": 100},
        ])
        assert _position_starts(td) == {"A": {"date": "2026-07-01", "reopened": False}}

    def test_same_day_add_and_trim_stays_one_holding(self, tmp_path):
        """同日の買い増し+一部売却を新規保有と読まない。読むと未判定のバーを飛ばす（再レビュー指摘 2）."""
        td = self._td(tmp_path, [
            {"date": "2026-07-01", "action": "buy", "symbol": "A", "shares": 100},
            {"date": "2026-09-30", "action": "sell", "symbol": "A", "shares": 100},
            {"date": "2026-09-30", "action": "buy", "symbol": "A", "shares": 100},
        ])
        assert _position_starts(td) == {"A": {"date": "2026-07-01", "reopened": False}}

    def test_sold_out_and_unreadable(self, tmp_path):
        td = self._td(tmp_path, [
            {"date": "2026-07-01", "action": "buy", "symbol": "A", "shares": 100},
            {"date": "2026-08-01", "action": "sell", "symbol": "A", "shares": 100},
        ])
        assert _position_starts(td) == {}
        assert _position_starts(str(tmp_path / "missing")) == {}

    def test_get_stop_levels_carries_opened_on(self, tmp_path):
        (tmp_path / "A.json").write_text(json.dumps([{
            "symbol": "A", "type": "exit-rule", "date": "2026-09-28",
            "timestamp": "2026-09-28T10:00:00", "stop_loss": "130"}]), encoding="utf-8")
        td = self._td(tmp_path, [
            {"date": "2026-07-01", "action": "buy", "symbol": "A", "shares": 100},
            {"date": "2026-09-20", "action": "sell", "symbol": "A", "shares": 100},
            {"date": "2026-09-28", "action": "buy", "symbol": "A", "shares": 100},
        ])
        got = get_stop_levels(base_dir=str(tmp_path), trade_dir=td)["A"]
        assert got["stop"] == 130.0 and got["opened_on"] == "2026-09-28" and got["reopened"]

    def test_pre_log_holding_never_reopens(self, tmp_path):
        """記録前から 300 株。売り100→買い200→売り100 で記録上 0 でも、実際は 200 株持っている（4回目レビュー指摘）."""
        td = self._td(tmp_path, [
            {"date": "2026-08-01", "action": "sell", "symbol": "P", "shares": 100},
            {"date": "2026-08-10", "action": "buy", "symbol": "P", "shares": 200},
            {"date": "2026-09-01", "action": "sell", "symbol": "P", "shares": 100},
            {"date": "2026-09-24", "action": "buy", "symbol": "P", "shares": 100},
        ])
        assert _position_starts(td)["P"]["reopened"] is False

    def test_buy_without_logged_sell_out_is_not_reopened(self, tmp_path):
        """記録前からの保有（買いの記録なし）への買い増し・記録前の一部売却は買い直しではない."""
        td = self._td(tmp_path, [
            {"date": "2026-08-01", "action": "sell", "symbol": "P", "shares": 100},  # 記録前の買い
            {"date": "2026-09-24", "action": "buy", "symbol": "P", "shares": 200},
            {"date": "2026-09-24", "action": "buy", "symbol": "Q", "shares": 100},
        ])
        got = _position_starts(td)
        assert got["P"] == {"date": "2026-09-24", "reopened": False}
        assert got["Q"] == {"date": "2026-09-24", "reopened": False}


class TestIncompleteTradeLog:
    def test_add_on_to_pre_log_holding_keeps_cursor(self):
        """記録前から持つ X に 9/24 買い増し。カーソル 9/23 を捨てず、9/24 のバーも判定する（再々レビュー指摘 1）."""
        stops = {"X": {"stop": 100.0, "opened_on": "2026-09-24", "reopened": False}}
        h = {"X": [("2026-09-23", 120.0, 118.0), ("2026-09-24", 110.0, 95.0),
                   ("2026-09-25", 120.0, 115.0)]}
        r = _rl6(stops, h, {"X": {"date": "2026-09-23", "stop": 100.0}})
        assert r["status"] == "FAIL" and "X 2026-09-24" in r["detail"]
        assert "購入日に合わせた" not in r["detail"]


class TestStalledStopRaised:
    def _case(self, gap_close):
        stops = {"A": {"stop": 10.0}, "B": {"stop": 1100.0, "opened_on": "2026-06-01"}}
        h = {"A": [("2026-09-30", 20.0, 20.0)],
             "B": [("2026-09-05", 1200.0, 1150.0), ("2026-09-15", gap_close, gap_close),
                   ("2026-09-30", 1300.0, 1250.0)]}
        cur = {"A": {"date": "2026-09-29", "stop": 10.0},
               "B": {"date": "2026-09-05", "stop": 1000.0}}
        return _rl6(stops, h, cur)

    def test_gap_bars_use_stop_at_cursor_not_todays(self):
        """途切れていた間に 1000→1100 へ切り上げ。1050 を 1100 で判定して偽の FAIL にしない（再々レビュー指摘 2）."""
        r = self._case(1050.0)
        assert r["status"] == "WARN", r["detail"]
        assert "見逃し抵触" not in r["detail"] and "間に 2026" not in r["detail"]
        assert "切り上げ後なら触れている" in r["detail"] and "2026-09-15" in r["detail"]

    def test_gap_hit_below_old_stop_is_warned_not_failed(self):
        r = self._case(990.0)
        assert r["status"] == "WARN" and "間に 2026-09-15" in r["detail"]

    def test_latest_bar_uses_todays_stop(self):
        stops = {"A": {"stop": 10.0}, "B": {"stop": 1100.0, "opened_on": "2026-06-01"}}
        h = {"A": [("2026-09-30", 20.0, 20.0)],
             "B": [("2026-09-05", 1200.0, 1150.0), ("2026-09-30", 1080.0, 1070.0)]}
        cur = {"A": {"date": "2026-09-29", "stop": 10.0},
               "B": {"date": "2026-09-05", "stop": 1000.0}}
        assert _rl6(stops, h, cur)["status"] == "FAIL"
