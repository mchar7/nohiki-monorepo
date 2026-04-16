"""Evaluation datasets for job extraction testing.

Provides test cases for evaluating LLM extraction accuracy with various
job posting types, locations, compensation structures, and skill sets.
"""

from __future__ import annotations

from typing import Final

from job_ingest_enrichment_service.schemas.extraction import (
    CompensationBoundEstimate,
    CompensationEstimate,
    ExperienceExtraction,
    ExperienceYearsBound,
    ExtractedSkill,
    JobExtractionSchema,
    LocationExtraction,
)
from nohiki.common.v1 import (
    CountryCode,
    CurrencyCode,
    EmploymentTerm,
    PaymentFrequency,
    SeniorityLevel,
    WorkArrangement,
)
from nohiki_test_utils.sample_data.listings import (
    DIRECTOR_ENGINEERING,
    MARKETING_MANAGER_REMOTE,
    SENIOR_PYTHON_REMOTE,
)
from nohiki_test_utils.sample_data.raw_postings import (
    DIRECTOR_ENGINEERING_POSTING,
    MARKETING_MANAGER_REMOTE_POSTING,
    SENIOR_PYTHON_REMOTE_POSTING,
)
from pydantic_evals import Case

# Constants for relation types (avoid magic string repetition)
RELATION_ESSENTIAL: Final[str] = "essential"
SOURCE_EMPLOYER: Final[str] = "employer_provided"
SOURCE_EXPLICIT: Final[str] = "explicit"

# Expected extraction results for validation
EXPECTED_SENIOR_PYTHON_REMOTE = JobExtractionSchema(
    cleaned_title=SENIOR_PYTHON_REMOTE.title,
    cleaned_company=SENIOR_PYTHON_REMOTE.company_name,
    location=LocationExtraction(
        city=None,
        state_province=None,
        country_code=CountryCode.USA,
        is_remote_eligible=True,
        confidence_percent=95,
    ),
    work_arrangement=WorkArrangement.REMOTE,
    employment_term=EmploymentTerm.FULL_TIME,
    seniority_level=SeniorityLevel.SENIOR,
    experience=ExperienceExtraction(
        min_years=ExperienceYearsBound(years=5, source=SOURCE_EXPLICIT),
        max_years=None,
    ),
    skills=[
        ExtractedSkill(raw_skill=skill, relation_type=RELATION_ESSENTIAL)
        for skill in SENIOR_PYTHON_REMOTE.required_skills
    ],
    compensation_estimate=CompensationEstimate(
        min_amount=CompensationBoundEstimate(
            amount=150_000,
            source=SOURCE_EMPLOYER,
        ),
        max_amount=CompensationBoundEstimate(
            amount=180_000,
            source=SOURCE_EMPLOYER,
        ),
        currency=CurrencyCode.USD,
        period=PaymentFrequency.ANNUALLY,
        reasoning="Employer stated $150,000-$180,000 base salary range for remote role",
    ),
)

EXPECTED_MARKETING_MANAGER_REMOTE = JobExtractionSchema(
    cleaned_title=MARKETING_MANAGER_REMOTE.title,
    cleaned_company=MARKETING_MANAGER_REMOTE.company_name,
    location=LocationExtraction(
        city=None,
        state_province=None,
        country_code=CountryCode.USA,
        is_remote_eligible=True,
        confidence_percent=100,
    ),
    work_arrangement=WorkArrangement.REMOTE,
    employment_term=EmploymentTerm.FULL_TIME,
    seniority_level=SeniorityLevel.SENIOR,
    experience=ExperienceExtraction(
        min_years=ExperienceYearsBound(years=5, source=SOURCE_EXPLICIT),
        max_years=ExperienceYearsBound(years=10, source=SOURCE_EXPLICIT),
    ),
    skills=[
        ExtractedSkill(raw_skill=skill, relation_type=RELATION_ESSENTIAL)
        for skill in MARKETING_MANAGER_REMOTE.required_skills
    ],
    compensation_estimate=CompensationEstimate(
        min_amount=CompensationBoundEstimate(
            amount=100_000,
            source=SOURCE_EMPLOYER,
        ),
        max_amount=CompensationBoundEstimate(
            amount=130_000,
            source=SOURCE_EMPLOYER,
        ),
        currency=CurrencyCode.USD,
        period=PaymentFrequency.ANNUALLY,
        reasoning="Employer stated $100,000-$130,000 annual salary range for remote senior IC role",
    ),
)

EXPECTED_DIRECTOR_ENGINEERING = JobExtractionSchema(
    cleaned_title=DIRECTOR_ENGINEERING.title,
    cleaned_company=DIRECTOR_ENGINEERING.company_name,
    location=LocationExtraction(
        city="New York",
        state_province="New York",
        country_code=CountryCode.USA,
        is_remote_eligible=True,
        confidence_percent=95,
    ),
    work_arrangement=WorkArrangement.HYBRID,
    employment_term=EmploymentTerm.FULL_TIME,
    seniority_level=SeniorityLevel.DIRECTOR,
    experience=ExperienceExtraction(
        min_years=ExperienceYearsBound(years=10, source=SOURCE_EXPLICIT),
        max_years=None,
    ),
    skills=[
        ExtractedSkill(raw_skill=skill, relation_type=RELATION_ESSENTIAL)
        for skill in DIRECTOR_ENGINEERING.required_skills
    ],
    compensation_estimate=CompensationEstimate(
        min_amount=CompensationBoundEstimate(
            amount=250_000,
            source=SOURCE_EMPLOYER,
        ),
        max_amount=CompensationBoundEstimate(
            amount=300_000,
            source=SOURCE_EMPLOYER,
        ),
        currency=CurrencyCode.USD,
        period=PaymentFrequency.ANNUALLY,
        reasoning="Employer stated $250,000-$300,000 base salary plus 20% annual performance bonus",
    ),
)


# Evaluation cases for dataset
def get_extraction_cases() -> list[Case[str, JobExtractionSchema]]:
    """Get evaluation cases for job extraction testing.

    Returns:
        List of test cases with raw postings and expected extractions.
    """
    return [
        Case(
            name="senior_python_remote",
            inputs=SENIOR_PYTHON_REMOTE_POSTING.simulate_enrichment(),
            expected_output=EXPECTED_SENIOR_PYTHON_REMOTE,
            metadata={
                "difficulty": "medium",
                "has_explicit_salary": True,
                "is_remote": True,
                "job_type": "senior_software_engineer",
            },
        ),
        Case(
            name="marketing_manager_remote",
            inputs=MARKETING_MANAGER_REMOTE_POSTING.simulate_enrichment(),
            expected_output=EXPECTED_MARKETING_MANAGER_REMOTE,
            metadata={
                "difficulty": "medium",
                "has_explicit_salary": True,
                "is_remote": True,
                "job_type": "marketing_manager",
            },
        ),
        Case(
            name="director_engineering",
            inputs=DIRECTOR_ENGINEERING_POSTING.simulate_enrichment(),
            expected_output=EXPECTED_DIRECTOR_ENGINEERING,
            metadata={
                "difficulty": "hard",
                "has_explicit_salary": True,
                "has_bonus_equity": True,
                "job_type": "director_engineering",
            },
        ),
    ]
