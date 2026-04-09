"""Software and technology listing personas."""

from __future__ import annotations

from nohiki.common.v1 import JobBoardSource, SeniorityLevel, WorkArrangement

from nohiki_test_utils.sample_data._common import (
    build_listing_snapshot,
    make_compensation_range,
    make_location,
    make_remote_location,
)
from nohiki_test_utils.sample_data._ids import (
    LISTING_DATA_SCIENTIST_REMOTE_ID,
    LISTING_DEVOPS_ENGINEER_HYBRID_ID,
    LISTING_JUNIOR_FRONTEND_HYBRID_ID,
    LISTING_MID_SOFTWARE_ONSITE_ID,
    LISTING_SENIOR_PYTHON_REMOTE_ID,
    LISTING_STAFF_PLATFORM_ONSITE_ID,
)
from nohiki_test_utils.sample_data._types import ListingPersonaSpec
from nohiki_test_utils.sample_data.raw_postings.software import (
    DATA_SCIENTIST_REMOTE_POSTING,
    DEVOPS_ENGINEER_HYBRID_POSTING,
    JUNIOR_FRONTEND_HYBRID_POSTING,
    MID_SOFTWARE_ONSITE_POSTING,
    SENIOR_PYTHON_REMOTE_POSTING,
    STAFF_PLATFORM_HYBRID_POSTING,
)

SENIOR_PYTHON_REMOTE = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_SENIOR_PYTHON_REMOTE_ID,
        listing_url="https://jobs.cascadeinfrastructurelabs.com/senior-python-engineer",
        source=JobBoardSource.LINKEDIN,
        title="Senior Python Engineer",
        company_name="Cascade Infrastructure Labs",
        description=SENIOR_PYTHON_REMOTE_POSTING.simulate_enrichment(),
        location_raw="Remote - United States",
        location=make_remote_location(),
        work_arrangement=WorkArrangement.REMOTE,
        seniority_level=SeniorityLevel.SENIOR,
        required_skills=[
            "Python",
            "FastAPI",
            "Kafka",
            "PostgreSQL",
            "Redis",
            "Docker",
            "Kubernetes",
            "OpenTelemetry",
        ],
        compensation=make_compensation_range(15000000, 18000000),
        experience_years_min=5,
        experience_years_max=10,
    )
)

JUNIOR_FRONTEND_HYBRID = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_JUNIOR_FRONTEND_HYBRID_ID,
        listing_url="https://jobs.pixelharbor.io/junior-frontend-developer",
        source=JobBoardSource.INDEED,
        title="Junior Frontend Developer",
        company_name="Pixel Harbor Studio",
        description=JUNIOR_FRONTEND_HYBRID_POSTING.simulate_enrichment(),
        location_raw="San Francisco, CA (Hybrid)",
        location=make_location("San Francisco", "CA"),
        work_arrangement=WorkArrangement.HYBRID,
        seniority_level=SeniorityLevel.ENTRY,
        required_skills=[
            "React",
            "TypeScript",
            "CSS",
            "Tailwind CSS",
            "Jest",
            "Accessibility",
        ],
        compensation=make_compensation_range(8000000, 10000000),
        experience_years_min=0,
        experience_years_max=2,
    )
)

STAFF_PLATFORM_HYBRID = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_STAFF_PLATFORM_ONSITE_ID,
        listing_url="https://careers.nimbusdata.com/staff-platform-swe",
        source=JobBoardSource.LINKEDIN,
        title="Staff Software Engineer, Platform Infrastructure",
        company_name="Nimbus Data Systems",
        description=STAFF_PLATFORM_HYBRID_POSTING.simulate_enrichment(),
        location_raw="San Francisco, CA",
        location=make_location("San Francisco", "CA"),
        work_arrangement=WorkArrangement.HYBRID,
        seniority_level=SeniorityLevel.STAFF,
        required_skills=[
            "Python",
            "Go",
            "Terraform",
            "Kubernetes",
            "AWS",
            "PostgreSQL",
            "Service Mesh",
            "SRE",
        ],
        compensation=make_compensation_range(20000000, 25000000),
        experience_years_min=8,
        experience_years_max=15,
    )
)

DATA_SCIENTIST_REMOTE = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_DATA_SCIENTIST_REMOTE_ID,
        listing_url="https://jobs.signalpath.ai/data-scientist",
        source=JobBoardSource.LINKEDIN,
        title="Data Scientist",
        company_name="SignalPath AI",
        description=DATA_SCIENTIST_REMOTE_POSTING.simulate_enrichment(),
        location_raw="Remote - USA",
        location=make_remote_location(),
        work_arrangement=WorkArrangement.REMOTE,
        seniority_level=SeniorityLevel.MID,
        required_skills=[
            "Python",
            "Pandas",
            "SQL",
            "LightGBM",
            "A/B Testing",
            "Feature Engineering",
            "Statistics",
        ],
        compensation=make_compensation_range(13000000, 16000000),
        experience_years_min=3,
        experience_years_max=7,
    )
)

DEVOPS_ENGINEER_HYBRID = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_DEVOPS_ENGINEER_HYBRID_ID,
        listing_url="https://careers.westerngrid.com/devops-engineer",
        source=JobBoardSource.INDEED,
        title="DevOps Engineer",
        company_name="Western Grid Technologies",
        description=DEVOPS_ENGINEER_HYBRID_POSTING.simulate_enrichment(),
        location_raw="Seattle, WA (Hybrid)",
        location=make_location("Seattle", "WA"),
        work_arrangement=WorkArrangement.HYBRID,
        seniority_level=SeniorityLevel.MID,
        required_skills=[
            "Kubernetes",
            "Terraform",
            "GitHub Actions",
            "Docker",
            "AWS",
            "Linux",
            "Prometheus",
            "Incident Response",
        ],
        compensation=make_compensation_range(14000000, 17000000),
        experience_years_min=4,
        experience_years_max=8,
    )
)

MID_SOFTWARE_ONSITE = build_listing_snapshot(
    ListingPersonaSpec(
        entity_id=LISTING_MID_SOFTWARE_ONSITE_ID,
        listing_url="https://jobs.metroenterprise.com/software-engineer",
        source=JobBoardSource.LINKEDIN,
        title="Software Engineer",
        company_name="Metro Enterprise Platforms",
        description=MID_SOFTWARE_ONSITE_POSTING.simulate_enrichment(),
        location_raw="New York, NY",
        location=make_location("New York", "NY"),
        work_arrangement=WorkArrangement.ON_SITE,
        seniority_level=SeniorityLevel.MID,
        required_skills=["Java", "Spring Boot", "Microservices", "PostgreSQL", "REST APIs"],
        compensation=make_compensation_range(11500000, 14500000),
        experience_years_min=3,
        experience_years_max=6,
    )
)

__all__ = [
    "DATA_SCIENTIST_REMOTE",
    "DEVOPS_ENGINEER_HYBRID",
    "JUNIOR_FRONTEND_HYBRID",
    "MID_SOFTWARE_ONSITE",
    "SENIOR_PYTHON_REMOTE",
    "STAFF_PLATFORM_HYBRID",
]
