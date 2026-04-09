"""Skilled-trades listing personas."""

from __future__ import annotations

from nohiki.common.v1 import JobBoardSource, SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_listing_snapshot,
    make_compensation_range,
    make_location,
)
from nohiki_test_utils.sample_data._ids import (
    LISTING_ELECTRICIAN_ONSITE_ID,
    LISTING_HVAC_TECHNICIAN_ID,
)
from nohiki_test_utils.sample_data._types import ListingPersonaSpec
from nohiki_test_utils.sample_data.raw_postings.trades import (
    ELECTRICIAN_ONSITE_POSTING,
    HVAC_TECHNICIAN_POSTING,
)

ELECTRICIAN_ONSITE = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_ELECTRICIAN_ONSITE_ID,
        listing_url="https://jobs.suncrestfacilities.com/licensed-electrician",
        source=JobBoardSource.INDEED,
        title="Licensed Electrician",
        company_name="Suncrest Facilities Group",
        description=ELECTRICIAN_ONSITE_POSTING.simulate_enrichment(),
        location_raw="Austin, TX",
        location=make_location("Austin", "TX"),
        work_arrangement=WorkArrangement.ON_SITE,
        seniority_level=SeniorityLevel.MID,
        required_skills=[
            "Electrical Troubleshooting",
            "Blueprint Reading",
            "NEC Compliance",
            "Preventive Maintenance",
            "Panel Installation",
        ],
        compensation=make_compensation_range(5500000, 7500000),
        experience_years_min=3,
        experience_years_max=12,
    )
)

HVAC_TECHNICIAN = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_HVAC_TECHNICIAN_ID,
        listing_url="https://careers.desertairservices.com/hvac-tech",
        source=JobBoardSource.INDEED,
        title="HVAC Service Technician",
        company_name="Desert Air Services",
        description=HVAC_TECHNICIAN_POSTING.simulate_enrichment(),
        location_raw="Phoenix, AZ",
        location=make_location("Phoenix", "AZ"),
        work_arrangement=WorkArrangement.ON_SITE,
        seniority_level=SeniorityLevel.ENTRY,
        required_skills=[
            "HVAC Diagnostics",
            "EPA 608 Certification",
            "Preventive Maintenance",
            "Customer Service",
            "Equipment Installation",
        ],
        compensation=make_compensation_range(4000000, 5500000),
        experience_years_min=1,
        experience_years_max=4,
    )
)

__all__ = ["ELECTRICIAN_ONSITE", "HVAC_TECHNICIAN"]
