"""Integration tests for compensation extraction.

Tests that the extraction agent correctly:
- Identifies explicit salary ranges when provided
- Estimates reasonable salary ranges when not provided
- Properly attributes sources (employer_provided vs llm_inferred)
- Provides meaningful reasoning

EFFICIENCY: All tests share cached LLM extraction results to avoid redundant API calls.
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
type FixtureListGetter = Callable[[], list[JobListingFixtureProtocol]]


def _validate_explicit_compensation(
    extraction: JobExtractionSchema,
    fixture: JobListingFixtureProtocol,
    validator: ValidatorProtocol,
    failure_logger: FailureLoggerProtocol,
) -> list[str]:
    """Validate explicit compensation extraction for a single fixture."""
    errors: list[str] = []
    validation = validator.validate(extraction, fixture)

    if not validation.passed:
        for issue in validation.error_messages():
            failure_logger.log_extraction_failure(
                fixture=fixture,
                field_name="compensation",
                expected=str(fixture.expected.min_salary),
                actual=issue,
                extraction=extraction,
            )
        errors.append(f"{fixture.id}: {', '.join(validation.error_messages())}")

    return errors


def _validate_inferred_compensation(
    extraction: JobExtractionSchema,
    fixture: JobListingFixtureProtocol,
) -> list[str]:
    """Validate inferred compensation extraction for a single fixture."""
    errors: list[str] = []
    comp = extraction.compensation_estimate

    if comp.min_amount.source != "llm_inferred":
        errors.append(f"{fixture.id}: Expected llm_inferred source, got {comp.min_amount.source}")

    if comp.min_amount.amount <= 0:
        errors.append(f"{fixture.id}: Invalid min amount: {comp.min_amount.amount}")

    return errors


def _validate_reasoning_quality(
    extraction: JobExtractionSchema,
    fixture: JobListingFixtureProtocol,
    failure_logger: FailureLoggerProtocol,
) -> list[str]:
    """Validate compensation reasoning quality for a single fixture."""
    errors: list[str] = []
    reasoning = extraction.compensation_estimate.reasoning

    if len(reasoning) < 20:
        errors.append(f"{fixture.id}: Reasoning too short ({len(reasoning)} chars)")

    keywords = {"salary", "compensation", "pay", "range", "market", "based"}
    if not any(kw in reasoning.lower() for kw in keywords):
        failure_logger.log_validation_failure(
            fixture=fixture,
            validator="compensation_reasoning",
            issues=["Reasoning lacks compensation-related keywords"],
            extraction=extraction,
        )

    return errors


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.llm_cost
@pytest.mark.asyncio
class TestCompensationExtraction:
    """Tests for compensation extraction accuracy."""

    async def test_explicit_compensation_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        compensation_validator: ValidatorProtocol,
        get_fixtures_with_explicit_compensation: FixtureListGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test extraction of explicitly stated compensation ranges."""
        fixtures = get_fixtures_with_explicit_compensation()

        if not fixtures:
            pytest.skip("No fixtures with explicit compensation found")

        errors: list[str] = []

        for fixture in fixtures[:5]:
            try:
                extraction = await get_extraction(fixture)
                errors.extend(
                    _validate_explicit_compensation(extraction, fixture, compensation_validator, failure_logger)
                )
            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Compensation extraction errors:\n" + "\n".join(errors))

    async def test_inferred_compensation_extraction(
        self,
        failure_logger: FailureLoggerProtocol,
        get_fixtures_without_explicit_compensation: FixtureListGetter,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test that LLM provides reasonable estimates when compensation not stated."""
        fixtures = get_fixtures_without_explicit_compensation()

        if not fixtures:
            pytest.skip("No fixtures without explicit compensation found")

        errors: list[str] = []

        for fixture in fixtures[:3]:
            try:
                extraction = await get_extraction(fixture)
                errors.extend(_validate_inferred_compensation(extraction, fixture))
            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Inferred compensation errors:\n" + "\n".join(errors))

    async def test_compensation_reasoning_quality(
        self,
        failure_logger: FailureLoggerProtocol,
        iter_fixtures: FixtureIterator,
        get_extraction: ExtractionGetter,
    ) -> None:
        """Test that compensation reasoning is meaningful and substantive."""
        fixtures = list(iter_fixtures())[:3]

        if not fixtures:
            pytest.skip("No fixtures found")

        errors: list[str] = []

        for fixture in fixtures:
            try:
                extraction = await get_extraction(fixture)
                errors.extend(_validate_reasoning_quality(extraction, fixture, failure_logger))
            except Exception as e:
                failure_logger.log_exception(fixture, e)
                errors.append(f"{fixture.id}: Exception - {e}")

        if errors:
            pytest.fail("Reasoning quality errors:\n" + "\n".join(errors))
