"""Skills API routes - skill search from local projections with Redis caching."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from nohiki_observability import get_logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.api.deps.auth import get_current_user_id_from_cookie
from bff_service.core.db import get_async_db
from bff_service.db.models import SkillProjection
from bff_service.services.skill_service import (
    get_skill_categories_cached,
    get_skills_by_ids_cached,
    search_skills_cached,
)

logger = get_logger(__name__)

router = APIRouter()


class SkillSearchResult(BaseModel):
    """Single skill in search results."""

    id: str
    name: str
    display_name: str | None = None
    description: str | None = None
    category: str | None = None


class SkillSearchResponse(BaseModel):
    """Response for skill search."""

    skills: list[SkillSearchResult]
    total: int
    query: str


class SkillBatchRequest(BaseModel):
    """Request to get skills by IDs."""

    skill_ids: list[str] = Field(max_length=100)


class SkillBatchResponse(BaseModel):
    """Response for batch skill lookup."""

    skills: list[SkillSearchResult]


@router.get("/search", response_model=SkillSearchResponse)
async def search_skills(
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    q: Annotated[str, Query(min_length=2, max_length=100, description="Search query")],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    category: Annotated[str | None, Query(description="Filter by category")] = None,
) -> SkillSearchResponse:
    """Search canonical skills by name.

    Uses PostgreSQL ILIKE for prefix matching on normalized_text and display_name.
    Results are ordered by popularity (job_count + profile_count).
    Results are cached in Redis for 5 minutes.
    """
    cached_skills = await search_skills_cached(q, limit, category, db)
    skills = cached_skills if isinstance(cached_skills, list) else []

    return SkillSearchResponse(
        skills=[SkillSearchResult.model_validate(s, from_attributes=True) for s in skills],
        total=len(skills),
        query=q,
    )


@router.post("/batch", response_model=SkillBatchResponse)
async def get_skills_by_ids(
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    request: SkillBatchRequest,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> SkillBatchResponse:
    """Get multiple skills by their IDs.

    Used to resolve skill IDs to names for display purposes.
    Results are cached in Redis for 10 minutes.
    """
    if not request.skill_ids:
        return SkillBatchResponse(skills=[])

    skill_ids_key = ",".join(sorted(request.skill_ids))
    cached_skills = await get_skills_by_ids_cached(skill_ids_key, request.skill_ids, db)
    skills = cached_skills if isinstance(cached_skills, list) else []

    return SkillBatchResponse(
        skills=[SkillSearchResult.model_validate(s, from_attributes=True) for s in skills],
    )


@router.get("/{skill_id}", response_model=SkillSearchResult)
async def get_skill(
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    skill_id: UUID,
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> SkillSearchResult:
    """Get a single skill by ID."""
    stmt = select(SkillProjection).where(SkillProjection.id == skill_id)
    result = await db.execute(stmt)
    skill = result.scalar_one_or_none()

    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    return SkillSearchResult(
        id=str(skill.id),
        name=skill.normalized_text,
        display_name=skill.display_name,
        description=skill.description,
        category=skill.category,
    )


@router.get("/categories/list", response_model=list[str])
async def list_skill_categories(
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> list[str]:
    """List all skill categories.

    Results are cached in Redis for 30 minutes.
    """
    return await get_skill_categories_cached(db)
