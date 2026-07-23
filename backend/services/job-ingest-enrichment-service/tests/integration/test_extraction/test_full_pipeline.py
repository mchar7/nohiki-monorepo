"""Integration tests for the full extraction pipeline.

Tests that run_extraction_agent produces valid, complete extractions
across diverse job listings from multiple industries.
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
type FixtureListGetter = Callable[[], list[JobListingFixtureProtocol]]
type FixtureByAttributeGetter = Callable[[str], list[JobListingFixtureProtocol]]


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.llm_cost
@pytest.mark.asyncio
class TestFullExtractionPipeline:
    """End-to-end tests for the extraction pipeline."""

    async def test_diverse_industries_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        get_fixtures_by_industry: FixtureByAttributeGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction works across diverse industries."""
        industries = [
            "technology",
            "healthcare",
            "finance",
            "legal",
            "education",
            "hospitality",
        ]

        errors: list[str] = []

        for industry in industries:
            fixtures = get_fixtures_by_industry(industry)
            if not fixtures:
                continue

            fixture = fixtures[0]
            try:
                extraction = await get_extraction(fixture)

                if not extraction.cleaned_title:
                    errors.append(f"{fixture.id}: Missing cleaned_title")

                if not extraction.cleaned_company:
                    errors.append(f"{fixture.id}: Missing cleaned_company")

                if not extraction.compensation_estimate:
                    errors.append(f"{fixture.id}: Missing compensation_estimate")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id} ({industry}): Exception - {e}")

        if errors:
            pytest.fail("Multi-industry extraction errors:\n" + "\n".join(errors))

    async def test_extraction_completeness(
        self,
        failure_logger: FailureLoggerProtocol,
        iter_fixtures: FixtureIterator,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test that extractions include all required fields."""
        fixtures = list(iter_fixtures())[:5]

        if not fixtures:
            pytest.skip("No fixtures found")

        errors: list[str] = []

        for fixture in fixtures:
            try:
                extraction = await get_extraction(fixture)

                required_fields = [
                    ("cleaned_title", extraction.cleaned_title),
                    ("cleaned_company", extraction.cleaned_company),
                    ("seniority_level", extraction.seniority_level),
                    ("work_arrangement", extraction.work_arrangement),
                    ("employment_term", extraction.employment_term),
                    ("compensation_estimate", extraction.compensation_estimate),
                ]

                missing = [name for name, value in required_fields if not value]

                if missing:
                    failure_logger.log_validation_failure(
                        fixture=fixture,
                        validator="completeness",
                        issues=[f"Missing fields: {', '.join(missing)}"],
                        extraction=extraction,
                    )
                    errors.append(f"{fixture.id}: Missing {', '.join(missing)}")

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Completeness errors:\n" + "\n".join(errors))

    async def test_all_validators_pass(
        self,
        failure_logger: FailureLoggerProtocol,
        load_all_fixtures: FixtureListGetter,
        get_extraction: ExtractionGetter,
        compensation_validator: ValidatorProtocol,
        seniority_validator: ValidatorProtocol,
        skills_validator: ValidatorProtocol,
        work_arrangement_validator: ValidatorProtocol,
    ) -> None:
        """Test that all validators pass for well-defined fixtures."""
        validators = [
            compensation_validator,
            seniority_validator,
            skills_validator,
            work_arrangement_validator,
        ]

        fixtures = [f for f in load_all_fixtures() if f.expected.min_skills_count > 0][:3]

        if not fixtures:
            pytest.skip("No detailed fixtures found")

        all_issues: list[str] = []

        for fixture in fixtures:
            try:
                extraction = await get_extraction(fixture)

                for validator in validators:
                    validation = validator.validate(extraction, fixture)

                    if not validation.passed:
                        for msg in validation.error_messages():
                            all_issues.append(f"{fixture.id}/{validator.name}: {msg}")
                            failure_logger.log_validation_failure(
                                fixture=fixture,
                                validator=validator.name,
                                issues=[msg],
                                extraction=extraction,
                            )

            except Exception as e:
                failure_logger.log_exception(fixture, e)
                all_issues.append(f"{fixture.id}: Exception - {e}")

        if all_issues:
            pytest.fail("Validation errors:\n" + "\n".join(all_issues))
