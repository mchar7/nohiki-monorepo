"""Tests for CompensationBuilder."""

from __future__ import annotations

import pytest
from job_ingest_enrichment_service.schemas.extraction import (
    CompensationBoundEstimate,
    CompensationEstimate,
)
from job_ingest_enrichment_service.services.compensation_builder import (
    JOB_BOARD_ESTIMATE_CONFIDENCE_PERCENT,
    CompensationBuilder,
    _has_valid_bound,
)
from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CompensationSource,
    CurrencyCode,
    MonetaryAmount,
    PaymentFrequency,
)
from nohiki.job.ingest.v1 import DiscoveredListing


class TestHasValidBound:
    """Tests for _has_valid_bound helper function."""

    def test_valid_min_bound(self) -> None:
        """Test returns True when min_amount has valid currency."""
        comp = Compensation(
            min_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=5000000, currency=CurrencyCode.USD),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
        )
        assert _has_valid_bound(comp) is True

    def test_valid_max_bound(self) -> None:
        """Test returns True when max_amount has valid currency."""
        comp = Compensation(
            max_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=10000000, currency=CurrencyCode.EUR),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
        )
        assert _has_valid_bound(comp) is True

    def test_valid_both_bounds(self) -> None:
        """Test returns True when both bounds have valid currencies."""
        comp = Compensation(
            min_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=5000000, currency=CurrencyCode.GBP),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
            max_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=10000000, currency=CurrencyCode.GBP),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
        )
        assert _has_valid_bound(comp) is True

    def test_unspecified_min_currency(self) -> None:
        """Test returns False when only min_amount has UNSPECIFIED currency."""
        comp = Compensation(
            min_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=5000000, currency=CurrencyCode.UNSPECIFIED),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
        )
        assert _has_valid_bound(comp) is False

    def test_unspecified_max_currency(self) -> None:
        """Test returns False when only max_amount has UNSPECIFIED currency."""
        comp = Compensation(
            max_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=10000000, currency=CurrencyCode.UNSPECIFIED),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
        )
        assert _has_valid_bound(comp) is False

    def test_both_unspecified(self) -> None:
        """Test returns False when both bounds have UNSPECIFIED currency."""
        comp = Compensation(
            min_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=5000000, currency=CurrencyCode.UNSPECIFIED),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
            max_amount=CompensationBound(
                amount=MonetaryAmount(minor_units=10000000, currency=CurrencyCode.UNSPECIFIED),
                source=CompensationSource.EMPLOYER_PROVIDED,
            ),
        )
        assert _has_valid_bound(comp) is False

    def test_empty_compensation(self) -> None:
        """Test returns False when compensation has no amounts."""
        comp = Compensation()
        assert _has_valid_bound(comp) is False


