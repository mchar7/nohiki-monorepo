"""Business and finance search preference personas."""

from __future__ import annotations

from nohiki.common.v1 import SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_search_pref_snapshot,
    make_location,
    make_remote_location,
)
from nohiki_test_utils.sample_data._ids import (
    PREF_FINANCE_ANALYST_ID,
    USER_FINANCE_ID,
)
from nohiki_test_utils.sample_data._types import PrefPersonaSpec

FINANCE_ANALYST_PREF = build_search_pref_snapshot(
    PrefPersonaSpec(
        entity_id=PREF_FINANCE_ANALYST_ID,
        user_id=USER_FINANCE_ID,
        pref_name="Financial Analyst Roles",
        search_keywords=[
            "financial analyst",
            "finance",
            "analyst",
            "financial modeling",
            "excel",
            "accounting",
        ],
        disallowed_keywords=["senior", "director", "manager"],
        physical_locations=[
            make_location("New York", "NY"),
            make_location("Chicago", "IL"),
            make_location("Boston", "MA"),
        ],
        remote_locations=[make_remote_location()],
        work_arrangements=[WorkArrangement.HYBRID, WorkArrangement.ON_SITE],
        open_to_relocation=False,
        experience_years=3,
        seniority_levels=[SeniorityLevel.MID],
        min_salary_minor_units=8000000,
        target_salary_minor_units=10000000,
        user_skill_names=[
            "Financial Modeling",
            "Excel",
            "Financial Analysis",
            "Accounting",
            "SQL",
            "PowerPoint",
            "Tableau",
            "Python",
        ],
    )
)
