"""Integration test configuration for job-ingest-enrichment-service.

Provides pytest fixtures for:
- Job listing test fixtures built from centralized persona catalog
- Extraction output validators
- LLM extraction cache for efficiency
- Failure logging for model refinement

All shared utilities are exposed as pytest fixtures - tests receive them
via fixture injection, eliminating cross-directory imports.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Coroutine, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest
from nohiki.job.ingest.v1 import DiscoveredListing
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki_observability import get_logger
from nohiki_test_utils.sample_data import format_location_raw
from nohiki_test_utils.sample_data._types import RawJobPosting
from nohiki_test_utils.sample_data.listings import (
    DATA_SCIENTIST_REMOTE,
    DEVOPS_ENGINEER_HYBRID,
    DIRECTOR_ENGINEERING,
    ELECTRICIAN_ONSITE,
    FINANCIAL_ANALYST_HYBRID,
    HR_DIRECTOR_HYBRID,
    HVAC_TECHNICIAN,
    JUNIOR_FRONTEND_HYBRID,
    MARKETING_MANAGER_REMOTE,
    MID_SOFTWARE_ONSITE,
    NURSE_ICU_ONSITE,
    PHARMACIST_HYBRID,
    PHYSICAL_THERAPIST,
    SENIOR_PYTHON_REMOTE,
    STAFF_PLATFORM_HYBRID,
    VP_PRODUCT_REMOTE,
)
from nohiki_test_utils.sample_data.raw_postings import (
    DATA_SCIENTIST_REMOTE_POSTING,
    DEVOPS_ENGINEER_HYBRID_POSTING,
    DIRECTOR_ENGINEERING_POSTING,
    ELECTRICIAN_ONSITE_POSTING,
    FINANCIAL_ANALYST_HYBRID_POSTING,
    HR_DIRECTOR_HYBRID_POSTING,
    HVAC_TECHNICIAN_POSTING,
    JUNIOR_FRONTEND_HYBRID_POSTING,
    MARKETING_MANAGER_REMOTE_POSTING,
    MID_SOFTWARE_ONSITE_POSTING,
    NURSE_ICU_ONSITE_POSTING,
    PHARMACIST_HYBRID_POSTING,
    PHYSICAL_THERAPIST_POSTING,
    SENIOR_PYTHON_REMOTE_POSTING,
    STAFF_PLATFORM_HYBRID_POSTING,
    VP_PRODUCT_REMOTE_POSTING,
)
from pytest_unused_fixtures import ignore_unused_fixture

if TYPE_CHECKING:
    from job_ingest_enrichment_service.schemas import (
        CompensationEstimate,
        JobExtractionSchema,
    )

_logger = get_logger(__name__)

FAILURES_DIR = Path(__file__).parent / "failures"


# Job Listing Fixtures - Data Classes and Loading


@dataclass(frozen=True, slots=True)
class ExpectedValues:
    """Expected extraction values for validation."""

    seniority: str
    work_arrangement: str
    employment_term: str
    min_explicit: bool = False
    max_explicit: bool = False
    min_salary: int | None = None
    max_salary: int | None = None
    min_skills_count: int = 0
    industry: str = "unspecified"

    @property
    def has_any_explicit_compensation(self) -> bool:
        """Return True if either min or max is explicit."""
        return self.min_explicit or self.max_explicit

    @property
    def has_both_explicit_compensation(self) -> bool:
        """Return True if both min and max are explicit."""
        return self.min_explicit and self.max_explicit


@dataclass(frozen=True, slots=True)
class JobListingFixture:
    """A job listing test fixture with expected extraction values."""

    id: str
    listing: DiscoveredListing
    expected: ExpectedValues

    @property
    def title(self) -> str:
        """Convenience accessor for listing title."""
        return self.listing.title

    @property
    def company(self) -> str:
        """Convenience accessor for company name."""
        return self.listing.company_name

    @property
    def description(self) -> str:
        """Convenience accessor for description."""
        return self.listing.description

    @property
    def location_raw(self) -> str:
        """Convenience accessor for raw location."""
        return self.listing.location_raw

    @property
    def raw_skills(self) -> list[str]:
        """Convenience accessor for raw skills."""
        return list(self.listing.raw_skills)


@dataclass(frozen=True, slots=True)
class _PersonaEntry:
    """Associates a listing persona with its raw posting text and industry label."""

    fixture_id: str
    persona: ListingSnapshot
    raw_posting: RawJobPosting
    industry: str


def _build_discovered_listing(persona: ListingSnapshot, raw_description: str) -> DiscoveredListing:
    """Build a DiscoveredListing with raw posting text for extraction testing.

    Args:
        persona: Listing persona snapshot to source all metadata from.
        raw_description: Raw, unenriched posting text to use as the description.

    Returns:
        DiscoveredListing populated from persona fields with the raw description.
    """
    return DiscoveredListing(
        listing_url=persona.listing_url,
        source=persona.source,
        external_id=persona.id,
        title=persona.title,
        company_name=persona.company_name,
        description=raw_description,
        location_raw=format_location_raw(persona.location),
        raw_skills=list(persona.required_skills),
        compensation=persona.compensation,
        apply_url=persona.listing_url,
        company_url=None,
        discovered_timestamp=persona.discovered_at,
        posted_timestamp=persona.posted_at if persona.posted_at is not None else persona.discovered_at,
        content_hash=persona.raw_content_hash,
    )


def _build_expected_values(entry: _PersonaEntry) -> ExpectedValues:
    """Derive ExpectedValues from the persona's structured fields.

    Args:
        entry: The persona registry entry to derive values from.

    Returns:
        ExpectedValues populated from the persona's compensation and classification data.
    """
    comp = entry.persona.compensation
    min_amount = comp.min_amount if comp else None
    max_amount = comp.max_amount if comp else None
    return ExpectedValues(
        seniority=entry.persona.seniority_level.name,
        work_arrangement=entry.persona.work_arrangement.name,
        employment_term="FULL_TIME",
        min_explicit=True,
        max_explicit=True,
        min_salary=min_amount.amount.minor_units if min_amount else None,
        max_salary=max_amount.amount.minor_units if max_amount else None,
        min_skills_count=len(entry.persona.required_skills),
        industry=entry.industry,
    )


def _build_fixture(entry: _PersonaEntry) -> JobListingFixture:
    """Build a JobListingFixture from a persona registry entry.

    Args:
        entry: The persona registry entry to build from.

    Returns:
        JobListingFixture with the raw description and derived expected values.
    """
    return JobListingFixture(
        id=entry.fixture_id,
        listing=_build_discovered_listing(entry.persona, entry.raw_posting.raw),
        expected=_build_expected_values(entry),
    )


_PERSONA_REGISTRY: Final[tuple[_PersonaEntry, ...]] = (
    _PersonaEntry("senior_python_remote", SENIOR_PYTHON_REMOTE, SENIOR_PYTHON_REMOTE_POSTING, "software"),
    _PersonaEntry("junior_frontend_hybrid", JUNIOR_FRONTEND_HYBRID, JUNIOR_FRONTEND_HYBRID_POSTING, "software"),
    _PersonaEntry("staff_platform_hybrid", STAFF_PLATFORM_HYBRID, STAFF_PLATFORM_HYBRID_POSTING, "software"),
    _PersonaEntry("data_scientist_remote", DATA_SCIENTIST_REMOTE, DATA_SCIENTIST_REMOTE_POSTING, "software"),
    _PersonaEntry("devops_engineer_hybrid", DEVOPS_ENGINEER_HYBRID, DEVOPS_ENGINEER_HYBRID_POSTING, "software"),
    _PersonaEntry("mid_software_onsite", MID_SOFTWARE_ONSITE, MID_SOFTWARE_ONSITE_POSTING, "software"),
    _PersonaEntry("nurse_icu_onsite", NURSE_ICU_ONSITE, NURSE_ICU_ONSITE_POSTING, "healthcare"),
    _PersonaEntry("physical_therapist", PHYSICAL_THERAPIST, PHYSICAL_THERAPIST_POSTING, "healthcare"),
    _PersonaEntry("pharmacist_hybrid", PHARMACIST_HYBRID, PHARMACIST_HYBRID_POSTING, "healthcare"),
    _PersonaEntry("director_engineering", DIRECTOR_ENGINEERING, DIRECTOR_ENGINEERING_POSTING, "leadership"),
    _PersonaEntry("vp_product_remote", VP_PRODUCT_REMOTE, VP_PRODUCT_REMOTE_POSTING, "leadership"),
    _PersonaEntry("financial_analyst_hybrid", FINANCIAL_ANALYST_HYBRID, FINANCIAL_ANALYST_HYBRID_POSTING, "business"),
    _PersonaEntry("marketing_manager_remote", MARKETING_MANAGER_REMOTE, MARKETING_MANAGER_REMOTE_POSTING, "business"),
    _PersonaEntry("hr_director_hybrid", HR_DIRECTOR_HYBRID, HR_DIRECTOR_HYBRID_POSTING, "business"),
    _PersonaEntry("electrician_onsite", ELECTRICIAN_ONSITE, ELECTRICIAN_ONSITE_POSTING, "trades"),
    _PersonaEntry("hvac_technician", HVAC_TECHNICIAN, HVAC_TECHNICIAN_POSTING, "trades"),
)


class _FixtureCache:
    """Cached fixture storage with O(1) lookups by common attributes."""

    def __init__(self) -> None:
        self._all: list[JobListingFixture] | None = None
        self._by_id: dict[str, JobListingFixture] | None = None
        self._by_industry: dict[str, list[JobListingFixture]] | None = None
        self._by_seniority: dict[str, list[JobListingFixture]] | None = None
        self._by_work_arrangement: dict[str, list[JobListingFixture]] | None = None

    def _ensure_loaded(self) -> None:
        """Load and index all fixtures if not already cached."""
        if self._all is not None:
            return

        self._all = []
        self._by_id = {}
        self._by_industry = {}
        self._by_seniority = {}
        self._by_work_arrangement = {}

        for entry in _PERSONA_REGISTRY:
            fixture = _build_fixture(entry)
            self._all.append(fixture)
            self._by_id[fixture.id] = fixture
            self._index_fixture(fixture)

    def _index_fixture(self, fixture: JobListingFixture) -> None:
        """Add fixture to all index dictionaries."""
        industry = fixture.expected.industry
        seniority = fixture.expected.seniority
        work_arr = fixture.expected.work_arrangement

        if self._by_industry is not None:
            self._by_industry.setdefault(industry, []).append(fixture)
        if self._by_seniority is not None:
            self._by_seniority.setdefault(seniority, []).append(fixture)
        if self._by_work_arrangement is not None:
            self._by_work_arrangement.setdefault(work_arr, []).append(fixture)

    def get_all(self) -> list[JobListingFixture]:
        """Return all fixtures."""
        self._ensure_loaded()
        return self._all if self._all is not None else []

    def get_by_id(self, fixture_id: str) -> JobListingFixture | None:
        """O(1) lookup by fixture ID."""
        self._ensure_loaded()
        return self._by_id.get(fixture_id) if self._by_id else None

    def get_by_industry(self, industry: str) -> list[JobListingFixture]:
        """O(1) lookup by industry."""
        self._ensure_loaded()
        return self._by_industry.get(industry, []) if self._by_industry else []

    def get_by_seniority(self, seniority: str) -> list[JobListingFixture]:
        """O(1) lookup by seniority."""
        self._ensure_loaded()
        return self._by_seniority.get(seniority, []) if self._by_seniority else []

    def get_by_work_arrangement(self, work_arrangement: str) -> list[JobListingFixture]:
        """O(1) lookup by work arrangement."""
        self._ensure_loaded()
        return self._by_work_arrangement.get(work_arrangement, []) if self._by_work_arrangement else []


_fixture_cache = _FixtureCache()
_SENIOR_LEVELS: frozenset[str] = frozenset({"SENIOR", "STAFF", "PRINCIPAL", "DIRECTOR"})
_ENTRY_LEVELS: frozenset[str] = frozenset({"ENTRY", "INTERN"})


# Validators - Base Classes and Implementations


class ValidationSeverity(Enum):
    """Severity level for validation issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A single validation issue with context."""

    field: str
    message: str
    severity: ValidationSeverity
    expected: str | None = None
    actual: str | None = None


@dataclass
class ValidationResult:
    """Result of validating an extraction output."""

    validator_name: str
    fixture_id: str
    passed: bool = True
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_error(
        self,
        field_name: str,
        message: str,
        *,
        expected: str | None = None,
        actual: str | None = None,
    ) -> None:
        """Add an error-level issue and mark validation as failed."""
        self.issues.append(
            ValidationIssue(
                field=field_name,
                message=message,
                severity=ValidationSeverity.ERROR,
                expected=expected,
                actual=actual,
            )
        )
        self.passed = False

    def add_warning(
        self,
        field_name: str,
        message: str,
        *,
        expected: str | None = None,
        actual: str | None = None,
    ) -> None:
        """Add a warning-level issue (does not fail validation)."""
        self.issues.append(
            ValidationIssue(
                field=field_name,
                message=message,
                severity=ValidationSeverity.WARNING,
                expected=expected,
                actual=actual,
            )
        )

    def add_info(self, field_name: str, message: str) -> None:
        """Add an info-level observation."""
        self.issues.append(
            ValidationIssue(
                field=field_name,
                message=message,
                severity=ValidationSeverity.INFO,
            )
        )

    @property
    def error_count(self) -> int:
        """Count of error-level issues."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warning-level issues."""
        return sum(1 for i in self.issues if i.severity == ValidationSeverity.WARNING)

    def error_messages(self) -> list[str]:
        """Get all error messages."""
        return [i.message for i in self.issues if i.severity == ValidationSeverity.ERROR]


