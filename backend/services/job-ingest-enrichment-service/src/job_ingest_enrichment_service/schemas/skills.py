"""Pydantic schemas for skill extraction from job postings.

The taxonomy fields (skill_type, reuse_level) follow the ESCO/Tabiya
classification scheme so that skill-graph normalization can use them as hints
when proposing canonical entries. Today the skill-graph proto only carries
raw_skill / proficiency / is_required, so the ESCO classifications and the
explicit-vs-inferred provenance are extracted but not propagated downstream;
they are logged at the proto-mapping boundary so we can size the value of
adding them to RawSkillWithLevel.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

type EscoSkillType = Literal[
    "skill/competence",
    "knowledge",
    "language",
    "attitude",
]

type EscoReuseLevel = Literal[
    "transversal",
    "cross-sector",
    "sector-specific",
    "occupation-specific",
]

type SkillRelationType = Literal[
    "essential",
    "optional",
    "mentioned",
]

type SkillSource = Literal[
    "explicit",
    "inferred",
]


class ExtractedSkill(BaseModel):
    """A single skill extracted from the job posting.

    Capitalisation, version qualifiers, and product names are preserved verbatim
    so downstream skill-graph normalization can match against canonical entries.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    raw_skill: Annotated[str, Field(min_length=1, max_length=100)] = Field(
        ...,
        description=(
            "Skill name exactly as it appears in the posting. "
            "Preserve capitalisation and product names: 'Python', 'AWS', 'Kubernetes', 'REST APIs'. "
            "Include version info when stated: 'Python 3.11', 'Terraform >= 1.5'."
        ),
    )

    skill_type: EscoSkillType = Field(
        default="skill/competence",
        description=(
            "ESCO skill_type classification. "
            "'skill/competence': practical abilities (programming, design, communication). "
            "'knowledge': domain understanding (machine learning, finance, biology). "
            "'language': natural-language proficiency (English, Spanish, Mandarin). "
            "'attitude': behavioural traits (leadership, teamwork, attention to detail). "
            "Default to 'skill/competence' when uncertain."
        ),
    )

    reuse_level: EscoReuseLevel = Field(
        default="cross-sector",
        description=(
            "ESCO reuse_level classification. "
            "'transversal': broadly applicable across domains (communication, problem solving). "
            "'cross-sector': useful in many industries (Python, project management). "
            "'sector-specific': common to one industry (HIPAA compliance, FinTech regulations). "
            "'occupation-specific': tied to a single role (Salesforce CPQ admin, Kubernetes SRE). "
            "Default to 'cross-sector' when uncertain."
        ),
    )

    relation_type: SkillRelationType = Field(
        default="essential",
        description=(
            "Whether the skill is required, preferred, or merely mentioned. "
            "'essential': required, must-have, or listed under hard requirements. "
            "'optional': nice-to-have, preferred, bonus, listed under 'would be great'. "
            "'mentioned': appears in the posting (e.g. tech stack list) without explicit requirement weight."
        ),
    )

    source: SkillSource = Field(
        default="explicit",
        description=(
            "Whether this skill is stated in the posting or inferred from role context. "
            "'explicit': the skill name (or a clear synonym) appears in the posting text. "
            "'inferred': the skill is not in the text but is strongly implied by the role and "
            "would be expected of any qualified candidate (e.g. 'Git' for any software engineering role). "
            "Use 'inferred' sparingly; prefer 'explicit' when the skill is anywhere in the posting."
        ),
    )

    years_experience: Annotated[int | None, Field(ge=0, le=50)] = Field(
        default=None,
        description=(
            "Years of experience required for this specific skill, when stated. "
            "Examples: '5+ years of Python' -> 5, '3-5 years AWS' -> 3 (lower bound). "
            "None when no skill-specific experience is mentioned."
        ),
    )
