"""Integration tests for Debezium CDC infrastructure.

These tests verify that:
1. OutboxWriter correctly inserts events into the outbox table
2. Debezium CDC captures outbox inserts and publishes to Kafka
3. Events are routed to the correct topic based on the `type` field
4. Payload is correctly extracted and preserved

Prerequisite: a running container runtime that Testcontainers can access.

Run with:
    pytest -m requires_docker tests/integration/test_debezium_cdc.py -v
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator

    from aiokafka import AIOKafkaConsumer
    from testcontainers.core.network import Network


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_docker,
    pytest.mark.asyncio,
    pytest.mark.timeout(180),
]


# Test configuration
TEST_TOPIC_PREFIX = "test.cdc"
OUTBOX_CONNECTOR_SUFFIX = "-outbox"
DEBEZIUM_CONNECT_IMAGE = (
    "quay.io/debezium/connect:3.6.0.Final@sha256:698f0559e667a242f962221079e75917b2b7a3ad4de62661e977628da0e33b45"
)
CONNECTOR_CLASS = "io.debezium.connector.postgresql.PostgresConnector"
# Connect scans every plugin directory before it serves REST; all 40 bundled connectors outlast the readiness budget.
CONNECTOR_PLUGIN_DIR = "/kafka/connect/debezium-connector-postgres"
CONNECT_API_READY_TIMEOUT_SECONDS = 15.0
CONNECTOR_READY_TIMEOUT_SECONDS = 15.0
PROBE_TIMEOUT_SECONDS = 1.0
POLL_INTERVAL_SECONDS = 0.5


def _is_canonical_outbox_connector_name(name: str) -> bool:
    """Return whether a connector follows Helm's <service>-outbox name."""
    return name.endswith(OUTBOX_CONNECTOR_SUFFIX) and name != OUTBOX_CONNECTOR_SUFFIX


@dataclass(frozen=True, slots=True)
class ContainerEnvironment:
    """Host and container-network access to the CDC dependencies."""

    kafka_bootstrap_servers: str
    postgres_url: str
    network: Network


@dataclass(frozen=True, slots=True)
class CdcEnvironment:
    """Endpoints for one self-provisioned CDC stack."""

    kafka_bootstrap_servers: str
    connect_url: str


@pytest.fixture(scope="module")
def container_environment() -> Generator[ContainerEnvironment]:
    """Provision Kafka and logical-replication PostgreSQL on one network."""
    from nohiki_db_utils.testing import POSTGRES_CONTAINER_COMMAND, POSTGRES_CONTAINER_IMAGE
    from nohiki_kafka_client.testing import KAFKA_CONTAINER_IMAGE
    from testcontainers.core.network import Network
    from testcontainers.kafka import KafkaContainer
    from testcontainers.postgres import PostgresContainer

    with Network() as network:
        postgres = PostgresContainer(POSTGRES_CONTAINER_IMAGE).with_network(network).with_network_aliases("postgres")
        postgres.with_command(POSTGRES_CONTAINER_COMMAND)
        kafka = KafkaContainer(KAFKA_CONTAINER_IMAGE).with_kraft().with_network(network).with_network_aliases("kafka")
        kafka.with_env("KAFKA_AUTO_CREATE_TOPICS_ENABLE", "true")
        with postgres, kafka:
            postgres_url = postgres.get_connection_url().replace("postgresql+psycopg2://", "postgresql+asyncpg://")
            yield ContainerEnvironment(kafka.get_bootstrap_server(), postgres_url, network)


@pytest_asyncio.fixture
async def async_engine(container_environment: ContainerEnvironment) -> AsyncGenerator[AsyncEngine]:
    """Create an async engine for the isolated logical-replication database."""
    engine = create_async_engine(container_environment.postgres_url, echo=False)
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


def _connect_api_is_ready(connect_url: str, *, timeout_seconds: float = PROBE_TIMEOUT_SECONDS) -> bool:
    """Report whether Kafka Connect serves REST and has loaded the connector under test."""
    try:
        with urlopen(f"{connect_url}/connector-plugins", timeout=timeout_seconds) as response:  # noqa: S310
            plugins = json.load(response)
    except HTTPError as exc:
        exc.close()
        return False
    except OSError, URLError, ValueError:
        return False
    return any(plugin.get("class") == CONNECTOR_CLASS for plugin in plugins)