class BaseValidator:
    """Base class for extraction output validators."""

    name: str = "base"

    def validate(
        self,
        extraction: JobExtractionSchema,
        fixture: JobListingFixture,
    ) -> ValidationResult:
        """Validate extraction output against fixture expectations."""
        raise NotImplementedError


# Validator constants
_VALID_WORK_ARRANGEMENTS = frozenset({"REMOTE", "HYBRID", "ON_SITE", "UNSPECIFIED"})
_REMOTE_KEYWORDS = frozenset(
    {"remote", "work from home", "wfh", "fully distributed", "anywhere", "remote-first", "100% remote"}
)
_HYBRID_KEYWORDS = frozenset({"hybrid", "flexible", "days in office", "days onsite"})
_ONSITE_KEYWORDS = frozenset({"on-site", "onsite", "in-person", "in office"})

_VALID_SENIORITY_LEVELS = frozenset(
    {"INTERN", "ENTRY", "MID", "SENIOR", "STAFF", "PRINCIPAL", "DIRECTOR", "UNSPECIFIED"}
)
_SENIORITY_ADJACENT: dict[str, set[str]] = {
    "INTERN": {"ENTRY"},
    "ENTRY": {"INTERN", "MID"},
    "MID": {"ENTRY", "SENIOR"},
    "SENIOR": {"MID", "STAFF"},
    "STAFF": {"SENIOR", "PRINCIPAL"},
    "PRINCIPAL": {"STAFF", "DIRECTOR"},
    "DIRECTOR": {"PRINCIPAL"},
}
_TITLE_SENIORITY_KEYWORDS: dict[str, set[str]] = {
    "INTERN": {"intern", "internship"},
    "ENTRY": {"junior", "jr", "entry", "graduate", "associate"},
    "MID": set(),
    "SENIOR": {"senior", "sr", "lead"},
    "STAFF": {"staff"},
    "PRINCIPAL": {"principal", "distinguished", "fellow"},
    "DIRECTOR": {"director", "vp", "head of", "chief"},
}

