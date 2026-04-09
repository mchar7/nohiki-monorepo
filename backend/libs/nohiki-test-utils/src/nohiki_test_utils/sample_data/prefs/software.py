"""Software engineering search preference personas."""

from __future__ import annotations

from nohiki.common.v1 import SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_search_pref_snapshot,
    make_location,
    make_remote_location,
)
from nohiki_test_utils.sample_data._ids import (
    PREF_BACKEND_ENGINEER_ID,
    PREF_DATA_SCIENTIST_ID,
    PREF_DEVOPS_ENGINEER_ID,
    PREF_FRONTEND_DEVELOPER_ID,
    PREF_FULLSTACK_DEVELOPER_ID,
    USER_BACKEND_ENGINEER_ID,
    USER_DATA_SCIENTIST_ID,
    USER_DEVOPS_ENGINEER_ID,
    USER_FRONTEND_DEVELOPER_ID,
    USER_FULLSTACK_DEVELOPER_ID,
)
from nohiki_test_utils.sample_data._types import PrefPersonaSpec

KEYWORD_DATA_SCIENTIST = "data scientist"

BACKEND_ENGINEER_PREF = build_search_pref_snapshot(
    PrefPersonaSpec(
        entity_id=PREF_BACKEND_ENGINEER_ID,
        user_id=USER_BACKEND_ENGINEER_ID,
        pref_name="Backend Engineering Roles",
        search_keywords=["python", "backend", "api", "microservices", "fastapi", "django"],
        disallowed_keywords=["frontend", "react", "vue", "angular"],
        physical_locations=[
            make_location("San Francisco", "CA"),
            make_location("Seattle", "WA"),
            make_location("Austin", "TX"),
        ],
        remote_locations=[make_remote_location()],
        work_arrangements=[WorkArrangement.REMOTE, WorkArrangement.HYBRID],
        open_to_relocation=False,
        experience_years=5,
        seniority_levels=[SeniorityLevel.MID, SeniorityLevel.SENIOR],
        min_salary_minor_units=13000000,
        target_salary_minor_units=16000000,
        user_skill_names=[
            "Python",
            "FastAPI",
            "PostgreSQL",
            "Redis",
            "Kafka",
            "Docker",
            "Kubernetes",
            "AWS",
        ],
    )
)

FRONTEND_DEVELOPER_PREF = build_search_pref_snapshot(
    PrefPersonaSpec(
        entity_id=PREF_FRONTEND_DEVELOPER_ID,
        user_id=USER_FRONTEND_DEVELOPER_ID,
        pref_name="Frontend Development Positions",
        search_keywords=["react", "typescript", "frontend", "ui", "ux", "javascript"],
        disallowed_keywords=["backend", "devops", "data"],
        physical_locations=[
            make_location("New York", "NY"),
            make_location("Boston", "MA"),
        ],
        remote_locations=[make_remote_location()],
        work_arrangements=[WorkArrangement.REMOTE, WorkArrangement.HYBRID],
        open_to_relocation=False,
        experience_years=3,
        seniority_levels=[SeniorityLevel.MID],
        min_salary_minor_units=11000000,
        target_salary_minor_units=14000000,
        user_skill_names=[
            "React",
            "TypeScript",
            "JavaScript",
            "CSS",
            "HTML",
            "Tailwind CSS",
            "Next.js",
            "Vite",
        ],
    )
)

FULLSTACK_DEVELOPER_PREF = build_search_pref_snapshot(
    PrefPersonaSpec(
        entity_id=PREF_FULLSTACK_DEVELOPER_ID,
        user_id=USER_FULLSTACK_DEVELOPER_ID,
        pref_name="Full Stack Engineering",
        search_keywords=["fullstack", "full-stack", "react", "python", "node", "typescript"],
        disallowed_keywords=[KEYWORD_DATA_SCIENTIST, "machine learning"],
        physical_locations=[
            make_location("Denver", "CO"),
            make_location("Portland", "OR"),
        ],
        remote_locations=[make_remote_location()],
        work_arrangements=[WorkArrangement.REMOTE, WorkArrangement.HYBRID],
        open_to_relocation=True,
        experience_years=4,
        seniority_levels=[SeniorityLevel.MID, SeniorityLevel.SENIOR],
        min_salary_minor_units=12000000,
        target_salary_minor_units=15500000,
        user_skill_names=[
            "Python",
            "React",
            "TypeScript",
            "Node.js",
            "PostgreSQL",
            "Docker",
            "AWS",
        ],
    )
)

DATA_SCIENTIST_PREF = build_search_pref_snapshot(
    PrefPersonaSpec(
        entity_id=PREF_DATA_SCIENTIST_ID,
        user_id=USER_DATA_SCIENTIST_ID,
        pref_name="Data Science & ML Roles",
        search_keywords=[
            KEYWORD_DATA_SCIENTIST,
            "machine learning",
            "ml",
            "ai",
            "python",
            "tensorflow",
            "pytorch",
        ],
        disallowed_keywords=["frontend", "devops"],
        physical_locations=[
            make_location("San Francisco", "CA"),
            make_location("New York", "NY"),
        ],
        remote_locations=[make_remote_location()],
        work_arrangements=[WorkArrangement.REMOTE, WorkArrangement.HYBRID],
        open_to_relocation=False,
        experience_years=6,
        seniority_levels=[SeniorityLevel.SENIOR, SeniorityLevel.STAFF],
        min_salary_minor_units=15000000,
        target_salary_minor_units=19000000,
        user_skill_names=[
            "Python",
            "TensorFlow",
            "PyTorch",
            "Scikit-learn",
            "Pandas",
            "NumPy",
            "SQL",
            "Statistics",
        ],
    )
)

DEVOPS_ENGINEER_PREF = build_search_pref_snapshot(
    PrefPersonaSpec(
        entity_id=PREF_DEVOPS_ENGINEER_ID,
        user_id=USER_DEVOPS_ENGINEER_ID,
        pref_name="DevOps & Infrastructure",
        search_keywords=[
            "devops",
            "sre",
            "infrastructure",
            "kubernetes",
            "terraform",
            "ci/cd",
            "aws",
        ],
        disallowed_keywords=["frontend", KEYWORD_DATA_SCIENTIST],
        physical_locations=[
            make_location("Seattle", "WA"),
            make_location("Austin", "TX"),
        ],
        remote_locations=[make_remote_location()],
        work_arrangements=[WorkArrangement.REMOTE, WorkArrangement.HYBRID],
        open_to_relocation=False,
        experience_years=7,
        seniority_levels=[SeniorityLevel.SENIOR, SeniorityLevel.STAFF],
        min_salary_minor_units=14000000,
        target_salary_minor_units=18000000,
        user_skill_names=[
            "Kubernetes",
            "Docker",
            "Terraform",
            "AWS",
            "Python",
            "Bash",
            "CI/CD",
            "Prometheus",
        ],
    )
)
