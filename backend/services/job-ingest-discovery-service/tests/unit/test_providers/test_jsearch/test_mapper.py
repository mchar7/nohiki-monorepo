"""Tests for JSearch mapper."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import pytest
from job_ingest_discovery_service.providers.jsearch.mapper import (
    map_response_to_listings,
)
from job_ingest_discovery_service.providers.jsearch.models import (
    ApplyOption,
    JSearchJob,
    JSearchResponse,
    SalaryPeriod,
)
from nohiki.common.v1 import CompensationSource, CurrencyCode, JobBoardSource, PaymentFrequency

# Valid description meeting the MIN_DESCRIPTION_LENGTH (200 char) gate.
_VALID_DESCRIPTION: Final[str] = (
    "We are looking for a Software Engineer to join our backend team. "
    "You will design and implement scalable APIs using Python and PostgreSQL. "
    "Experience with cloud platforms (AWS, GCP) is required. "
    "Strong communication skills and ability to work in an agile environment."
)


def _valid_job(**overrides: Any) -> JSearchJob:  # noqa: ANN401  # JSearchJob fields span many primitive types
    """Build a JSearchJob that satisfies all DiscoveredListing gates by default."""
    fields: dict[str, Any] = {
        "job_id": "job-1",
        "job_title": "Software Engineer",
        "employer_name": "Acme Corp",
        "job_google_link": "https://google.com/jobs/1",
        "job_location": "San Francisco, CA",
        "job_description": _VALID_DESCRIPTION,
    }
    fields.update(overrides)
    return JSearchJob(**fields)


class TestMapResponseToJobs:
    """Tests for map_response_to_listings function."""

    def test_empty_response(self) -> None:
        """Test mapping empty response."""
        response = JSearchResponse(status="OK", data=[])
        listings = map_response_to_listings(response)
        assert listings == []

    def test_single_job(self) -> None:
        """Test mapping single job."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(job_is_remote=True)],
        )

        listings = map_response_to_listings(response)

        assert len(listings) == 1
        listing = listings[0]
        assert listing.title == "Software Engineer"
        assert listing.company == "Acme Corp"

    def test_job_with_no_title_or_url(self) -> None:
        """Test that job with missing title or URL returns None."""
        response = JSearchResponse(
            status="OK",
            data=[
                JSearchJob(
                    job_id="job-1",
                    employer_name="Acme Corp",
                ),
            ],
        )

        listings = map_response_to_listings(response)

        assert len(listings) == 0

    def test_multiple_jobs(self) -> None:
        """Test mapping multiple jobs."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(job_id="job-1", job_title="Engineer", job_google_link="u1"),
                _valid_job(job_id="job-2", job_title="Designer", job_google_link="u2"),
                _valid_job(job_id="job-3", job_title="Manager", job_google_link="u3"),
            ],
        )

        listings = map_response_to_listings(response)
        assert len(listings) == 3

    def test_posted_date_parsing(self) -> None:
        """Test that posted date is correctly parsed from datetime or timestamp."""
        dt = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(job_id="job-1", job_google_link="u1", job_posted_at_datetime_utc=dt),
                _valid_job(job_id="job-2", job_google_link="u2", job_posted_at_timestamp=1705320000),
            ],
        )

        listings = map_response_to_listings(response)
        assert len(listings) == 2
        assert listings[0].posted_at == dt
        assert listings[1].posted_at is not None
        assert listings[1].posted_at.year == 2024

    def test_source_mapping(self) -> None:
        """Test publisher strings map to correct sources."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(job_id="1", job_google_link="u1", job_publisher="Indeed"),
                _valid_job(job_id="2", job_google_link="u2", job_publisher="LinkedIn"),
                _valid_job(job_id="3", job_google_link="u3", job_publisher="Something Else"),
            ],
        )

        listings = map_response_to_listings(response)
        assert listings[0].source == JobBoardSource.INDEED
        assert listings[1].source == JobBoardSource.LINKEDIN
        assert listings[2].source == JobBoardSource.GOOGLE

    def test_apply_url_logic(self) -> None:
        """Test apply URL logic prioritizing direct links."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_apply_link="https://indirect.com",
                    job_apply_is_direct=False,
                    apply_options=[ApplyOption(publisher="Direct", apply_link="https://direct.com", is_direct=True)],
                )
            ],
        )

        listings = map_response_to_listings(response)
        assert listings[0].apply_url == "https://direct.com"

    def test_compensation_requires_country_for_currency(self) -> None:
        """Test that compensation is None when country is missing."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_min_salary=80000.0,
                    job_max_salary=120000.0,
                )
            ],
        )

        listings = map_response_to_listings(response)
        assert listings[0].compensation is None


