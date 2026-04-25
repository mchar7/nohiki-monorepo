"""Behavior tests for the one-shot schedule tick publisher."""

from __future__ import annotations

import uuid
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.sys.v1 import ScheduleTick
from nohiki_kafka_client import Topics
from sys_tick_job import publish_schedule_tick


def _set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set an explicit valid publisher environment for each test."""
    monkeypatch.setenv("SCHEDULE_TICK_SOURCE_SERVICE", "scheduler-test")
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", "broker-a:9092,broker-b:9092")
    monkeypatch.setenv("SCHEDULE_TICK_BATCH_LIMIT", "37")


def _mock_client() -> MagicMock:
    """Create the broker-boundary fake used by publisher tests."""
    client = MagicMock()
    client.publish = AsyncMock()
    client.close = AsyncMock()
    return client


def test_main_publishes_one_complete_tick_and_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI publishes one correctly addressed tick and releases its Kafka client."""
    _set_valid_environment(monkeypatch)
    client = _mock_client()

    with patch.object(publish_schedule_tick, "AutoKafkaClient", return_value=client) as client_type:
        publish_schedule_tick.main()

    client.publish.assert_awaited_once()
    topic, tick = client.publish.await_args.args
    assert topic == Topics.SYS_SCHEDULE_TICK == "sys.fct.schedule-tick.v1"
    assert client.publish.await_args.kwargs == {}  # The producer contract therefore uses key=None.
    assert isinstance(tick, ScheduleTick)
    assert tick.batch_limit == 37
    assert tick.metadata.source_service == "scheduler-test"
    assert tick.metadata.version == "v1"
    assert tick.metadata.timestamp.tzinfo == UTC
    uuid.UUID(tick.metadata.event_id)
    client.close.assert_awaited_once_with()

    config = client_type.call_args.args[0]
    assert config.bootstrap_servers == "broker-a:9092,broker-b:9092"
    assert config.consumer.group_id == "scheduler-test-publisher"
    assert config.default_group_id == "scheduler-test-publisher"
    assert config.observability.service_name == "scheduler-test"


@pytest.mark.asyncio
async def test_publish_propagates_broker_failure_after_closing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed send remains visible to the job runner, but still closes the client."""
    _set_valid_environment(monkeypatch)
    failure = RuntimeError("broker rejected tick")
    client = _mock_client()
    client.publish.side_effect = failure

    with (
        patch.object(publish_schedule_tick, "AutoKafkaClient", return_value=client),
        pytest.raises(RuntimeError, match="broker rejected tick") as caught,
    ):
        await publish_schedule_tick._publish()

    assert caught.value is failure
    client.close.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("variable", "value", "error_type", "message"),
    [
        (
            "SCHEDULE_TICK_SOURCE_SERVICE",
            "   ",
            ValueError,
            "SCHEDULE_TICK_SOURCE_SERVICE must not be blank",
        ),
        (
            "KAFKA_BOOTSTRAP_SERVERS",
            "   ",
            RuntimeError,
            "KAFKA_BOOTSTRAP_SERVERS is required and must not be blank",
        ),
        (
            "SCHEDULE_TICK_BATCH_LIMIT",
            "many",
            ValueError,
            "Invalid SCHEDULE_TICK_BATCH_LIMIT: 'many'",
        ),
        (
            "SCHEDULE_TICK_BATCH_LIMIT",
            "2147483648",
            ValueError,
            "SCHEDULE_TICK_BATCH_LIMIT must be between 0 and 2147483647",
        ),
    ],
)
async def test_invalid_event_configuration_fails_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
    error_type: type[Exception],
    message: str,
) -> None:
    """Invalid event or broker inputs fail deterministically without opening Kafka."""
    _set_valid_environment(monkeypatch)
    monkeypatch.setenv(variable, value)

    with (
        patch.object(publish_schedule_tick, "AutoKafkaClient") as client_type,
        pytest.raises(error_type, match=message),
    ):
        await publish_schedule_tick._publish()

    client_type.assert_not_called()
