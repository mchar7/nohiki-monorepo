"""Integration tests for skills extraction.

Tests that the extraction agent correctly:
- Extracts skills mentioned in job descriptions
- Assigns appropriate requirement levels
- Handles listings with few or no skills
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import pytest

if TYPE_CHECKING:
    from job_ingest_enrichment_service.schemas import JobExtractionSchema


@dataclass(frozen=True, slots=True)
class ExpectedValues:
    """Expected extraction values (stub for type hints)."""

    seniority: str
    work_arrangement: str
    employment_term: str
    min_explicit: bool = False
    max_explicit: bool = False
    min_salary: int | None = None
    max_salary: int | None = None
    min_skills_count: int = 0
    industry: str = "unspecified"


class JobListingFixtureProtocol(Protocol):
    """Protocol for job listing fixture type hints."""

    id: str
    title: str
    company: str
    expected: ExpectedValues


class ValidationResultProtocol(Protocol):
    """Protocol for validation result type hints."""

    passed: bool

    def error_messages(self) -> list[str]: ...


class ValidatorProtocol(Protocol):
    """Protocol for validator type hints."""

    name: str

    def validate(
        self,
        extraction: JobExtractionSchema,
        fixture: JobListingFixtureProtocol,
    ) -> ValidationResultProtocol: ...


class FailureLoggerProtocol(Protocol):
    """Protocol for failure logger type hints."""

    def log_extraction_failure(
        self,
        fixture: JobListingFixtureProtocol,
        field_name: str,
        expected: object,
        actual: object,
        extraction: JobExtractionSchema | None = None,
    ) -> None: ...

    def log_validation_failure(
        self,
        fixture: JobListingFixtureProtocol,
        validator: str,
        issues: list[str],
        extraction: JobExtractionSchema | None = None,
    ) -> None: ...

    def log_exception(
        self,
        fixture: JobListingFixtureProtocol,
        error: Exception,
    ) -> None: ...


type ExtractionGetter = Callable[[JobListingFixtureProtocol], Coroutine[None, None, JobExtractionSchema]]
type FixtureIterator = Callable[[], Iterator[JobListingFixtureProtocol]]
type FixtureByAttributeGetter = Callable[[str], list[JobListingFixtureProtocol]]


@pytest.mark.llm_cost
@pytest.mark.asyncio
class TestSkillsExtraction:
    """Tests for skills extraction accuracy."""

    async def test_technology_skills_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        skills_validator: ValidatorProtocol,
        get_fixtures_by_industry: FixtureByAttributeGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of technology-related skills."""
        fixtures = get_fixtures_by_industry("technology")

        if not fixtures:
            pytest.skip("No technology industry fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                validation = skills_validator.validate(extraction, fixture)

                if not validation.passed:
                    failure_logger.log_validation_failure(
                        fixture=fixture,
                        validator="skills",
                        issues=validation.error_messages(),
                        extraction=extraction,
                    )
                    errors.append(f"{fixture.id}: {', '.join(validation.error_messages())}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Technology skills extraction errors:\n" + "\n".join(errors))

    async def test_healthcare_skills_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        skills_validator: ValidatorProtocol,
        get_fixtures_by_industry: FixtureByAttributeGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of healthcare-related skills."""
        fixtures = get_fixtures_by_industry("healthcare")

        if not fixtures:
            pytest.skip("No healthcare industry fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                validation = skills_validator.validate(extraction, fixture)

                if not validation.passed:
                    errors.append(f"{fixture.id}: {', '.join(validation.error_messages())}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Healthcare skills extraction errors:\n" + "\n".join(errors))

    async def test_skill_count_reasonable(
        self,
        failure_logger: FailureLoggerProtocol,
        iter_fixtures: FixtureIterator,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test that skill counts are reasonable for detailed listings."""
        fixtures = [f for f in iter_fixtures() if f.expected.min_skills_count > 0]

        if not fixtures:
            pytest.skip("No fixtures with expected skills found")

        errors: list[str] = []

        for fixture in fixtures[:5]:
            try:
                extraction = await get_extraction(fixture)
                skill_count = len(extraction.skills)
                min_expected = fixture.expected.min_skills_count

                if skill_count < min_expected:
                    failure_logger.log_extraction_failure(
                        fixture=fixture,
                        field_name="skills_count",
                        expected=f">={min_expected}",
                        actual=str(skill_count),
                        extraction=extraction,
                    )
                    errors.append(f"{fixture.id}: Expected >={min_expected} skills, got {skill_count}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Skill count errors:\n" + "\n".join(errors))

    async def test_vague_listing_skills(
        self,
        failure_logger: FailureLoggerProtocol,
        iter_fixtures: FixtureIterator,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test that vague listings handle skill extraction gracefully."""
        fixtures = [f for f in iter_fixtures() if f.expected.min_skills_count == 0]

        if not fixtures:
            pytest.skip("No vague fixtures found")

        for fixture in fixtures[:2]:
            try:
                extraction = await get_extraction(fixture)
                assert extraction.skills is not None

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                pytest.fail(f"{fixture.id}: Exception during extraction - {e}")
