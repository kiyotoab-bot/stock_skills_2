"""EC6 増資（希薄化）履歴チェックのテスト。"""

import datetime
import random

import pandas as pd

from src.data import dilution
from src.data.checklist_review import check_dilution as reexported_check
from src.data.dilution import check_dilution, get_share_count_history

TODAY = datetime.date(2026, 9, 21)


def _series(*points):
    return list(points)


class TestCheckDilution:
    def test_empty_returns_na(self):
        results = check_dilution({}, today=TODAY)
        assert len(results) == 1
        assert results[0]["id"] == "EC6"
        assert results[0]["status"] == "N/A"

    def test_stable_shares_pass(self):
        series = _series(("2024-05-10", 100_000_000), ("2025-05-10", 100_000_000),
                         ("2026-05-10", 100_500_000))  # +0.5%: SO行使の範囲
        r = check_dilution({"7777.T": series}, today=TODAY)[0]
        assert r["status"] == "PASS"
        assert "7777.T" in r["detail"]

    def test_buyback_decrease_is_pass(self):
        # 自己株消却で緩やかに減少 → 希薄化ではない
        series = _series(("2024-05-10", 100_000_000), ("2025-05-10", 96_000_000),
                         ("2026-05-10", 92_000_000))
        r = check_dilution({"7777.T": series}, today=TODAY)[0]
        assert r["status"] == "PASS"

    def test_dilution_range_warn(self):
        # +15%: 公募増資の典型レンジ
        series = _series(("2024-05-10", 100_000_000), ("2025-05-10", 115_000_000))
        r = check_dilution({"9999.T": series}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "増資疑い" in r["detail"]
        assert "2025-05-10" in r["detail"]  # イベント時期を出す

    def test_gradual_dilution_caught_by_cumulative(self):
        # MSCB 型: 隣接では毎回 +4%（単発閾値未満）だが累計 +12.5%
        series = _series(("2024-11-10", 100_000_000), ("2025-02-10", 104_000_000),
                         ("2025-05-10", 108_160_000), ("2025-08-10", 112_486_400))
        r = check_dilution({"9999.T": series}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "累計" in r["detail"]

    def test_split_range_needs_manual_check(self):
        # +100%: 1:2 分割の可能性が高い → 目視確認を要求（PASS で素通りさせない）
        series = _series(("2024-05-10", 100_000_000), ("2025-05-10", 200_000_000))
        r = check_dilution({"1926.T": series}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "目視確認" in r["detail"]
        assert "増資疑い" not in r["detail"]

    def test_merge_needs_manual_check(self):
        # -50%: 併合の可能性 → 目視確認（併合+新株発行の複合を覆い隠さない）
        series = _series(("2024-05-10", 100_000_000), ("2025-05-10", 50_000_000))
        r = check_dilution({"8888.T": series}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "併合" in r["detail"]

    def test_split_plus_dilution_shows_both(self):
        # 分割(+100%)と公募増資(+20%)が同一窓 → 両方 detail に出す。
        # 分割だけ見て「OK」と閉じさせない
        series = _series(("2024-05-10", 100_000_000), ("2025-02-10", 200_000_000),
                         ("2025-08-10", 240_000_000))
        r = check_dilution({"7777.T": series}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "増資疑い" in r["detail"]
        assert "目視確認" in r["detail"]
        assert "2025-08-10 +20.0%" in r["detail"]

    def test_gradual_dilution_after_split_detected(self):
        # 分割(+100%)の後に毎四半期+4%×8（累計+36.9%）。分割イベントで系列を
        # 区切り、分割後の区間累計で検知する。「分割を確認して閉じる」動作で
        # 段階的希薄化を見逃させない
        series = [("2024-05-10", 100_000_000.0), ("2024-08-10", 200_000_000.0)]
        v = 200_000_000.0
        for d in ["2024-11-10", "2025-02-10", "2025-05-10", "2025-08-10",
                  "2025-11-10", "2026-02-10", "2026-05-10", "2026-08-10"]:
            v *= 1.04
            series.append((d, v))
        r = check_dilution({"7777.T": series}, today=TODAY)[0]
        assert "目視確認" in r["detail"]           # 分割は引き続き目視確認
        assert "累計(2024-08-10以降)" in r["detail"]  # 分割後の区間累計も出す
        assert "増資疑い" in r["detail"]

    def test_same_day_duplicate_input_no_phantom_event(self):
        # check_dilution へ直接渡した系列の同日重複は後勝ち。
        # タプル全体ソートだと (d,100M)→(d,106M) が +6% の架空イベントになる
        series = _series(("2024-05-10", 100_000_000), ("2024-05-10", 106_000_000),
                         ("2026-05-10", 106_000_000))
        r = check_dilution({"7777.T": series}, today=TODAY)[0]
        assert r["status"] == "PASS"

    def test_old_events_outside_lookback_ignored(self):
        # 増資イベントが4年前 → 3年窓の外
        series = _series(("2022-05-10", 100_000_000), ("2022-11-10", 130_000_000),
                         ("2024-05-10", 130_000_000), ("2026-05-10", 130_000_000))
        r = check_dilution({"7777.T": series}, today=TODAY)[0]
        assert r["status"] == "PASS"

    def test_event_straddling_window_boundary_detected(self):
        # cutoff(2023-09-21) の直前の開示を基準点として残す。
        # 窓の最初の開示に現れる増加（d0 < cutoff <= d1）を盲点にしない
        series = _series(("2023-06-10", 100_000_000), ("2023-11-10", 120_000_000),
                         ("2026-05-10", 120_000_000))
        r = check_dilution({"9999.T": series}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "2023-11-10" in r["detail"]

    def test_single_point_is_data_insufficient_warn(self):
        # 「見られなかったのに総合 PASS」を作らない（SD1/SD2 と同じ方針）
        r = check_dilution({"7777.T": _series(("2026-05-10", 100_000_000))},
                           today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "データ不足" in r["detail"]

    def test_unknown_alongside_clean_still_warn(self):
        clean = _series(("2024-05-10", 50_000_000), ("2026-05-10", 50_000_000))
        r = check_dilution({"1111.T": clean, "2222.T": []}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "1111.T" in r["detail"] and "2222.T" in r["detail"]

    def test_all_candidates_listed_even_when_one_warns(self):
        # 全候補を detail に載せる（SD1/RL6 と同じ方針）
        clean = _series(("2024-05-10", 50_000_000), ("2026-05-10", 50_000_000))
        dirty = _series(("2024-05-10", 100_000_000), ("2025-05-10", 120_000_000))
        r = check_dilution({"1111.T": clean, "2222.T": dirty}, today=TODAY)[0]
        assert r["status"] == "WARN"
        assert "1111.T" in r["detail"] and "2222.T" in r["detail"]

    def test_unsorted_input_is_sorted(self):
        series = _series(("2026-05-10", 115_000_000), ("2024-05-10", 100_000_000))
        r = check_dilution({"9999.T": series}, today=TODAY)[0]
        assert r["status"] == "WARN"

    def test_detail_includes_thresholds(self):
        # 閾値が detail に出て判定が再現できる（SD1 と同じ方針）
        r = check_dilution({}, today=TODAY)[0]
        assert "+5%" in r["detail"]
        assert "+10%" in r["detail"]

    def test_reexport_from_checklist_review(self):
        series = _series(("2024-05-10", 100_000_000), ("2025-05-10", 115_000_000))
        r = reexported_check({"9999.T": series}, today=TODAY)[0]
        assert r["id"] == "EC6"
        assert r["status"] == "WARN"


class TestGetShareCountHistory:
    def _patch_client(self, monkeypatch, df):
        class FakeClient:
            def get_fin_summary(self, code):
                return df

        monkeypatch.setattr("src.data.jquants_client._client.is_available",
                            lambda: True)
        monkeypatch.setattr("src.data.jquants_client._client.get_client",
                            lambda: FakeClient())

    def test_returns_oldest_first_and_skips_missing(self, monkeypatch):
        df = pd.DataFrame([
            {"DiscDate": "2026-05-10", "ShOutFY": 115_000_000},
            {"DiscDate": "2025-05-10", "ShOutFY": None},   # 欠損はスキップ
            {"DiscDate": "2024-05-10", "ShOutFY": 100_000_000},
        ])
        self._patch_client(monkeypatch, df)
        hist = get_share_count_history("9999.T")
        assert hist == [("2024-05-10", 100_000_000.0),
                        ("2026-05-10", 115_000_000.0)]

    def test_limit_keeps_newest_even_if_api_order_is_shuffled(self, monkeypatch):
        # ⚠️ J-Quants は日付順に返さない。ソート前に行数で切ると最新を落とす
        dates = [f"20{20 + i // 4}-{(i % 4) * 3 + 1:02d}-10" for i in range(20)]
        rows = [{"DiscDate": d, "ShOutFY": 100_000_000 + i}
                for i, d in enumerate(dates)]
        random.Random(42).shuffle(rows)
        self._patch_client(monkeypatch, pd.DataFrame(rows))
        hist = get_share_count_history("9999.T", limit=16)
        assert len(hist) == 16
        assert [d for d, _ in hist] == sorted(dates)[-16:]  # 新しい16件が古い順
        assert hist[-1][0] == max(dates)                    # 最新は必ず残る

    def test_same_day_correction_uses_later_row(self, monkeypatch):
        # 訂正短信: 同一開示日は API 応答の後の行を採用
        df = pd.DataFrame([
            {"DiscDate": "2026-05-10", "ShOutFY": 100_000_000},
            {"DiscDate": "2026-05-10", "ShOutFY": 101_000_000},  # 訂正
        ])
        self._patch_client(monkeypatch, df)
        assert get_share_count_history("9999.T") == [("2026-05-10", 101_000_000.0)]

    def test_invalid_dates_skipped(self, monkeypatch):
        # NaT は str() で "NaT" になり、文字列ソートで全 ISO 日付より後ろ
        # ＝「最新の開示」に化けて架空イベントを作る。非 ISO も同罪
        df = pd.DataFrame([
            {"DiscDate": pd.NaT, "ShOutFY": 999_000_000},
            {"DiscDate": "20260510", "ShOutFY": 888_000_000},
            {"DiscDate": "2024-05-10", "ShOutFY": 100_000_000},
        ])
        self._patch_client(monkeypatch, df)
        assert get_share_count_history("9999.T") == [("2024-05-10", 100_000_000.0)]

    def test_nonpositive_shares_skipped(self, monkeypatch):
        df = pd.DataFrame([
            {"DiscDate": "2026-05-10", "ShOutFY": 0},
            {"DiscDate": "2025-05-10", "ShOutFY": -5},
            {"DiscDate": "2024-05-10", "ShOutFY": 100_000_000},
        ])
        self._patch_client(monkeypatch, df)
        assert get_share_count_history("9999.T") == [("2024-05-10", 100_000_000.0)]

    def test_unavailable_returns_empty(self, monkeypatch):
        monkeypatch.setattr("src.data.jquants_client._client.is_available",
                            lambda: False)
        assert get_share_count_history("9999.T") == []

    def test_api_exception_returns_empty(self, monkeypatch):
        class BoomClient:
            def get_fin_summary(self, code):
                raise RuntimeError("boom")

        monkeypatch.setattr("src.data.jquants_client._client.is_available",
                            lambda: True)
        monkeypatch.setattr("src.data.jquants_client._client.get_client",
                            lambda: BoomClient())
        assert get_share_count_history("9999.T") == []


class TestThresholds:
    def test_warn_threshold_above_so_noise(self):
        # SO行使は年1%未満が普通。閾値がそれより十分上にあること
        assert dilution.DILUTION_WARN_PCT >= 3.0

    def test_cumulative_threshold_between_warn_and_split(self):
        assert (dilution.DILUTION_WARN_PCT
                <= dilution.DILUTION_CUM_WARN_PCT
                < dilution.DILUTION_SPLIT_PCT)

    def test_split_threshold_below_minimum_common_split(self):
        # 1:2 分割は +100%。閾値はその下で拾えること
        assert dilution.DILUTION_SPLIT_PCT < 100.0

    def test_merge_threshold_is_negative(self):
        assert dilution.DILUTION_MERGE_PCT < 0
