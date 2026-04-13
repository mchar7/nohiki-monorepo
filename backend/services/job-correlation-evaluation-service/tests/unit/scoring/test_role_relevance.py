"""Behavioral contracts for deterministic role relevance and mismatch scoring."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest
from job_correlation_evaluation_service.services.scoring.features.base import FactorName, FeatureComposition
from job_correlation_evaluation_service.services.scoring.features.role_relevance import role_relevance
from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import _score_composition
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot


def _profile(*keywords: str, pref_name: str = "") -> SearchPrefSnapshot:
    return cast(SearchPrefSnapshot, SimpleNamespace(search_keywords=list(keywords), pref_name=pref_name))


def _listing(title: str) -> ListingSnapshot:
    return cast(ListingSnapshot, SimpleNamespace(title=title))


@pytest.mark.parametrize(
    ("case", "keywords", "pref_name", "title", "expected"),
    [
        ("direct phrase", ("Data Analyst", "Python"), "", "Data Analyst", 1.0),
        ("reordered tokens", ("Data Analyst",), "", "Analyst Data", 1.0),
        ("seniority stripping", ("Senior Data Analyst",), "", "Data Analyst", 1.0),
        ("partial adjacent title", ("Data Analyst",), "", "Data Scientist", 0.5),
        ("unrelated occupation", ("Data Analyst",), "", "Registered Nurse", 0.0),
        ("punctuation and case", ("data-analyst",), "", "SENIOR, DATA ANALYST!", 1.0),
        (
            "first role phrase wins over later skill",
            ("Data Analyst", "Python"),
            "",
            "Python Developer",
            0.0,
        ),
        ("legacy pref name fallback", (), "Data Analyst", "Senior Data Analyst", 1.0),
        ("empty profile", (), "", "Data Analyst", None),
        ("skill-only search terms", ("Python", "SQL"), "", "Python Developer", None),
        ("single-token occupation remains a skill term", ("Nurse",), "", "Nurse", None),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_role_relevance_normalizes_role_intent(
    case: str,
    keywords: tuple[str, ...],
    pref_name: str,
    title: str,
    expected: float | None,
) -> None:
    """Role identity uses only the first ordered role-shaped search term."""
    result = role_relevance(_listing(title), _profile(*keywords, pref_name=pref_name))

    if expected is None:
        assert result is None, case
    else:
        assert result == pytest.approx(expected), case


@pytest.mark.parametrize(
    ("case", "profile", "title"),
    [
        ("missing profile fields", SimpleNamespace(), "Data Analyst"),
        (
            "none profile fields",
            SimpleNamespace(search_keywords=None, pref_name=None),
            "Data Analyst",
        ),
        (
            "non-string profile fields",
            SimpleNamespace(search_keywords=[object()], pref_name=object()),
            "Data Analyst",
        ),
        ("non-string title", SimpleNamespace(search_keywords=["Data Analyst"], pref_name=""), None),
    ],
)
def test_malformed_role_inputs_fall_back_to_no_role(case: str, profile: SimpleNamespace, title: object) -> None:
    """Malformed role fields must not crash scoring or invent role intent."""
    listing = cast(ListingSnapshot, SimpleNamespace(title=title))

    result = role_relevance(listing, cast(SearchPrefSnapshot, profile))

    assert result is None, case


def _importance_profile() -> SearchPrefSnapshot:
    return cast(
        SearchPrefSnapshot,
        SimpleNamespace(
            feature_importance=SimpleNamespace(
                skill_match_importance=100,
                location_importance=100,
            )
        ),
    )


def _composition(*, role: float | None, **factors: float) -> FeatureComposition:
    return FeatureComposition(
        raw_features=np.array([0.25, math.nan], dtype=np.float32),
        factor_scores=cast(dict[FactorName, float], factors),
        role_relevance=role,
    )


def test_explicit_role_mismatch_suppresses_favorable_preferences() -> None:
    """A known title mismatch cannot be rescued by additive preference factors."""
    result = _score_composition(
        "job",
        maxsim_score=0.6,
        rerank_score=0.0,
        composition=_composition(role=0.0, skills=1.0, location=1.0),
        profile=_importance_profile(),
    )

    assert result.rank_index == pytest.approx(0.3)
    assert result.final_score == 30
    assert [(factor.name, factor.compatibility) for factor in result.factor_attributions] == [
        ("skills", 1.0),
        ("location", 1.0),
    ]


def test_partial_role_overlap_preserves_semantic_adjacency() -> None:
    """A non-zero adjacent title remains rankable while a zero-overlap title does not."""
    adjacent = _score_composition(
        "adjacent",
        maxsim_score=0.6,
        rerank_score=0.0,
        composition=_composition(role=0.5, skills=1.0),
        profile=_importance_profile(),
    )
    mismatch = _score_composition(
        "mismatch",
        maxsim_score=0.6,
        rerank_score=0.0,
        composition=_composition(role=0.0, skills=1.0),
        profile=_importance_profile(),
    )

    assert adjacent.role_relevance_raw == pytest.approx(50.0)
    assert adjacent.rank_index > mismatch.rank_index
    assert adjacent.final_score > mismatch.final_score


def test_no_role_intent_preserves_legacy_preference_scoring() -> None:
    """Skill-only profiles keep the pre-role weighted formula instead of triggering mismatch handling."""
    result = _score_composition(
        "job",
        maxsim_score=0.6,
        rerank_score=0.0,
        composition=_composition(role=None, skills=1.0),
        profile=_importance_profile(),
    )

    expected = (0.6 + (1.0 / 6.0)) / (1.0 + (1.0 / 6.0))
    assert result.rank_index == pytest.approx(expected)
    assert result.final_score == 66
    assert result.role_relevance_raw == pytest.approx(60.0)
