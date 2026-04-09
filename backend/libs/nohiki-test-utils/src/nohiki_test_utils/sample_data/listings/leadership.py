"""Leadership listing personas."""

from __future__ import annotations

from nohiki.common.v1 import JobBoardSource, SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_listing_snapshot,
    make_compensation_range,
    make_location,
    make_remote_location,
)
from nohiki_test_utils.sample_data._ids import (
    LISTING_DIRECTOR_ENGINEERING_ID,
    LISTING_VP_PRODUCT_REMOTE_ID,
)
from nohiki_test_utils.sample_data._types import ListingPersonaSpec
from nohiki_test_utils.sample_data.raw_postings.leadership import (
    DIRECTOR_ENGINEERING_POSTING,
    VP_PRODUCT_REMOTE_POSTING,
)

DIRECTOR_ENGINEERING = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_DIRECTOR_ENGINEERING_ID,
        listing_url="https://careers.lighthouseplatform.com/director-engineering",
        source=JobBoardSource.LINKEDIN,
        title="Director of Engineering",
        company_name="Lighthouse Platform Group",
        description=DIRECTOR_ENGINEERING_POSTING.simulate_enrichment(),
        location_raw="New York, NY (Hybrid)",
        location=make_location("New York", "NY"),
        work_arrangement=WorkArrangement.HYBRID,
        seniority_level=SeniorityLevel.DIRECTOR,
        required_skills=[
            "Engineering Leadership",
            "Organizational Design",
            "Distributed Systems",
            "Roadmap Planning",
            "Incident Management",
            "Mentorship",
        ],
        compensation=make_compensation_range(25000000, 30000000),
        experience_years_min=10,
        experience_years_max=20,
    )
)

VP_PRODUCT_REMOTE = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_VP_PRODUCT_REMOTE_ID,
        listing_url="https://jobs.northstarventures.com/vp-product",
        source=JobBoardSource.LINKEDIN,
        title="VP of Product",
        company_name="Northstar Ventures",
        description=VP_PRODUCT_REMOTE_POSTING.simulate_enrichment(),
        location_raw="Remote - United States",
        location=make_remote_location(),
        work_arrangement=WorkArrangement.REMOTE,
        seniority_level=SeniorityLevel.VP,
        required_skills=[
            "Product Strategy",
            "Portfolio Management",
            "Pricing",
            "Market Research",
            "Executive Communication",
            "Cross-functional Leadership",
        ],
        compensation=make_compensation_range(28000000, 35000000),
        experience_years_min=12,
        experience_years_max=25,
    )
)

__all__ = ["DIRECTOR_ENGINEERING", "VP_PRODUCT_REMOTE"]
