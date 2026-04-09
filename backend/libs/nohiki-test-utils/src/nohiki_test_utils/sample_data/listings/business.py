"""Business-domain listing personas."""

from __future__ import annotations

from nohiki.common.v1 import JobBoardSource, SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_listing_snapshot,
    make_compensation_range,
    make_location,
    make_remote_location,
)
from nohiki_test_utils.sample_data._ids import (
    LISTING_FINANCIAL_ANALYST_HYBRID_ID,
    LISTING_HR_DIRECTOR_ONSITE_ID,
    LISTING_MARKETING_MANAGER_REMOTE_ID,
)
from nohiki_test_utils.sample_data._types import ListingPersonaSpec
from nohiki_test_utils.sample_data.raw_postings.business import (
    FINANCIAL_ANALYST_HYBRID_POSTING,
    HR_DIRECTOR_HYBRID_POSTING,
    MARKETING_MANAGER_REMOTE_POSTING,
)

FINANCIAL_ANALYST_HYBRID = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_FINANCIAL_ANALYST_HYBRID_ID,
        listing_url="https://careers.harborcapitalgroup.com/financial-analyst",
        source=JobBoardSource.LINKEDIN,
        title="Financial Analyst",
        company_name="Harbor Capital Group",
        description=FINANCIAL_ANALYST_HYBRID_POSTING.simulate_enrichment(),
        location_raw="New York, NY (Hybrid)",
        location=make_location("New York", "NY"),
        work_arrangement=WorkArrangement.HYBRID,
        seniority_level=SeniorityLevel.MID,
        required_skills=[
            "Financial Modeling",
            "Variance Analysis",
            "Excel",
            "SQL",
            "Budget Planning",
            "Executive Reporting",
        ],
        compensation=make_compensation_range(9000000, 12000000),
        experience_years_min=3,
        experience_years_max=7,
    )
)

MARKETING_MANAGER_REMOTE = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_MARKETING_MANAGER_REMOTE_ID,
        listing_url="https://jobs.aurorabrand.com/marketing-manager",
        source=JobBoardSource.LINKEDIN,
        title="Marketing Manager",
        company_name="Aurora Brand Collective",
        description=MARKETING_MANAGER_REMOTE_POSTING.simulate_enrichment(),
        location_raw="Remote - United States",
        location=make_remote_location(),
        work_arrangement=WorkArrangement.REMOTE,
        seniority_level=SeniorityLevel.SENIOR,
        required_skills=[
            "Campaign Strategy",
            "Paid Media",
            "Marketing Analytics",
            "A/B Testing",
            "Content Marketing",
            "CRM Automation",
        ],
        compensation=make_compensation_range(10000000, 13000000),
        experience_years_min=5,
        experience_years_max=10,
    )
)

HR_DIRECTOR_HYBRID = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_HR_DIRECTOR_ONSITE_ID,
        listing_url="https://careers.atlantaworks.com/director-hr",
        source=JobBoardSource.INDEED,
        title="Director of Human Resources",
        company_name="Atlanta Works Manufacturing",
        description=HR_DIRECTOR_HYBRID_POSTING.simulate_enrichment(),
        location_raw="Atlanta, GA",
        location=make_location("Atlanta", "GA"),
        work_arrangement=WorkArrangement.HYBRID,
        seniority_level=SeniorityLevel.DIRECTOR,
        required_skills=[
            "HR Compliance",
            "Workforce Planning",
            "Talent Acquisition",
            "Performance Management",
            "Employee Relations",
        ],
        compensation=make_compensation_range(13000000, 16000000),
        experience_years_min=8,
        experience_years_max=15,
    )
)

__all__ = ["FINANCIAL_ANALYST_HYBRID", "HR_DIRECTOR_HYBRID", "MARKETING_MANAGER_REMOTE"]