_MIN_ANNUAL_SALARY_CENTS = 2000000
_MAX_ANNUAL_SALARY_CENTS = 100000000
_MIN_REASONING_LENGTH = 20
_MAX_RANGE_RATIO = 3.0
_SENIORITY_TOLERANCE_LOW = 0.5
_SENIORITY_TOLERANCE_HIGH = 1.5
_VALUE_TOLERANCE = 0.15
_VALID_COMP_SOURCES = frozenset({"employer_provided", "llm_inferred", "job_board_estimate"})
_SENIORITY_SALARY_RANGES_CENTS: dict[str, tuple[int, int]] = {
    "INTERN": (3000000, 12000000),
    "ENTRY": (3500000, 10000000),
    "MID": (6000000, 18000000),
    "SENIOR": (10000000, 30000000),
    "STAFF": (15000000, 40000000),
    "PRINCIPAL": (18000000, 50000000),
    "DIRECTOR": (20000000, 60000000),
}

_MIN_SKILLS_DETAILED = 3
_MAX_SKILLS = 50
_MIN_SKILL_NAME_LENGTH = 2
_MAX_SKILL_NAME_LENGTH = 100
_VALID_REQUIREMENT_LEVELS = frozenset({0, 1, 2, 3, 4})


class WorkArrangementValidator(BaseValidator):
    """Validates work arrangement extraction output."""

    name = "work_arrangement"

    def validate(
        self,
        extraction: JobExtractionSchema,
        fixture: JobListingFixture,
    ) -> ValidationResult:
        """Validate work arrangement extraction against fixture expectations."""
        result = ValidationResult(validator_name=self.name, fixture_id=fixture.id)
        actual = extraction.work_arrangement.name

        self._validate_enum_value(result, actual)
        self._validate_expected_match(result, actual, fixture)
        self._validate_description_consistency(result, actual, fixture)
        self._validate_location_consistency(result, actual, fixture)

        return result

    def _validate_enum_value(self, result: ValidationResult, actual: str) -> None:
        if actual not in _VALID_WORK_ARRANGEMENTS:
            result.add_error(
                "work_arrangement",
                f"Invalid work arrangement: {actual}",
                expected=str(_VALID_WORK_ARRANGEMENTS),
                actual=actual,
            )

    def _validate_expected_match(self, result: ValidationResult, actual: str, fixture: JobListingFixture) -> None:
        expected = fixture.expected.work_arrangement
        if actual == expected:
            return
        if expected == "UNSPECIFIED":
            result.add_info("work_arrangement", f"Extracted {actual} when UNSPECIFIED expected (acceptable)")
            return
        if actual == "UNSPECIFIED":
            result.add_warning(
                "work_arrangement",
                f"Could not determine work arrangement (expected {expected})",
                expected=expected,
                actual=actual,
            )
            return
        result.add_error(
            "work_arrangement",
            f"Work arrangement mismatch: expected {expected}, got {actual}",
            expected=expected,
            actual=actual,
        )

    def _validate_description_consistency(
        self, result: ValidationResult, actual: str, fixture: JobListingFixture
    ) -> None:
        desc_lower = fixture.description.lower()
        has_remote = any(kw in desc_lower for kw in _REMOTE_KEYWORDS)
        has_hybrid = any(kw in desc_lower for kw in _HYBRID_KEYWORDS)
        has_onsite = any(kw in desc_lower for kw in _ONSITE_KEYWORDS)

        if has_remote and actual not in ("REMOTE", "HYBRID"):
            result.add_warning(
                "work_arrangement",
                "Description contains remote keywords but extracted non-remote",
                expected="REMOTE or HYBRID",
                actual=actual,
            )
        if has_hybrid and actual != "HYBRID":
            result.add_info("work_arrangement", f"Description contains hybrid keywords but extracted {actual}")
        if has_onsite and actual == "REMOTE":
            result.add_warning(
                "work_arrangement",
                "Description contains on-site keywords but extracted REMOTE",
                expected="ON_SITE or HYBRID",
                actual=actual,
            )

    def _validate_location_consistency(self, result: ValidationResult, actual: str, fixture: JobListingFixture) -> None:
        location_lower = fixture.location_raw.lower()
        if "remote" in location_lower and actual not in ("REMOTE", "HYBRID"):
            result.add_warning(
                "work_arrangement",
                "Location indicates remote but extracted different arrangement",
                expected="REMOTE or HYBRID",
                actual=actual,
            )
        if not fixture.location_raw and actual == "ON_SITE":
            result.add_info("work_arrangement", "No location provided but extracted ON_SITE")


