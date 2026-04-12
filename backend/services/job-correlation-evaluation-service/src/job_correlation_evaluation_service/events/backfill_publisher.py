"""Publisher for backfill request events."""

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from nohiki.common.v1 import CommandHeader
from nohiki.job.listing.v1 import BackfillRequested
from nohiki_kafka_client import CallbackStateMixin, Topics, create_event_metadata
from nohiki_observability import get_logger
from sqlalchemy import text

from job_correlation_evaluation_service.core.config import get_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)
settings = get_settings()
AGGREGATE_TYPE: Final[str] = "profile_backfill"
_EMIT_TRANSACTIONAL_WAL = text("SELECT pg_logical_emit_message(true, CAST(:prefix AS text), CAST(:content AS bytea))")


@dataclass(frozen=True, slots=True)
class BackfillCallerContext(CallbackStateMixin):
    """Typed state echoed by job-storage-service in backfill callbacks."""

    force_rescore: bool = False


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    """Stable input identity and payload for one backfill command."""

    pref_id: str
    user_id: str
    correlation_id: str
    operation_id: str
    force_rescore: bool = False


async def publish_backfill_request(db: AsyncSession, request: BackfillRequest) -> str:
    """Emit a deterministic backfill command in the caller's transaction."""
    backfill_config = settings.backfill
    metadata = create_event_metadata(settings.service_name, request.correlation_id)
    event = BackfillRequested(
        metadata=metadata,
        command=CommandHeader(
            operation_id=request.operation_id,
            callback_topic=backfill_config.callback_topic,
            caller_context=BackfillCallerContext(force_rescore=request.force_rescore).to_bytes(),
        ),
        pref_id=request.pref_id,
        user_id=request.user_id,
        max_listings=backfill_config.max_listings,
        since_days=backfill_config.since_days,
    )
    prefix = json.dumps(
        {
            "id": str(metadata.event_id),
            "topic": Topics.JOB_LISTING_BACKFILL_REQUESTED,
            "aggregate_id": request.operation_id,
            "aggregate_type": AGGREGATE_TYPE,
            "correlation_id": request.correlation_id or None,
        },
        separators=(",", ":"),
    )
    await db.execute(_EMIT_TRANSACTIONAL_WAL, {"prefix": prefix, "content": bytes(event)})
    logger.info(
        "Emitted backfill request to transactional WAL",
        operation_id=request.operation_id,
        pref_id=request.pref_id,
        user_id=request.user_id,
        correlation_id=request.correlation_id,
    )
    return request.operation_id
