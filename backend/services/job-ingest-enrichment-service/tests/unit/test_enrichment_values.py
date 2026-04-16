"""Table-driven value object tests for job-ingest-enrichment-service extraction schemas.

Tests Pydantic model validators for LocationExtraction, ExperienceExtraction,
CompensationEstimate, and the mapper functions in proto_builders.
"""

from __future__ import annotations

import pytest
from job_ingest_enrichment_service.schemas.extraction import (
    CompensationBoundEstimate,
    CompensationEstimate,
    CompensationSourceLiteral,
    ExperienceExtraction,
    ExperienceSourceLiteral,
    ExperienceYearsBound,
    ExtractedSkill,
    JobExtractionSchema,
    LocationExtraction,
)
from job_ingest_enrichment_service.services.proto_builders import (
    map_compensation_source,
    map_experience_source,
)
from nohiki.common.v1 import (
    CompensationSource,
    CountryCode,
    EmploymentTerm,
    ExperienceSource,
    SeniorityLevel,
    WorkArrangement,
)
from pydantic import ValidationError


class TestLocationExtraction:
    """Table-driven tests for LocationExtraction validation."""

    @pytest.mark.parametrize(
        ("city", "state", "country", "remote"),
        [
            ("San Francisco", "California", CountryCode.USA, False),
            ("London", None, CountryCode.GBR, False),
            ("Toronto", "Ontario", CountryCode.CAN, True),
            (None, None, CountryCode.UNSPECIFIED, True),
            (None, None, CountryCode.USA, False),
        ],
    )
    def test_valid_locations(
        self,
        city: str | None,
        state: str | None,
        country: CountryCode,
        remote: bool,  # noqa: FBT001
    ) -> None:
        """Valid location combinations must pass validation."""
        loc = LocationExtraction(
            city=city,
            state_province=state,
            country_code=country,
            is_remote_eligible=remote,
        )
        assert loc.country_code == country

    def test_unspecified_country_clears_city_state(self) -> None:
        """UNSPECIFIED country must clear city and state via validator."""
        loc = LocationExtraction(
            city="Bogus",
            state_province="Fake",
            country_code=CountryCode.UNSPECIFIED,
        )
        assert loc.city is None
        assert loc.state_province is None
        assert loc.country_code == CountryCode.UNSPECIFIED


class TestExperienceYearsBound:
    """Table-driven tests for ExperienceYearsBound validation."""

    @pytest.mark.parametrize(
        ("years", "source", "confidence"),
        [
            (5, "explicit", None),
            (0, "explicit", None),
        ],
    )
    def test_valid_bounds(self, years: int, source: ExperienceSourceLiteral, confidence: int | None) -> None:
        """Valid experience bounds must pass validation."""
        bound = ExperienceYearsBound(
            years=years,
            source=source,
            confidence_percent=confidence,
        )
        assert bound.years == years

    def test_explicit_with_confidence_coerced_to_none(self) -> None:
        """Explicit bounds silently coerce confidence_percent to None."""
        bound = ExperienceYearsBound(years=5, source="explicit", confidence_percent=80)
        assert bound.confidence_percent is None

    def test_inferred_without_confidence_raises(self) -> None:
        """Inferred source must have confidence."""
        with pytest.raises(ValidationError, match="confidence_percent is required for source"):
            ExperienceYearsBound(years=5, source="inferred", confidence_percent=None)


class TestExperienceExtraction:
    """Table-driven tests for ExperienceExtraction validation."""

    def test_valid_range(self) -> None:
        """Valid min < max range passes."""
        exp = ExperienceExtraction(
            min_years=ExperienceYearsBound(years=2, source="explicit"),
            max_years=ExperienceYearsBound(years=5, source="explicit"),
        )
        assert exp.min_years is not None
        assert exp.min_years.years == 2

    def test_min_exceeds_max_raises(self) -> None:
        """Min > max must raise."""
        with pytest.raises(ValidationError, match="cannot exceed"):
            ExperienceExtraction(
                min_years=ExperienceYearsBound(years=10, source="explicit"),
                max_years=ExperienceYearsBound(years=5, source="explicit"),
            )

    def test_none_bounds_valid(self) -> None:
        """Both bounds None is valid (no experience info)."""
        exp = ExperienceExtraction()
        assert exp.min_years is None
        assert exp.max_years is None


