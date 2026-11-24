"""資産推移の記録（KIK-789）."""

import json

import pytest

from src.data import asset_history as A


def _write(d, name, text):
    (d / name).write_text(text, encoding="utf-8")


class TestExtract:
    @pytest.mark.parametrize("text,expected", [
        ("- 総資産 **¥7,942,991**（株式 ¥1,646,500）", 7942991),
        ("| 総資産推計** | **¥7,973,421** |", 7973421),
        ("総資産 ¥ 8,000,000", 8000000),
        ("総資産 | ~¥797万", None),            # 万単位は対象外
        ("総資産800万→1000万", None),
        ("総資産\n¥7,000,000", None),           # 改行をまたがない
        ("", None), (None, None),
    ])
    def test_formats(self, text, expected):
        assert A.extract_total(text) == expected


class TestBackfill:
    def test_priority_and_dates(self, tmp_path):
        _write(tmp_path, "daily_20260901.md", "総資産 ¥8,000,000")
        _write(tmp_path, "daily_20260901_2350.md", "総資産 ¥8,010,000")   # 同日の後の回
        _write(tmp_path, "weekly_20260901_2359.md", "総資産 ¥9,999,999")  # 時刻が後でも daily が優先
        _write(tmp_path, "monthly_20260906.md", "総資産 ¥7,777,777")      # weekly が monthly より優先
        _write(tmp_path, "weekly_20260906.md", "総資産 ¥8,020,000")
        _write(tmp_path, "daily_20260905.md", "総資産なし")
        _write(tmp_path, "other_20260901.md", "総資産 ¥1,000,000")
        _write(tmp_path, "daily_20261399.md", "総資産 ¥8,000,000")        # 不正な日付
        r = A.backfill_from_reports(str(tmp_path))
        assert [(p["date"], p["total"]) for p in r["points"]] == [("2026-09-01", 8010000), ("2026-09-06", 8020000)]
        assert all(p["source"] == "report_text" for p in r["points"])
        assert r["unparsed"] == ["daily_20260905.md"]

    def test_missing_dir(self, tmp_path):
        assert A.backfill_from_reports(str(tmp_path / "nope"))["points"] == []


class TestOutliers:
    def _pts(self, vals):
        return [{"date": f"2026-09-{i + 1:02d}", "total": v} for i, v in enumerate(vals)]

    def test_spike_dropped(self):
        keep, dropped = A.drop_outliers(self._pts([800, 801, 1000, 802, 803]))
        assert [p["total"] for p in dropped] == [1000] and len(keep) == 4

    def test_level_shift_kept(self):
        # 段差（誤発注の日のような実際の下落）は、前後どちらかに同じ水準が続くので残る
        keep, dropped = A.drop_outliers(self._pts([840, 841, 842, 790, 791, 792]))
        assert dropped == []

    def test_boundary_15pct(self):
        keep, dropped = A.drop_outliers(self._pts([100, 100, 115, 100, 100]))
        assert dropped == []
        keep, dropped = A.drop_outliers(self._pts([100, 100, 115.1, 100, 100]))
        assert len(dropped) == 1

    @pytest.mark.parametrize("vals", [[1000, 800, 801, 802], [800, 801, 802, 1000], [800, 801, 802, 600]])
    def test_endpoints_never_dropped(self, vals):
        # 最終日の本当の暴落（600）も、片側しか比べられないので残す
        keep, dropped = A.drop_outliers(self._pts(vals))
        assert dropped == [] and len(keep) == 4

    def test_short_series_untouched(self):
        assert A.drop_outliers(self._pts([1, 1000])) == (self._pts([1, 1000]), [])


class TestSnapshot:
    def test_record_overwrite_same_day(self, tmp_path):
        path = str(tmp_path / "h" / "assets.jsonl")
        A.record_snapshot(8_000_000, 3_000_000, 5_000_000, date="2026-11-24", path=path)
        A.record_snapshot(8_100_000, date="2026-11-24", path=path)
        A.record_snapshot(7_900_000, date="2026-11-20", path=path)
        rows = [json.loads(x) for x in open(path, encoding="utf-8")]
        assert not (tmp_path / "h" / "assets.jsonl.tmp").exists()
        assert [(r["date"], r["total"]) for r in rows] == [("2026-11-20", 7.9e6), ("2026-11-24", 8.1e6)]

    @pytest.mark.parametrize("bad", [0, -1, None, "8000000", -0.0, float("nan"), float("inf"), True])
    def test_invalid_total(self, tmp_path, bad):
        with pytest.raises(ValueError):
            A.record_snapshot(bad, path=str(tmp_path / "a.jsonl"))

    @pytest.mark.parametrize("bad", ["2026/11/24", "today", "20261124"])
    def test_invalid_date(self, tmp_path, bad):
        with pytest.raises(ValueError):
            A.record_snapshot(8e6, date=bad, path=str(tmp_path / "a.jsonl"))

    def test_equity_cash_sanitized(self, tmp_path):
        rec = A.record_snapshot(8e6, equity=float("nan"), cash="x", date="2026-11-24",
                                path=str(tmp_path / "a.jsonl"))
        assert rec["equity"] is None and rec["cash"] is None

    def test_bad_date_and_bool_lines_skipped(self, tmp_path):
        path = tmp_path / "assets.jsonl"
        path.write_text('{"date":"today","total":1}\n{"date":"2026-11-03","total":true}\n'
                        '{"date":"2026-11-04","total":2}\n', encoding="utf-8")
        assert [r["date"] for r in A._read_jsonl(str(path))] == ["2026-11-04"]

    def test_broken_lines_skipped(self, tmp_path):
        path = tmp_path / "assets.jsonl"
        path.write_text('{"date":"2026-11-01","total":1}\n{broken\n{"date":"2026-11-02"}\n[]\n', encoding="utf-8")
        assert [r["date"] for r in A._read_jsonl(str(path))] == ["2026-11-01"]

    def test_merge_daily_wins(self, tmp_path):
        rep = tmp_path / "reports"
        rep.mkdir()
        _write(rep, "daily_20261120.md", "総資産 ¥7,000,000")
        _write(rep, "daily_20261121.md", "総資産 ¥7,100,000")
        path = str(tmp_path / "assets.jsonl")
        A.record_snapshot(7_150_000, date="2026-11-21", path=path)
        A.record_snapshot(7_200_000, date="2026-11-22", path=path)
        h = A.load_asset_history(path, str(rep))
        assert [(p["date"], p["total"], p["source"]) for p in h] == [
            ("2026-11-20", 7_000_000, "report_text"), ("2026-11-21", 7_150_000, "daily"),
            ("2026-11-22", 7_200_000, "daily")]
        assert A.load_asset_history(path, None)[0]["date"] == "2026-11-21"
        # 日次の記録が始まった後の推計は混ぜない
        _write(rep, "daily_20261123.md", "総資産 ¥7,300,000")
        assert [p["date"] for p in A.load_asset_history(path, str(rep))][-1] == "2026-11-22"
