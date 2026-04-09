"""Shared sample-data types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from nohiki.common.v1 import (
    Compensation,
    JobBoardSource,
    Location,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot

type TransformFn = Callable[[str], str]


@dataclass(frozen=True, slots=True)
class RawJobPosting:
    """Raw scraped job posting text with enrichment simulation capability.

    Holds the unmodified scraper output alongside a transform pipeline that
    mimics what the LLM enrichment step produces when cleaning the description.

    Use ``.raw`` for ``DiscoveredListing`` construction: benchmark and eval
    dataset inputs that are fed directly to the LLM.
    Use ``.simulate_enrichment()`` for ``ListingSnapshot.description``: curated
    listing personas representing the enriched domain model output.
    """

    raw: str
    enrichment_transforms: tuple[TransformFn, ...] = ()

    def simulate_enrichment(self) -> str:
        """Apply the enrichment transform pipeline and return cleaned text.

        Returns:
            Post-enrichment description with boilerplate and artifacts removed.
        """
        result = self.raw
        for transform in self.enrichment_transforms:
            result = transform(result)
        return result.strip()


@dataclass(frozen=True, slots=True)
class ListingPersonaSpec:
    """Input spec for constructing a listing persona."""

    entity_id: str
    listing_url: str
    source: JobBoardSource
    title: str
    company_name: str
    description: str
    location_raw: str
    location: Location
    work_arrangement: WorkArrangement
    seniority_level: SeniorityLevel
    required_skills: list[str]
    compensation: Compensation
    experience_years_min: int | None = None
    experience_years_max: int | None = None
    version: int = 1


@dataclass(frozen=True, slots=True)
class PrefPersonaSpec:
    """Input spec for constructing a search preference persona."""

    entity_id: str
    user_id: str
    pref_name: str
    search_keywords: list[str]
    disallowed_keywords: list[str]
    physical_locations: list[Location]
    remote_locations: list[Location]
    work_arrangements: list[WorkArrangement]
    open_to_relocation: bool
    experience_years: int
    seniority_levels: list[SeniorityLevel]
    min_salary_minor_units: int
    target_salary_minor_units: int
    user_skill_names: list[str]


@dataclass(frozen=True, slots=True)
class MatchScenario:
    """Pre-composed listing and preference pair for match-quality testing."""

    name: str
    listing: ListingSnapshot
    pref: SearchPrefSnapshot
    expected_quality: str
    expected_score_range: tuple[float, float]
    notes: str = ""
