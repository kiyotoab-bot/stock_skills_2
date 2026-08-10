"""Tests for PO9 — 発注後の注文突合 (KIK-752).

PO1-PO8 は発注**前**の検査で、指示書が正しいことしか確かめない。
2026-08-04（逆指値→指値売り）と 2026-08-10（指値→成行）はどちらも
指示書が正しく、入力の工程で食い違った。PO9 はそこを見る。

目視で確認したつもりを検証する手段が他にないので、**記録の有無**で判定する。
"""

import pytest
import yaml

from src.data.checklist_review import (
    FAIL,
    PASS,
    ORDER_CHECK_NOTE_TYPE,
    check_order_verification,
)


def _note(symbol, date, note_type=ORDER_CHECK_NOTE_TYPE):
    return {"type": note_type, "symbol": symbol, "date": date, "content": "確認済み"}


class TestCheckOrderVerification:
    def test_no_record_fails(self):
        """記録が無ければ FAIL。『確認したつもり』を通さない。"""
        r = check_order_verification("7751.T", "2026-08-10", [])[0]
        assert r["id"] == "PO9"
        assert r["status"] == FAIL

    def test_failure_detail_says_what_to_do(self):
        r = check_order_verification("7751.T", "2026-08-10", [])[0]
        assert "注文一覧" in r["detail"]
        assert ORDER_CHECK_NOTE_TYPE in r["detail"]

    def test_record_on_order_date_passes(self):
        notes = [_note("7751.T", "2026-08-10")]
        r = check_order_verification("7751.T", "2026-08-10", notes)[0]
        assert r["status"] == PASS
        assert "2026-08-10" in r["detail"]

    def test_record_after_order_date_passes(self):
        notes = [_note("7751.T", "2026-08-12")]
        assert check_order_verification("7751.T", "2026-08-10", notes)[0]["status"] == PASS

    def test_record_before_order_date_does_not_count(self):
        """前回の発注時の記録で今回を通さない。"""
        notes = [_note("7751.T", "2026-07-01")]
        assert check_order_verification("7751.T", "2026-08-10", notes)[0]["status"] == FAIL

    def test_other_symbol_does_not_count(self):
        notes = [_note("9104.T", "2026-08-10")]
        assert check_order_verification("7751.T", "2026-08-10", notes)[0]["status"] == FAIL

    def test_other_note_type_does_not_count(self):
        """thesis や exit-rule を書いただけでは突合したことにならない。"""
        notes = [_note("7751.T", "2026-08-10", note_type="thesis"),
                 _note("7751.T", "2026-08-10", note_type="exit-rule")]
        assert check_order_verification("7751.T", "2026-08-10", notes)[0]["status"] == FAIL

    def test_latest_record_is_reported(self):
        notes = [_note("7751.T", "2026-08-10"), _note("7751.T", "2026-08-14")]
        r = check_order_verification("7751.T", "2026-08-10", notes)[0]
        assert "2026-08-14" in r["detail"]

    def test_missing_date_on_note_does_not_crash(self):
        notes = [{"type": ORDER_CHECK_NOTE_TYPE, "symbol": "7751.T"}]
        assert check_order_verification("7751.T", "2026-08-10", notes)[0]["status"] == FAIL

    def test_empty_order_date_accepts_any_record(self):
        """発注日が不明なら、記録があること自体を通す（何も無いよりよい）。"""
        notes = [_note("7751.T", "2026-08-10")]
        assert check_order_verification("7751.T", "", notes)[0]["status"] == PASS


class TestChecklistYaml:
    def test_po9_is_defined(self):
        with open("config/checklists.yaml", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        ids = [i["id"] for i in doc["pre_order"]["items"]]
        assert "PO9" in ids

    def test_po9_has_code(self):
        """code のある項目は目視で代替しない（SKILL.md の規約）。"""
        with open("config/checklists.yaml", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        po9 = [i for i in doc["pre_order"]["items"] if i["id"] == "PO9"][0]
        assert "check_order_verification" in po9["code"]

    def test_po9_records_both_incidents(self):
        """why から事故の実例を落とさない。抽象化すると効かなくなる。"""
        with open("config/checklists.yaml", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        po9 = [i for i in doc["pre_order"]["items"] if i["id"] == "PO9"][0]
        assert "08-04" in po9["why"] and "08-10" in po9["why"]