class SeniorityValidator(BaseValidator):
    """Validates seniority/experience level extraction."""

    name = "seniority"

    def validate(
        self,
        extraction: JobExtractionSchema,
        fixture: JobListingFixture,
    ) -> ValidationResult:
        result = ValidationResult(validator_name=self.name, fixture_id=fixture.id)
        actual_seniority = extraction.seniority_level.name

        self._validate_enum_value(result, actual_seniority)
        self._validate_expected_match(result, actual_seniority, fixture)
        self._validate_title_consistency(result, actual_seniority, fixture)

        return result

    def _validate_enum_value(self, result: ValidationResult, actual: str) -> None:
        if actual not in _VALID_SENIORITY_LEVELS:
            result.add_error(
                "seniority_level",
                f"Invalid seniority level: {actual}",
                expected=str(_VALID_SENIORITY_LEVELS),
                actual=actual,
            )

    def _validate_expected_match(self, result: ValidationResult, actual: str, fixture: JobListingFixture) -> None:
        expected = fixture.expected.seniority
        if actual == expected:
            return
        adjacent = _SENIORITY_ADJACENT.get(expected, set())
        if actual in adjacent:
            result.add_info("seniority_level", f"Extracted {actual} is adjacent to expected {expected} (acceptable)")
            return
        if expected == "UNSPECIFIED" or actual == "UNSPECIFIED":
            result.add_warning(
                "seniority_level",
                f"Seniority mismatch: expected {expected}, got {actual}",
                expected=expected,
                actual=actual,
            )
            return
        result.add_error(
            "seniority_level",
            f"Seniority mismatch: expected {expected}, got {actual}",
            expected=expected,
            actual=actual,
        )

    def _validate_title_consistency(self, result: ValidationResult, actual: str, fixture: JobListingFixture) -> None:
        title_lower = fixture.title.lower()
        for seniority, keywords in _TITLE_SENIORITY_KEYWORDS.items():
            if any(kw in title_lower for kw in keywords):
                if actual != seniority:
                    adjacent = _SENIORITY_ADJACENT.get(seniority, set())
                    if actual not in adjacent:
                        result.add_warning(
                            "seniority_level",
                            f"Title contains '{seniority}' keywords but extracted {actual}",
                            expected=seniority,
                            actual=actual,
                        )
                break


