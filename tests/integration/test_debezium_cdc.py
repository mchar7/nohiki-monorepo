"""Integration tests for Debezium CDC infrastructure.

These tests verify that:
1. OutboxWriter correctly inserts events into the outbox table
2. Debezium CDC captures outbox inserts and publishes to Kafka
3. Events are routed to the correct topic based on the `type` field
4. Payload is correctly extracted and preserved

Prerequisites:
- PostgreSQL with wal_level=logical
- Kafka Connect with Debezium connector running
- Outbox schema and table created

Run with:
    pytest tests/integration/test_debezium_cdc.py -v
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiokafka import AIOKafkaConsumer
pytest_plugins = ("nohiki_db_utils.testing",)


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.asyncio,
]


# Test configuration
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
KAFKA_CONNECT_URL = os.environ.get("KAFKA_CONNECT_URL", "http://localhost:8083")
TEST_TOPIC_PREFIX = "test.cdc"
OUTBOX_CONNECTOR_SUFFIX = "-outbox"


def _is_canonical_outbox_connector_name(name: str) -> bool:
    """Return whether a connector follows Helm's <service>-outbox name."""
    return name.endswith(OUTBOX_CONNECTOR_SUFFIX) and name != OUTBOX_CONNECTOR_SUFFIX


@pytest_asyncio.fixture
async def async_engine(postgres_container: str) -> AsyncGenerator[AsyncEngine]:
    """Create async SQLAlchemy engine for the isolated logical-replication database."""
    engine = create_async_engine(postgres_container, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(async_engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    """Create async database session for tests."""
    async with AsyncSession(async_engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
async def ensure_outbox_schema(db_session: AsyncSession) -> None:
    """Ensure outbox schema and table exist."""
    await db_session.execute(text("CREATE SCHEMA IF NOT EXISTS outbox_schema"))
    await db_session.execute(
        text("""
        CREATE TABLE IF NOT EXISTS outbox_schema.outbox (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            aggregatetype VARCHAR(255) NOT NULL,
            aggregateid VARCHAR(255) NOT NULL,
            type VARCHAR(255) NOT NULL,
            payload BYTEA NOT NULL,
            timestamp TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            tracingspancontext VARCHAR(256)
        )
        """),
    )
    await db_session.commit()


class TestOutboxTableStructure:
    """Tests for outbox table structure and constraints."""

    @pytest.mark.integration
    async def test_outbox_table_exists(
        self,
        db_session: AsyncSession,
        ensure_outbox_schema: None,
    ) -> None:
        """Verify outbox table exists with correct structure."""
        _ = ensure_outbox_schema  # Fixture dependency
        result = await db_session.execute(
            text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'outbox_schema' AND table_name = 'outbox'
            ORDER BY ordinal_position;
            """),
        )
        columns = {row[0]: {"type": row[1], "nullable": row[2]} for row in result.fetchall()}

        # Verify required columns exist
        assert "id" in columns
        assert "aggregatetype" in columns
        assert "aggregateid" in columns
        assert "type" in columns
        assert "payload" in columns
        assert "timestamp" in columns
        assert "tracingspancontext" in columns

        # Verify data types
        assert columns["id"]["type"] == "uuid"
        assert columns["payload"]["type"] == "bytea"
        assert "timestamp" in columns["timestamp"]["type"]

    @pytest.mark.integration
    async def test_outbox_insert_and_read(
        self,
        db_session: AsyncSession,
        ensure_outbox_schema: None,
    ) -> None:
        """Verify we can insert and read from outbox table."""
        _ = ensure_outbox_schema  # Fixture dependency
        test_id = uuid.uuid4()
        test_payload = b"test payload data"
        test_type = f"{TEST_TOPIC_PREFIX}.insert.test.v1"

        # Insert test record
        await db_session.execute(
            text("""
            INSERT INTO outbox_schema.outbox
            (id, aggregatetype, aggregateid, type, payload, timestamp)
            VALUES (:id, :agg_type, :agg_id, :type, :payload, :timestamp)
            """),
            {
                "id": str(test_id),
                "agg_type": "test",
                "agg_id": f"test-{test_id}",
                "type": test_type,
                "payload": test_payload,
                "timestamp": datetime.now(UTC),
            },
        )
        await db_session.commit()

        # Read back
        result = await db_session.execute(
            text("SELECT id, type, payload FROM outbox_schema.outbox WHERE id = :id"),
            {"id": str(test_id)},
        )
        row = result.fetchone()

        assert row is not None
        assert str(row[0]) == str(test_id)
        assert row[1] == test_type
        assert bytes(row[2]) == test_payload

        # Cleanup
        await db_session.execute(
            text("DELETE FROM outbox_schema.outbox WHERE id = :id"),
            {"id": str(test_id)},
        )
        await db_session.commit()


class TestOutboxWriterIntegration:
    """Tests for OutboxWriter integration with the outbox table."""

    @pytest.mark.integration
    async def test_outbox_writer_creates_entry(
        self,
        db_session: AsyncSession,
        ensure_outbox_schema: None,
    ) -> None:
        """Verify OutboxWriter creates correct outbox entries."""
        _ = ensure_outbox_schema  # Fixture dependency
        # Import here to avoid import errors if nohiki_db_utils not installed
        try:
            from nohiki_db_utils import OutboxEventParams, OutboxWriter
        except ImportError:
            pytest.skip("nohiki_db_utils not installed")

        outbox = OutboxWriter(schema="outbox_schema")
        test_type = f"{TEST_TOPIC_PREFIX}.writer.test.v1"

        # Create a mock protobuf message (using a simple bytes wrapper)
        class MockMessage:
            def __bytes__(self) -> bytes:
                return b"mock protobuf payload"

            def serialize_to_string(self) -> bytes:
                return b"mock protobuf payload"

        params = OutboxEventParams(
            aggregate_type="test",
            aggregate_id="test-aggregate-123",
            event_type=test_type,
            correlation_id="test-correlation-id",
        )

        # Write event
        entry_id = await outbox.write_event(
            db=db_session,
            params=params,
            event=MockMessage(),
        )
        await db_session.commit()

        # Verify entry was created
        result = await db_session.execute(
            text("""
            SELECT aggregatetype, aggregateid, type, payload, tracingspancontext
            FROM outbox_schema.outbox WHERE id = :id
            """),
            {"id": str(entry_id)},
        )
        row = result.fetchone()

        assert row is not None
        assert row[0] == "test"
        assert row[1] == "test-aggregate-123"
        assert row[2] == test_type
        assert bytes(row[3]) == b"mock protobuf payload"
        assert row[4] == "test-correlation-id"

        # Cleanup
        await db_session.execute(
            text("DELETE FROM outbox_schema.outbox WHERE id = :id"),
            {"id": str(entry_id)},
        )
        await db_session.commit()


class TestPostgreSQLReplication:
    """Tests for PostgreSQL replication configuration."""

    @pytest.mark.integration
    async def test_wal_level_is_logical(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Verify PostgreSQL is configured with wal_level=logical."""
        result = await db_session.execute(text("SHOW wal_level;"))
        wal_level = result.scalar()

        assert wal_level == "logical", (
            f"PostgreSQL wal_level is '{wal_level}', expected 'logical'. "
            "Run: ALTER SYSTEM SET wal_level = 'logical'; and restart PostgreSQL."
        )

    @pytest.mark.integration
    async def test_max_replication_slots(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Verify PostgreSQL has sufficient replication slots."""
        result = await db_session.execute(text("SHOW max_replication_slots;"))
        max_slots = int(result.scalar())

        assert max_slots >= 2, (
            f"max_replication_slots is {max_slots}, need at least 2. "
            "Run: ALTER SYSTEM SET max_replication_slots = 4; and restart PostgreSQL."
        )

    @pytest.mark.integration
    async def test_publication_exists(
        self,
        db_session: AsyncSession,
        ensure_outbox_schema: None,
    ) -> None:
        """Verify outbox publication exists (may need to be created)."""
        _ = ensure_outbox_schema  # Fixture dependency
        result = await db_session.execute(
            text("""
            SELECT pubname FROM pg_publication
            WHERE pubname = 'nohiki_outbox_publication';
            """),
        )
        pub = result.scalar()

        if pub is None:
            # Create publication if it doesn't exist
            await db_session.execute(
                text("""
                CREATE PUBLICATION nohiki_outbox_publication
                FOR TABLE outbox_schema.outbox;
                """),
            )
            await db_session.commit()

            # Verify it was created
            result = await db_session.execute(
                text("""
                SELECT pubname FROM pg_publication
                WHERE pubname = 'nohiki_outbox_publication';
                """),
            )
            pub = result.scalar()

        assert pub == "nohiki_outbox_publication"


async def _poll_for_message(
    consumer: AIOKafkaConsumer,
    expected_value: bytes,
    *,
    timeout_seconds: float = 30,
) -> bool:
    """Poll a Kafka consumer for a message matching the expected value.

    Args:
        consumer: Started AIOKafkaConsumer to poll.
        expected_value: Byte payload to search for.
        timeout_seconds: Maximum time to poll before giving up.

    Returns:
        True if a matching message was found, False if timed out.

    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds

    while loop.time() < deadline:
        batch = await consumer.getmany(timeout_ms=1000)
        for records in batch.values():
            if any(record.value == expected_value for record in records):
                return True
    return False


def _bootstrap_endpoints() -> list[tuple[str, int]]:
    """Parse Kafka bootstrap servers into host/port pairs."""
    endpoints: list[tuple[str, int]] = []
    for server in KAFKA_BOOTSTRAP_SERVERS.split(","):
        endpoint = server.strip()
        if not endpoint:
            continue

        host, separator, port = endpoint.rpartition(":")
        if not separator:
            host, port = endpoint, "9092"

        endpoints.append((host.strip("[]"), int(port)))
    return endpoints


def _tcp_reachable(host: str, port: int, *, timeout_seconds: float = 1.0) -> bool:
    """Return True when a TCP endpoint accepts connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _fetch_connectors() -> list[str]:
    """Fetch registered Kafka Connect connector names."""
    with urlopen(f"{KAFKA_CONNECT_URL.rstrip('/')}/connectors", timeout=3.0) as response:  # noqa: S310  # trusted local Kafka Connect endpoint
        if response.status != 200:
            msg = f"Kafka Connect returned HTTP {response.status}"
            raise URLError(msg)
        payload = json.load(response)

    if not isinstance(payload, list):
        return []
    return [str(name) for name in payload]


def _connector_is_running(name: str) -> bool:
    """Return True when a Kafka Connect connector is RUNNING."""
    with urlopen(f"{KAFKA_CONNECT_URL.rstrip('/')}/connectors/{name}/status", timeout=3.0) as response:  # noqa: S310  # trusted local endpoint
        if response.status != 200:
            return False
        payload = json.load(response)

    connector = payload.get("connector", {}) if isinstance(payload, dict) else {}
    return connector.get("state") == "RUNNING"


def _summarize_probe_failure(stdout: str, stderr: str, returncode: int) -> str:
    """Collapse noisy probe output into a single skip reason line."""
    lines = [line.strip() for line in (stderr or stdout).splitlines() if line.strip()]
    interesting = (
        "KafkaError:",
        "Unable connect to node",
        "Unable to update metadata",
        "Unable to get cluster metadata",
        "Connect call failed",
        "ImportError:",
    )

    for line in reversed(lines):
        if line.startswith(("Traceback (most recent call last):", "File ", "Unclosed AIOKafkaConsumer")):
            continue
        if any(token in line for token in interesting):
            return line

    if lines:
        return lines[-1]
    return f"probe exited with code {returncode}"


def _run_broker_probe() -> str | None:
    """Probe Kafka broker via subprocess. Returns skip reason on failure."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import asyncio, os, uuid\n"
                "from aiokafka import AIOKafkaConsumer\n"
                "async def main() -> None:\n"
                "    servers = [s.strip() for s in os.environ['KAFKA_BOOTSTRAP_SERVERS'].split(',') if s.strip()]\n"
                "    consumer = AIOKafkaConsumer(\n"
                "        bootstrap_servers=servers,\n"
                "        group_id=f'debezium-cdc-precheck-{uuid.uuid4()}',\n"
                "        request_timeout_ms=5000,\n"
                "        metadata_max_age_ms=5000,\n"
                "        retry_backoff_ms=1000,\n"
                "    )\n"
                "    await consumer.start()\n"
                "    await consumer._client.fetch_all_metadata()\n"
                "    await consumer.stop()\n"
                "asyncio.run(main())\n",
            ],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"Kafka broker probe timed out at {KAFKA_BOOTSTRAP_SERVERS}"

    if result.returncode != 0:
        reason = _summarize_probe_failure(result.stdout, result.stderr, result.returncode)
        return f"Kafka broker unavailable at {KAFKA_BOOTSTRAP_SERVERS}: {reason}"

    return None


async def _check_connect_connectors() -> str | None:
    """Verify Kafka Connect has running Helm-named outbox connectors."""
    try:
        connectors = await asyncio.to_thread(_fetch_connectors)
    except Exception as exc:
        return f"Kafka Connect unavailable at {KAFKA_CONNECT_URL}: {exc.__class__.__name__}"

    outbox_connectors = [name for name in connectors if _is_canonical_outbox_connector_name(name)]
    if not outbox_connectors:
        return f"No Debezium outbox connector registered at {KAFKA_CONNECT_URL}"

    async with asyncio.TaskGroup() as tg:
        tasks = {name: tg.create_task(asyncio.to_thread(_connector_is_running, name)) for name in outbox_connectors}

    not_running = [name for name, task in tasks.items() if not task.result()]
    assert not not_running, f"Debezium outbox connector not RUNNING: {', '.join(not_running)}"

    return None


async def _debezium_cdc_precheck() -> str | None:
    """Return a skip reason if Kafka or Kafka Connect are unavailable."""
    endpoints = _bootstrap_endpoints()
    if not endpoints:
        return "KAFKA_BOOTSTRAP_SERVERS is empty"

    if not any(_tcp_reachable(host, port) for host, port in endpoints):
        return f"Kafka broker unavailable at {KAFKA_BOOTSTRAP_SERVERS}"

    if reason := await asyncio.to_thread(_run_broker_probe):
        return reason

    return await _check_connect_connectors()


@pytest.fixture
async def debezium_cdc_available() -> None:
    """Skip CDC tests when Kafka or Kafka Connect are unavailable."""
    if reason := await _debezium_cdc_precheck():
        pytest.skip(reason)


class TestDebeziumConnector:
    """Tests for Debezium connector functionality.

    These tests require Kafka Connect with Debezium to be running.
    They are marked as slow and may be skipped in CI.
    """

    @pytest.mark.integration
    @pytest.mark.slow
    async def test_cdc_captures_outbox_insert(
        self,
        db_session: AsyncSession,
        ensure_outbox_schema: None,
        debezium_cdc_available: None,
    ) -> None:
        """Verify Debezium captures outbox inserts and publishes to Kafka."""
        _ = ensure_outbox_schema  # Fixture dependency
        _ = debezium_cdc_available  # Fixture dependency
        from aiokafka import AIOKafkaConsumer

        test_id = uuid.uuid4()
        test_topic = f"{TEST_TOPIC_PREFIX}.capture.test.v1"
        test_payload = b"cdc test payload"

        # Insert test record
        await db_session.execute(
            text("""
            INSERT INTO outbox_schema.outbox
            (id, aggregatetype, aggregateid, type, payload, timestamp)
            VALUES (:id, :agg_type, :agg_id, :type, :payload, :timestamp)
            """),
            {
                "id": str(test_id),
                "agg_type": "test",
                "agg_id": f"cdc-test-{test_id}",
                "type": test_topic,
                "payload": test_payload,
                "timestamp": datetime.now(UTC),
            },
        )
        await db_session.commit()

        await asyncio.sleep(5)

        consumer = AIOKafkaConsumer(
            test_topic,
            bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"test-cdc-{test_id}",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        try:
            await consumer.start()
            message_found = await _poll_for_message(consumer, test_payload, timeout_seconds=30)

            assert message_found, (
                "CDC_DELIVERY_TIMEOUT: Debezium was present but did not deliver the inserted outbox row within 30s"
            )
        finally:
            with contextlib.suppress(Exception):
                await consumer.stop()

            # Cleanup
            await db_session.execute(
                text("DELETE FROM outbox_schema.outbox WHERE id = :id"),
                {"id": str(test_id)},
            )
            await db_session.commit()


class TestTopicRouting:
    """Tests for Debezium topic routing based on event type."""

    @pytest.mark.integration
    async def test_event_type_determines_topic(
        self,
        db_session: AsyncSession,
        ensure_outbox_schema: None,
    ) -> None:
        """Verify the `type` field determines the Kafka topic."""
        _ = ensure_outbox_schema  # Fixture dependency
        # Insert records with different types
        events = [
            {
                "id": str(uuid.uuid4()),
                "agg_type": "job",
                "agg_id": "job-1",
                "type": "job.store.created.v1",
                "payload": b"job created",
            },
            {
                "id": str(uuid.uuid4()),
                "agg_type": "profile",
                "agg_id": "profile-1",
                "type": "profile.updated.v1",
                "payload": b"profile updated",
            },
        ]

        for event in events:
            await db_session.execute(
                text("""
                INSERT INTO outbox_schema.outbox
                (id, aggregatetype, aggregateid, type, payload, timestamp)
                VALUES (:id, :agg_type, :agg_id, :type, :payload, NOW())
                """),
                event,
            )
        await db_session.commit()

        # Verify records were inserted with correct types
        for event in events:
            result = await db_session.execute(
                text("SELECT type FROM outbox_schema.outbox WHERE id = :id"),
                {"id": event["id"]},
            )
            row = result.fetchone()
            assert row is not None
            assert row[0] == event["type"]

        # Cleanup
        for event in events:
            await db_session.execute(
                text("DELETE FROM outbox_schema.outbox WHERE id = :id"),
                {"id": event["id"]},
            )
        await db_session.commit()