async def _wait_for_connect_api(
    connect_url: str,
    *,
    timeout_seconds: float = CONNECT_API_READY_TIMEOUT_SECONDS,
) -> bool:
    """Wait up to one wall-clock budget for the Kafka Connect REST API."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while (remaining := deadline - loop.time()) > 0:
        try:
            ready = await asyncio.wait_for(
                asyncio.to_thread(
                    _connect_api_is_ready,
                    connect_url,
                    timeout_seconds=min(PROBE_TIMEOUT_SECONDS, remaining),
                ),
                timeout=remaining,
            )
        except TimeoutError:
            return False
        if ready:
            return True
        remaining = deadline - loop.time()
        if remaining > 0:
            await asyncio.sleep(min(POLL_INTERVAL_SECONDS, remaining))
    return False


def _register_test_connector(connect_url: str, postgres_container: str) -> str:
    """Register the isolated outbox connector used by the CDC contract."""
    database = urlparse(postgres_container)
    connector_name = f"nohiki-test{OUTBOX_CONNECTOR_SUFFIX}"
    connector = {
        "name": connector_name,
        "config": {
            "connector.class": CONNECTOR_CLASS,
            "tasks.max": "1",
            "database.hostname": "postgres",
            "database.port": "5432",
            "database.user": database.username,
            "database.password": database.password,
            "database.dbname": database.path.removeprefix("/"),
            "topic.prefix": "nohiki_test",
            "plugin.name": "pgoutput",
            "slot.name": "nohiki_test_outbox_slot",
            "publication.name": "nohiki_test_outbox_pub",
            "publication.autocreate.mode": "filtered",
            "schema.include.list": "outbox_schema",
            "table.include.list": "outbox_schema.outbox",
            "tombstones.on.delete": "false",
            "snapshot.mode": "when_needed",
            "transforms": "outbox",
            "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
            "transforms.outbox.table.field.event.id": "id",
            "transforms.outbox.table.field.event.key": "aggregateid",
            "transforms.outbox.table.field.event.type": "type",
            "transforms.outbox.table.field.event.payload": "payload",
            "transforms.outbox.route.by.field": "type",
            "transforms.outbox.route.topic.replacement": "${routedByValue}",
            "key.converter": "org.apache.kafka.connect.storage.StringConverter",
            "value.converter": "io.debezium.converters.BinaryDataConverter",
            "value.converter.delegate.converter.type": "org.apache.kafka.connect.json.JsonConverter",
            "value.converter.delegate.converter.type.schemas.enable": "false",
            "topic.creation.enable": "true",
            "topic.creation.default.replication.factor": "1",
            "topic.creation.default.partitions": "1",
        },
    }
    request = Request(  # noqa: S310 -- fixed local testcontainer endpoint
        f"{connect_url}/connectors",
        data=json.dumps(connector).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=5.0) as response:  # noqa: S310
            if response.status != 201:
                msg = f"Kafka Connect registration returned HTTP {response.status}"
                raise RuntimeError(msg)
    except HTTPError as exc:
        with exc:
            diagnostics = exc.read().decode(errors="replace")
        msg = f"Kafka Connect rejected the connector: {diagnostics}"
        raise RuntimeError(msg) from exc
    return connector_name


def _connector_is_running(
    connect_url: str,
    name: str,
    *,
    timeout_seconds: float = PROBE_TIMEOUT_SECONDS,
) -> bool:
    """Return True when the self-provisioned connector and its tasks are running."""
    try:
        with urlopen(  # noqa: S310
            f"{connect_url}/connectors/{name}/status", timeout=timeout_seconds
        ) as response:
            payload = json.load(response)
    except HTTPError as exc:
        exc.close()
        return False
    except OSError, URLError:
        return False
    connector = payload.get("connector", {}) if isinstance(payload, dict) else {}
    tasks = payload.get("tasks", []) if isinstance(payload, dict) else []
    return connector.get("state") == "RUNNING" and bool(tasks) and all(task.get("state") == "RUNNING" for task in tasks)


async def _wait_for_connector_running(
    connect_url: str,
    name: str,
    *,
    timeout_seconds: float = CONNECTOR_READY_TIMEOUT_SECONDS,
) -> bool:
    """Wait up to one wall-clock budget for the connector and its tasks."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while (remaining := deadline - loop.time()) > 0:
        try:
            running = await asyncio.wait_for(
                asyncio.to_thread(
                    _connector_is_running,
                    connect_url,
                    name,
                    timeout_seconds=min(PROBE_TIMEOUT_SECONDS, remaining),
                ),
                timeout=remaining,
            )
        except OSError, URLError:
            running = False
        if running:
            return True
        remaining = deadline - loop.time()
        if remaining > 0:
            await asyncio.sleep(min(POLL_INTERVAL_SECONDS, remaining))
    return False