class SkillsValidator(BaseValidator):
    """Validates skills extraction output."""

    name = "skills"

    def validate(
        self,
        extraction: JobExtractionSchema,
        fixture: JobListingFixture,
    ) -> ValidationResult:
        result = ValidationResult(validator_name=self.name, fixture_id=fixture.id)
        skills = extraction.skills

        self._validate_skill_count(result, skills, fixture)
        self._validate_individual_skills(result, skills)
        self._validate_fixture_coverage(result, skills, fixture)
        self._validate_no_duplicates(result, skills)

        return result

    def _validate_skill_count(self, result: ValidationResult, skills: list, fixture: JobListingFixture) -> None:
        count = len(skills)
        if count == 0:
            if fixture.raw_skills:
                result.add_error(
                    "skills",
                    "No skills extracted but fixture has raw_skills",
                    expected=f">={len(fixture.raw_skills)}",
                    actual="0",
                )
            else:
                result.add_warning("skills", "No skills extracted (may be acceptable for vague listings)")
            return
        if count > _MAX_SKILLS:
            result.add_warning(
                "skills", f"Unusually high number of skills ({count})", expected=f"<={_MAX_SKILLS}", actual=str(count)
            )
        if fixture.raw_skills and count < _MIN_SKILLS_DETAILED:
            result.add_warning(
                "skills",
                f"Low skill count ({count}) for detailed listing",
                expected=f">={_MIN_SKILLS_DETAILED}",
                actual=str(count),
            )

    def _validate_individual_skills(self, result: ValidationResult, skills: list) -> None:
        for i, skill in enumerate(skills):
            skill_name = skill.raw_skill
            if not skill_name:
                result.add_error(f"skills[{i}].raw_skill", "Skill name is empty")
                continue
            if len(skill_name) < _MIN_SKILL_NAME_LENGTH:
                result.add_warning(
                    f"skills[{i}].raw_skill",
                    f"Skill name too short: {skill_name!r}",
                    expected=f">={_MIN_SKILL_NAME_LENGTH} chars",
                    actual=f"{len(skill_name)} chars",
                )
            if len(skill_name) > _MAX_SKILL_NAME_LENGTH:
                result.add_warning(
                    f"skills[{i}].raw_skill",
                    f"Skill name too long: {skill_name[:50]}...",
                    expected=f"<={_MAX_SKILL_NAME_LENGTH} chars",
                    actual=f"{len(skill_name)} chars",
                )
            req_level = skill.requirement_level
            if req_level not in _VALID_REQUIREMENT_LEVELS:
                result.add_error(
                    f"skills[{i}].requirement_level",
                    f"Invalid requirement level: {req_level}",
                    expected=str(_VALID_REQUIREMENT_LEVELS),
                    actual=str(req_level),
                )

    def _validate_fixture_coverage(self, result: ValidationResult, skills: list, fixture: JobListingFixture) -> None:
        if not fixture.raw_skills:
            return
        extracted_lower = {s.raw_skill.lower() for s in skills if s.raw_skill}
        missing = []
        for fixture_skill in fixture.raw_skills:
            fixture_lower = fixture_skill.lower()
            found = any(fixture_lower in extracted or extracted in fixture_lower for extracted in extracted_lower)
            if not found:
                missing.append(fixture_skill)
        if missing:
            coverage = 1 - (len(missing) / len(fixture.raw_skills))
            if coverage < 0.5:
                result.add_error(
                    "skills_coverage",
                    f"Low coverage of fixture skills: {coverage:.0%}",
                    expected=">=50% coverage",
                    actual=f"{coverage:.0%} (missing: {', '.join(missing)})",
                )
            elif coverage < 0.8:
                result.add_warning(
                    "skills_coverage",
                    f"Incomplete coverage of fixture skills: {coverage:.0%}",
                    expected=">=80% coverage",
                    actual=f"{coverage:.0%} (missing: {', '.join(missing)})",
                )

    def _validate_no_duplicates(self, result: ValidationResult, skills: list) -> None:
        seen: set[str] = set()
        duplicates: list[str] = []
        for skill in skills:
            name_lower = skill.raw_skill.lower() if skill.raw_skill else ""
            if name_lower in seen:
                duplicates.append(skill.raw_skill)
            seen.add(name_lower)
        if duplicates:
            result.add_warning("skills", f"Duplicate skills detected: {', '.join(duplicates)}")


