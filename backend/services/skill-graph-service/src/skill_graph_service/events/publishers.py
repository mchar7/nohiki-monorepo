"""Event publishing functions for skill lifecycle events using outbox pattern."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from nohiki.skill.v1 import CanonicalSkill, ReviewStatus, SkillCreated, SkillSource
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils import OutboxEventParams, OutboxWriter
from nohiki_kafka_client import Topics, create_event_metadata
from nohiki_observability import get_logger

from skill_graph_service.core.config import get_settings
from skill_graph_service.db.models import SCHEMA_NAME, SkillNode, SkillSeedProvenance

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SkillCreatedPublisher(Protocol):
    """Protocol for publishing SKILL_CREATED events.

    Enables dependency injection of the publisher function, breaking
    circular imports and improving testability.
    """

    async def __call__(
        self,
        db: AsyncSession,
        skill: SkillNode,
        provenance: SkillSeedProvenance | None = None,
        *,
        correlation_id: str | None = None,
    ) -> UUID:
        """Publish a SKILL_CREATED event.

        Args:
            db: Active database session.
            skill: SkillNode being published.
            provenance: Optional provenance for source mapping.
            correlation_id: Optional correlation ID for tracing.

        Returns:
            UUID of the created outbox entry.

        """
        ...


class SkillCreatedBatchPublisher(Protocol):
    """Protocol for publishing a batch of SKILL_CREATED events."""

    async def __call__(
        self,
        db: AsyncSession,
        skills: Sequence[tuple[SkillNode, SkillSeedProvenance | None]],
        *,
        correlation_id: str | None = None,
    ) -> list[UUID]:
        """Publish one outbox row per skill with a single database execute."""
        ...


def _build_skill_created_request(
    skill: SkillNode,
    provenance: SkillSeedProvenance | None,
    correlation_id: str | None,
) -> tuple[OutboxEventParams, SkillCreated]:
    """Build a SKILL_CREATED outbox request."""
    return (
        OutboxEventParams(
            aggregate_type=AGGREGATE_TYPE,
            aggregate_id=str(skill.id),
            event_type=Topics.SKILL_CREATED,
            correlation_id=correlation_id,
        ),
        SkillCreated(
            metadata=create_event_metadata(settings.service_name, correlation_id),
            skill_id=str(skill.id),
            skill_snapshot=build_canonical_skill_snapshot(skill, provenance),
        ),
    )


async def publish_skill_created_batch(
    db: AsyncSession,
    skills: Sequence[tuple[SkillNode, SkillSeedProvenance | None]],
    *,
    correlation_id: str | None = None,
) -> list[UUID]:
    """Publish a batch of SKILL_CREATED events in one outbox insert."""
    if not skills:
        return []

    outbox = OutboxWriter(schema=SCHEMA_NAME)
    entry_ids = await outbox.write_events(
        db=db,
        entries=[_build_skill_created_request(skill, provenance, correlation_id) for skill, provenance in skills],
    )
    logger.debug("Wrote SKILL_CREATED batch to outbox", event_count=len(entry_ids))
    return entry_ids


logger = get_logger(__name__)
settings = get_settings()

AGGREGATE_TYPE = "skill"


def _map_review_status(db_status: str) -> ReviewStatus:
    """Map database review_status string to proto enum.

    Database stores lowercase strings ("pending", "approved"); proto enum
    names are uppercase (PENDING, APPROVED). Unknown values raise
    ``ValidationError`` rather than silently coercing to UNSPECIFIED.
    """
    try:
        return ReviewStatus[db_status.upper()]
    except KeyError as exc:
        raise ValidationError(
            field_name="review_status",
            invalid_value=db_status,
            constraint=f"must map to one of {[m.name for m in ReviewStatus]}",
        ) from exc


def _map_source(source_name: str | None) -> SkillSource:
    """Map provenance source_name to proto enum.

    Database stores lowercase source names ("tabiya", "nohiki"); proto enum
    names are uppercase (TABIYA, NOHIKI). A ``None`` source_name represents
    the explicit absence of provenance and maps to UNSPECIFIED. Any other
    unknown value raises ``ValidationError``.
    """
    if source_name is None:
        return SkillSource.UNSPECIFIED
    try:
        return SkillSource[source_name.upper()]
    except KeyError as exc:
        raise ValidationError(
            field_name="source_name",
            invalid_value=source_name,
            constraint=f"must map to one of {[m.name for m in SkillSource]}",
        ) from exc


def build_canonical_skill_snapshot(
    skill: SkillNode,
    provenance: SkillSeedProvenance | None = None,
) -> CanonicalSkill:
    """Build CanonicalSkill proto from database model.

    Args:
        skill: SkillNode database model.
        provenance: Optional provenance record for source mapping.

    Returns:
        CanonicalSkill proto message with all fields populated.

    """
    source = _map_source(provenance.source_name if provenance else None)

    return CanonicalSkill(
        id=str(skill.id),
        canonical_id=skill.normalized_text,
        normalized_text=skill.normalized_text,
        display_name=skill.display_name or "",
        description=skill.description or "",
        category=skill.category or "",
        subcategory=skill.subcategory or "",
        skill_type=skill.skill_type or "",
        reuse_level=skill.reuse_level or "",
        source=source,
        review_status=_map_review_status(skill.review_status),
        confidence_score=skill.confidence_score,
        mention_count=skill.mention_count,
        job_count=skill.job_count,
        profile_count=skill.profile_count,
    )


async def publish_skill_created(
    db: AsyncSession,
    skill: SkillNode,
    provenance: SkillSeedProvenance | None = None,
    *,
    correlation_id: str | None = None,
) -> UUID:
    """Publish SKILL_CREATED event via outbox (atomic with DB transaction).

    Writes event to outbox table within caller's transaction. Debezium CDC
    captures the outbox entry and publishes to Kafka after commit.

    Args:
        db: Active database session (caller manages transaction).
        skill: SkillNode being published.
        provenance: Optional provenance for source mapping.
        correlation_id: Optional correlation ID for distributed tracing.

    Returns:
        UUID of the outbox entry created.

    """
    outbox = OutboxWriter(schema=SCHEMA_NAME)
    params, event = _build_skill_created_request(skill, provenance, correlation_id)
    entry_id = await outbox.write_event(db=db, params=params, event=event)

    logger.debug(
        "Wrote SKILL_CREATED to outbox",
        skill_id=str(skill.id),
        entry_id=str(entry_id),
    )
    return entry_id
