"""Compensation builder with source priority.

Priority:
1. Explicit from employer (source=EMPLOYER_PROVIDED) with valid currency
2. Job board estimate (source=ESTIMATED_BY_JOB_BOARD) with valid currency
3. LLM estimate (ALWAYS present - PydanticAI retries)

Discovery compensation is only used if it has a valid (non-UNSPECIFIED) currency.

New proto structure uses per-bound source tracking:
- Each bound (min/max) has its own source and optional confidence
- Compensation contains min_amount: CompensationBound, max_amount: CompensationBound, frequency
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nohiki.common.v1 import (
    Compensation,
    CompensationBound,
    CompensationSource,
    CurrencyCode,
    MonetaryAmount,
)

from job_ingest_enrichment_service.services.proto_builders import COMPENSATION_SOURCE_MAP

if TYPE_CHECKING:
    from nohiki.job.ingest.v1 import DiscoveredListing

    from job_ingest_enrichment_service.schemas.compensation import CompensationEstimate

JOB_BOARD_ESTIMATE_CONFIDENCE_PERCENT = 70

_MINOR_UNITS_PER_MAJOR: int = 100


class CompensationBuilder:
    """Builds Compensation from best available source with per-bound tracking."""

    def build(
        self,
        discovered: DiscoveredListing,
        llm_estimate: CompensationEstimate,
    ) -> Compensation:
        """Build from best source. LLM estimate ALWAYS present."""
        if comp := self._try_from_discovered(discovered):
            return comp
        return self._from_llm_estimate(llm_estimate)

    def _try_from_discovered(
        self,
        discovered: DiscoveredListing,
    ) -> Compensation | None:
        """Try to build from discovered data if it has valid bounds."""
        if not discovered.compensation:
            return None
        if not _has_valid_bound(discovered.compensation):
            return None
        return discovered.compensation

    def _from_llm_estimate(self, estimate: CompensationEstimate) -> Compensation:
        """Build from LLM estimate with per-bound source tracking."""
        return Compensation(
            min_amount=_build_bound_from_estimate(
                estimate.min_amount.amount,
                estimate.currency,
                estimate.min_amount.source,
                estimate.min_amount.confidence_percent,
            ),
            max_amount=_build_bound_from_estimate(
                estimate.max_amount.amount,
                estimate.currency,
                estimate.max_amount.source,
                estimate.max_amount.confidence_percent,
            ),
            frequency=estimate.period,
        )


def _build_bound_from_estimate(
    amount: int,
    currency: CurrencyCode,
    source: str,
    confidence: int | None,
) -> CompensationBound:
    """Build CompensationBound from extraction estimate."""
    proto_source = COMPENSATION_SOURCE_MAP.get(source, CompensationSource.ESTIMATED_BY_NOHIKI)

    bound = CompensationBound(
        amount=MonetaryAmount(minor_units=amount * _MINOR_UNITS_PER_MAJOR, currency=currency),
        source=proto_source,
    )
    if proto_source != CompensationSource.EMPLOYER_PROVIDED and confidence is not None:
        bound.confidence_percent = confidence
    return bound


def _has_valid_bound(comp: Compensation) -> bool:
    """Check if compensation has at least one bound with valid currency."""
    min_valid = (
        comp.min_amount and comp.min_amount.amount and comp.min_amount.amount.currency != CurrencyCode.UNSPECIFIED
    )
    max_valid = (
        comp.max_amount and comp.max_amount.amount and comp.max_amount.amount.currency != CurrencyCode.UNSPECIFIED
    )
    return bool(min_valid or max_valid)
