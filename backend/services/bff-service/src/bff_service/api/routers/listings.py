"""Job listings API routes - read-only projections for job discovery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from nohiki.common.v1 import CorrelationStatus
from nohiki_db_utils import build_prefix_tsquery, paginate_query
from nohiki_domain_utils import BetterprotoEnumAdapter, parse_enum_string
from nohiki_fastapi_utils import PaginatedResponse, PaginationParams
from nohiki_observability import get_logger
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Subquery

from bff_service.api.deps.auth import get_current_user_id_from_cookie
from bff_service.api.schemas.listings import JobListingResponse
from bff_service.core.db import get_async_db
from bff_service.db.models import JobCorrelationProjection, JobListingProjection, ProfileProjection
from bff_service.services.listings_cache import (
    CachedSearchResult,
    get_cached_search_results,
    normalize_listing_filter,
    set_cached_search_results,
)

logger = get_logger(__name__)

router = APIRouter()


class FitFactorName(StrEnum):
    """Stable human-facing fit ranking factors."""

    ROLE_RELEVANCE = "ROLE_RELEVANCE"
    SKILLS = "SKILLS"
    LOCATION = "LOCATION"
    WORK_ARRANGEMENT = "WORK_ARRANGEMENT"
    EXPERIENCE = "EXPERIENCE"
    SALARY = "SALARY"
    RECENCY = "RECENCY"


class FitFactorContributionResponse(BaseModel):
    """One factor's compatibility and signed effect on the ranking index."""

    factor: FitFactorName
    compatibility_score: float = Field(ge=0, le=100)
    importance: int = Field(ge=0, le=100)
    contribution_points: float = Field(ge=-100, le=100)


class FitRankingBreakdownResponse(BaseModel):
    """Versioned deterministic fit ranking explanation."""

    method_version: str = Field(min_length=1, max_length=64)
    factors: list[FitFactorContributionResponse] = Field(min_length=1, max_length=7)


class JobCorrelationResponse(BaseModel):
    """Response for a single job correlation/match."""

    id: str
    pref_id: str
    listing_id: str
    fit_score: int
    status: Annotated[CorrelationStatus, BetterprotoEnumAdapter(exclude_unspecified=True)]
    score_breakdown: dict[str, str]
    fit_ranking_breakdown: FitRankingBreakdownResponse | None = None
    listing_title: str
    listing_company: str | None
    listing_url: str
    listing_location: str | None
    created_at: str
    updated_at: str


class CorrelationFilters(BaseModel):
    """Domain-specific query parameters for correlations."""

    pref_id: UUID | None = None
    min_score: int = Field(default=0, ge=0, le=100)


class ListingFilters(BaseModel):
    """Domain-specific query parameters for listings."""

    source: str | None = None
    company: str | None = None
    q: Annotated[str | None, Field(min_length=2, max_length=200)] = None
    has_salary: bool | None = None
    show_dismissed: bool = False
    sort: Literal["posted_at", "company_name", "title", "match_score"] = "posted_at"
    dir: Literal["asc", "desc"] = "desc"
    work_arrangement: str | None = None
    seniority: str | None = None
    date_range: Literal["24h", "7d", "30d"] | None = None


_DATE_RANGE_DAYS: dict[str, int] = {"24h": 1, "7d": 7, "30d": 30}


def _user_correlation_scores(user_id: UUID) -> Subquery:
    """Aggregate active, owned profile correlations to one row per listing."""
    return (
        select(
            JobCorrelationProjection.listing_id.label("listing_id"),
            func.max(JobCorrelationProjection.fit_score).label("match_score"),
            func.bool_and(func.upper(JobCorrelationProjection.status) == "DISMISSED").label("all_dismissed"),
        )
        .join(ProfileProjection, ProfileProjection.id == JobCorrelationProjection.pref_id)
        .where(
            JobCorrelationProjection.user_id == user_id,
            ProfileProjection.user_id == user_id,
            ProfileProjection.is_active.is_(True),
        )
        .group_by(JobCorrelationProjection.listing_id)
        .subquery()
    )


def _listing_to_response(listing: JobListingProjection) -> JobListingResponse:
    """Convert JobListingProjection to response model."""
    return JobListingResponse(
        id=str(listing.id),
        listing_url=listing.listing_url,
        source=listing.source,
        title=listing.title,
        company_name=listing.company_name,
        description=listing.description,
        location_raw=listing.location_raw,
        work_arrangement=listing.work_arrangement,
        seniority_level=listing.seniority_level,
        language=listing.language,
        required_skills=listing.required_skills,
        posted_at=listing.posted_at.isoformat() if listing.posted_at else None,
        discovered_at=listing.discovered_at.isoformat(),
        created_at=listing.created_at.isoformat(),
        salary_min=listing.salary_min,
        salary_max=listing.salary_max,
        salary_currency=listing.salary_currency,
        salary_frequency=listing.salary_frequency,
        company_logo_url=listing.company_logo_url,
        experience_years_min=listing.experience_years_min,
        experience_years_max=listing.experience_years_max,
    )


