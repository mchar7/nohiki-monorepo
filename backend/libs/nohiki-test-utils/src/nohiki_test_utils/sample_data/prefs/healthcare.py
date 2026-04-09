"""Healthcare search preference personas."""

from __future__ import annotations

from nohiki.common.v1 import SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_search_pref_snapshot,
    make_location,
)
from nohiki_test_utils.sample_data._ids import (
    PREF_EXPERIENCED_NURSE_ID,
    USER_HEALTHCARE_ID,
)
from nohiki_test_utils.sample_data._types import PrefPersonaSpec

EXPERIENCED_NURSE_PREF = build_search_pref_snapshot(
    PrefPersonaSpec(
        entity_id=PREF_EXPERIENCED_NURSE_ID,
        user_id=USER_HEALTHCARE_ID,
        pref_name="Registered Nurse Positions",
        search_keywords=[
            "registered nurse",
            "rn",
            "nursing",
            "patient care",
            "icu",
            "critical care",
            "hospital",
        ],
        disallowed_keywords=["lpn", "cna", "travel nurse"],
        physical_locations=[
            make_location("Houston", "TX"),
            make_location("Dallas", "TX"),
            make_location("Austin", "TX"),
        ],
        remote_locations=[],
        work_arrangements=[WorkArrangement.ON_SITE],
        open_to_relocation=True,
        experience_years=5,
        seniority_levels=[SeniorityLevel.MID, SeniorityLevel.SENIOR],
        min_salary_minor_units=6000000,
        target_salary_minor_units=7500000,
        user_skill_names=[
            "Patient Care",
            "Critical Care",
            "ICU",
            "Emergency Medicine",
            "Medication Administration",
            "Electronic Health Records",
            "ACLS",
            "BLS",
        ],
    )
)
