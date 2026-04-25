"""Alias management service for skill canonicalization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki_common_exceptions import DataIntegrityError
from nohiki_observability import get_logger
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from skill_graph_service.db.models import SkillAlias, SkillNode
from skill_graph_service.seeding.normalizer import normalize_skill_text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AliasUpsertParams:
    """Parameters for upserting a skill alias."""

    alias_text: str
    canonical_skill_id: UUID
    source: str
    source_version: str
    context_hint: str | None = None
    confidence: float = 0.9
    source_job_id: UUID | None = None


async def resolve_alias(
    raw_skill: str,
    db: AsyncSession,
    *,
    context_hint: str | None = None,
) -> SkillNode | None:
    """Resolve a skill alias to its canonical skill.

    Resolution priority:
    1. Context-specific alias (if context_hint provided)
    2. Universal alias (context_hint is NULL)

    Args:
        raw_skill: Raw skill string to resolve
        db: Database session
        context_hint: Optional context (industry/category) for disambiguation

    Returns:
        SkillNode if alias found, None otherwise

    """
    normalized = normalize_skill_text(raw_skill)
    normalized_context = context_hint.strip().lower() if context_hint and context_hint.strip() else None

    context_condition = SkillAlias.context_hint.is_(None)
    if normalized_context is not None:
        context_condition = or_(
            SkillAlias.context_hint == normalized_context,
            SkillAlias.context_hint.is_(None),
        )

    stmt = (
        select(SkillNode)
        .join(SkillAlias, SkillAlias.canonical_skill_id == SkillNode.id)
        .where(func.lower(SkillAlias.alias_text) == normalized)
        .where(context_condition)
        .order_by(
            case(
                (SkillAlias.context_hint == normalized_context, 0),
                else_=1,
            )
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    skill = result.scalar_one_or_none()

    if skill:
        logger.debug(
            "Alias resolved",
            alias=normalized,
            context=normalized_context,
            canonical=skill.normalized_text,
        )

    return skill


async def upsert_alias(db: AsyncSession, params: AliasUpsertParams) -> SkillAlias:
    """Create or update an alias mapping.

    If alias already exists:
    - Increment usage_count
    - Update confidence (slight increase, capped at 1.0)
    - Update timestamp

    Args:
        db: Database session
        params: Alias upsert parameters

    Returns:
        The created or updated SkillAlias

    """
    normalized = normalize_skill_text(params.alias_text)
    normalized_context = (
        params.context_hint.strip().lower() if params.context_hint and params.context_hint.strip() else None
    )
    now = datetime.now(UTC)

    stmt = (
        insert(SkillAlias)
        .values(
            alias_text=normalized,
            canonical_skill_id=params.canonical_skill_id,
            context_hint=normalized_context,
            source=params.source,
            source_version=params.source_version,
            confidence=params.confidence,
            usage_count=1,
            source_job_id=params.source_job_id,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["alias_text", "context_hint"],
            set_={
                "usage_count": SkillAlias.usage_count + 1,
                "confidence": func.least(1.0, SkillAlias.confidence + 0.01),
                "updated_at": now,
            },
            where=SkillAlias.canonical_skill_id == params.canonical_skill_id,
        )
        .returning(SkillAlias)
    )

    result = await db.execute(stmt)
    alias = result.scalar_one_or_none()
    if alias is None:
        raise DataIntegrityError(
            resource_type="SkillAlias",
            resource_ids=(normalized,),
            message="Alias is already mapped to a different canonical skill",
        )
    await db.commit()

    logger.info(
        "Alias upserted",
        alias=normalized,
        canonical_id=str(params.canonical_skill_id),
        source=params.source,
    )

    return alias


async def increment_alias_usage(
    alias_text: str,
    db: AsyncSession,
    *,
    context_hint: str | None = None,
) -> bool:
    """Increment usage count for an alias.

    Args:
        alias_text: The alias text
        db: Database session
        context_hint: Optional context

    Returns:
        True if alias was found and updated, False otherwise

    """
    normalized = normalize_skill_text(alias_text)
    normalized_context = context_hint.strip().lower() if context_hint and context_hint.strip() else None

    context_condition = (
        SkillAlias.context_hint == normalized_context
        if normalized_context is not None
        else SkillAlias.context_hint.is_(None)
    )

    stmt = (
        update(SkillAlias)
        .where(func.lower(SkillAlias.alias_text) == normalized)
        .where(context_condition)
        .values(
            usage_count=SkillAlias.usage_count + 1,
            updated_at=datetime.now(UTC),
        )
    )

    cursor_result = await db.execute(stmt)
    await db.commit()

    rowcount = int(getattr(cursor_result, "rowcount", 0) or 0)
    return rowcount > 0