def _fit_ranking_breakdown_to_response(
    breakdown: dict[str, object] | None,
) -> FitRankingBreakdownResponse | None:
    return FitRankingBreakdownResponse.model_validate(breakdown) if breakdown is not None else None


def _apply_listing_predicates(
    query: Select,
    filters: ListingFilters,
    correlation_scores: Subquery | None,
) -> Select:
    normalized_source = normalize_listing_filter(filters.source)
    if normalized_source is not None:
        query = query.where(func.lower(func.trim(JobListingProjection.source)) == normalized_source)
    normalized_company = normalize_listing_filter(filters.company)
    if normalized_company is not None:
        query = query.where(
            func.lower(func.trim(JobListingProjection.company_name)).contains(normalized_company, autoescape=True)
        )
    if filters.has_salary:
        query = query.where(
            or_(JobListingProjection.salary_min.is_not(None), JobListingProjection.salary_max.is_not(None))
        )
    if filters.work_arrangement:
        query = query.where(
            func.lower(func.trim(JobListingProjection.work_arrangement))
            == normalize_listing_filter(filters.work_arrangement)
        )
    if filters.seniority:
        query = query.where(
            func.lower(func.trim(JobListingProjection.seniority_level)) == normalize_listing_filter(filters.seniority)
        )
    if filters.date_range:
        cutoff = datetime.now(UTC) - timedelta(days=_DATE_RANGE_DAYS[filters.date_range])
        query = query.where(JobListingProjection.posted_at >= cutoff)
    if correlation_scores is not None and not filters.show_dismissed:
        query = query.where(
            or_(correlation_scores.c.listing_id.is_(None), correlation_scores.c.all_dismissed.is_(False))
        )
    return query


def _apply_listing_order(
    query: Select,
    filters: ListingFilters,
    correlation_scores: Subquery | None,
    ts_query: ColumnElement[bool] | None,
) -> Select:
    if filters.sort == "match_score" and correlation_scores is not None:
        score_order = (
            correlation_scores.c.match_score.asc() if filters.dir == "asc" else correlation_scores.c.match_score.desc()
        )
        return query.order_by(
            score_order.nulls_last(), JobListingProjection.created_at.desc(), JobListingProjection.id.asc()
        )
    if filters.sort == "company_name":
        name_order = (
            JobListingProjection.company_name.asc()
            if filters.dir == "asc"
            else JobListingProjection.company_name.desc()
        )
        return query.order_by(name_order, JobListingProjection.created_at.desc(), JobListingProjection.id.asc())
    if filters.sort == "title":
        title_order = JobListingProjection.title.asc() if filters.dir == "asc" else JobListingProjection.title.desc()
        return query.order_by(title_order, JobListingProjection.created_at.desc(), JobListingProjection.id.asc())
    if filters.q and ts_query is not None:
        return query.order_by(
            func.ts_rank_cd(JobListingProjection.search_vector, ts_query).desc(),
            JobListingProjection.created_at.desc(),
            JobListingProjection.id.asc(),
        )
    posted_order = (
        JobListingProjection.posted_at.asc() if filters.dir == "asc" else JobListingProjection.posted_at.desc()
    )
    return query.order_by(
        posted_order.nulls_last(), JobListingProjection.created_at.desc(), JobListingProjection.id.asc()
    )


def _build_listing_query(user_id: UUID, filters: ListingFilters) -> Select:
    uses_profile_query = filters.sort == "match_score" or not filters.show_dismissed
    correlation_scores = _user_correlation_scores(user_id) if uses_profile_query else None
    query = select(JobListingProjection)
    if correlation_scores is not None:
        query = query.outerjoin(correlation_scores, JobListingProjection.id == correlation_scores.c.listing_id)

    ts_query = None
    if filters.q:
        prefix_query = build_prefix_tsquery(filters.q)
        ts_query = (
            func.to_tsquery("english", prefix_query) if prefix_query else func.plainto_tsquery("english", filters.q)
        )
        query = query.where(JobListingProjection.search_vector.op("@@")(ts_query))
    query = _apply_listing_predicates(query, filters, correlation_scores)
    return _apply_listing_order(query, filters, correlation_scores, ts_query)


