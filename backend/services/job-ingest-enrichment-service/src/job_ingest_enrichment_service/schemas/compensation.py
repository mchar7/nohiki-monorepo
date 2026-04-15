"""Compensation extraction schemas for job posting enrichment.

Per-bound source tracking for compensation estimates with confidence scoring.
All monetary amounts are in MAJOR UNITS (whole currency units as stated in the job posting).
"""

from __future__ import annotations

from typing import Annotated, Literal

from nohiki.common.v1 import CurrencyCode, PaymentFrequency
from nohiki_domain_utils import BetterprotoEnumAdapter
from pydantic import BaseModel, ConfigDict, Field, model_validator

type CompensationSourceLiteral = Literal["employer_provided", "job_board_estimate", "llm_inferred"]

MAX_COMPENSATION_RANGE_RATIO = 5.0

_currency_adapter = BetterprotoEnumAdapter(exclude_unspecified=True)
_payment_freq_adapter = BetterprotoEnumAdapter(exclude_unspecified=True)


class CompensationBoundEstimate(BaseModel):
    """Single compensation bound with per-bound source tracking.

    Each bound (min/max) can have an independent source:
    - Employer states "$80k minimum" → employer_provided
    - Job board shows an estimate → job_board_estimate
    - LLM infers the upper bound → llm_inferred with confidence

    All amounts are in MAJOR UNITS (whole currency units as stated in the job posting).
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    amount: int = Field(
        ...,
        ge=0,
        description=(
            "Compensation amount in whole major currency units -- no conversion or multiplication needed. "
            "Write the number exactly as stated in the posting: "
            "$80,000 → 80000 | £60,000 → 60000 | €75,000 → 75000 | "
            "SGD 95,000 → 95000 | ₹2,000,000 → 2000000 | AED 300,000 → 300000."
        ),
    )

    source: CompensationSourceLiteral = Field(
        ...,
        description=(
            "How this bound was determined. "
            "'employer_provided': Amount stated explicitly in the job posting. "
            "'job_board_estimate': Shown as a job board salary estimate (e.g. 'Indeed estimate'). "
            "'llm_inferred': You estimated it from role, seniority, location, and market context."
        ),
    )

    confidence_percent: Annotated[int, Field(ge=1, le=100)] | None = Field(
        default=None,
        description=(
            "Confidence in this bound (1-100). "
            "Must be None when source='employer_provided' - stated figures have no uncertainty. "
            "Required (1-100) when source='llm_inferred' or 'job_board_estimate'."
        ),
    )

    @model_validator(mode="after")
    def validate_source_confidence(self) -> CompensationBoundEstimate:
        """Validate and coerce confidence consistency with source.

        For ``employer_provided`` bounds, ``confidence_percent`` is silently
        coerced to ``None``: employer-stated figures carry implicit certainty
        and weaker models consistently include a confidence value despite the
        schema description, creating retry loops when combined with other corrections.
        """
        if self.source == "employer_provided":
            self.confidence_percent = None
        elif self.source in ("job_board_estimate", "llm_inferred") and self.confidence_percent is None:
            msg = f"confidence_percent is required for source='{self.source}'"
            raise ValueError(msg)
        return self


class CompensationEstimate(BaseModel):
    """Full compensation estimate with per-bound source tracking.

    ALWAYS provide an estimate: even with low confidence.
    Each bound has independent source/confidence:
    - Employer states "$100k-$120k" → both bounds employer_provided
    - Employer states "$100k minimum" → min employer_provided, max llm_inferred
    - No salary stated → both bounds llm_inferred with confidence

    All amounts are in MAJOR UNITS (whole currency units, no conversion needed).
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    min_amount: CompensationBoundEstimate = Field(
        ...,
        description="Lower bound of the compensation range. REQUIRED.",
    )

    max_amount: CompensationBoundEstimate = Field(
        ...,
        description="Upper bound of the compensation range. REQUIRED.",
    )

    currency: Annotated[CurrencyCode, _currency_adapter] = Field(
        default=CurrencyCode.USD,
        description=(
            "ISO 4217 currency code for the amounts. "
            "Infer from country/context when not explicitly stated: "
            "US roles → USD | UK roles → GBP | EU/Eurozone roles → EUR | "
            "CA roles → CAD | AU roles → AUD | SG roles → SGD | "
            "IN roles → INR | AE roles → AED | IL roles → ILS. "
            "UNSPECIFIED only when the currency is genuinely unknowable."
        ),
    )

    period: Annotated[PaymentFrequency, _payment_freq_adapter] = Field(
        default=PaymentFrequency.ANNUALLY,
        description=(
            "Payment frequency for the stated amounts. "
            "ANNUALLY: annual salary ('$80k/yr', '$80,000 salary', 'competitive salary'). "
            "HOURLY: per-hour rate ('$45/hr', '$45 per hour', hourly contract). "
            "DAILY / WEEKLY / MONTHLY: use when explicitly stated in that period. "
            "Do NOT convert between periods -- use the period the posting states. "
            "Default ANNUALLY for ambiguous cases."
        ),
    )

    reasoning: Annotated[str, Field(min_length=20, max_length=500)] = Field(
        ...,
        description=(
            "Brief explanation of how this estimate was formed. Include the source for each bound, "
            "key factors used (role level, location, industry), and confidence rationale. "
            "Example: 'Min $120k employer-stated. Max $150k inferred from senior SF fintech role, "
            "70% confident based on market comparables.'"
        ),
    )

    @model_validator(mode="after")
    def validate_range(self) -> CompensationEstimate:
        """Validate that min ≤ max and the range ratio is reasonable."""
        min_val = self.min_amount.amount
        max_val = self.max_amount.amount

        if min_val > max_val:
            msg = f"min_amount ({min_val}) cannot exceed max_amount ({max_val}). Swap min and max if they are reversed."
            raise ValueError(msg)

        if min_val > 0 and max_val / min_val > MAX_COMPENSATION_RANGE_RATIO:
            ratio = max_val / min_val
            msg = (
                f"Compensation range ratio {ratio:.1f}x exceeds the maximum of {MAX_COMPENSATION_RANGE_RATIO}x "
                f"(min={min_val}, max={max_val}). A range this wide is implausible -- re-assess the bounds."
            )
            raise ValueError(msg)

        return self
