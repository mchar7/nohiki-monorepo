"""Profiles API routes - job target profile management via CQRS projections."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from nohiki.common.v1 import CurrencyCode, PaymentFrequency, SeniorityLevel, WorkArrangement
from nohiki_domain_utils import BetterprotoEnumAdapter
from nohiki_fastapi_utils import PaginatedResponse, PaginationParams
from nohiki_observability import get_logger
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.api.deps.auth import get_current_user_id_from_cookie
from bff_service.api.schemas import CommandAcceptedResponse
from bff_service.core.db import get_async_db
from bff_service.services.models import CommandStatusDetail
from bff_service.services.profile_service import ProfileService

logger = get_logger(__name__)

CanonicalSkillId = Annotated[UUID, PlainSerializer(str, return_type=str)]


Keyword = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
_KEYWORDS_MUST_BE_UNIQUE = "keywords must be unique"


def _require_unique_keywords(keywords: list[Keyword]) -> list[Keyword]:
    if len(keywords) != len(set(keywords)):
        raise ValueError(_KEYWORDS_MUST_BE_UNIQUE)
    return keywords


SearchKeywords = Annotated[list[Keyword], Field(min_length=1, max_length=20), AfterValidator(_require_unique_keywords)]
DisallowedKeywords = Annotated[list[Keyword], Field(max_length=20), AfterValidator(_require_unique_keywords)]

router = APIRouter()


# Request/Response Schemas


class MonetaryAmountRequest(BaseModel):
    """Monetary amount with currency in minor units (cents)."""

    model_config = ConfigDict(extra="forbid")

    minor_units: int = Field(..., ge=0, description="Amount in minor units (e.g., cents)")
    currency: Annotated[CurrencyCode, BetterprotoEnumAdapter(exclude_unspecified=True)] = Field(
        ..., description="Currency code (required)"
    )


class SalaryPreferenceRequest(BaseModel):
    """Request to set salary preference."""

    model_config = ConfigDict(extra="forbid")

    min_salary: MonetaryAmountRequest = Field(..., description="Minimum acceptable annual salary (required)")
    target_salary: MonetaryAmountRequest = Field(..., description="Target/ideal annual salary (required)")
    preferred_frequency: Annotated[PaymentFrequency, BetterprotoEnumAdapter()] = Field(
        default=PaymentFrequency.ANNUALLY, description="Preferred payment frequency"
    )


class ExperiencePreferenceRequest(BaseModel):
    """Request to set experience preference."""

    model_config = ConfigDict(extra="forbid")

    experience_years: int = Field(..., ge=0, le=50, description="Years of experience (required)")
    seniority_levels: list[Annotated[SeniorityLevel, BetterprotoEnumAdapter()]] = Field(
        ..., min_length=1, max_length=10, description="At least one preferred seniority level required"
    )


class ProfileCreate(BaseModel):
    """Request to create a job target profile."""

    model_config = ConfigDict(extra="forbid")

    pref_name: str = Field(..., min_length=1, max_length=100)
    search_keywords: SearchKeywords = Field(..., description="At least one search keyword required")
    disallowed_keywords: DisallowedKeywords = Field(default_factory=list)
    user_skills: list[CanonicalSkillId] = Field(
        default_factory=list, max_length=100, description="Canonical skill IDs from user profile"
    )
    work_arrangements: list[Annotated[WorkArrangement, BetterprotoEnumAdapter()]] = Field(
        ..., min_length=1, max_length=5, description="At least one work arrangement required"
    )
    notification_threshold: float = Field(default=0.7, ge=0, le=1)
    auto_tailor_threshold: float | None = Field(default=None, ge=0, le=1)
    open_to_relocation: bool = Field(default=False)
    salary_preference: SalaryPreferenceRequest | None = None
    experience_preference: ExperiencePreferenceRequest | None = None


class ProfileUpdate(BaseModel):
    """Request to update a job target profile."""

    model_config = ConfigDict(extra="forbid")

    pref_name: str | None = Field(None, min_length=1, max_length=100)
    search_keywords: SearchKeywords | None = None
    disallowed_keywords: DisallowedKeywords | None = None
    user_skills: list[CanonicalSkillId] | None = Field(None, max_length=100)
    work_arrangements: list[Annotated[WorkArrangement, BetterprotoEnumAdapter()]] | None = Field(
        None, min_length=1, max_length=5
    )
    notification_threshold: float | None = Field(None, ge=0, le=1)
    auto_tailor_threshold: float | None = Field(None, ge=0, le=1)
    open_to_relocation: bool | None = None
    salary_preference: SalaryPreferenceRequest | None = None
    experience_preference: ExperiencePreferenceRequest | None = None


class MonetaryAmountResponse(BaseModel):
    """Monetary amount response."""

    minor_units: int
    currency: Annotated[CurrencyCode, BetterprotoEnumAdapter()]


class SalaryPreferenceResponse(BaseModel):
    """Salary preference response."""

    min_salary: MonetaryAmountResponse | None = None
    target_salary: MonetaryAmountResponse | None = None
    preferred_frequency: Annotated[PaymentFrequency, BetterprotoEnumAdapter()] = PaymentFrequency.ANNUALLY


class ExperiencePreferenceResponse(BaseModel):
    """Experience preference response."""

    experience_years: int | None = None
    seniority_levels: list[Annotated[SeniorityLevel, BetterprotoEnumAdapter()]] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    """Response for a single profile."""

    id: str
    user_id: str
    pref_name: str
    search_keywords: list[str]
    disallowed_keywords: list[str]
    work_arrangements: list[Annotated[WorkArrangement, BetterprotoEnumAdapter()]]
    user_skills: list[str] = Field(default_factory=list, description="Canonical skill IDs from user profile")
    notification_threshold: float
    auto_tailor_threshold: float | None
    open_to_relocation: bool
    salary_preference: SalaryPreferenceResponse | None = None
    experience_preference: ExperiencePreferenceResponse | None = None
    created_at: str | None = None
    updated_at: str | None = None


class FeatureImportanceRequest(BaseModel):
    """Request to set feature importance preferences."""

    skill_match_importance: int | None = Field(None, ge=0, le=100)
    location_importance: int | None = Field(None, ge=0, le=100)
    work_arrangement_importance: int | None = Field(None, ge=0, le=100)
    experience_importance: int | None = Field(None, ge=0, le=100)
    salary_importance: int | None = Field(None, ge=0, le=100)
    recency_importance: int | None = Field(None, ge=0, le=100)


class ResolvedFeatureImportanceResponse(BaseModel):
    """Response with resolved (merged) preferences and source."""

    model_config = ConfigDict(from_attributes=True)

    skill_match_importance: int
    location_importance: int
    work_arrangement_importance: int
    experience_importance: int
    salary_importance: int
    recency_importance: int
    source: str


# Dependencies


def get_profile_service() -> ProfileService:
    """Get profile service instance."""
    return ProfileService()


# Routes


@router.get("")
async def list_profiles(
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    pagination: Annotated[PaginationParams, Depends()],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> PaginatedResponse[ProfileResponse]:
    """List all job target profiles for the current user."""
    profiles_data, total = await service.list_profiles(
        db,
        user_id,
        offset=pagination.offset,
        limit=pagination.page_size,
    )
    profiles = [
        ProfileResponse.model_validate(p.model_dump() if hasattr(p, "model_dump") else p) for p in profiles_data
    ]
    return PaginatedResponse[ProfileResponse].create(
        items=profiles,
        total=total,
        params=pagination,
    )


@router.post("", response_model=CommandAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_profile(
    data: ProfileCreate,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandAcceptedResponse:
    """Create a new job target profile.

    Returns 202 Accepted with request_id for async completion tracking.
    """
    request_id = await service.create_profile_command(db, user_id, data.model_dump())
    return CommandAcceptedResponse(request_id=request_id)


@router.get("/commands/{request_id}", response_model=CommandStatusDetail)
async def get_profile_command_status(
    request_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandStatusDetail:
    """Return an owned profile command request's current status."""
    command = await service.get_command_status(db, user_id, request_id)
    if command is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Command request not found")
    return command


