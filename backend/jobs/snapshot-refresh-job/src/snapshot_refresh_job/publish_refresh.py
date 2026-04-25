"""One-shot publisher for snapshot refresh commands.

Publishes a SnapshotRefreshRequested event to trigger re-publication of
ECST snapshots from a CDC-publishing service.

Usage:
    KAFKA_BOOTSTRAP_SERVERS=localhost:29092 \
    REFRESH_TOPIC=job-listing.cmd.snapshot-refresh-requested.v1 \
    REFRESH_REASON="fix: location snapshot builder bug" \
    uv run python -m snapshot_refresh_job.publish_refresh

Optional:
    REFRESH_ENTITY_IDS=uuid1,uuid2,uuid3  (comma-separated), or REFRESH_ALL=true
"""

from __future__ import annotations

import asyncio
import os
import re

from nohiki.common.v1 import SnapshotRefreshRequested
from nohiki_kafka_client import AutoKafkaClient, GlobalDLQConfig, create_event_metadata
from nohiki_kafka_client.config import ConsumerConfig, KafkaClientConfig, ObservabilityConfig
from nohiki_observability import get_logger

logger = get_logger(__name__)

_SERVICE_NAME = "snapshot-refresh-job"
_REFRESH_TOPIC_SUFFIX = ".cmd.snapshot-refresh-requested.v1"
_MAX_KAFKA_TOPIC_LENGTH = 249
_MAX_ENTITY_IDS = 10_000
_MAX_ENTITY_IDS_BYTES = 900_000
_MAX_REASON_BYTES = 4_096
_TOPIC_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


def _require_env(name: str) -> str:
    """Read a required environment variable or raise with a clear message."""
    value = os.environ.get(name, "").strip()
    if not value:
        msg = f"{name} is required and must not be blank"
        raise RuntimeError(msg)
    return value


def _read_entity_ids() -> list[str]:
    """Read targeted IDs or require explicit confirmation for a full refresh."""
    raw = os.environ.get("REFRESH_ENTITY_IDS", "").strip()
    if len(raw.encode()) > _MAX_ENTITY_IDS_BYTES or raw.count(",") >= _MAX_ENTITY_IDS:
        msg = (
            f"REFRESH_ENTITY_IDS must contain at most {_MAX_ENTITY_IDS} IDs and "
            f"use at most {_MAX_ENTITY_IDS_BYTES} UTF-8 bytes"
        )
        raise ValueError(msg)
    refresh_all = os.environ.get("REFRESH_ALL", "").strip().lower()
    if refresh_all not in {"", "true", "false"}:
        msg = "REFRESH_ALL must be 'true' or 'false'"
        raise ValueError(msg)

    if raw and refresh_all == "true":
        msg = "REFRESH_ENTITY_IDS and REFRESH_ALL=true are mutually exclusive"
        raise ValueError(msg)
    if not raw:
        if refresh_all != "true":
            msg = "Set REFRESH_ENTITY_IDS or explicitly set REFRESH_ALL=true"
            raise RuntimeError(msg)
        return []

    entity_ids = [entity_id.strip() for entity_id in raw.split(",")]
    if any(not entity_id for entity_id in entity_ids):
        msg = "REFRESH_ENTITY_IDS must not contain empty entries"
        raise ValueError(msg)
    return list(dict.fromkeys(entity_ids))


def _build_event() -> tuple[str, SnapshotRefreshRequested]:
    """Build the refresh command from environment configuration.

    Returns:
        Tuple of (target_topic, event).

    """
    topic = _require_env("REFRESH_TOPIC")
    if (
        len(topic) > _MAX_KAFKA_TOPIC_LENGTH
        or _TOPIC_PATTERN.fullmatch(topic) is None
        or not topic.endswith(_REFRESH_TOPIC_SUFFIX)
    ):
        msg = (
            f"REFRESH_TOPIC must be a valid Kafka topic ending with "
            f"{_REFRESH_TOPIC_SUFFIX!r} and be at most "
            f"{_MAX_KAFKA_TOPIC_LENGTH} characters"
        )
        raise ValueError(msg)
    reason = _require_env("REFRESH_REASON")
    if len(reason.encode()) > _MAX_REASON_BYTES:
        msg = f"REFRESH_REASON must use at most {_MAX_REASON_BYTES} UTF-8 bytes"
        raise ValueError(msg)
    entity_ids = _read_entity_ids()

    event = SnapshotRefreshRequested(
        metadata=create_event_metadata(_SERVICE_NAME),
        entity_ids=entity_ids,
        reason=reason,
    )

    return topic, event


async def _publish() -> None:
    """Publish a single SnapshotRefreshRequested event and shut down."""
    bootstrap_servers = _require_env("KAFKA_BOOTSTRAP_SERVERS")
    topic, event = _build_event()

    logger.info(
        "Publishing snapshot refresh command",
        topic=topic,
        reason=event.reason,
        entity_count=len(event.entity_ids) or "all",
    )

    client = AutoKafkaClient(
        KafkaClientConfig(
            bootstrap_servers=bootstrap_servers,
            consumer=ConsumerConfig(group_id=f"{_SERVICE_NAME}-publisher"),
            dlq=GlobalDLQConfig(),
            observability=ObservabilityConfig(service_name=_SERVICE_NAME),
            default_group_id=f"{_SERVICE_NAME}-publisher",
        )
    )

    try:
        await client.publish(topic, event)
        logger.info("Snapshot refresh command published", topic=topic)
    finally:
        await client.close()


def main() -> None:
    """CLI entrypoint."""
    asyncio.run(_publish())


if __name__ == "__main__":
    main()
