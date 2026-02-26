"""Tests for theme inference from industry (KIK-487).

Tests the reverse-lookup logic: given an industry name, determine matching themes.
"""

import pytest
from unittest.mock import patch

from src.core.screening.query_builder import load_themes


class TestThemeInference:
    """Test industry-to-theme reverse lookup logic."""

    def _infer_themes(self, industry: str) -> list[str]:
        """Reproduce the _infer_themes logic from generate_report.py."""
        if not industry:
            return []
        themes = load_themes()
        industry_lower = industry.lower()
        matched = []
        for key, defn in themes.items():
            industries = defn.get("industries", [])
            for ind in industries:
                if ind.lower() in industry_lower or industry_lower in ind.lower():
                    matched.append(key)
                    break
        return matched

    def test_semiconductors_matches_ai(self):
        result = self._infer_themes("Semiconductors")
        assert "ai" in result

    def test_auto_manufacturers_matches_ev(self):
        result = self._infer_themes("Auto Manufacturers")
        assert "ev" in result

    def test_software_infrastructure_matches_multiple(self):
        result = self._infer_themes("Software—Infrastructure")
        assert "ai" in result
        assert "cloud-saas" in result
        assert "cybersecurity" in result

    def test_biotechnology_matches_biotech(self):
        result = self._infer_themes("Biotechnology")
        assert "biotech" in result

    def test_aerospace_defense_matches_defense(self):
        result = self._infer_themes("Aerospace & Defense")
        assert "defense" in result

    def test_medical_devices_matches_healthcare_and_biotech(self):
        result = self._infer_themes("Medical Devices")
        assert "biotech" in result
        assert "healthcare" in result

    def test_empty_industry_returns_empty(self):
        assert self._infer_themes("") == []

    def test_unknown_industry_returns_empty(self):
        result = self._infer_themes("Restaurants")
        assert result == []

    def test_case_insensitive(self):
        result = self._infer_themes("semiconductors")
        assert "ai" in result

    def test_solar_matches_renewable(self):
        result = self._infer_themes("Solar")
        assert "renewable-energy" in result

    def test_credit_services_matches_fintech(self):
        result = self._infer_themes("Credit Services")
        assert "fintech" in result
