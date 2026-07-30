"""Permanent adversarial quality regression for Data Analyst ranking."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isclose
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

from .evaluator import (
    RankedItem,
    evaluate,
    failure_diagnostic,
    load_fixture,
    ndcg,
    percentile_nearest_rank,
    precision_at,
    reciprocal_rank,
)

FIXTURE = Path(__file__).parent / "fixtures" / "data_analyst_48.v1.json"


def test_metric_oracles() -> None:
    perfect = [3, 2, 2, 1, 0]
    assert ndcg(perfect, 5) == 1.0
    assert reciprocal_rank(perfect) == 1.0
    assert precision_at(perfect, 5) == 0.6
    assert isclose(ndcg(list(reversed(perfect)), 5), 0.5664478625498257)
    assert reciprocal_rank([0, 1, 3, 2]) == 1 / 3
    assert precision_at([3, 2, 0, 0, 0], 5) == 0.4
    assert percentile_nearest_rank(list(range(1, 11)), 0.1) == 1
    assert percentile_nearest_rank(list(range(1, 11)), 0.9) == 9


def test_fixture_is_complete_supported_and_immutable() -> None:
    fixture = load_fixture(FIXTURE)
    candidates = fixture["candidates"]
    assert len(candidates) == 48
    assert all(candidate["judgment"]["adjudication_status"] in {"agreed", "adjudicated"} for candidate in candidates)
    assert all(candidate["judgment"]["reviewer_a"] in range(4) for candidate in candidates)
    assert all(candidate["judgment"]["reviewer_b"] in range(4) for candidate in candidates)
    assert fixture["provenance"]["training_use_prohibited"] is True


def test_data_analyst_ranking_quality() -> None:
    fixture = load_fixture(FIXTURE)
    assert fixture["provenance"]["semantic_inputs_status"] == "ready", (
        "quality regression cannot run: corrected QUERY-mode semantic inputs are missing; "
        "legacy DOCUMENT-mode scores are negative-control data only"
    )
    profile_data = fixture["profile"]
    profile = SearchPrefSnapshot(
        id="quality-data-analyst",
        user_id="quality-user",
        pref_name="Data Analyst regression",
        search_keywords=profile_data["search_keywords"],
        physical_locations=[Location.from_dict(value) for value in profile_data["physical_locations"]],
        remote_locations=[Location.from_dict(value) for value in profile_data["remote_locations"]],
        open_to_relocation=profile_data["open_to_relocation"],
        work_arrangements=[WorkArrangement[value] for value in profile_data["work_arrangements"]],
        experience_preference=ExperiencePreference(
            experience_years=profile_data["experience_years"],
            seniority_levels=[SeniorityLevel[value] for value in profile_data["seniority_levels"]],
        ),
    )
    listings: dict[str, ListingSnapshot] = {}
    candidates: list[RerankCandidate] = []
    judgments: dict[str, tuple[str, int]] = {}
    for data in fixture["candidates"]:
        fixture_id = data["fixture_id"]
        semantic_score = data["semantic_score"]
        assert semantic_score is not None
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
                maxsim_score=semantic_score,
                rerank_score=0.0,
                payload={},
            )
        )
        judgments[fixture_id] = (data["title"], data["judgment"]["grade"])

    scored = DeterministicFinalStage.create().score_batch(candidates, listings, profile)
    items = [
        RankedItem(
            fixture_id=result.entity_id,
            title=judgments[result.entity_id][0],
            grade=judgments[result.entity_id][1],
            score=result.final_score,
            ranking_index=result.rank_index,
        )
        for result in scored
    ]
    report = evaluate(items)
    assert not report["violations"], failure_diagnostic(items, report)
