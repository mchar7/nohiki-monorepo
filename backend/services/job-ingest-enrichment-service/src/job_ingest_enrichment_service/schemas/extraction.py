"""Unified PydanticAI extraction schema for job posting enrichment.

SINGLE LLM CALL: This schema extracts ALL fields in one request.
PydanticAI retries automatically until validation passes.

Sub-models are organized by domain concern:
- location.py: City/state/country extraction with confidence
- experience.py: Per-bound experience requirements with source tracking
- compensation.py: Per-bound compensation estimates with source tracking
- skills.py: ESCO/Tabiya taxonomy skill extraction

This module defines the root JobExtractionSchema and re-exports all sub-models.
"""

from __future__ import annotations

from typing import Annotated

from nohiki.common.v1 import EmploymentTerm, SeniorityLevel, WorkArrangement
from nohiki_domain_utils import BetterprotoEnumAdapter
from pydantic import BaseModel, ConfigDict, Field

from job_ingest_enrichment_service.schemas.compensation import (
    MAX_COMPENSATION_RANGE_RATIO,
    CompensationBoundEstimate,
    CompensationEstimate,
    CompensationSourceLiteral,
)
from job_ingest_enrichment_service.schemas.experience import (
    ExperienceExtraction,
    ExperienceSourceLiteral,
    ExperienceYearsBound,
)
from job_ingest_enrichment_service.schemas.location import LocationExtraction
from job_ingest_enrichment_service.schemas.skills import (
    EscoReuseLevel,
    EscoSkillType,
    ExtractedSkill,
    SkillRelationType,
    SkillSource,
)

_seniority_adapter = BetterprotoEnumAdapter(exclude_unspecified=False)
_work_arr_adapter = BetterprotoEnumAdapter(exclude_unspecified=False)
_emp_term_adapter = BetterprotoEnumAdapter(exclude_unspecified=False)

__all__ = [
    "MAX_COMPENSATION_RANGE_RATIO",
    "CompensationBoundEstimate",
    "CompensationEstimate",
    "CompensationSourceLiteral",
    "EscoReuseLevel",
    "EscoSkillType",
    "ExperienceExtraction",
    "ExperienceSourceLiteral",
    "ExperienceYearsBound",
    "ExtractedSkill",
    "JobExtractionSchema",
    "LocationExtraction",
    "SkillRelationType",
    "SkillSource",
]


class JobExtractionSchema(BaseModel):
    """Unified job posting extraction schema.

    Field-level descriptions provide extraction guidance.
    See per-field docstrings for detailed rules.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_default=True,
    )

    cleaned_title: Annotated[str, Field(min_length=1, max_length=200)] = Field(
        ...,
        description=(
            "Standardized job title. Expand abbreviations, fix typos, remove noise. "
            "'Sr. SWE' → 'Senior Software Engineer' | 'ML Eng II' → 'Machine Learning Engineer II' | "
            "'PM - Growth' → 'Product Manager, Growth'."
        ),
    )

    cleaned_company: Annotated[str, Field(min_length=1, max_length=200)] = Field(
        ...,
        description=(
            "Standardized company name. Remove legal suffixes unless they are distinctive. "
            "'Google LLC' → 'Google' | 'Stripe, Inc.' → 'Stripe' | 'HSBC Holdings plc' → 'HSBC'."
        ),
    )

    location: LocationExtraction = Field(
        default_factory=LocationExtraction,
        description="Primary physical work location. See LocationExtraction for field guidance.",
    )

    work_arrangement: Annotated[WorkArrangement, _work_arr_adapter] = Field(
        default=WorkArrangement.UNSPECIFIED,
        description=(
            "Where the work is physically performed. "
            "ON_SITE: Must report to an office or facility. "
            "REMOTE: Fully remote with no location requirement. "
            "HYBRID: Scheduled mix of office and remote days. "
            "UNSPECIFIED: Not mentioned or genuinely unclear."
        ),
    )

    employment_term: Annotated[EmploymentTerm, _emp_term_adapter] = Field(
        default=EmploymentTerm.UNSPECIFIED,
        description=(
            "Employment structure. "
            "FULL_TIME: Permanent, typically 40 hrs/week. "
            "PART_TIME: Fewer than full-time hours. "
            "CONTRACT: Fixed-term engagement or freelance/1099. "
            "INTERNSHIP: Student or trainee program (paid or unpaid). "
            "UNSPECIFIED: Not mentioned."
        ),
    )

    seniority_level: Annotated[SeniorityLevel, _seniority_adapter] = Field(
        ...,
        description=(
            "Career level inferred from job title, stated responsibilities, team scope, and org impact. "
            "INTERN: Student internship or trainee program. "
            "ENTRY: 0-2 years, individual contributor, close supervision expected. "
            "MID: 2-5 years, works independently on defined problems. "
            "SENIOR: 5+ years, leads projects and actively mentors others. "
            "STAFF: Principal/Staff-equivalent -- deep domain expertise with cross-team or org-wide "
            "technical impact; no direct reports. "
            "MANAGER: Directly manages a team of individual contributors. "
            "DIRECTOR: Manages multiple teams or managers; owns a department or domain. "
            "VP: Vice President -- owns a function, major product area, or business unit. "
            "EXECUTIVE: C-suite or equivalent board-level role (CEO, CTO, CPO, CRO, CFO)."
        ),
    )

    language: Annotated[str, Field(min_length=2, max_length=5)] = Field(
        ...,
        description=(
            "IETF BCP 47 language tag of the primary language the job posting is written in. "
            "Use 2-letter base codes for unambiguous languages: 'en', 'fr', 'de', 'ja', 'es', 'nl', 'it'. "
            "Use language-region subtags where the variant is distinguishable from text content: "
            "'zh-CN' (Simplified Chinese), 'zh-TW' (Traditional Chinese), "
            "'pt-BR' (Brazilian Portuguese), 'pt-PT' (European Portuguese). "
            "Detect from the actual text content -- NOT the company location or job board country."
        ),
    )

    experience: ExperienceExtraction = Field(
        default_factory=ExperienceExtraction,
        description=(
            "Explicit or inferred experience requirements. Use None bounds when experience is genuinely not mentioned."
        ),
    )

    skills: Annotated[list[ExtractedSkill], Field(min_length=1)] = Field(
        ...,
        description=(
            "All skills mentioned in the posting: technical tools, languages, frameworks, "
            "domain knowledge, soft skills, and certifications. "
            "Extract every skill mentioned (at minimum 1). Do not invent skills not implied by the posting. "
            "Preserve original product names (AWS, not 'Amazon Web Services'). "
            "DEDUPLICATION: Each distinct skill appears ONCE. Prefer the most specific form "
            "('Python 3.11' over 'Python' if version is stated). Do not list both an acronym "
            "and its expansion ('k8s' OR 'Kubernetes', not both). "
            "Do not list both a category and its specific instance unless the posting "
            "explicitly requires both ('cloud computing' AND 'AWS' only if both are stated)."
        ),
    )

    compensation_estimate: CompensationEstimate = Field(
        ...,
        description=(
            "ALWAYS provide an estimate -- even with low confidence. "
            "Amounts are in MAJOR UNITS: $80,000/yr → 80000, £60,000/yr → 60000. "
            "Use employer_provided when stated; llm_inferred with confidence when estimated."
        ),
    )
