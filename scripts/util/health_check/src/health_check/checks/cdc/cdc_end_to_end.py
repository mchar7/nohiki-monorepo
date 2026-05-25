"""Health check: end-to-end CDC flow from outbox insert to Kafka delivery."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import (
    CDC_END_TO_END_INITIAL_WAIT_SECONDS,
    CDC_END_TO_END_MAX_WAIT_SECONDS,
    CDC_END_TO_END_POLL_INTERVAL_SECONDS,
    CDC_END_TO_END_TIMEOUT_SECONDS,
)
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="cdc_end_to_end",
    name="CDC End-to-End",
    category=CheckCategory.CDC,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"debezium_connectors", "postgres_connectivity"}),
    timeout_seconds=CDC_END_TO_END_TIMEOUT_SECONDS,
    description="Insert a test row into the outbox and verify it reaches Kafka.",
)

_PROBE_SCHEMA: Final[str] = "user_pref_schema"
_PROBE_AGGREGATE_TYPE: Final[str] = "health_check"
_PROBE_PAYLOAD_HEX: Final[str] = "7b7d"

_INSERT_QUERY: Final[str] = (
    f"INSERT INTO {_PROBE_SCHEMA}.outbox (aggregatetype, aggregateid, type, payload) "
    "VALUES ('{aggregate_type}', '{row_id}', '{probe_topic}', DECODE('{payload_hex}', 'hex'))"
)
_CLEANUP_QUERY: Final[str] = f"DELETE FROM {_PROBE_SCHEMA}.outbox WHERE aggregatetype = '{_PROBE_AGGREGATE_TYPE}'"
_CONSUME_TIMEOUT_MS: Final[int] = 8000
_CONSUME_EXEC_TIMEOUT_SECONDS: Final[int] = _CONSUME_TIMEOUT_MS // 1000 + 6


async def _insert_test_row(platform: Platform, row_id: str, probe_topic: str) -> bool:
    """Insert a test row into the outbox table.

    The ``probe_topic`` value becomes the Kafka topic name via the Debezium
    outbox event router's ``route.by.field = type`` mapping.

    Args:
        platform: Active platform for psql execution.
        row_id: UUID string used as the row identifier and Kafka message key.
        probe_topic: Unique Kafka topic name for this probe run.

    Returns:
        True if the insert succeeded.
    """
    query = _INSERT_QUERY.format(
        aggregate_type=_PROBE_AGGREGATE_TYPE,
        row_id=row_id,
        probe_topic=probe_topic,
        payload_hex=_PROBE_PAYLOAD_HEX,
    )
    code, _, _ = await asyncio.to_thread(platform.exec_psql, query)
    return code == 0


async def _poll_kafka_for_row(
    platform: Platform,
    row_id: str,
    probe_topic: str,
) -> bool:
    """Poll Kafka for the test message up to CDC_END_TO_END_MAX_WAIT_SECONDS.

    Uses a per-run unique ``probe_topic`` so there is never more than one message
    in the topic. ``--max-messages 1`` ensures the consumer exits cleanly (code 0)
    immediately after reading the probe message, flushing Java's buffered stdout.
    Without ``--max-messages``, stdout is only flushed on JVM shutdown, which may
    not happen before the subprocess timeout when the topic is slow to populate.

    Caller is responsible for waiting ``CDC_END_TO_END_INITIAL_WAIT_SECONDS`` before
    calling this function so that Debezium has time to process the outbox change.

    Args:
        platform: Active platform for Kafka CLI execution.
        row_id: The aggregateid inserted into the outbox; present in the key output.
        probe_topic: Unique per-run topic derived from ``row_id``.

    Returns:
        True if the message was found within the wait window.
    """
    deadline = time.monotonic() + CDC_END_TO_END_MAX_WAIT_SECONDS
    while time.monotonic() < deadline:
        _code, stdout, _ = await asyncio.to_thread(
            platform.exec_kafka_cmd,
            [
                "kafka-console-consumer",
                "--bootstrap-server",
                platform.kafka_bootstrap_server,
                "--topic",
                probe_topic,
                "--from-beginning",
                "--max-messages",
                "1",
                "--timeout-ms",
                str(_CONSUME_TIMEOUT_MS),
                "--property",
                "print.key=true",
            ],
            timeout=_CONSUME_EXEC_TIMEOUT_SECONDS,
        )
        if row_id in stdout:
            return True
        await asyncio.sleep(CDC_END_TO_END_POLL_INTERVAL_SECONDS)
    return False


async def _cleanup(platform: Platform) -> None:
    """Remove health-check test rows from the outbox."""
    await asyncio.to_thread(platform.exec_psql, _CLEANUP_QUERY)


class CdcEndToEndCheck(HealthCheck):
    """Verify the full CDC pipeline by inserting an outbox row and confirming Kafka delivery."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the CDC end-to-end test."""
        row_id = str(uuid.uuid4())
        probe_topic = f"health-check-probe.{row_id}"

        if not await _insert_test_row(platform, row_id, probe_topic):
            return self._make_result(
                CheckStatus.ERROR,
                f"Cannot insert test row into {_PROBE_SCHEMA}.outbox",
                remediation_hint=(
                    f"Verify PostgreSQL connectivity and {_PROBE_SCHEMA} exists. Ensure service migrations have run."
                ),
            )

        await asyncio.sleep(CDC_END_TO_END_INITIAL_WAIT_SECONDS)

        try:
            delivered = await _poll_kafka_for_row(platform, row_id, probe_topic)
        finally:
            await _cleanup(platform)

        if not delivered:
            return self._make_result(
                CheckStatus.FAILED,
                f"CDC message not delivered within {CDC_END_TO_END_MAX_WAIT_SECONDS:.0f}s",
                remediation_hint="Check Debezium connector status and replication slot activity",
            )
        return self._make_result(CheckStatus.PASSED, "CDC pipeline delivered test event end-to-end")
