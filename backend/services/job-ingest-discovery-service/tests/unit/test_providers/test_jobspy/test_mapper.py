"""Tests for JobSpy mapper."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final
from unittest.mock import patch

import pandas as pd
import pytest
from job_ingest_discovery_service.core.models import DiscoveryLocation, DiscoveryRequest
from job_ingest_discovery_service.providers.jobspy.mapper import (
    build_jobspy_params,
    map_dataframe_to_listings,
)
from nohiki.common.v1 import CountryCode, CurrencyCode, JobBoardSource, WorkArrangement

# Valid description meeting the MIN_DESCRIPTION_LENGTH (200 char) gate.
_VALID_DESCRIPTION: Final[str] = (
    "We are looking for a Software Engineer to join our backend team. "
    "You will design and implement scalable APIs using Python and PostgreSQL. "
    "Experience with cloud platforms (AWS, GCP) is required. "
    "Strong communication skills and ability to work in an agile environment."
)


def _valid_row(**overrides: object) -> dict[str, object]:
    """Build a row that satisfies all DiscoveredListing gates by default."""
    row: dict[str, object] = {
        "listing_url": "https://example.com/1",
        "title": "Engineer",
        "site": "indeed",
        "company": "Acme Corp",
        "location": "San Francisco, CA",
        "description": _VALID_DESCRIPTION,
    }
    row.update(overrides)
    return row


def test_build_jobspy_params_defaults_sites_when_no_sources() -> None:
    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(),
        locations=(),
        work_arrangements=(WorkArrangement.REMOTE,),
        results_per_source=10,
    )

    params = build_jobspy_params(request)

    assert len(params) == 1
    assert params[0]["site_name"] == ["indeed", "linkedin"]
    assert params[0]["search_term"] == "python"
    assert params[0]["is_remote"] is True


def test_build_jobspy_params_any_adds_remote_and_physical() -> None:
    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(JobBoardSource.GOOGLE,),
        locations=(
            DiscoveryLocation(city="Toronto", region="ON", country=CountryCode.CAN),
            DiscoveryLocation(is_remote=True),
        ),
        work_arrangements=(WorkArrangement.UNSPECIFIED,),
        results_per_source=10,
    )

    params = build_jobspy_params(request)

    # One for physical location, one for remote
    assert len(params) == 2

    remote_params = [p for p in params if p.get("is_remote") is True]
    physical_params = [p for p in params if p.get("is_remote") is False]

    assert len(remote_params) == 1
    assert len(physical_params) == 1

    assert remote_params[0]["site_name"] == ["google"]
    assert physical_params[0]["location"] == "Toronto, ON, Canada"


def test_build_jobspy_params_onsite_only_without_locations_falls_back_to_remote() -> None:
    request = DiscoveryRequest(
        query_id="q1",
        keywords=("python",),
        sources=(JobBoardSource.INDEED,),
        locations=(),
        work_arrangements=(WorkArrangement.ON_SITE,),
        results_per_source=10,
    )

    params = build_jobspy_params(request)

    assert len(params) == 1
    assert params[0]["is_remote"] is True


def test_map_dataframe_to_listings_sanitizes_and_parses_fields() -> None:
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    df = pd.DataFrame(
        [
            _valid_row(
                title="Title\x00with\x01control",
                company="Acme\ue000Corp",
                min_amount="100000",
                max_amount="bad",
                currency="USD",
                date_posted=dt,
                job_url_direct="https://example.com/direct",
            )
        ]
    )

    listings = map_dataframe_to_listings(df)

    assert len(listings) == 1
    listing = listings[0]

    assert "\x00" not in listing.title
    assert "\x01" not in listing.title
    assert "\ue000" not in listing.company

    assert listing.posted_at == dt
    assert listing.source == JobBoardSource.INDEED

    assert listing.compensation is not None
    assert listing.compensation.min_amount is not None
    assert listing.compensation.min_amount.amount.minor_units == 10000000  # 100000 * 100
    assert listing.compensation.min_amount.amount.currency == CurrencyCode.USD
    assert listing.compensation.max_amount is None


def test_drops_listings_without_description() -> None:
    """Listings with missing or short descriptions are filtered out."""
    df = pd.DataFrame(
        [
            _valid_row(description=None),
            _valid_row(listing_url="https://example.com/2", description="short"),
            _valid_row(listing_url="https://example.com/3", description=""),
        ]
    )

    listings = map_dataframe_to_listings(df)
    assert len(listings) == 0


def test_accepts_listings_with_sufficient_description() -> None:
    """Listings with descriptions >= 200 chars pass the validation gate."""
    df = pd.DataFrame([_valid_row()])

    listings = map_dataframe_to_listings(df)
    assert len(listings) == 1


def test_drops_listings_without_company() -> None:
    """Listings missing company_name are dropped to satisfy proto contract."""
    df = pd.DataFrame(
        [
            _valid_row(company=""),
            _valid_row(listing_url="https://example.com/2", company="   "),
            _valid_row(listing_url="https://example.com/3", company=None),
        ]
    )
    assert map_dataframe_to_listings(df) == []


def test_drops_listings_without_location() -> None:
    """Listings missing location_raw are dropped to satisfy proto contract."""
    df = pd.DataFrame(
        [
            _valid_row(location=""),
            _valid_row(listing_url="https://example.com/2", location="   "),
            _valid_row(listing_url="https://example.com/3", location=None),
        ]
    )
    assert map_dataframe_to_listings(df) == []


def test_drops_linkedin_auth_wall_row() -> None:
    """LinkedIn auth-wall rows are dropped with structured diagnostics."""
    df = pd.DataFrame(
        [
            _valid_row(
                listing_url="https://linkedin.com/jobs/view/1",
                site="linkedin",
                description="",
            )
        ]
    )

    with patch("job_ingest_discovery_service.providers.jobspy.mapper.logger") as mock_logger:
        listings = map_dataframe_to_listings(df)

    assert listings == []
    mock_logger.warning.assert_any_call(
        "Dropping invalid listing",
        source="jobspy",
        reason="description_too_short",
        url="https://linkedin.com/jobs/view/1",
    )
    assert mock_logger.warning.call_count == 2


class TestCompensationCurrencyInference:
    """Tests for compensation currency inference from country fallback."""

    def test_currency_from_explicit_field(self) -> None:
        """Test that explicit currency field is used when present."""
        df = pd.DataFrame(
            [
                _valid_row(
                    min_amount=50000,
                    currency="EUR",
                    country="US",
                )
            ]
        )

        listings = map_dataframe_to_listings(df)

        assert len(listings) == 1
        assert listings[0].compensation is not None
        assert listings[0].compensation.min_amount is not None
        assert listings[0].compensation.min_amount.amount.currency == CurrencyCode.EUR

    @pytest.mark.parametrize(
        ("country", "expected_currency"),
        [
            ("US", CurrencyCode.USD),
            ("usa", CurrencyCode.USD),
            ("CA", CurrencyCode.CAD),
            ("can", CurrencyCode.CAD),
            ("GB", CurrencyCode.GBP),
            ("uk", CurrencyCode.GBP),
            ("DE", CurrencyCode.EUR),
            ("FR", CurrencyCode.EUR),
            ("NL", CurrencyCode.EUR),
            ("IE", CurrencyCode.EUR),
            ("CH", CurrencyCode.CHF),
            ("AU", CurrencyCode.AUD),
            ("NZ", CurrencyCode.NZD),
            ("SG", CurrencyCode.SGD),
            ("IN", CurrencyCode.INR),
            ("AE", CurrencyCode.AED),
            ("IL", CurrencyCode.ILS),
        ],
    )
    def test_currency_inferred_from_country(self, country: str, expected_currency: CurrencyCode) -> None:
        """Test currency inference from country when currency field is empty."""
        df = pd.DataFrame(
            [
                _valid_row(
                    min_amount=50000,
                    currency="",
                    country=country,
                )
            ]
        )

        listings = map_dataframe_to_listings(df)

        assert len(listings) == 1
        assert listings[0].compensation is not None
        assert listings[0].compensation.min_amount is not None
        assert listings[0].compensation.min_amount.amount.currency == expected_currency

    def test_no_compensation_when_currency_and_country_missing(self) -> None:
        """Test that no compensation is returned when both currency and country are missing."""
        df = pd.DataFrame(
            [
                _valid_row(
                    min_amount=50000,
                    currency="",
                    country="",
                )
            ]
        )

        listings = map_dataframe_to_listings(df)

        assert len(listings) == 1
        assert listings[0].compensation is None

    def test_no_compensation_when_unknown_country(self) -> None:
        """Test that no compensation is returned for unknown country codes."""
        df = pd.DataFrame(
            [
                _valid_row(
                    min_amount=50000,
                    currency="",
                    country="XX",
                )
            ]
        )

        listings = map_dataframe_to_listings(df)

        assert len(listings) == 1
        assert listings[0].compensation is None

    def test_compensation_with_both_min_and_max(self) -> None:
        """Test compensation parsing with both min and max amounts."""
        df = pd.DataFrame(
            [
                _valid_row(
                    min_amount=80000,
                    max_amount=120000,
                    currency="GBP",
                    interval="yearly",
                    salary_source="direct_data",
                )
            ]
        )

        listings = map_dataframe_to_listings(df)

        assert len(listings) == 1
        comp = listings[0].compensation
        assert comp is not None
        assert comp.min_amount is not None
        assert comp.max_amount is not None
        assert comp.min_amount.amount.minor_units == 8000000
        assert comp.max_amount.amount.minor_units == 12000000
        assert comp.min_amount.amount.currency == CurrencyCode.GBP
        assert comp.max_amount.amount.currency == CurrencyCode.GBP

    def test_hours_old_parameter(self) -> None:
        """Test that hours_old is set in params when provided."""
        request = DiscoveryRequest(
            query_id="q1",
            keywords=("python",),
            sources=(JobBoardSource.GOOGLE,),
            locations=(),
            work_arrangements=(WorkArrangement.REMOTE,),
            results_per_source=10,
            hours_old=24,
        )

        params = build_jobspy_params(request)

        assert len(params) == 1
        assert params[0]["hours_old"] == 24
