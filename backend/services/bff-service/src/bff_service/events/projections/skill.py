"""Skill domain projection handlers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from nohiki.skill.v1 import SkillCreated
from nohiki_kafka_client import MessageContext, Topics
from nohiki_observability import get_logger
from sqlalchemy.dialects.postgresql import insert

from bff_service.core.kafka import kafka_client
from bff_service.db.models import SkillProjection
from bff_service.events.projections._constants import projection_bulk_group_id

logger = get_logger(__name__)


def _extract_skill_source_name(source: object) -> str:
    """Extract skill source enum name safely."""
    if not source:
        return "UNSPECIFIED"
    return str(source.name) if hasattr(source, "name") else "UNSPECIFIED"


@kafka_client.message_handler(
    Topics.SKILL_CREATED, SkillCreated, group_id=projection_bulk_group_id, preserve_partition_order=False
)
@kafka_client.with_db_session()
async def handle_skill_created(message: SkillCreated, context: MessageContext) -> None:
    """Handle skill created event - create projection for skill search."""
    snapshot = message.skill_snapshot
    if snapshot is None:
        logger.warning("SkillCreated missing skill_snapshot")
        return

    now = datetime.now(UTC)
    skill_id = UUID(snapshot.id)

    session = context.require_db_session()
    stmt = (
        insert(SkillProjection)
        .values(
            id=skill_id,
            canonical_id=snapshot.canonical_id,
            normalized_text=snapshot.normalized_text,
            display_name=snapshot.display_name or None,
            description=snapshot.description or None,
            category=snapshot.category or None,
            subcategory=snapshot.subcategory or None,
            skill_type=snapshot.skill_type or None,
            reuse_level=snapshot.reuse_level or None,
            source=_extract_skill_source_name(snapshot.source),
            mention_count=snapshot.mention_count,
            job_count=snapshot.job_count,
            profile_count=snapshot.profile_count,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "normalized_text": snapshot.normalized_text,
                "display_name": snapshot.display_name or None,
                "description": snapshot.description or None,
                "category": snapshot.category or None,
                "subcategory": snapshot.subcategory or None,
                "skill_type": snapshot.skill_type or None,
                "reuse_level": snapshot.reuse_level or None,
                "mention_count": snapshot.mention_count,
                "job_count": snapshot.job_count,
                "profile_count": snapshot.profile_count,
                "updated_at": now,
            },
        )
    )
    await session.execute(stmt)
    logger.debug("Skill projection created/updated", skill_id=str(skill_id), name=snapshot.normalized_text)
