"""Negative control for malformed profile input."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import (
    DeterministicFinalStage,
)
from job_correlation_evaluation_service.services.scoring.stages.llm_rerank import (
    RerankCandidate,
)
from nohiki.common.v1 import (
    Compensation,
    ExperiencePreference,
    Location,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot

from .evaluator import load_fixture

FIXTURE = Path(__file__).parent / "fixtures" / "data_analyst_48.v1.json"
ACTIONABLE_THRESHOLD = 70


def test_gibberish_profile_does_not_produce_actionable_scores() -> None:
    fixture = load_fixture(FIXTURE)
    profile = SearchPrefSnapshot(
        id="negative-control",
        user_id="negative-control-user",
        pref_name="Sanitized nonsense query",
        search_keywords=["hyfr qzpt"],
        work_arrangements=[WorkArrangement.REMOTE],
        experience_preference=ExperiencePreference(
            experience_years=0,
            seniority_levels=[SeniorityLevel.MID],
        ),
    )
    listings: dict[str, ListingSnapshot] = {}
    candidates: list[RerankCandidate] = []
    for data in fixture["candidates"]:
        fixture_id = data["fixture_id"]
        listings[fixture_id] = ListingSnapshot(
            id=fixture_id,
            listing_url=f"https://quality.invalid/{fixture_id}",
            title=data["title"],
            company_name="Sanitized employer",
            description=data["description"],
            location=Location.from_dict(data["location"]),
            work_arrangement=WorkArrangement[data["work_arrangement"]],
            seniority_level=SeniorityLevel[data["seniority_level"]],
            required_skills=data["required_skills"],
            experience_years_min=data["min_experience_years"],
            experience_years_max=data["max_experience_years"],
            compensation=Compensation.from_dict(data["compensation"]) if data["compensation"] else None,
            posted_at=datetime.fromisoformat(data["posted_at"]) if data["posted_at"] else None,
            discovered_at=datetime(2026, 7, 11, tzinfo=UTC),
        )
        candidates.append(
            RerankCandidate(
                entity_id=fixture_id,
                maxsim_score=data["legacy_document_mode_semantic_score"],
                rerank_score=0.0,
                payload={},
            )
        )

    scored = DeterministicFinalStage.create().score_batch(candidates, listings, profile)
    actionable = [result for result in scored if result.final_score >= ACTIONABLE_THRESHOLD]
    assert not actionable, "underspecified gibberish profile produced actionable ranking indices: " + ", ".join(
        f"{result.entity_id}={result.final_score}" for result in actionable[:10]
    )
