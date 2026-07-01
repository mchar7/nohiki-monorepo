"""Schema families API routes - read-only access to schema projections."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from nohiki_db_utils import paginate_query
from nohiki_fastapi_utils import PaginatedResponse, PaginationParams
from nohiki_observability import get_logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bff_service.api.deps.auth import get_current_user_id_from_cookie
from bff_service.core.db import get_async_db
from bff_service.db.models import SchemaFamilyProjection, SchemaVersionProjection

logger = get_logger(__name__)

router = APIRouter()


class SchemaVersionResponse(BaseModel):
    """Response for a schema version."""

    id: str
    family_id: str
    version: int
    json_schema: dict[str, Any]


class SchemaFamilyResponse(BaseModel):
    """Response for a schema family."""

    id: str
    name: str
    description: str | None
    latest_version: SchemaVersionResponse | None


def _version_to_response(v: SchemaVersionProjection) -> SchemaVersionResponse:
    """Convert a schema version projection to response."""
    return SchemaVersionResponse(
        id=str(v.id),
        family_id=str(v.family_id),
        version=v.version,
        json_schema=v.schema_content or {},
    )


async def _get_latest_versions_batch(
    db: AsyncSession,
    family_ids: list[UUID],
) -> dict[UUID, SchemaVersionResponse]:
    """Fetch the latest schema version per family in one query.

    Uses PostgreSQL DISTINCT ON to return one row per family, picking
    the row with the highest version number.

    Args:
        db: Database session.
        family_ids: Family IDs to fetch latest versions for.

    Returns:
        Mapping of family_id to its latest SchemaVersionResponse.

    """
    if not family_ids:
        return {}
    stmt = (
        select(SchemaVersionProjection)
        .where(
            SchemaVersionProjection.family_id.in_(family_ids),
            SchemaVersionProjection.is_active.is_(True),
        )
        .order_by(SchemaVersionProjection.family_id, SchemaVersionProjection.version.desc())
        .distinct(SchemaVersionProjection.family_id)
    )
    result = await db.execute(stmt)
    return {v.family_id: _version_to_response(v) for v in result.scalars().all()}


async def _get_latest_version(db: AsyncSession, family_id: UUID) -> SchemaVersionResponse | None:
    """Get the latest version for a schema family."""
    versions = await _get_latest_versions_batch(db, [family_id])
    return versions.get(family_id)


@router.get("")
async def list_schema_families(
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    pagination: Annotated[PaginationParams, Query()],
) -> PaginatedResponse[SchemaFamilyResponse]:
    """List all schema families from projection DB."""
    logger.debug("Listing schema families")

    query = select(SchemaFamilyProjection).where(SchemaFamilyProjection.is_active.is_(True))
    result = await paginate_query(db, query, offset=pagination.offset, limit=pagination.page_size)
    families = list(result.items)

    versions_by_family = await _get_latest_versions_batch(db, [f.id for f in families])

    return PaginatedResponse[SchemaFamilyResponse].create(
        items=[
            SchemaFamilyResponse(
                id=str(f.id),
                name=f.name,
                description=f.description,
                latest_version=versions_by_family.get(f.id),
            )
            for f in families
        ],
        total=result.total,
        params=pagination,
    )


@router.get("/{family_id}", response_model=SchemaFamilyResponse)
async def get_schema_family(
    family_id: UUID,
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> SchemaFamilyResponse:
    """Get a specific schema family with its latest version."""
    logger.debug("Getting schema family", family_id=str(family_id))

    stmt = select(SchemaFamilyProjection).where(
        SchemaFamilyProjection.id == family_id,
        SchemaFamilyProjection.is_active.is_(True),
    )
    result = await db.execute(stmt)
    family = result.scalar_one_or_none()

    if not family:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema family not found")

    latest = await _get_latest_version(db, family_id)
    return SchemaFamilyResponse(
        id=str(family.id),
        name=family.name,
        description=family.description,
        latest_version=latest,
    )


@router.get("/{family_id}/versions", response_model=list[SchemaVersionResponse])
async def list_schema_versions(
    family_id: UUID,
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> list[SchemaVersionResponse]:
    """List all versions of a schema family."""
    logger.debug("Listing schema versions", family_id=str(family_id))

    stmt = (
        select(SchemaVersionProjection)
        .where(
            SchemaVersionProjection.family_id == family_id,
            SchemaVersionProjection.is_active.is_(True),
        )
        .order_by(SchemaVersionProjection.version.desc())
    )
    result = await db.execute(stmt)
    versions = result.scalars().all()

    return [_version_to_response(v) for v in versions]


@router.get("/{family_id}/versions/{version}", response_model=SchemaVersionResponse)
async def get_schema_version(
    family_id: UUID,
    version: int,
    _user_id: Annotated[UUID, Depends(get_current_user_id_from_cookie)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
) -> SchemaVersionResponse:
    """Get a specific version of a schema."""
    logger.debug("Getting schema version", family_id=str(family_id), version=version)

    stmt = select(SchemaVersionProjection).where(
        SchemaVersionProjection.family_id == family_id,
        SchemaVersionProjection.version == version,
        SchemaVersionProjection.is_active.is_(True),
    )
    result = await db.execute(stmt)
    schema_version = result.scalar_one_or_none()

    if not schema_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema version not found")

    return _version_to_response(schema_version)
