"""One-shot publisher for sys.fct.schedule-tick.v1 (nohiki.sys.v1.ScheduleTick)."""

from __future__ import annotations

import asyncio
import os

from nohiki.sys.v1 import ScheduleTick
from nohiki_kafka_client import AutoKafkaClient, GlobalDLQConfig, Topics, create_event_metadata
from nohiki_kafka_client.config import ConsumerConfig, KafkaClientConfig, ObservabilityConfig

_MAX_BATCH_LIMIT = 2_147_483_647


async def _publish() -> None:
    """Publish a single ScheduleTick event to Kafka and cleanly shut down."""
    source_service = os.environ.get("SCHEDULE_TICK_SOURCE_SERVICE", "sys-tick-cronjob").strip()
    if not source_service:
        msg = "SCHEDULE_TICK_SOURCE_SERVICE must not be blank"
        raise ValueError(msg)

    kafka_bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
    if not kafka_bootstrap_servers:
        msg = "KAFKA_BOOTSTRAP_SERVERS is required and must not be blank"
        raise RuntimeError(msg)

    batch_limit_raw = os.environ.get("SCHEDULE_TICK_BATCH_LIMIT", "0").strip()

    try:
        batch_limit = int(batch_limit_raw)
    except ValueError as exc:
        msg = f"Invalid SCHEDULE_TICK_BATCH_LIMIT: {batch_limit_raw!r}"
        raise ValueError(msg) from exc

    if not 0 <= batch_limit <= _MAX_BATCH_LIMIT:
        msg = f"SCHEDULE_TICK_BATCH_LIMIT must be between 0 and {_MAX_BATCH_LIMIT}"
        raise ValueError(msg)

    tick = ScheduleTick(
        metadata=create_event_metadata(source_service),
        batch_limit=batch_limit,
    )

    client = AutoKafkaClient(
        KafkaClientConfig(
            bootstrap_servers=kafka_bootstrap_servers,
            consumer=ConsumerConfig(group_id=f"{source_service}-publisher"),
            dlq=GlobalDLQConfig(),
            observability=ObservabilityConfig(service_name=source_service),
            default_group_id=f"{source_service}-publisher",
        )
    )

    try:
        await client.publish(Topics.SYS_SCHEDULE_TICK, tick)
    finally:
        await client.close()


def main() -> None:
    """CLI entrypoint."""
    asyncio.run(_publish())


if __name__ == "__main__":
    main()