class TestCompensationBoundEstimate:
    """Table-driven tests for CompensationBoundEstimate validation."""

    @pytest.mark.parametrize(
        ("amount", "source", "confidence"),
        [
            (80_000, "employer_provided", None),
            (100_000, "job_board_estimate", 70),
            (120_000, "llm_inferred", 50),
        ],
    )
    def test_valid_bounds(self, amount: int, source: CompensationSourceLiteral, confidence: int | None) -> None:
        """Valid compensation bounds pass validation."""
        bound = CompensationBoundEstimate(
            amount=amount,
            source=source,
            confidence_percent=confidence,
        )
        assert bound.amount == amount

    def test_employer_with_confidence_coerced_to_none(self) -> None:
        """Employer-provided with confidence is silently coerced to None.

        LLM models often supply a confidence value even for employer-stated
        figures. Raising here creates a cyclic failure (model corrects confidence
        but then mis-states amount in cents). Silent coercion is the designed
        behavior: see validator docstring.
        """
        bound = CompensationBoundEstimate(amount=80_000, source="employer_provided", confidence_percent=80)
        assert bound.confidence_percent is None

    def test_inferred_without_confidence_raises(self) -> None:
        """Inferred source must have confidence."""
        with pytest.raises(ValidationError, match="confidence_percent is required for source"):
            CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=None)


class TestCompensationEstimate:
    """Table-driven tests for CompensationEstimate validation."""

    def test_valid_range(self) -> None:
        """Valid min < max range passes."""
        comp = CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=80_000, source="employer_provided"),
            max_amount=CompensationBoundEstimate(amount=120_000, source="employer_provided"),
            reasoning="Min $80k and max $120k stated in posting for senior role.",
        )
        assert comp.min_amount.amount == 80_000

    def test_min_exceeds_max_raises(self) -> None:
        """Min > max must raise."""
        with pytest.raises(ValidationError, match="cannot exceed"):
            CompensationEstimate(
                min_amount=CompensationBoundEstimate(amount=150_000, source="employer_provided"),
                max_amount=CompensationBoundEstimate(amount=80_000, source="employer_provided"),
                reasoning="Invalid range where min exceeds max for testing.",
            )

    def test_excessive_range_ratio_raises(self) -> None:
        """Range ratio > 5x must raise."""
        with pytest.raises(ValidationError, match="range ratio"):
            CompensationEstimate(
                min_amount=CompensationBoundEstimate(amount=10_000, source="llm_inferred", confidence_percent=30),
                max_amount=CompensationBoundEstimate(amount=100_000, source="llm_inferred", confidence_percent=30),
                reasoning="Extremely wide range from $10k to $100k annual.",
            )


class TestExtractedSkill:
    """Tests for ExtractedSkill validation."""

    def test_valid_skill(self) -> None:
        """Valid skill extraction passes."""
        skill = ExtractedSkill(raw_skill="Python", relation_type="essential")
        assert skill.raw_skill == "Python"
        assert skill.relation_type == "essential"

    def test_empty_skill_raises(self) -> None:
        """Empty skill name must raise."""
        with pytest.raises(ValidationError):
            ExtractedSkill(raw_skill="")

    def test_source_defaults_to_explicit(self) -> None:
        """Source defaults to 'explicit' when not provided."""
        skill = ExtractedSkill(raw_skill="Python")
        assert skill.source == "explicit"

    @pytest.mark.parametrize("source", ["explicit", "inferred"])
    def test_source_accepts_valid_values(self, source: str) -> None:
        """Source accepts the two literal values defined by SkillSource."""
        skill = ExtractedSkill.model_validate({"raw_skill": "Python", "source": source})
        assert skill.source == source

    @pytest.mark.parametrize("invalid", ["EXPLICIT", "guessed", "", "implicit"])
    def test_source_rejects_invalid_values(self, invalid: str) -> None:
        """Source rejects values outside the SkillSource literal set."""
        with pytest.raises(ValidationError):
            ExtractedSkill.model_validate({"raw_skill": "Python", "source": invalid})


