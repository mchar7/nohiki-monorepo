"""Integration tests for work arrangement extraction.

Tests that the extraction agent correctly:
- Identifies remote, hybrid, and on-site arrangements
- Infers work arrangement from location and description context
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


class ValidatorProtocol(Protocol):
    """Protocol for validator type hints."""

    name: str

    def validate(
        self,
        extraction: JobExtractionSchema,
        fixture: JobListingFixtureProtocol,
    ) -> object: ...


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
type FixtureIterator = Callable[[], Iterator[JobListingFixtureProtocol]]
type FixtureListGetter = Callable[[], list[JobListingFixtureProtocol]]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.llm_cost
@pytest.mark.asyncio
class TestWorkArrangementExtraction:
    """Tests for work arrangement extraction accuracy."""

    async def test_remote_work_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        work_arrangement_validator: ValidatorProtocol,
        get_remote_listings: FixtureListGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of remote work positions."""
        fixtures = get_remote_listings()

        if not fixtures:
            pytest.skip("No remote work fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                validation = work_arrangement_validator.validate(extraction, fixture)

                if not getattr(validation, "passed", True):
                    failure_logger.log_extraction_failure(
                        fixture=fixture,
                        field_name="work_arrangement",
                        expected=fixture.expected.work_arrangement,
                        actual=extraction.work_arrangement.name,
                        extraction=extraction,
                    )
                    errors.append(f"{fixture.id}: Expected REMOTE, got {extraction.work_arrangement.name}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Remote work extraction errors:\n" + "\n".join(errors))

    async def test_hybrid_work_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        work_arrangement_validator: ValidatorProtocol,
        iter_fixtures: FixtureIterator,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of hybrid work positions."""
        fixtures = [f for f in iter_fixtures() if f.expected.work_arrangement == "HYBRID"]

        if not fixtures:
            pytest.skip("No hybrid work fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                validation = work_arrangement_validator.validate(extraction, fixture)

                if not getattr(validation, "passed", True):
                    errors.append(f"{fixture.id}: Expected HYBRID, got {extraction.work_arrangement.name}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Hybrid work extraction errors:\n" + "\n".join(errors))

    async def test_onsite_work_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        work_arrangement_validator: ValidatorProtocol,
        iter_fixtures: FixtureIterator,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of on-site work positions."""
        fixtures = [f for f in iter_fixtures() if f.expected.work_arrangement == "ON_SITE"]

        if not fixtures:
            pytest.skip("No on-site work fixtures found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                validation = work_arrangement_validator.validate(extraction, fixture)

                if not getattr(validation, "passed", True):
                    errors.append(f"{fixture.id}: Expected ON_SITE, got {extraction.work_arrangement.name}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("On-site work extraction errors:\n" + "\n".join(errors))
