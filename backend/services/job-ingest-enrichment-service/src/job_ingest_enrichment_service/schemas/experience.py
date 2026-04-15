"""Experience extraction schemas for job posting enrichment.

Per-bound source tracking for experience requirements with explicit/inferred distinction.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

type ExperienceYears = Annotated[int, Field(ge=0, le=50)]
type ExperienceSourceLiteral = Literal["explicit", "inferred"]


class ExperienceYearsBound(BaseModel):
    """Single experience bound with per-bound source tracking.

    Each bound (min/max) can have independent source:
    - Employer might state "5+ years" (explicit min) but no max
    - LLM might infer a reasonable max (inferred with confidence)

    Year value semantics:
    - 0 = explicitly zero years (entry-level, no experience required)
    - N > 0 = N years required
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    years: ExperienceYears = Field(
        ...,
        description=(
            "Number of years for this bound (0-50). "
            "0 means zero experience required (entry-level). "
            "For '5+ years' the min bound is years=5; for '3-5 years' min=3 and max=5."
        ),
    )

    source: ExperienceSourceLiteral = Field(
        ...,
        description=(
            "'explicit': Employer stated this number directly (e.g., '5+ years required'). "
            "'inferred': You estimated from context such as title, seniority, or responsibilities."
        ),
    )

    confidence_percent: Annotated[int, Field(ge=1, le=100)] | None = Field(
        default=None,
        description=(
            "Confidence in this bound (1-100). "
            "Must be None when source='explicit' \u2014 stated figures have no uncertainty. "
            "Required (1-100) when source='inferred'."
        ),
    )

    @model_validator(mode="after")
    def validate_source_confidence(self) -> ExperienceYearsBound:
        """Validate and coerce confidence consistency with source.

        For ``explicit`` bounds, ``confidence_percent`` is silently coerced to
        ``None``: models frequently include a confidence value for explicit bounds
        despite the schema description, and raising here forces a retry that can
        collide with other correction attempts (e.g., fixing min/max ordering).
        """
        if self.source == "explicit":
            self.confidence_percent = None
        elif self.source == "inferred" and self.confidence_percent is None:
            msg = "confidence_percent is required for source='inferred'"
            raise ValueError(msg)
        return self


class ExperienceExtraction(BaseModel):
    """Experience requirements with per-bound source tracking.

    Each bound has independent source/confidence:
    - "5+ years" → min_years={years=5, source="explicit"}, max_years=None
    - "3-5 years" → min={years=3, source="explicit"}, max={years=5, source="explicit"}
    - "Entry level" → min={years=0, source="explicit"}, max={years=2, source="inferred", confidence=70}
    - Senior title, no explicit exp → min={years=5, source="inferred", confidence=60}, max=None
    - No experience info → min_years=None, max_years=None
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    min_years: ExperienceYearsBound | None = Field(
        default=None,
        description=(
            "Minimum years of experience required. "
            "None only when experience is genuinely not mentioned and cannot be reasonably inferred."
        ),
    )

    max_years: ExperienceYearsBound | None = Field(
        default=None,
        description=(
            "Maximum years of experience. "
            "None when no upper bound is stated (e.g., '5+ years' has no max). "
            "Provide inferred max only when the posting clearly implies a ceiling."
        ),
    )

    @model_validator(mode="after")
    def validate_range(self) -> ExperienceExtraction:
        """Validate min \u2264 max when both are specified."""
        if self.min_years is not None and self.max_years is not None and self.min_years.years > self.max_years.years:
            msg = (
                f"min_years ({self.min_years.years}) cannot exceed max_years ({self.max_years.years}). "
                f"Swap min and max if they are reversed."
            )
            raise ValueError(msg)
        return self