class TestDiscoveredListingGates:
    """Tests for proto-contract gates: company, location, description min lengths."""

    def test_drops_empty_description(self) -> None:
        """Listings with empty descriptions are dropped (LinkedIn auth-wall pattern)."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(job_description="")],
        )
        assert map_response_to_listings(response) == []

    def test_drops_short_description(self) -> None:
        """Listings with descriptions < 200 chars are dropped."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(job_description="Too short to enrich.")],
        )
        assert map_response_to_listings(response) == []

    def test_drops_empty_employer_name(self) -> None:
        """Listings with empty employer_name are dropped (proto requires min_len=1)."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(employer_name="")],
        )
        assert map_response_to_listings(response) == []

    def test_drops_whitespace_only_employer_name(self) -> None:
        """Whitespace-only employer_name is treated as missing."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(employer_name="   ")],
        )
        assert map_response_to_listings(response) == []

    def test_drops_empty_location_for_non_remote(self) -> None:
        """Empty location_raw is dropped for non-remote postings."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(job_location="", job_is_remote=False)],
        )
        assert map_response_to_listings(response) == []

    def test_drops_empty_location_when_remote_flag_unset(self) -> None:
        """Empty location with no remote flag still drops (no Remote fallback)."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(job_location="", job_is_remote=None)],
        )
        assert map_response_to_listings(response) == []

    def test_remote_fallback_synthesizes_location(self) -> None:
        """Fully-remote jobs with empty location get 'Remote' as location_raw."""
        response = JSearchResponse(
            status="OK",
            data=[_valid_job(job_location="", job_is_remote=True)],
        )
        listings = map_response_to_listings(response)
        assert len(listings) == 1
        assert listings[0].location_raw == "Remote"

    def test_keeps_fully_valid_listing(self) -> None:
        """All gates passing yields a kept listing."""
        response = JSearchResponse(status="OK", data=[_valid_job()])
        listings = map_response_to_listings(response)
        assert len(listings) == 1
        assert listings[0].company == "Acme Corp"
        assert listings[0].location_raw == "San Francisco, CA"
        assert len(listings[0].description) >= 200


class TestCompensationCurrencyInference:
    """Tests for JSearch compensation currency inference from job_country."""

    @pytest.mark.parametrize(
        ("country", "expected_currency"),
        [
            ("US", CurrencyCode.USD),
            ("CA", CurrencyCode.CAD),
            ("GB", CurrencyCode.GBP),
            ("UK", CurrencyCode.GBP),
            ("DE", CurrencyCode.EUR),
            ("FR", CurrencyCode.EUR),
            ("CH", CurrencyCode.CHF),
            ("AU", CurrencyCode.AUD),
            ("NZ", CurrencyCode.NZD),
            ("SG", CurrencyCode.SGD),
            ("IN", CurrencyCode.INR),
            ("AE", CurrencyCode.AED),
            ("IL", CurrencyCode.ILS),
        ],
    )
    def test_currency_inferred_from_job_country(self, country: str, expected_currency: CurrencyCode) -> None:
        """Test currency is correctly inferred from job_country field."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_min_salary=80000.0,
                    job_max_salary=120000.0,
                    job_country=country,
                )
            ],
        )

        listings = map_response_to_listings(response)
        comp = listings[0].compensation
        assert comp is not None
        assert comp.min_amount is not None
        assert comp.max_amount is not None
        assert comp.min_amount.amount.minor_units == 8000000
        assert comp.max_amount.amount.minor_units == 12000000
        assert comp.min_amount.amount.currency == expected_currency
        assert comp.max_amount.amount.currency == expected_currency

    def test_compensation_source_is_job_board_estimate(self) -> None:
        """Test that compensation source is set to ESTIMATED_BY_JOB_BOARD."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_min_salary=50000.0,
                    job_country="US",
                )
            ],
        )

        listings = map_response_to_listings(response)
        comp = listings[0].compensation
        assert comp is not None
        assert comp.min_amount is not None
        # Compensation itself doesn't have source field, check bounds have sources
        assert comp.min_amount.source == CompensationSource.ESTIMATED_BY_JOB_BOARD

    def test_compensation_with_salary_period(self) -> None:
        """Test that salary period is correctly mapped to payment frequency."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_min_salary=100000.0,
                    job_salary_period=SalaryPeriod.YEAR,
                    job_country="US",
                )
            ],
        )

        listings = map_response_to_listings(response)
        comp = listings[0].compensation
        assert comp is not None
        assert comp.frequency == PaymentFrequency.ANNUALLY

    def test_no_compensation_when_unknown_country(self) -> None:
        """Test that compensation is None for unknown country codes."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_min_salary=80000.0,
                    job_country="XX",
                )
            ],
        )

        listings = map_response_to_listings(response)
        assert listings[0].compensation is None

    def test_compensation_with_min_only(self) -> None:
        """Test compensation parsing with only min amount."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_min_salary=50000.0,
                    job_country="CA",
                )
            ],
        )

        listings = map_response_to_listings(response)
        comp = listings[0].compensation
        assert comp is not None
        assert comp.min_amount is not None
        assert comp.min_amount.amount.minor_units == 5000000
        assert comp.min_amount.amount.currency == CurrencyCode.CAD
        assert not comp.max_amount

    def test_compensation_with_max_only(self) -> None:
        """Test compensation parsing with only max amount."""
        response = JSearchResponse(
            status="OK",
            data=[
                _valid_job(
                    job_id="1",
                    job_google_link="u1",
                    job_max_salary=150000.0,
                    job_country="GB",
                )
            ],
        )

        listings = map_response_to_listings(response)
        comp = listings[0].compensation
        assert comp is not None
        assert not comp.min_amount
        assert comp.max_amount is not None
        assert comp.max_amount.amount.minor_units == 15000000
        assert comp.max_amount.amount.currency == CurrencyCode.GBP
