"""Service for publishing SKILL_CREATED events during bootstrap seeding.

This module handles streaming publication of SKILL_CREATED events when the
skill graph is seeded. It processes skills in batches to avoid memory pressure;
callers can either commit each batch or retain one encompassing transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from nohiki_observability import get_logger

from skill_graph_service.db.repositories import SKILL_BATCH_SIZE, stream_skills_with_provenance

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from skill_graph_service.events.publishers import SkillCreatedBatchPublisher, SkillCreatedPublisher

logger = get_logger(__name__)

_LOG_PROGRESS_INTERVAL: Final[int] = 5
"""Log progress every N batches to avoid log spam."""


@dataclass(frozen=True, slots=True)
class BootstrapPublishResult:
    """Result of bootstrap SKILL_CREATED publishing.

    Attributes:
        total_published: Total number of SKILL_CREATED events written to outbox.
        batch_count: Number of batches processed.

    """

    total_published: int
    batch_count: int


async def publish_skill_created_events_for_bootstrap(
    db: AsyncSession,
    *,
    skill_created_publisher: SkillCreatedPublisher,
    skill_created_batch_publisher: SkillCreatedBatchPublisher | None = None,
    batch_size: int = SKILL_BATCH_SIZE,
    commit_batches: bool = True,
) -> BootstrapPublishResult:
    """Publish SKILL_CREATED events for all seeded skills using streaming.

    Streams skills from the database in batches and writes SKILL_CREATED events
    to the outbox for each batch. By default each batch is committed for
    standalone callers. Event handlers that claim an incoming event must pass
    ``commit_batches=False`` so the handler-owned transaction remains open until
    every batch and follow-up command has completed.

    Args:
        db: Async SQLAlchemy session.
        skill_created_publisher: Fallback single-event publisher used by injected callers.
        skill_created_batch_publisher: Optional production batch publisher.
        batch_size: Number of skills per batch. Defaults to SKILL_BATCH_SIZE.
        commit_batches: Commit each batch when true. Set false when the caller
            owns an encompassing transaction.

    Returns:
        BootstrapPublishResult with total count and batch count.

    """
    total_published = 0
    batch_count = 0

    async for batch in stream_skills_with_provenance(db, batch_size=batch_size):
        if skill_created_batch_publisher is not None:
            await skill_created_batch_publisher(db, batch)
        else:
            for skill, provenance in batch:
                await skill_created_publisher(db, skill, provenance)

        if commit_batches:
            await db.commit()

        batch_count += 1
        total_published += len(batch)

        if batch_count % _LOG_PROGRESS_INTERVAL == 0:
            logger.debug(
                "Bootstrap SKILL_CREATED progress",
                batches_completed=batch_count,
                total_published=total_published,
            )

    logger.info(
        "Bootstrap SKILL_CREATED publishing complete",
        total_published=total_published,
        batch_count=batch_count,
    )

    return BootstrapPublishResult(
        total_published=total_published,
        batch_count=batch_count,
    )
