"""Tests for format_auto_theme_header (KIK-440)."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.output.formatter import format_auto_theme_header


class TestFormatAutoThemeHeader:
    def test_basic_output(self):
        themes = [
            {"theme": "ai", "reason": "半導体需要拡大", "confidence": 0.9},
            {"theme": "defense", "reason": "地政学リスク", "confidence": 0.8},
        ]
        output = format_auto_theme_header(themes)
        assert "ai" in output
        assert "defense" in output
        assert "90%" in output
        assert "80%" in output
        assert "半導体需要拡大" in output
        assert "地政学リスク" in output
        assert "Grok" in output
        assert "---" in output

    def test_with_skipped_themes(self):
        themes = [{"theme": "ai", "reason": "r1", "confidence": 0.9}]
        skipped = [{"theme": "quantum-computing"}, {"theme": "space-tech"}]
        output = format_auto_theme_header(themes, skipped)
        assert "未対応テーマ" in output
        assert "quantum-computing" in output
        assert "space-tech" in output

    def test_no_skipped(self):
        themes = [{"theme": "ev", "reason": "r1", "confidence": 0.7}]
        output = format_auto_theme_header(themes)
        assert "未対応テーマ" not in output

    def test_empty_themes(self):
        output = format_auto_theme_header([])
        assert "Grok" in output
        assert "---" in output

    def test_no_reason(self):
        themes = [{"theme": "ai", "reason": "", "confidence": 0.5}]
        output = format_auto_theme_header(themes)
        assert "ai" in output
        assert "50%" in output

    def test_confidence_as_percentage(self):
        themes = [{"theme": "biotech", "reason": "r", "confidence": 0.65}]
        output = format_auto_theme_header(themes)
        assert "65%" in output

    def test_date_in_header(self):
        from datetime import date
        themes = [{"theme": "ai", "reason": "r", "confidence": 0.5}]
        output = format_auto_theme_header(themes)
        assert date.today().isoformat() in output

    def test_empty_skipped_list(self):
        themes = [{"theme": "ai", "reason": "r", "confidence": 0.5}]
        output = format_auto_theme_header(themes, skipped=[])
        assert "未対応テーマ" not in output