class TestCompensationBuilder:
    """Tests for CompensationBuilder class."""

    @pytest.fixture
    def builder(self) -> CompensationBuilder:
        """Create CompensationBuilder instance."""
        return CompensationBuilder()

    @pytest.fixture
    def llm_estimate(self) -> CompensationEstimate:
        """Create a standard LLM estimate for testing."""
        return CompensationEstimate(
            min_amount=CompensationBoundEstimate(
                amount=60_000,
                source="llm_inferred",
                confidence_percent=75,
            ),
            max_amount=CompensationBoundEstimate(
                amount=90_000,
                source="llm_inferred",
                confidence_percent=75,
            ),
            currency=CurrencyCode.USD,
            period=PaymentFrequency.ANNUALLY,
            reasoning="Estimated based on typical mid-level software engineer compensation in the US market.",
        )

    def test_employer_provided_with_valid_currency(self, builder: CompensationBuilder) -> None:
        """Test employer provided compensation is used when currency is valid."""
        discovered = DiscoveredListing(
            listing_url="https://example.com",
            title="Engineer",
            compensation=Compensation(
                min_amount=CompensationBound(
                    amount=MonetaryAmount(minor_units=8000000, currency=CurrencyCode.USD),
                    source=CompensationSource.EMPLOYER_PROVIDED,
                ),
                max_amount=CompensationBound(
                    amount=MonetaryAmount(minor_units=12000000, currency=CurrencyCode.USD),
                    source=CompensationSource.EMPLOYER_PROVIDED,
                ),
                frequency=PaymentFrequency.ANNUALLY,
            ),
        )
        llm_estimate = CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=70_000, source="llm_inferred", confidence_percent=70),
            max_amount=CompensationBoundEstimate(amount=100_000, source="llm_inferred", confidence_percent=70),
            currency=CurrencyCode.USD,
            period=PaymentFrequency.ANNUALLY,
            reasoning="Estimated based on job title and market data.",
        )

        result = builder.build(discovered, llm_estimate)

        assert result.min_amount is not None
        assert result.max_amount is not None
        assert result.min_amount.source == CompensationSource.EMPLOYER_PROVIDED
        assert result.min_amount.amount.minor_units == 8_000_000
        assert result.max_amount.amount.minor_units == 12_000_000

    def test_employer_provided_rejected_with_unspecified_currency(
        self, builder: CompensationBuilder, llm_estimate: CompensationEstimate
    ) -> None:
        """Test employer provided compensation is rejected when currency is UNSPECIFIED."""
        discovered = DiscoveredListing(
            listing_url="https://example.com",
            title="Engineer",
            compensation=Compensation(
                min_amount=CompensationBound(
                    amount=MonetaryAmount(minor_units=8000000, currency=CurrencyCode.UNSPECIFIED),
                    source=CompensationSource.EMPLOYER_PROVIDED,
                ),
                frequency=PaymentFrequency.ANNUALLY,
            ),
        )

        result = builder.build(discovered, llm_estimate)

        assert result.min_amount is not None
        assert result.min_amount.source == CompensationSource.ESTIMATED_BY_NOHIKI
        assert result.min_amount.amount.minor_units == llm_estimate.min_amount.amount * 100

    def test_discovered_with_valid_currency_is_used(self, builder: CompensationBuilder) -> None:
        """Test discovered compensation is used when currency is valid."""
        discovered = DiscoveredListing(
            listing_url="https://example.com",
            title="Engineer",
            compensation=Compensation(
                min_amount=CompensationBound(
                    amount=MonetaryAmount(minor_units=7500000, currency=CurrencyCode.GBP),
                    source=CompensationSource.ESTIMATED_BY_JOB_BOARD,
                    confidence_percent=JOB_BOARD_ESTIMATE_CONFIDENCE_PERCENT,
                ),
                max_amount=CompensationBound(
                    amount=MonetaryAmount(minor_units=11000000, currency=CurrencyCode.GBP),
                    source=CompensationSource.ESTIMATED_BY_JOB_BOARD,
                    confidence_percent=JOB_BOARD_ESTIMATE_CONFIDENCE_PERCENT,
                ),
                frequency=PaymentFrequency.ANNUALLY,
            ),
        )
        llm_estimate = CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=70_000, source="llm_inferred", confidence_percent=70),
            max_amount=CompensationBoundEstimate(amount=100_000, source="llm_inferred", confidence_percent=70),
            currency=CurrencyCode.GBP,
            period=PaymentFrequency.ANNUALLY,
            reasoning="Estimated based on UK market rates for this role.",
        )

        result = builder.build(discovered, llm_estimate)

        assert result.min_amount is not None
        assert result.min_amount.source == CompensationSource.ESTIMATED_BY_JOB_BOARD
        assert result.min_amount.amount.minor_units == 7500000

    def test_discovered_rejected_with_unspecified_currency(
        self, builder: CompensationBuilder, llm_estimate: CompensationEstimate
    ) -> None:
        """Test discovered compensation is rejected when currency is UNSPECIFIED."""
        discovered = DiscoveredListing(
            listing_url="https://example.com",
            title="Engineer",
            compensation=Compensation(
                min_amount=CompensationBound(
                    amount=MonetaryAmount(minor_units=7500000, currency=CurrencyCode.UNSPECIFIED),
                    source=CompensationSource.ESTIMATED_BY_JOB_BOARD,
                ),
                max_amount=CompensationBound(
                    amount=MonetaryAmount(minor_units=11000000, currency=CurrencyCode.UNSPECIFIED),
                    source=CompensationSource.ESTIMATED_BY_JOB_BOARD,
                ),
                frequency=PaymentFrequency.ANNUALLY,
            ),
        )

        result = builder.build(discovered, llm_estimate)

        assert result.min_amount is not None
        assert result.min_amount.source == CompensationSource.ESTIMATED_BY_NOHIKI

    def test_falls_back_to_llm_estimate_when_no_compensation(
        self, builder: CompensationBuilder, llm_estimate: CompensationEstimate
    ) -> None:
        """Test LLM estimate is used when no discovered compensation."""
        discovered = DiscoveredListing(
            listing_url="https://example.com",
            title="Engineer",
        )

        result = builder.build(discovered, llm_estimate)

        assert result.min_amount is not None
        assert result.max_amount is not None
        assert result.min_amount.source == CompensationSource.ESTIMATED_BY_NOHIKI
        assert result.min_amount.amount.minor_units == llm_estimate.min_amount.amount * 100
        assert result.max_amount.amount.minor_units == llm_estimate.max_amount.amount * 100
        assert result.min_amount.amount.currency == llm_estimate.currency
        assert result.frequency == llm_estimate.period

    def test_falls_back_to_llm_when_compensation_has_no_amounts(
        self, builder: CompensationBuilder, llm_estimate: CompensationEstimate
    ) -> None:
        """Test LLM estimate is used when compensation has empty amounts."""
        discovered = DiscoveredListing(
            listing_url="https://example.com",
            title="Engineer",
            compensation=Compensation(
                frequency=PaymentFrequency.ANNUALLY,
            ),
        )

        result = builder.build(discovered, llm_estimate)

        assert result.min_amount is not None
        assert result.min_amount.source == CompensationSource.ESTIMATED_BY_NOHIKI

    @pytest.mark.parametrize(
        ("currency", "expected_currency"),
        [
            (CurrencyCode.USD, CurrencyCode.USD),
            (CurrencyCode.EUR, CurrencyCode.EUR),
            (CurrencyCode.GBP, CurrencyCode.GBP),
            (CurrencyCode.CAD, CurrencyCode.CAD),
            (CurrencyCode.AUD, CurrencyCode.AUD),
        ],
    )
    def test_llm_estimate_preserves_currency(
        self,
        builder: CompensationBuilder,
        currency: CurrencyCode,
        expected_currency: CurrencyCode,
    ) -> None:
        """Test LLM estimate preserves all supported currencies."""
        discovered = DiscoveredListing(listing_url="https://example.com", title="Engineer")
        llm_estimate = CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=50_000, source="llm_inferred", confidence_percent=80),
            max_amount=CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=80),
            currency=currency,
            period=PaymentFrequency.ANNUALLY,
            reasoning="Estimated based on market rates for this role and location.",
        )

        result = builder.build(discovered, llm_estimate)

        assert result.min_amount is not None
        assert result.max_amount is not None
        assert result.min_amount.amount.currency == expected_currency
        assert result.max_amount.amount.currency == expected_currency
