"""Tests for currency inference module."""

from __future__ import annotations

import pytest
from job_ingest_discovery_service.core.currency import (
    COUNTRY_TO_CURRENCY,
    ISO2_TO_COUNTRY,
    infer_currency_from_country,
    infer_currency_from_country_string,
    parse_country_code,
)
from nohiki.common.v1 import CountryCode, CurrencyCode


class TestInferCurrencyFromCountry:
    """Tests for infer_currency_from_country function."""

    @pytest.mark.parametrize(
        ("country", "expected"),
        [
            (CountryCode.USA, CurrencyCode.USD),
            (CountryCode.CAN, CurrencyCode.CAD),
            (CountryCode.GBR, CurrencyCode.GBP),
            (CountryCode.AUS, CurrencyCode.AUD),
            (CountryCode.DEU, CurrencyCode.EUR),
            (CountryCode.FRA, CurrencyCode.EUR),
            (CountryCode.NLD, CurrencyCode.EUR),
            (CountryCode.IRL, CurrencyCode.EUR),
            (CountryCode.CHE, CurrencyCode.CHF),
            (CountryCode.NZL, CurrencyCode.NZD),
            (CountryCode.SGP, CurrencyCode.SGD),
            (CountryCode.IND, CurrencyCode.INR),
            (CountryCode.ARE, CurrencyCode.AED),
            (CountryCode.ISR, CurrencyCode.ILS),
        ],
    )
    def test_known_countries(self, country: CountryCode, expected: CurrencyCode) -> None:
        """Test currency inference for all supported countries."""
        assert infer_currency_from_country(country) == expected

    def test_unspecified_country_returns_unspecified(self) -> None:
        """Test that UNSPECIFIED country returns UNSPECIFIED currency."""
        assert infer_currency_from_country(CountryCode.UNSPECIFIED) == CurrencyCode.UNSPECIFIED


class TestParseCountryCode:
    """Tests for parse_country_code function."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("us", CountryCode.USA),
            ("US", CountryCode.USA),
            ("usa", CountryCode.USA),
            ("USA", CountryCode.USA),
            ("gb", CountryCode.GBR),
            ("GB", CountryCode.GBR),
            ("gbr", CountryCode.GBR),
            ("uk", CountryCode.GBR),
            ("UK", CountryCode.GBR),
            ("de", CountryCode.DEU),
            ("deu", CountryCode.DEU),
            ("fr", CountryCode.FRA),
            ("fra", CountryCode.FRA),
            ("ca", CountryCode.CAN),
            ("can", CountryCode.CAN),
            ("au", CountryCode.AUS),
            ("aus", CountryCode.AUS),
            ("nz", CountryCode.NZL),
            ("sg", CountryCode.SGP),
            ("in", CountryCode.IND),
            ("ae", CountryCode.ARE),
            ("il", CountryCode.ISR),
            ("ch", CountryCode.CHE),
            ("nl", CountryCode.NLD),
            ("ie", CountryCode.IRL),
        ],
    )
    def test_valid_country_codes(self, value: str, expected: CountryCode) -> None:
        """Test parsing of valid country codes."""
        assert parse_country_code(value) == expected

    def test_empty_string_returns_unspecified(self) -> None:
        """Test that empty string returns UNSPECIFIED."""
        assert parse_country_code("") == CountryCode.UNSPECIFIED

    def test_unknown_code_returns_unspecified(self) -> None:
        """Test that unknown codes return UNSPECIFIED."""
        assert parse_country_code("xx") == CountryCode.UNSPECIFIED
        assert parse_country_code("unknown") == CountryCode.UNSPECIFIED

    def test_whitespace_handling(self) -> None:
        """Test that whitespace is stripped."""
        assert parse_country_code("  us  ") == CountryCode.USA


class TestInferCurrencyFromCountryString:
    """Tests for infer_currency_from_country_string function."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("us", CurrencyCode.USD),
            ("US", CurrencyCode.USD),
            ("usa", CurrencyCode.USD),
            ("gb", CurrencyCode.GBP),
            ("uk", CurrencyCode.GBP),
            ("de", CurrencyCode.EUR),
            ("fr", CurrencyCode.EUR),
            ("ch", CurrencyCode.CHF),
            ("sg", CurrencyCode.SGD),
            ("in", CurrencyCode.INR),
            ("ae", CurrencyCode.AED),
            ("il", CurrencyCode.ILS),
        ],
    )
    def test_valid_country_strings(self, value: str, expected: CurrencyCode) -> None:
        """Test currency inference from valid country strings."""
        assert infer_currency_from_country_string(value) == expected

    def test_empty_string_returns_unspecified(self) -> None:
        """Test that empty string returns UNSPECIFIED currency."""
        assert infer_currency_from_country_string("") == CurrencyCode.UNSPECIFIED

    def test_unknown_string_returns_unspecified(self) -> None:
        """Test that unknown strings return UNSPECIFIED currency."""
        assert infer_currency_from_country_string("xyz") == CurrencyCode.UNSPECIFIED


class TestMappingConsistency:
    """Tests to ensure mapping dictionaries are consistent."""

    def test_country_to_currency_covers_all_iso2_countries(self) -> None:
        """Test that all countries in ISO2_TO_COUNTRY have currency mappings."""
        countries = set(ISO2_TO_COUNTRY.values())
        for country in countries:
            if country != CountryCode.UNSPECIFIED:
                assert country in COUNTRY_TO_CURRENCY, f"Missing currency for {country}"

    def test_eurozone_countries_map_to_eur(self) -> None:
        """Test that all Eurozone countries in the mapping return EUR."""
        eurozone = [CountryCode.DEU, CountryCode.FRA, CountryCode.NLD, CountryCode.IRL]
        for country in eurozone:
            assert infer_currency_from_country(country) == CurrencyCode.EUR