async def test_connect_readiness_waiters_enforce_wall_clock_budgets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Probe timeouts remain retryable without extending either total deadline."""

    def timeout_probe(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError

    monkeypatch.setitem(globals(), "urlopen", timeout_probe)
    assert not _connector_is_running("http://connect.invalid", "connector")

    def slow_probe(*_args: object, **_kwargs: object) -> bool:
        time.sleep(1)
        return False

    loop = asyncio.get_running_loop()
    monkeypatch.setitem(globals(), "_connect_api_is_ready", slow_probe)
    started = loop.time()
    assert not await _wait_for_connect_api("http://connect.invalid", timeout_seconds=0.05)
    assert loop.time() - started < 0.5

    monkeypatch.setitem(globals(), "_connector_is_running", slow_probe)
    started = loop.time()
    assert not await _wait_for_connector_running("http://connect.invalid", "connector", timeout_seconds=0.05)
    assert loop.time() - started < 0.5


@pytest.fixture
async def debezium_cdc_environment(
    ensure_outbox_schema: None,
    container_environment: ContainerEnvironment,
) -> AsyncGenerator[CdcEnvironment]:
    """Provision Kafka Connect and a running outbox connector for the CDC test."""
    from testcontainers.core.container import DockerContainer

    _ = ensure_outbox_schema
    kafka_bootstrap_servers = container_environment.kafka_bootstrap_servers
    suffix = uuid.uuid4().hex
    container = (
        DockerContainer(DEBEZIUM_CONNECT_IMAGE, command="start")
        .with_exposed_ports(8083)
        .with_network(container_environment.network)
        .with_network_aliases("connect")
    )
    container.with_envs(
        BOOTSTRAP_SERVERS="kafka:9092",
        GROUP_ID=f"nohiki-test-connect-{suffix}",
        CONFIG_STORAGE_TOPIC=f"_nohiki_test_connect_configs_{suffix}",
        OFFSET_STORAGE_TOPIC=f"_nohiki_test_connect_offsets_{suffix}",
        STATUS_STORAGE_TOPIC=f"_nohiki_test_connect_status_{suffix}",
        CONFIG_STORAGE_REPLICATION_FACTOR="1",
        OFFSET_STORAGE_REPLICATION_FACTOR="1",
        STATUS_STORAGE_REPLICATION_FACTOR="1",
        KEY_CONVERTER="org.apache.kafka.connect.storage.StringConverter",
        VALUE_CONVERTER="org.apache.kafka.connect.storage.StringConverter",
        REST_ADVERTISED_HOST_NAME="127.0.0.1",
        CONNECT_PLUGIN_PATH=CONNECTOR_PLUGIN_DIR,
    )
    try:
        await asyncio.to_thread(container.start)
        connect_url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(8083)}"
        if not await _wait_for_connect_api(connect_url):
            stdout, stderr = await asyncio.to_thread(container.get_logs)
            diagnostics = (stdout + stderr).decode(errors="replace")[-8000:]
            pytest.fail(f"Kafka Connect did not become ready at {connect_url}:\n{diagnostics}")
        connector_name = await asyncio.to_thread(
            _register_test_connector, connect_url, container_environment.postgres_url
        )
        if not await _wait_for_connector_running(connect_url, connector_name):
            pytest.fail(f"Debezium connector {connector_name} did not reach RUNNING")
        yield CdcEnvironment(kafka_bootstrap_servers, connect_url)
    finally:
        await asyncio.to_thread(container.stop)


class TestDebeziumConnector:
    """Tests for the self-provisioned Debezium connector."""

    @pytest.mark.integration
    @pytest.mark.slow
    async def test_cdc_captures_outbox_insert(
        self,
        db_session: AsyncSession,
        ensure_outbox_schema: None,
        debezium_cdc_environment: CdcEnvironment,
    ) -> None:
        """Verify Debezium captures outbox inserts and publishes to Kafka."""
        _ = ensure_outbox_schema  # Fixture dependency
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

        consumer = AIOKafkaConsumer(
            test_topic,
            bootstrap_servers=debezium_cdc_environment.kafka_bootstrap_servers,
            group_id=f"test-cdc-{test_id}",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        try:
            await consumer.start()
            assert await _poll_for_message(consumer, test_payload, timeout_seconds=30), (
                f"Debezium did not publish outbox event {test_id} to {test_topic}"
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
