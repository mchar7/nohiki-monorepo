"""Typed response models for BFF service layer methods.

Replaces raw ``dict[str, Any]`` returns with validated Pydantic models,
providing type safety at the service-router boundary and enabling
auto-generated OpenAPI schemas.
"""

from typing import Any

from pydantic import BaseModel, Field


class ProfileDetail(BaseModel):
    """Profile data returned from the service layer."""

    id: str
    user_id: str
    pref_name: str
    search_keywords: list[str] = Field(default_factory=list)
    disallowed_keywords: list[str] = Field(default_factory=list)
    work_arrangements: list[str] = Field(default_factory=list)
    user_skills: list[str] = Field(default_factory=list)
    notification_threshold: float = 0.70
    auto_tailor_threshold: float | None = None
    open_to_relocation: bool = False

    salary_preference: dict[str, Any] | None = None
    experience_preference: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None


class CommandStatusDetail(BaseModel):
    """Command request status returned from the service layer."""

    request_id: str
    command_type: str
    status: str
    created_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None


class ResolvedImportanceWeights(BaseModel):
    """Resolved (merged) feature importance weights for scoring.

    Resolution order: search-pref override → user default → neutral (50).
    """

    skill_match_importance: int
    location_importance: int
    work_arrangement_importance: int
    experience_importance: int
    salary_importance: int
    recency_importance: int
    source: str


class SkillDetail(BaseModel):
    """Canonical skill data returned from the service layer."""

    id: str
    name: str
    display_name: str | None = None
    description: str | None = None
    category: str | None = None
    reuse_level: str | None = None
