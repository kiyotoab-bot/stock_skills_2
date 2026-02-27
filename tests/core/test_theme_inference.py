"""Tests for theme inference from industry (KIK-487/520).

Tests the reverse-lookup logic: given an industry name, determine matching themes.
Uses the real infer_themes() from query_builder (not a re-implementation).
"""

import pytest

from src.core.screening.query_builder import infer_themes


class TestThemeInference:
    """Test industry-to-theme reverse lookup logic."""

    def test_semiconductors_matches_ai(self):
        result = infer_themes("Semiconductors")
        assert "ai" in result

    def test_auto_manufacturers_matches_ev(self):
        result = infer_themes("Auto Manufacturers")
        assert "ev" in result

    def test_software_infrastructure_matches_multiple(self):
        result = infer_themes("Software—Infrastructure")
        assert "ai" in result
        assert "cloud-saas" in result
        assert "cybersecurity" in result

    def test_biotechnology_matches_biotech(self):
        result = infer_themes("Biotechnology")
        assert "biotech" in result

    def test_aerospace_defense_matches_defense(self):
        result = infer_themes("Aerospace & Defense")
        assert "defense" in result

    def test_medical_devices_matches_healthcare_and_biotech(self):
        result = infer_themes("Medical Devices")
        assert "biotech" in result
        assert "healthcare" in result

    def test_empty_industry_returns_empty(self):
        assert infer_themes("") == []

    def test_unknown_industry_returns_empty(self):
        result = infer_themes("Restaurants")
        assert result == []

    def test_case_insensitive(self):
        result = infer_themes("semiconductors")
        assert "ai" in result

    def test_solar_matches_renewable(self):
        result = infer_themes("Solar")
        assert "renewable-energy" in result

    def test_credit_services_matches_fintech(self):
        result = infer_themes("Credit Services")
        assert "fintech" in result