@router.get("/{pref_id}", response_model=ProfileResponse)
async def get_profile(
    pref_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ProfileResponse:
    """Get a specific job target profile."""
    profile_data = await service.get_profile(db, user_id, pref_id)
    if profile_data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return ProfileResponse.model_validate(
        profile_data.model_dump() if hasattr(profile_data, "model_dump") else profile_data
    )


@router.patch("/{pref_id}", response_model=CommandAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def update_profile(
    pref_id: UUID,
    data: ProfileUpdate,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandAcceptedResponse:
    """Update a job target profile.

    Returns 202 Accepted with request_id for async completion tracking.
    """
    request_id = await service.update_profile_command(
        db,
        user_id,
        pref_id,
        data.model_dump(exclude_unset=True, exclude_none=True),
    )
    return CommandAcceptedResponse(request_id=request_id)


@router.delete("/{pref_id}", response_model=CommandAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def delete_profile(
    pref_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandAcceptedResponse:
    """Delete a job target profile.

    Returns 202 Accepted with request_id for async completion tracking.
    """
    request_id = await service.delete_profile_command(user_id, pref_id)
    return CommandAcceptedResponse(request_id=request_id)


@router.post(
    "/{pref_id}/attachments/{upload_id}",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def associate_attachment(
    pref_id: UUID,
    upload_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandAcceptedResponse:
    """Associate an attachment with a profile."""
    request_id = await service.associate_attachment_command(user_id, pref_id, upload_id)
    return CommandAcceptedResponse(request_id=request_id)


@router.delete(
    "/{pref_id}/attachments/{upload_id}",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def disassociate_attachment(
    pref_id: UUID,
    upload_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandAcceptedResponse:
    """Disassociate an attachment from a profile."""
    request_id = await service.disassociate_attachment_command(user_id, pref_id, upload_id)
    return CommandAcceptedResponse(request_id=request_id)


# Feature Importance Preferences


@router.put(
    "/settings/feature-importance",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def set_default_feature_importance(
    data: FeatureImportanceRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandAcceptedResponse:
    """Set user-level default feature importance preferences.

    These defaults apply to all search preferences unless overridden
    at the individual search preference level.
    """
    request_id = await service.set_default_feature_importance_command(
        user_id=user_id,
        importance_prefs=data.model_dump(exclude_unset=True),
    )
    return CommandAcceptedResponse(request_id=request_id)


@router.put(
    "/{pref_id}/feature-importance",
    response_model=CommandAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def set_pref_feature_importance(
    pref_id: UUID,
    data: FeatureImportanceRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> CommandAcceptedResponse:
    """Override feature importance for a specific search preference.

    These settings override the user-level defaults for this search preference only.
    """
    request_id = await service.set_pref_feature_importance_command(
        user_id=user_id,
        pref_id=pref_id,
        importance_prefs=data.model_dump(exclude_unset=True),
    )
    return CommandAcceptedResponse(request_id=request_id)


@router.get(
    "/{pref_id}/resolved-importance",
    response_model=ResolvedFeatureImportanceResponse,
)
async def get_resolved_feature_importance(
    pref_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    service: Annotated[ProfileService, Depends(get_profile_service)],
) -> ResolvedFeatureImportanceResponse:
    """Get the resolved (merged) feature importance for a search preference.

    Resolution order:
    1. SearchPref.feature_importance (if set)
    2. UserPrefSettings.default_feature_importance (if set)
    3. Neutral defaults (50 for all fields)

    Returns the resolved values and the source of the preference.
    """
    resolved = await service.get_resolved_importance(db, user_id, pref_id)
    return ResolvedFeatureImportanceResponse.model_validate(resolved)