class TestMapExperienceSource:
    """Table-driven tests for map_experience_source."""

    @pytest.mark.parametrize(
        ("source_str", "expected"),
        [
            ("explicit", ExperienceSource.EMPLOYER_PROVIDED),
            ("inferred", ExperienceSource.INFERRED_BY_NOHIKI),
            ("unknown", ExperienceSource.INFERRED_BY_NOHIKI),
        ],
    )
    def test_maps_correctly(self, source_str: str, expected: ExperienceSource) -> None:
        """Source strings map to correct proto enums."""
        assert map_experience_source(source_str) == expected


class TestMapCompensationSource:
    """Table-driven tests for map_compensation_source."""

    @pytest.mark.parametrize(
        ("source_str", "expected"),
        [
            ("employer_provided", CompensationSource.EMPLOYER_PROVIDED),
            ("job_board_estimate", CompensationSource.ESTIMATED_BY_JOB_BOARD),
            ("llm_inferred", CompensationSource.ESTIMATED_BY_NOHIKI),
            ("unknown", CompensationSource.ESTIMATED_BY_NOHIKI),
        ],
    )
    def test_maps_correctly(self, source_str: str, expected: CompensationSource) -> None:
        """Source strings map to correct proto enums."""
        assert map_compensation_source(source_str) == expected


def _make_minimal_schema(**overrides: object) -> JobExtractionSchema:
    """Build a minimal valid JobExtractionSchema for testing."""
    defaults: dict[str, object] = {
        "cleaned_title": "Software Engineer",
        "cleaned_company": "TechCorp",
        "seniority_level": SeniorityLevel.MID,
        "language": "en",
        "location": LocationExtraction(country_code=CountryCode.USA),
        "skills": [
            ExtractedSkill(raw_skill="Python"),
            ExtractedSkill(raw_skill="AWS"),
            ExtractedSkill(raw_skill="PostgreSQL"),
        ],
        "compensation_estimate": CompensationEstimate(
            min_amount=CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=50),
            max_amount=CompensationBoundEstimate(amount=120_000, source="llm_inferred", confidence_percent=50),
            reasoning="Mid-level SWE in US, estimated $80k-$120k range.",
        ),
    }
    defaults.update(overrides)
    # model_validate accepts dict[str, object] and handles coercion via Pydantic validators
    return JobExtractionSchema.model_validate(defaults)


class TestJobExtractionSchemaDefaults:
    """Tests for JobExtractionSchema default values."""

    def test_defaults_for_optional_fields(self) -> None:
        """Optional fields default correctly when skills and required fields provided."""
        schema = JobExtractionSchema(
            cleaned_title="Software Engineer",
            cleaned_company="TechCorp",
            seniority_level=SeniorityLevel.MID,
            language="en",
            location=LocationExtraction(country_code=CountryCode.USA),
            skills=[
                ExtractedSkill(raw_skill="Python"),
                ExtractedSkill(raw_skill="AWS"),
                ExtractedSkill(raw_skill="Docker"),
            ],
            compensation_estimate=CompensationEstimate(
                min_amount=CompensationBoundEstimate(amount=80_000, source="llm_inferred", confidence_percent=50),
                max_amount=CompensationBoundEstimate(amount=120_000, source="llm_inferred", confidence_percent=50),
                reasoning="Mid-level SWE in US, estimated $80k-$120k range.",
            ),
        )
        assert schema.work_arrangement == WorkArrangement.UNSPECIFIED
        assert schema.employment_term == EmploymentTerm.UNSPECIFIED
        assert len(schema.skills) == 3


class TestLanguageField:
    """Tests for language field extraction and BCP 47 tag validation."""

    @pytest.mark.parametrize(
        "tag",
        ["en", "fr", "de", "ja", "es", "nl", "it", "zh-CN", "zh-TW", "pt-BR", "pt-PT", "fr-CA"],
    )
    def test_valid_bcp47_tags(self, tag: str) -> None:
        """Valid IETF BCP 47 language tags pass validation."""
        schema = _make_minimal_schema(language=tag)
        assert schema.language == tag

    @pytest.mark.parametrize(
        "invalid_tag",
        ["", "x", "english", "fr-Canada"],  # empty, too short, too long, too long
    )
    def test_invalid_tags_raise(self, invalid_tag: str) -> None:
        """Tags outside min/max length constraints raise ValidationError."""
        with pytest.raises(ValidationError):
            _make_minimal_schema(language=invalid_tag)
