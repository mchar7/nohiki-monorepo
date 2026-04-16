"""Unit tests for compensation extraction schemas.

Tests validation logic for CompensationBoundEstimate and CompensationEstimate,
including source/confidence consistency and range validation.
All amounts are in MAJOR UNITS (whole currency units as stated in job postings).
"""

from __future__ import annotations

import pytest
from job_ingest_enrichment_service.schemas.compensation import (
    MAX_COMPENSATION_RANGE_RATIO,
    CompensationBoundEstimate,
    CompensationEstimate,
)
from nohiki.common.v1 import PaymentFrequency
from pydantic import ValidationError


def _employer_bound(amount: int) -> CompensationBoundEstimate:
    return CompensationBoundEstimate(amount=amount, source="employer_provided")


def _inferred_bound(amount: int, confidence: int = 70) -> CompensationBoundEstimate:
    return CompensationBoundEstimate(amount=amount, source="llm_inferred", confidence_percent=confidence)


def _make_estimate(
    min_amount: int,
    max_amount: int,
    period: PaymentFrequency = PaymentFrequency.ANNUALLY,
    source: str = "employer_provided",
) -> CompensationEstimate:
    bound_fn = _employer_bound if source == "employer_provided" else _inferred_bound
    return CompensationEstimate(
        min_amount=bound_fn(min_amount),
        max_amount=bound_fn(max_amount),
        period=period,
        reasoning="Min and max employer-stated from job description range.",
    )


class TestCompensationBoundEstimate:
    """Tests for CompensationBoundEstimate validation."""

    def test_employer_provided_no_confidence(self) -> None:
        bound = CompensationBoundEstimate(amount=80_000, source="employer_provided")
        assert bound.confidence_percent is None

    def test_llm_inferred_requires_confidence(self) -> None:
        bound = CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=80)
        assert bound.confidence_percent == 80

    def test_employer_provided_coerces_confidence_to_none(self) -> None:
        bound = CompensationBoundEstimate(amount=80_000, source="employer_provided", confidence_percent=90)
        assert bound.confidence_percent is None

    def test_job_board_estimate_preserves_confidence(self) -> None:
        bound = CompensationBoundEstimate(amount=80_000, source="job_board_estimate", confidence_percent=90)
        assert bound.confidence_percent == 90

    def test_inferred_missing_confidence_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence_percent is required for source"):
            CompensationBoundEstimate(amount=80_000, source="llm_inferred")

    def test_job_board_missing_confidence_rejected(self) -> None:
        with pytest.raises(ValidationError, match="confidence_percent is required for source"):
            CompensationBoundEstimate(amount=80_000, source="job_board_estimate")

    def test_zero_amount_is_valid(self) -> None:
        bound = CompensationBoundEstimate(amount=0, source="employer_provided")
        assert bound.amount == 0

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CompensationBoundEstimate(amount=-1, source="employer_provided")

    def test_amount_stored_as_major_units(self) -> None:
        bound = CompensationBoundEstimate(amount=80_000, source="employer_provided")
        assert bound.amount == 80_000


class TestCompensationEstimateRangeValidation:
    """Tests for range and ratio validation."""

    def test_valid_annual_range(self) -> None:
        est = _make_estimate(65_000, 85_000, PaymentFrequency.ANNUALLY)
        assert est.min_amount.amount == 65_000
        assert est.max_amount.amount == 85_000

    def test_min_exceeds_max_rejected(self) -> None:
        with pytest.raises(ValidationError, match="cannot exceed max_amount"):
            _make_estimate(90_000, 70_000, PaymentFrequency.ANNUALLY)

    def test_min_exceeds_max_error_suggests_swap(self) -> None:
        with pytest.raises(ValidationError, match="Swap min and max"):
            _make_estimate(90_000, 70_000, PaymentFrequency.ANNUALLY)

    def test_ratio_exactly_at_limit_accepted(self) -> None:
        max_amount = int(10_000 * MAX_COMPENSATION_RANGE_RATIO)
        est = _make_estimate(10_000, max_amount, PaymentFrequency.ANNUALLY)
        assert est.max_amount.amount == max_amount

    def test_ratio_exceeds_limit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="range ratio"):
            _make_estimate(10_000, 60_000, PaymentFrequency.ANNUALLY)

    def test_ratio_error_suggests_reassessment(self) -> None:
        with pytest.raises(ValidationError, match="re-assess the bounds"):
            _make_estimate(10_000, 60_000, PaymentFrequency.ANNUALLY)

    def test_zero_amounts_skip_ratio_check(self) -> None:
        est = CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=0, source="employer_provided"),
            max_amount=CompensationBoundEstimate(amount=0, source="employer_provided"),
            period=PaymentFrequency.ANNUALLY,
            reasoning="No compensation data available in this posting.",
        )
        assert est.min_amount.amount == 0


class TestCompensationEstimatePeriod:
    """Tests that payment period is preserved and any major-unit amount is accepted.

    With major units in the LLM schema there are no magnitude restrictions --
    a $45/hr rate is simply 45, and a ₹2,000,000 annual salary is 2000000.
    The only constraints are range order and ratio.
    """

    def test_annual_salary_accepted(self) -> None:
        est = _make_estimate(80_000, 100_000, PaymentFrequency.ANNUALLY)
        assert est.period == PaymentFrequency.ANNUALLY

    def test_hourly_rate_accepted(self) -> None:
        est = _make_estimate(45, 65, PaymentFrequency.HOURLY)
        assert est.period == PaymentFrequency.HOURLY

    def test_daily_rate_accepted(self) -> None:
        est = _make_estimate(500, 700, PaymentFrequency.DAILY)
        assert est.period == PaymentFrequency.DAILY

    def test_monthly_salary_accepted(self) -> None:
        est = _make_estimate(6_000, 8_000, PaymentFrequency.MONTHLY)
        assert est.period == PaymentFrequency.MONTHLY

    def test_small_annual_amount_valid(self) -> None:
        est = _make_estimate(5_000, 8_000, PaymentFrequency.ANNUALLY)
        assert est.min_amount.amount == 5_000

    def test_high_hourly_rate_valid(self) -> None:
        est = _make_estimate(200, 400, PaymentFrequency.HOURLY)
        assert est.max_amount.amount == 400

    def test_inr_large_annual_salary_valid(self) -> None:
        est = _make_estimate(2_000_000, 3_000_000, PaymentFrequency.ANNUALLY)
        assert est.min_amount.amount == 2_000_000

    def test_period_defaults_to_annually(self) -> None:
        est = CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=80_000, source="employer_provided"),
            max_amount=CompensationBoundEstimate(amount=100_000, source="employer_provided"),
            reasoning="Annual salary stated in the job description.",
        )
        assert est.period == PaymentFrequency.ANNUALLY

    def test_zero_amount_annual_accepted(self) -> None:
        est = CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=0, source="employer_provided"),
            max_amount=CompensationBoundEstimate(amount=0, source="employer_provided"),
            period=PaymentFrequency.ANNUALLY,
            reasoning="No compensation information present in this job posting.",
        )
        assert est.period == PaymentFrequency.ANNUALLY