class CompensationValidator(BaseValidator):
    """Validates compensation extraction output."""

    name = "compensation"

    def validate(
        self,
        extraction: JobExtractionSchema,
        fixture: JobListingFixture,
    ) -> ValidationResult:
        result = ValidationResult(validator_name=self.name, fixture_id=fixture.id)
        comp = extraction.compensation_estimate

        self._validate_basic_constraints(result, comp)
        self._validate_source(result, comp, fixture)
        self._validate_amount_consistency(result, comp)
        self._validate_reasoning(result, comp)
        self._validate_seniority_range(result, comp, fixture)
        self._validate_explicit_bounds(result, comp, fixture)

        return result

    def _validate_basic_constraints(self, result: ValidationResult, comp: CompensationEstimate) -> None:
        min_amount = comp.min_amount.amount
        max_amount = comp.max_amount.amount
        if min_amount <= 0:
            result.add_error(
                "min_amount", "Minimum compensation must be positive", expected=">0", actual=str(min_amount)
            )
        if min_amount < _MIN_ANNUAL_SALARY_CENTS:
            result.add_warning(
                "min_amount",
                f"Minimum salary {min_amount} is below typical minimum",
                expected=f">={_MIN_ANNUAL_SALARY_CENTS}",
                actual=str(min_amount),
            )
        if max_amount > _MAX_ANNUAL_SALARY_CENTS:
            result.add_warning(
                "max_amount",
                f"Maximum salary {max_amount} exceeds typical maximum",
                expected=f"<={_MAX_ANNUAL_SALARY_CENTS}",
                actual=str(max_amount),
            )

    def _validate_source(
        self, result: ValidationResult, comp: CompensationEstimate, fixture: JobListingFixture
    ) -> None:
        for bound, is_explicit, label in [
            (comp.min_amount, fixture.expected.min_explicit, "min"),
            (comp.max_amount, fixture.expected.max_explicit, "max"),
        ]:
            source = bound.source
            if source not in _VALID_COMP_SOURCES:
                result.add_error(
                    f"{label}_source",
                    f"Invalid {label} compensation source: {source}",
                    expected="employer_provided|llm_inferred|job_board_estimate",
                    actual=source,
                )
            elif is_explicit and source != "employer_provided":
                result.add_warning(
                    f"{label}_source",
                    f"Fixture has explicit {label} but source is not employer_provided",
                    expected="employer_provided",
                    actual=source,
                )
            elif not is_explicit and source == "employer_provided":
                result.add_warning(
                    f"{label}_source",
                    f"Fixture has no explicit {label} but source is employer_provided",
                    expected="llm_inferred or job_board_estimate",
                    actual=source,
                )

    def _validate_amount_consistency(self, result: ValidationResult, comp: CompensationEstimate) -> None:
        min_amount = comp.min_amount.amount
        max_amount = comp.max_amount.amount
        if max_amount < min_amount:
            result.add_error(
                "amount_range",
                "Maximum compensation is less than minimum",
                expected=f"max >= {min_amount}",
                actual=str(max_amount),
            )
        if max_amount > 0 and min_amount > 0:
            range_ratio = max_amount / min_amount
            if range_ratio > _MAX_RANGE_RATIO:
                result.add_warning(
                    "amount_range",
                    f"Compensation range is unusually wide (ratio: {range_ratio:.1f}x)",
                    expected=f"<{_MAX_RANGE_RATIO}x range",
                    actual=f"{range_ratio:.1f}x",
                )

    def _validate_reasoning(self, result: ValidationResult, comp: CompensationEstimate) -> None:
        reasoning = comp.reasoning
        if not reasoning:
            result.add_error(
                "reasoning", "Compensation reasoning is empty", expected="Non-empty reasoning", actual="(empty)"
            )
            return
        if len(reasoning) < _MIN_REASONING_LENGTH:
            result.add_warning(
                "reasoning",
                f"Compensation reasoning is too short ({len(reasoning)} chars)",
                expected=f">={_MIN_REASONING_LENGTH} chars",
                actual=f"{len(reasoning)} chars",
            )

    def _validate_seniority_range(
        self, result: ValidationResult, comp: CompensationEstimate, fixture: JobListingFixture
    ) -> None:
        expected_seniority = fixture.expected.seniority
        if expected_seniority not in _SENIORITY_SALARY_RANGES_CENTS:
            return
        min_expected, max_expected = _SENIORITY_SALARY_RANGES_CENTS[expected_seniority]
        min_amount = comp.min_amount.amount
        max_amount = comp.max_amount.amount
        if min_amount < min_expected * _SENIORITY_TOLERANCE_LOW:
            result.add_warning(
                "min_amount",
                f"Minimum salary {min_amount} is very low for {expected_seniority} level",
                expected=f">={min_expected * _SENIORITY_TOLERANCE_LOW}",
                actual=str(min_amount),
            )
        if max_amount > max_expected * _SENIORITY_TOLERANCE_HIGH:
            result.add_warning(
                "max_amount",
                f"Maximum salary {max_amount} is very high for {expected_seniority} level",
                expected=f"<={max_expected * _SENIORITY_TOLERANCE_HIGH}",
                actual=str(max_amount),
            )

    def _validate_explicit_bounds(
        self, result: ValidationResult, comp: CompensationEstimate, fixture: JobListingFixture
    ) -> None:
        for amount_val, is_explicit, expected_val, label in [
            (comp.min_amount.amount, fixture.expected.min_explicit, fixture.expected.min_salary, "min_amount"),
            (comp.max_amount.amount, fixture.expected.max_explicit, fixture.expected.max_salary, "max_amount"),
        ]:
            if not is_explicit or expected_val is None:
                continue
            tolerance = expected_val * _VALUE_TOLERANCE
            if abs(amount_val - expected_val) > tolerance:
                result.add_error(
                    label,
                    f"Extracted {label} does not match explicit fixture value",
                    expected=str(expected_val),
                    actual=str(amount_val),
                )


