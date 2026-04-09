"""Software engineering match scenarios for correlation testing."""

from __future__ import annotations

from nohiki_test_utils.sample_data._types import MatchScenario
from nohiki_test_utils.sample_data.listings.software import (
    DATA_SCIENTIST_REMOTE,
    DEVOPS_ENGINEER_HYBRID,
    JUNIOR_FRONTEND_HYBRID,
    SENIOR_PYTHON_REMOTE,
)
from nohiki_test_utils.sample_data.prefs.software import (
    BACKEND_ENGINEER_PREF,
    DATA_SCIENTIST_PREF,
    DEVOPS_ENGINEER_PREF,
    FRONTEND_DEVELOPER_PREF,
)

EXCELLENT_BACKEND_MATCH = MatchScenario(
    name="Excellent Backend Match",
    listing=SENIOR_PYTHON_REMOTE,
    pref=BACKEND_ENGINEER_PREF,
    expected_quality="excellent",
    expected_score_range=(0.85, 1.0),
    notes=(
        "Senior Python remote role perfectly aligns with backend engineer preferences. "
        "Strong skill overlap (Python, FastAPI, PostgreSQL, Redis, Kafka), "
        "remote work arrangement matches, seniority level appropriate, "
        "salary range overlaps significantly."
    ),
)

EXCELLENT_DATA_SCIENCE_MATCH = MatchScenario(
    name="Excellent Data Science Match",
    listing=DATA_SCIENTIST_REMOTE,
    pref=DATA_SCIENTIST_PREF,
    expected_quality="excellent",
    expected_score_range=(0.85, 1.0),
    notes=(
        "Data scientist remote role perfectly matches data science preferences. "
        "Strong ML/AI skill alignment (TensorFlow, PyTorch, Python), "
        "remote work matches preference, senior/staff seniority appropriate, "
        "compensation aligns well."
    ),
)

GOOD_FRONTEND_MATCH = MatchScenario(
    name="Good Frontend Match",
    listing=JUNIOR_FRONTEND_HYBRID,
    pref=FRONTEND_DEVELOPER_PREF,
    expected_quality="good",
    expected_score_range=(0.70, 0.84),
    notes=(
        "Junior frontend hybrid role is good but not perfect match. "
        "Skill alignment on React/TypeScript/JavaScript is strong, "
        "hybrid work arrangement matches, but junior seniority is below "
        "mid-level preference, and salary is at lower end of range."
    ),
)

GOOD_DEVOPS_MATCH = MatchScenario(
    name="Good DevOps Match",
    listing=DEVOPS_ENGINEER_HYBRID,
    pref=DEVOPS_ENGINEER_PREF,
    expected_quality="good",
    expected_score_range=(0.70, 0.84),
    notes=(
        "DevOps hybrid role matches most preferences well. "
        "Strong infrastructure/K8s/Docker skill alignment, "
        "hybrid work arrangement matches, seniority appropriate, "
        "but location (San Francisco) may not be in top preference cities."
    ),
)

POOR_MISMATCH_BACKEND_TO_FRONTEND = MatchScenario(
    name="Poor Mismatch: Backend Pref to Frontend Job",
    listing=JUNIOR_FRONTEND_HYBRID,
    pref=BACKEND_ENGINEER_PREF,
    expected_quality="poor",
    expected_score_range=(0.0, 0.40),
    notes=(
        "Backend engineer preference applied to frontend job is poor match. "
        "Skill mismatch (React/TypeScript vs Python/FastAPI), "
        "frontend keywords in disallowed list, junior seniority too low, "
        "salary below minimum threshold."
    ),
)

POOR_MISMATCH_FRONTEND_TO_BACKEND = MatchScenario(
    name="Poor Mismatch: Frontend Pref to Backend Job",
    listing=SENIOR_PYTHON_REMOTE,
    pref=FRONTEND_DEVELOPER_PREF,
    expected_quality="poor",
    expected_score_range=(0.0, 0.40),
    notes=(
        "Frontend developer preference applied to backend job is poor match. "
        "Skill mismatch (Python/FastAPI vs React/TypeScript), "
        "backend keywords in disallowed list, "
        "seniority mismatch (senior vs mid preference)."
    ),
)
