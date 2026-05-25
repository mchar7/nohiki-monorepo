"""Behavior tests for read-only in-cluster PostgreSQL, Valkey, and Kafka clients."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg
import pytest
from aiokafka.errors import KafkaError
from health_check.platform import direct_clients


class _Cursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.description = object()
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.queries: list[str] = []
        self._cursor = _Cursor(rows)

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> _Cursor:
        self.queries.append(query)
        return self._cursor


@dataclass(frozen=True)
class _TopicPartition:
    topic: str
    partition: int


@dataclass(frozen=True)
class _CommittedOffset:
    offset: int


class _AdminClient:
    def __init__(
        self,
        bootstrap_servers: str,
        *,
        topics: set[str] | None = None,
        group_members: list[tuple[str, str]] | None = None,
        offsets: dict[_TopicPartition, _CommittedOffset] | None = None,
        start_error: BaseException | None = None,
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.topics = topics or set()
        self.group_members = group_members or []
        self.offsets = offsets or {}
        self.start_error = start_error
        self.started = False
        self.closed = False
        self.described_groups: list[list[str]] = []
        self.offset_groups: list[str] = []

    async def start(self) -> None:
        self.started = True
        if self.start_error is not None:
            raise self.start_error

    async def close(self) -> None:
        self.closed = True

    async def list_topics(self) -> set[str]:
        return self.topics

    async def describe_consumer_groups(self, groups: list[str]) -> list[SimpleNamespace]:
        self.described_groups.append(groups)
        response = (None, None, None, None, None, self.group_members)
        return [SimpleNamespace(groups=[response])]

    async def list_consumer_group_offsets(self, group: str) -> dict[_TopicPartition, _CommittedOffset]:
        self.offset_groups.append(group)
        return self.offsets


class _Consumer:
    def __init__(
        self,
        bootstrap_servers: str,
        end_offsets: dict[_TopicPartition, int],
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self._end_offsets = end_offsets
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def end_offsets(self, partitions: list[_TopicPartition]) -> dict[_TopicPartition, int]:
        assert partitions == list(self._end_offsets)
        return self._end_offsets


def test_psql_enforces_read_only_transaction_and_serializes_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection([(7, "ready"), (8, None)])
    connect = MagicMock(return_value=connection)
    monkeypatch.setenv("DATABASE_URL", "postgresql://health@postgres/nohiki")
    monkeypatch.setattr(direct_clients.psycopg, "connect", connect)

    result = direct_clients.psql("SELECT id, state FROM health", "|")

    assert result == (0, "7|ready\n8|\n", "")
    connect.assert_called_once_with("postgresql://health@postgres/nohiki", autocommit=True)
    assert connection.queries == [
        "SET default_transaction_read_only = on",
        "SELECT id, state FROM health",
    ]


@pytest.mark.parametrize(
    ("database_url", "failure", "expected_error"),
    [
        (None, None, "DATABASE_URL"),
        (
            "postgresql://health@postgres/nohiki",
            psycopg.OperationalError("read denied"),
            "read denied",
        ),
    ],
    ids=("missing-url", "database-error"),
)
def test_psql_maps_configuration_and_database_failures_to_typed_result(
    monkeypatch: pytest.MonkeyPatch,
    database_url: str | None,
    failure: BaseException | None,
    expected_error: str,
) -> None:
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setattr(
            direct_clients.psycopg,
            "connect",
            MagicMock(side_effect=failure),
        )

    code, stdout, stderr = direct_clients.psql("SELECT 1")

    assert (code, stdout) == (1, "")
    assert expected_error in stderr


@pytest.mark.parametrize(
    ("configured_url", "expected_url"),
    [
        ("redis://custom-valkey:6380/2", "redis://custom-valkey:6380/2"),
        (None, "redis://valkey:6379"),
    ],
    ids=("configured", "in-cluster-default"),
)
def test_valkey_info_uses_selected_service_url_and_stable_key_order(
    monkeypatch: pytest.MonkeyPatch,
    configured_url: str | None,
    expected_url: str,
) -> None:
    client = MagicMock()
    client.info.return_value = {"zeta": 2, "alpha": 1}
    from_url = MagicMock(return_value=client)
    if configured_url is None:
        monkeypatch.delenv("VALKEY_URL", raising=False)
    else:
        monkeypatch.setenv("VALKEY_URL", configured_url)
    monkeypatch.setattr(direct_clients.redis.Redis, "from_url", from_url)

    result = direct_clients.valkey_info()

    assert result == (0, "alpha:1\nzeta:2", "")
    from_url.assert_called_once_with(
        expected_url,
        socket_timeout=5,
        decode_responses=True,
    )


def test_valkey_info_maps_redis_failure_to_typed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        direct_clients.redis.Redis,
        "from_url",
        MagicMock(side_effect=direct_clients.redis.RedisError("valkey unavailable")),
    )

    result = direct_clients.valkey_info()

    assert result == (1, "", "valkey unavailable")


def test_kafka_topic_listing_is_sorted_and_closes_admin_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admins: list[_AdminClient] = []

    def admin_factory(*, bootstrap_servers: str) -> _AdminClient:
        admin = _AdminClient(
            bootstrap_servers,
            topics={"z-topic", "a-topic", "retry-events", "events-dlq"},
        )
        admins.append(admin)
        return admin

    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.nohiki.svc:9092")
    monkeypatch.setattr(direct_clients, "AIOKafkaAdminClient", admin_factory)

    result = direct_clients.kafka_command(["kafka-topics.sh", "--list"])

    assert result == (0, "a-topic\nevents-dlq\nretry-events\nz-topic\n", "")
    assert [(admin.bootstrap_servers, admin.started, admin.closed) for admin in admins] == [
        ("kafka.nohiki.svc:9092", True, True)
    ]


def test_kafka_group_description_reports_lag_and_closes_both_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partition = _TopicPartition("jobs", 0)
    admin = _AdminClient(
        "kafka.nohiki.svc:9092",
        group_members=[("consumer-1", "client-a")],
        offsets={partition: _CommittedOffset(4)},
    )
    consumers: list[_Consumer] = []

    def admin_factory(*, bootstrap_servers: str) -> _AdminClient:
        assert bootstrap_servers == "kafka.nohiki.svc:9092"
        return admin

    def consumer_factory(*, bootstrap_servers: str) -> _Consumer:
        consumer = _Consumer(bootstrap_servers, {partition: 9})
        consumers.append(consumer)
        return consumer

    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "kafka.nohiki.svc:9092")
    monkeypatch.setattr(direct_clients, "AIOKafkaAdminClient", admin_factory)
    monkeypatch.setattr(direct_clients, "AIOKafkaConsumer", consumer_factory)

    result = direct_clients.kafka_command(["kafka-consumer-groups", "--describe", "--group", "workers"])

    assert result == (
        0,
        "GROUP TOPIC PARTITION CURRENT-OFFSET LOG-END-OFFSET LAG CONSUMER-ID HOST CLIENT-ID\n"
        "workers jobs 0 4 9 5 consumer-1 - client-a\n",
        "",
    )
    assert admin.described_groups == [["workers"]]
    assert admin.offset_groups == ["workers"]
    assert admin.closed
    assert [(consumer.bootstrap_servers, consumer.started, consumer.stopped) for consumer in consumers] == [
        ("kafka.nohiki.svc:9092", True, True)
    ]


@pytest.mark.parametrize(
    ("args", "expected_error"),
    [
        ([], "unsupported read-only Kafka command: <empty>"),
        (
            ["kafka-topics", "--delete"],
            "unsupported read-only Kafka command: kafka-topics",
        ),
    ],
    ids=("empty", "mutating-command"),
)
def test_kafka_rejects_unsupported_commands_and_closes_admin(
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    expected_error: str,
) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "nohiki-kafka-bootstrap:9092")
    admin = _AdminClient("kafka:9092")

    def admin_factory(*, bootstrap_servers: str) -> _AdminClient:
        assert bootstrap_servers == "nohiki-kafka-bootstrap:9092"
        return admin

    monkeypatch.setattr(
        direct_clients,
        "AIOKafkaAdminClient",
        admin_factory,
    )

    result = direct_clients.kafka_command(args)

    assert result == (2, "", expected_error)
    assert admin.closed


def test_kafka_maps_client_failure_and_still_closes_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "nohiki-kafka-bootstrap:9092")
    admin = _AdminClient(
        "kafka:9092",
        start_error=KafkaError("broker unavailable"),
    )

    def admin_factory(*, bootstrap_servers: str) -> _AdminClient:
        assert bootstrap_servers == "nohiki-kafka-bootstrap:9092"
        return admin

    monkeypatch.setattr(
        direct_clients,
        "AIOKafkaAdminClient",
        admin_factory,
    )

    result = direct_clients.kafka_command(["kafka-topics", "--list"])

    assert result == (1, "", "KafkaError: broker unavailable")
    assert admin.closed
