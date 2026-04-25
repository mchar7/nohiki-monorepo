"""Database repository functions for skill-graph-service."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import select

from skill_graph_service.db.models import SkillAlias, SkillNode, SkillSeedProvenance

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SKILL_BATCH_SIZE: Final[int] = 500
"""Batch size for streaming skill operations. Balances memory vs DB round-trips."""


@dataclass(frozen=True, slots=True)
class SkillRecord:
    """Projection of SkillNode data needed for batch embedding.

    Attributes:
        id: Canonical skill UUID.
        preferred_label: Display name if available, otherwise normalized text.
        description: Optional skill description.
        alt_labels: List of alias texts ordered by confidence descending.

    """

    id: UUID
    preferred_label: str
    description: str | None
    alt_labels: list[str] = field(default_factory=list)


async def fetch_all_skills_for_embedding(db: AsyncSession) -> list[SkillRecord]:
    """Fetch all skill_node rows with their aliases for embedding.

    Returns all skills from the database. The caller is responsible for
    filtering out already-embedded skills by checking Qdrant (source of truth).

    Executes two queries: one for skills and one for aliases: then joins
    them in memory to avoid N+1 database round-trips or a large ``IN`` list.

    Args:
        db: Async SQLAlchemy session.

    Returns:
        List of SkillRecord for all skills, ordered by normalized_text.

    """
    skill_result = await db.execute(
        select(SkillNode.id, SkillNode.normalized_text, SkillNode.display_name, SkillNode.description).order_by(
            SkillNode.normalized_text
        )
    )
    skill_rows = skill_result.all()

    if not skill_rows:
        return []

    alias_result = await db.execute(
        select(SkillAlias.canonical_skill_id, SkillAlias.alias_text).order_by(
            SkillAlias.confidence.desc(), SkillAlias.alias_text
        )
    )
    aliases_by_skill: dict[UUID, list[str]] = defaultdict(list)
    for row in alias_result.all():
        aliases_by_skill[row.canonical_skill_id].append(row.alias_text)

    return [
        SkillRecord(
            id=row.id,
            preferred_label=row.display_name or row.normalized_text,
            description=row.description,
            alt_labels=aliases_by_skill.get(row.id, []),
        )
        for row in skill_rows
    ]


async def _fetch_provenance_for_skill_ids(
    db: AsyncSession,
    skill_ids: list[UUID],
) -> dict[UUID, SkillSeedProvenance]:
    """Fetch highest-authority provenance for a batch of skill IDs.

    Uses PostgreSQL DISTINCT ON to efficiently get only one record per skill_id,
    ordered by authority descending. This reduces data transfer compared to
    fetching all provenance records and filtering in Python.

    Args:
        db: Async SQLAlchemy session.
        skill_ids: List of skill UUIDs to fetch provenance for.

    Returns:
        Dict mapping skill_id to its highest-authority SkillSeedProvenance.

    """
    if not skill_ids:
        return {}

    result = await db.execute(
        select(SkillSeedProvenance)
        .where(SkillSeedProvenance.skill_id.in_(skill_ids))
        .distinct(SkillSeedProvenance.skill_id)
        .order_by(
            SkillSeedProvenance.skill_id,
            SkillSeedProvenance.authority.desc(),
            SkillSeedProvenance.source_name,
        )
    )

    return {prov.skill_id: prov for prov in result.scalars()}


async def stream_skills_with_provenance(
    db: AsyncSession,
    *,
    batch_size: int = SKILL_BATCH_SIZE,
) -> AsyncGenerator[list[tuple[SkillNode, SkillSeedProvenance | None]]]:
    """Stream skills with provenance in memory-efficient batches.

    Uses server-side cursor to avoid loading all skills into memory at once.
    Each yielded batch contains skills paired with their highest-authority
    provenance record (or None if no provenance exists).

    Args:
        db: Async SQLAlchemy session.
        batch_size: Number of skills per batch. Defaults to SKILL_BATCH_SIZE.

    Yields:
        Batches of (SkillNode, SkillSeedProvenance|None) tuples.

    """
    batch: list[SkillNode] = []

    stream = await db.stream_scalars(select(SkillNode).order_by(SkillNode.normalized_text))
    async for skill in stream:
        batch.append(skill)

        if len(batch) >= batch_size:
            provenance_map = await _fetch_provenance_for_skill_ids(db, [s.id for s in batch])
            yield [(s, provenance_map.get(s.id)) for s in batch]
            batch = []

    if batch:
        provenance_map = await _fetch_provenance_for_skill_ids(db, [s.id for s in batch])
        yield [(s, provenance_map.get(s.id)) for s in batch]
