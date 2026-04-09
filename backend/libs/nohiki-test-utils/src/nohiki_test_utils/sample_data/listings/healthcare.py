"""Healthcare listing personas."""

from __future__ import annotations

from nohiki.common.v1 import JobBoardSource, SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_listing_snapshot,
    make_compensation_range,
    make_location,
)
from nohiki_test_utils.sample_data._ids import (
    LISTING_NURSE_ICU_ONSITE_ID,
    LISTING_PHARMACIST_HYBRID_ID,
    LISTING_PHYSICAL_THERAPIST_ID,
)
from nohiki_test_utils.sample_data._types import ListingPersonaSpec
from nohiki_test_utils.sample_data.raw_postings.healthcare import (
    NURSE_ICU_ONSITE_POSTING,
    PHARMACIST_HYBRID_POSTING,
    PHYSICAL_THERAPIST_POSTING,
)

NURSE_ICU_ONSITE = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_NURSE_ICU_ONSITE_ID,
        listing_url="https://careers.meridianhealthsystems.com/rn-icu",
        source=JobBoardSource.INDEED,
        title="Registered Nurse, ICU",
        company_name="Meridian Health Systems",
        description=NURSE_ICU_ONSITE_POSTING.simulate_enrichment(),
        location_raw="Houston, TX",
        location=make_location("Houston", "TX"),
        work_arrangement=WorkArrangement.ON_SITE,
        seniority_level=SeniorityLevel.MID,
        required_skills=[
            "Critical Care Nursing",
            "BLS Certification",
            "ACLS Certification",
            "Epic EHR",
            "Patient Assessment",
            "Medication Administration",
        ],
        compensation=make_compensation_range(6500000, 8500000),
        experience_years_min=2,
        experience_years_max=8,
    )
)

PHYSICAL_THERAPIST = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_PHYSICAL_THERAPIST_ID,
        listing_url="https://jobs.bluemountainrehab.com/physical-therapist",
        source=JobBoardSource.INDEED,
        title="Physical Therapist",
        company_name="Blue Mountain Rehabilitation",
        description=PHYSICAL_THERAPIST_POSTING.simulate_enrichment(),
        location_raw="Denver, CO",
        location=make_location("Denver", "CO"),
        work_arrangement=WorkArrangement.ON_SITE,
        seniority_level=SeniorityLevel.MID,
        required_skills=[
            "Orthopedic Rehabilitation",
            "Manual Therapy",
            "Patient Education",
            "Care Planning",
            "Documentation",
        ],
        compensation=make_compensation_range(7000000, 9000000),
        experience_years_min=2,
        experience_years_max=7,
    )
)

PHARMACIST_HYBRID = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_PHARMACIST_HYBRID_ID,
        listing_url="https://careers.northsidecare.org/clinical-pharmacist",
        source=JobBoardSource.LINKEDIN,
        title="Clinical Pharmacist",
        company_name="Northside Care Network",
        description=PHARMACIST_HYBRID_POSTING.simulate_enrichment(),
        location_raw="Chicago, IL (Hybrid)",
        location=make_location("Chicago", "IL"),
        work_arrangement=WorkArrangement.HYBRID,
        seniority_level=SeniorityLevel.SENIOR,
        required_skills=[
            "Clinical Pharmacology",
            "Medication Therapy Management",
            "Formulary Development",
            "Cerner",
            "Interdisciplinary Rounds",
        ],
        compensation=make_compensation_range(12000000, 14000000),
        experience_years_min=5,
        experience_years_max=12,
    )
)

__all__ = ["NURSE_ICU_ONSITE", "PHARMACIST_HYBRID", "PHYSICAL_THERAPIST"]
