"""Integration tests for seniority level extraction.

Tests that the extraction agent correctly:
- Identifies seniority from job titles
- Infers seniority from requirements and responsibilities
- Handles ambiguous listings appropriately
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
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

    def log_exception(
        self,
        fixture: JobListingFixtureProtocol,
        error: Exception,
    ) -> None: ...


type ExtractionGetter = Callable[[JobListingFixtureProtocol], Coroutine[None, None, JobExtractionSchema]]
type FixtureListGetter = Callable[[], list[JobListingFixtureProtocol]]
type FixtureByAttributeGetter = Callable[[str], list[JobListingFixtureProtocol]]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.llm_cost
@pytest.mark.asyncio
class TestSeniorityExtraction:
    """Tests for seniority level extraction accuracy."""

    async def test_senior_level_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        seniority_validator: ValidatorProtocol,
        get_senior_listings: FixtureListGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of senior-level positions."""
        fixtures = get_senior_listings()

        if not fixtures:
            pytest.skip("No senior-level fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:4]:
            try:
                extraction = await get_extraction(fixture)
                validation = seniority_validator.validate(extraction, fixture)

                if not validation.passed:
                    for msg in validation.error_messages():
                        failure_logger.log_extraction_failure(
                            fixture=fixture,
                            field_name="seniority_level",
                            expected=fixture.expected.seniority,
                            actual=msg,
                            extraction=extraction,
                        )
                    errors.append(
                        f"{fixture.id}: Expected {fixture.expected.seniority}, got {extraction.seniority_level.name}"
                    )

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Senior level extraction errors:\n" + "\n".join(errors))

    async def test_entry_level_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        seniority_validator: ValidatorProtocol,
        get_entry_level_listings: FixtureListGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of entry-level and intern positions."""
        fixtures = get_entry_level_listings()

        if not fixtures:
            pytest.skip("No entry-level fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                validation = seniority_validator.validate(extraction, fixture)

                if not validation.passed:
                    errors.append(
                        f"{fixture.id}: Expected {fixture.expected.seniority}, got {extraction.seniority_level.name}"
                    )

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Entry level extraction errors:\n" + "\n".join(errors))

    async def test_mid_level_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        seniority_validator: ValidatorProtocol,
        get_fixtures_by_seniority: FixtureByAttributeGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of mid-level positions."""
        fixtures = get_fixtures_by_seniority("MID")

        if not fixtures:
            pytest.skip("No mid-level fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                validation = seniority_validator.validate(extraction, fixture)

                if not validation.passed:
                    errors.append(f"{fixture.id}: Expected MID, got {extraction.seniority_level.name}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Mid level extraction errors:\n" + "\n".join(errors))

    async def test_director_level_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        seniority_validator: ValidatorProtocol,
        get_fixtures_by_seniority: FixtureByAttributeGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of director-level positions."""
        fixtures = get_fixtures_by_seniority("DIRECTOR")

        if not fixtures:
            pytest.skip("No director-level fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:2]:
            try:
                extraction = await get_extraction(fixture)
                validation = seniority_validator.validate(extraction, fixture)

                if not validation.passed:
                    errors.append(f"{fixture.id}: Expected DIRECTOR, got {extraction.seniority_level.name}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Director level extraction errors:\n" + "\n".join(errors))