@router.get("")
async def list_job_listings(
    db: Annotated[AsyncSession, Depends(get_async_db)],
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    pagination: Annotated[PaginationParams, Depends()],
    filters: Annotated[ListingFilters, Depends()],
) -> PaginatedResponse[JobListingResponse]:
    """List listings with user-owned correlation filters applied before pagination."""
    cacheable_search = bool(filters.q and filters.show_dismissed and filters.sort != "match_score")

    if cacheable_search:
        cached = await get_cached_search_results(
            filters.q,
            pagination.page,
            pagination.page_size,
            source=filters.source,
            company=filters.company,
            has_salary=filters.has_salary,
            sort=filters.sort,
            direction=filters.dir,
            work_arrangement=filters.work_arrangement,
            seniority=filters.seniority,
            date_range=filters.date_range,
            show_dismissed=filters.show_dismissed,
        )
        if cached is not None:
            return PaginatedResponse[JobListingResponse](
                items=cached.items,
                total=cached.total,
                page=cached.page,
                page_size=cached.page_size,
                total_pages=cached.total_pages,
                has_next=cached.has_next,
                has_prev=cached.has_prev,
            )

    query = _build_listing_query(user_id, filters)

    result = await paginate_query(db, query, offset=pagination.offset, limit=pagination.page_size)
    response = PaginatedResponse[JobListingResponse].create(
        items=[_listing_to_response(listing) for listing in result.items],
        total=result.total,
        params=pagination,
    )

    if cacheable_search:
        await set_cached_search_results(
            filters.q,
            pagination.page,
            pagination.page_size,
            CachedSearchResult(
                items=response.items,
                total=response.total,
                page=response.page,
                page_size=response.page_size,
                total_pages=response.total_pages,
                has_next=response.has_next,
                has_prev=response.has_prev,
            ),
            source=filters.source,
            company=filters.company,
            has_salary=filters.has_salary,
            sort=filters.sort,
            direction=filters.dir,
            work_arrangement=filters.work_arrangement,
            seniority=filters.seniority,
            date_range=filters.date_range,
            show_dismissed=filters.show_dismissed,
        )

    return response


@router.get("/correlations/mine")
async def list_my_correlations(
    db: Annotated[AsyncSession, Depends(get_async_db)],
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    pagination: Annotated[PaginationParams, Depends()],
    filters: Annotated[CorrelationFilters, Depends()],
) -> PaginatedResponse[JobCorrelationResponse]:
    """List job correlations for the current user."""
    query = (
        select(JobCorrelationProjection)
        .where(JobCorrelationProjection.user_id == user_id)
        .where(JobCorrelationProjection.fit_score >= filters.min_score)
        .order_by(JobCorrelationProjection.fit_score.desc())
    )

    if filters.pref_id:
        query = query.where(JobCorrelationProjection.pref_id == filters.pref_id)

    result = await paginate_query(db, query, offset=pagination.offset, limit=pagination.page_size)

    return PaginatedResponse[JobCorrelationResponse].create(
        items=[
            JobCorrelationResponse(
                id=str(corr.id),
                pref_id=str(corr.pref_id),
                listing_id=str(corr.listing_id),
                fit_score=corr.fit_score,
                status=parse_enum_string(CorrelationStatus, corr.status),
                score_breakdown={k: str(v) for k, v in corr.score_breakdown.items()},
                fit_ranking_breakdown=_fit_ranking_breakdown_to_response(corr.fit_ranking_breakdown),
                listing_title=corr.listing_title,
                listing_company=corr.listing_company,
                listing_url=corr.listing_url,
                listing_location=corr.listing_location,
                created_at=corr.created_at.isoformat(),
                updated_at=corr.updated_at.isoformat(),
            )
            for corr in result.items
        ],
        total=result.total,
        params=pagination,
    )


@router.get("/{listing_id}", response_model=JobListingResponse)
async def get_job_listing(
    listing_id: UUID,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
) -> JobListingResponse:
    """Get a specific job listing by ID."""
    result = await db.execute(select(JobListingProjection).where(JobListingProjection.id == listing_id))
    listing = result.scalar_one_or_none()

    if listing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job listing not found")

    return _listing_to_response(listing)


@router.get("/correlations/{correlation_id}", response_model=JobCorrelationResponse)
async def get_correlation(
    correlation_id: UUID,
    db: Annotated[AsyncSession, Depends(get_async_db)],
    user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
) -> JobCorrelationResponse:
    """Get a specific job correlation by ID."""
    result = await db.execute(
        select(JobCorrelationProjection)
        .where(JobCorrelationProjection.id == correlation_id)
        .where(JobCorrelationProjection.user_id == user_id)
    )
    corr = result.scalar_one_or_none()

    if corr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Correlation not found")

    return JobCorrelationResponse(
        id=str(corr.id),
        pref_id=str(corr.pref_id),
        listing_id=str(corr.listing_id),
        fit_score=corr.fit_score,
        status=parse_enum_string(CorrelationStatus, corr.status),
        score_breakdown={k: str(v) for k, v in corr.score_breakdown.items()},
        fit_ranking_breakdown=_fit_ranking_breakdown_to_response(corr.fit_ranking_breakdown),
        listing_title=corr.listing_title,
        listing_company=corr.listing_company,
        listing_url=corr.listing_url,
        listing_location=corr.listing_location,
        created_at=corr.created_at.isoformat(),
        updated_at=corr.updated_at.isoformat(),
    )