# Extraction Cache

_extraction_cache: dict[str, JobExtractionSchema] = {}


async def _get_extraction_impl(fixture: JobListingFixture) -> JobExtractionSchema:
    """Get cached extraction result or run extraction and cache it."""
    if fixture.id in _extraction_cache:
        _logger.debug("Cache HIT", fixture_id=fixture.id, cache_size=len(_extraction_cache))
        return _extraction_cache[fixture.id]

    _logger.info("Cache MISS - running LLM extraction", fixture_id=fixture.id)

    from job_ingest_enrichment_service.services.extraction_agent import run_extraction_agent

    result = await run_extraction_agent(fixture.listing)
    _extraction_cache[fixture.id] = result.output

    _logger.info("Extraction cached", fixture_id=fixture.id, cache_size=len(_extraction_cache))

    return _extraction_cache[fixture.id]


# Failure Logger


class FailureLogger:
    """Logs test failures to JSON files for analysis and model refinement."""

    def __init__(self, test_name: str) -> None:
        """Initialize failure logger for a specific test."""
        self._test_name = test_name
        self._failures: list[dict[str, object]] = []

    def log_extraction_failure(
        self,
        fixture: JobListingFixture,
        field_name: str,
        expected: object,
        actual: object,
        extraction: JobExtractionSchema | None = None,
    ) -> None:
        """Log a field-level extraction failure."""
        self._failures.append(
            {
                "type": "extraction",
                "fixture_id": fixture.id,
                "field": field_name,
                "expected": str(expected),
                "actual": str(actual),
                "fixture_title": fixture.title,
                "fixture_company": fixture.company,
                "full_extraction": extraction.model_dump() if extraction else None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def log_validation_failure(
        self,
        fixture: JobListingFixture,
        validator: str,
        issues: list[str],
        extraction: JobExtractionSchema | None = None,
    ) -> None:
        """Log a validation failure with multiple issues."""
        self._failures.append(
            {
                "type": "validation",
                "fixture_id": fixture.id,
                "validator": validator,
                "issues": issues,
                "fixture_title": fixture.title,
                "full_extraction": extraction.model_dump() if extraction else None,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def log_exception(self, fixture: JobListingFixture, error: Exception) -> None:
        """Log an exception during extraction."""
        self._failures.append(
            {
                "type": "exception",
                "fixture_id": fixture.id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "fixture_title": fixture.title,
                "timestamp": datetime.now(UTC).isoformat(),
            }
        )

    def save(self) -> Path | None:
        """Save failures to JSON file if any exist. Returns file path or None."""
        if not self._failures:
            return None

        FAILURES_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{self._test_name}_{timestamp}.json"
        filepath = FAILURES_DIR / filename

        output = {
            "test_name": self._test_name,
            "failures": self._failures,
            "total_failures": len(self._failures),
        }

        filepath.write_text(json.dumps(output, indent=2, default=str))
        return filepath

    @property
    def failure_count(self) -> int:
        """Return the number of logged failures."""
        return len(self._failures)


# Pytest Configuration


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "llm_cost: mark tests that make real LLM API calls (incurs costs)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Skip llm_cost tests by default unless explicitly requested."""
    marker_expr = config.getoption("-m", default="")
    has_llm_cost_marker = marker_expr and "llm_cost" in marker_expr

    if not has_llm_cost_marker:
        skip_marker = pytest.mark.skip(reason="LLM cost tests skipped by default. Use -m llm_cost to run.")
        for item in items:
            if "llm_cost" in item.keywords:
                item.add_marker(skip_marker)
        return


# Pytest Fixtures


# Type aliases for fixture callables
type ExtractionGetter = Callable[[JobListingFixture], Coroutine[None, None, JobExtractionSchema]]
type FixtureIterator = Callable[[], Iterator[JobListingFixture]]
type FixtureListGetter = Callable[[], list[JobListingFixture]]
type FixtureByAttributeGetter = Callable[[str], list[JobListingFixture]]


@pytest.fixture
@ignore_unused_fixture
def failure_logger(request: pytest.FixtureRequest) -> Iterator[FailureLogger]:
    """Provide a failure logger that auto-saves on teardown."""
    logger = FailureLogger(request.node.name)
    yield logger

    if saved_path := logger.save():
        _logger.warning(
            "Test failures logged",
            failure_count=logger.failure_count,
            file_path=str(saved_path),
        )


@pytest.fixture
@ignore_unused_fixture
def get_extraction() -> ExtractionGetter:
    """Provide the extraction cache getter function."""
    return _get_extraction_impl


@pytest.fixture
@ignore_unused_fixture
def iter_fixtures() -> FixtureIterator:
    """Provide an iterator over all fixtures."""

    def _iter() -> Iterator[JobListingFixture]:
        return iter(_fixture_cache.get_all())

    return _iter


@pytest.fixture
@ignore_unused_fixture
def load_all_fixtures() -> FixtureListGetter:
    """Provide function to load all fixtures."""
    return _fixture_cache.get_all


@pytest.fixture
@ignore_unused_fixture
def get_remote_listings() -> FixtureListGetter:
    """Provide function to get remote work fixtures."""

    def _get() -> list[JobListingFixture]:
        return _fixture_cache.get_by_work_arrangement("REMOTE")

    return _get


@pytest.fixture
@ignore_unused_fixture
def get_senior_listings() -> FixtureListGetter:
    """Provide function to get senior-level fixtures."""

    def _get() -> list[JobListingFixture]:
        result: list[JobListingFixture] = []
        for level in _SENIOR_LEVELS:
            result.extend(_fixture_cache.get_by_seniority(level))
        return result

    return _get


@pytest.fixture
@ignore_unused_fixture
def get_entry_level_listings() -> FixtureListGetter:
    """Provide function to get entry-level fixtures."""

    def _get() -> list[JobListingFixture]:
        result: list[JobListingFixture] = []
        for level in _ENTRY_LEVELS:
            result.extend(_fixture_cache.get_by_seniority(level))
        return result

    return _get


@pytest.fixture
@ignore_unused_fixture
def get_fixtures_by_industry() -> FixtureByAttributeGetter:
    """Provide function to get fixtures by industry."""
    return _fixture_cache.get_by_industry


@pytest.fixture
@ignore_unused_fixture
def get_fixtures_by_seniority() -> FixtureByAttributeGetter:
    """Provide function to get fixtures by seniority."""
    return _fixture_cache.get_by_seniority


@pytest.fixture
@ignore_unused_fixture
def get_fixtures_with_explicit_compensation() -> FixtureListGetter:
    """Provide function to get fixtures with explicit compensation."""

    def _get() -> list[JobListingFixture]:
        return [f for f in _fixture_cache.get_all() if f.expected.has_any_explicit_compensation]

    return _get


@pytest.fixture
@ignore_unused_fixture
def get_fixtures_without_explicit_compensation() -> FixtureListGetter:
    """Provide function to get fixtures without explicit compensation."""

    def _get() -> list[JobListingFixture]:
        return [f for f in _fixture_cache.get_all() if not f.expected.has_any_explicit_compensation]

    return _get


@pytest.fixture
@ignore_unused_fixture
def work_arrangement_validator() -> WorkArrangementValidator:
    """Provide work arrangement validator instance."""
    return WorkArrangementValidator()


@pytest.fixture
@ignore_unused_fixture
def seniority_validator() -> SeniorityValidator:
    """Provide seniority validator instance."""
    return SeniorityValidator()


@pytest.fixture
@ignore_unused_fixture
def skills_validator() -> SkillsValidator:
    """Provide skills validator instance."""
    return SkillsValidator()


@pytest.fixture
@ignore_unused_fixture
def compensation_validator() -> CompensationValidator:
    """Provide compensation validator instance."""
    return CompensationValidator()
