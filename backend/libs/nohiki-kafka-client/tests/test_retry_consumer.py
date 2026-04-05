"""Unit tests for the RetryConsumer class."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiokafka import TopicPartition
from aiokafka.errors import KafkaError
from nohiki_kafka_client.config import KafkaClientConfig
from nohiki_kafka_client.consumer.retry_consumer import (
    RetryConsumer,
    _apply_backoff,
    _decode_headers,
    _decode_key,
    _dispatch_to_handler,
    _parse_next_retry_at,
    _parse_retry_count,
)


class TestDecodeHeaders:
    """Tests for _decode_headers helper."""

    def test_empty_headers(self) -> None:
        """Returns empty dict for None."""
        assert _decode_headers(None) == {}

    def test_empty_list(self) -> None:
        """Returns empty dict for empty list."""
        assert _decode_headers([]) == {}

    def test_decodes_bytes_to_str(self) -> None:
        """Decodes header byte values to UTF-8 strings."""
        raw = [("key1", b"value1"), ("key2", b"value2")]
        assert _decode_headers(raw) == {"key1": "value1", "key2": "value2"}

    def test_handles_invalid_utf8(self) -> None:
        """Replaces invalid UTF-8 bytes with replacement character."""
        raw = [("key", b"\xff\xfe")]
        result = _decode_headers(raw)
        assert "key" in result
        assert "\ufffd" in result["key"]


class TestDecodeKey:
    """Tests for _decode_key helper."""

    def test_none_key(self) -> None:
        """Returns None for None key."""
        assert _decode_key(None) is None

    def test_decodes_bytes(self) -> None:
        """Decodes bytes key to string."""
        assert _decode_key(b"my-key") == "my-key"


class TestParseRetryCount:
    """Tests for _parse_retry_count helper."""

    def test_default_zero(self) -> None:
        """Returns 0 when header is missing."""
        assert _parse_retry_count({}) == 0

    def test_valid_count(self) -> None:
        """Parses valid integer string."""
        assert _parse_retry_count({"x-retry-count": "3"}) == 3

    def test_invalid_count(self) -> None:
        """Returns 0 for non-integer values."""
        assert _parse_retry_count({"x-retry-count": "abc"}) == 0


class TestParseNextRetryAt:
    """Tests for _parse_next_retry_at helper."""

    def test_default_zero(self) -> None:
        """Returns 0.0 when header is missing."""
        assert _parse_next_retry_at({}) == pytest.approx(0.0)

    def test_valid_timestamp(self) -> None:
        """Parses valid float string."""
        assert _parse_next_retry_at({"x-next-retry-at": "1234567890.5"}) == pytest.approx(1234567890.5)

    def test_invalid_timestamp(self) -> None:
        """Returns 0.0 for non-float values."""
        assert _parse_next_retry_at({"x-next-retry-at": "not-a-float"}) == pytest.approx(0.0)


class TestApplyBackoff:
    """Tests for _apply_backoff async function."""

    @pytest.mark.asyncio
    async def test_no_sleep_when_past(self) -> None:
        """Does not sleep when next_retry_at is in the past."""
        past = time.time() - 10.0
        start = time.time()
        await _apply_backoff(past)
        elapsed = time.time() - start
        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_future_timestamp_is_uncapped_and_cancellable(self) -> None:
        """Honors a long delay and propagates cancellation without waiting."""
        sleep_started = asyncio.Event()
        observed_delays: list[float] = []

        async def _sleep(delay: float) -> None:
            observed_delays.append(delay)
            sleep_started.set()
            await asyncio.Event().wait()

        with (
            patch(
                "nohiki_kafka_client.consumer.retry_consumer.time.time",
                return_value=1_000.0,
            ),
            patch(
                "nohiki_kafka_client.consumer.retry_consumer.asyncio.sleep",
                side_effect=_sleep,
            ),
        ):
            task = asyncio.create_task(_apply_backoff(1_601.0))
            await sleep_started.wait()
            assert observed_delays == [pytest.approx(601.0)]
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


class TestDispatchToHandler:
    """Tests for _dispatch_to_handler module function."""

    @pytest.mark.asyncio
    async def test_dispatches_to_handler(self) -> None:
        """Deserializes message and calls handler with correct context."""
        mock_handler = AsyncMock()
        mock_handler.__name__ = "test_handler"
        mock_handler.__module__ = "test_module"

        mock_message_type = MagicMock()
        mock_instance = MagicMock()
        mock_message_type.return_value.parse.return_value = mock_instance

        registration = MagicMock()
        registration.message_type = mock_message_type
        registration.handler_func = mock_handler

        record = MagicMock()
        record.value = b"test-payload"
        record.topic = "test-group.retry"
        record.partition = 0
        record.offset = 42
        record.timestamp = 1000

        headers = {
            "x-original-topic": "my-topic.v1",
            "x-retry-count": "2",
        }

        await _dispatch_to_handler(record, registration, headers)

        mock_message_type.return_value.parse.assert_called_once_with(b"test-payload")
        mock_handler.assert_awaited_once()
        call_ctx = mock_handler.call_args[0][1]
        assert call_ctx.topic == "my-topic.v1"
        assert call_ctx.retry_count == 2

    @pytest.mark.asyncio
    async def test_handles_none_value(self) -> None:
        """Uses empty bytes when record.value is None."""
        mock_handler = AsyncMock()
        mock_handler.__name__ = "test_handler"
        mock_handler.__module__ = "test_module"

        mock_message_type = MagicMock()
        mock_message_type.return_value.parse.return_value = MagicMock()

        registration = MagicMock()
        registration.message_type = mock_message_type
        registration.handler_func = mock_handler

        record = MagicMock()
        record.value = None
        record.topic = "test-group.retry"
        record.partition = 0
        record.offset = 0
        record.timestamp = 0

        await _dispatch_to_handler(record, registration, {})

        mock_message_type.return_value.parse.assert_called_once_with(b"")


@pytest.fixture
def kafka_config() -> KafkaClientConfig:
    """Create a minimal KafkaClientConfig for testing."""
    return KafkaClientConfig(bootstrap_servers="localhost:29092")


def _retry_record(*, retry_at: float = 0.0) -> MagicMock:
    record = MagicMock()
    record.headers = [
        ("x-original-topic", b"my-topic.v1"),
        ("x-retry-count", b"1"),
        ("x-next-retry-at", str(retry_at).encode()),
    ]
    record.offset = 5
    record.partition = 0
    record.timestamp = 1_000
    record.value = b"payload"
    record.key = b"key"
    record.topic = "my-group.retry"
    return record


def _handler_registration(handler: AsyncMock) -> MagicMock:
    message_type = MagicMock()
    message_type.return_value.parse.return_value = MagicMock()
    registration = MagicMock()
    registration.message_type = message_type
    registration.handler_func = handler
    return registration


def _mock_consumer(*assigned: TopicPartition) -> MagicMock:
    consumer = MagicMock()
    consumer.start = AsyncMock()
    consumer.stop = AsyncMock()
    consumer.commit = AsyncMock()
    consumer.assignment.return_value = set(assigned)
    return consumer


class TestRetryConsumerInit:
    """Tests for RetryConsumer initialization."""

    def test_init_sets_topics(self, kafka_config: KafkaClientConfig) -> None:
        """RetryConsumer derives retry topic and consumer group from main group."""
        rc = RetryConsumer(
            consumer_group="my-service-handler-primary",
            handler_map={},
            config=kafka_config,
        )
        assert rc._retry_topic == "my-service-handler-primary.retry"
        assert rc._retry_consumer_group == "my-service-handler-primary.retry-cg"

    def test_init_stores_handler_map(self, kafka_config: KafkaClientConfig) -> None:
        """RetryConsumer stores the handler map for dispatch."""
        handler_map = {"topic.v1": MagicMock()}
        rc = RetryConsumer(
            consumer_group="my-group",
            handler_map=handler_map,
            config=kafka_config,
        )
        assert rc._handler_map is handler_map

    def test_stop_sets_event(self, kafka_config: KafkaClientConfig) -> None:
        """stop() signals the shutdown event."""
        rc = RetryConsumer(
            consumer_group="my-group",
            handler_map={},
            config=kafka_config,
        )
        assert not rc._shutdown_event.is_set()
        rc.stop()
        assert rc._shutdown_event.is_set()


class TestRetryConsumerStart:
    """Tests for RetryConsumer start/poll lifecycle."""

    @pytest.mark.asyncio
    async def test_startup_kafka_error_restarts_without_terminal_completion(
        self, kafka_config: KafkaClientConfig
    ) -> None:
        """A failed consumer startup is cleaned up before a fresh generation."""
        retry_consumer = RetryConsumer(consumer_group="my-group", handler_map={}, config=kafka_config)
        first = _mock_consumer()
        first.start.side_effect = KafkaError("startup failed")
        second = _mock_consumer()
        second_started = asyncio.Event()
        second.start.side_effect = second_started.set

        async def _blocking_records(
            _self: object = None,
        ) -> AsyncIterator[object]:
            await asyncio.Event().wait()
            yield

        second.__aiter__ = _blocking_records
        with (
            patch(
                "nohiki_kafka_client.consumer.retry_consumer.AIOKafkaConsumer",
                side_effect=[first, second],
            ),
            patch.object(retry_consumer, "_wait_for_restart", new=AsyncMock(return_value=False)) as wait_for_restart,
        ):
            task = asyncio.create_task(retry_consumer.start())
            await second_started.wait()
            assert not task.done()
            first.stop.assert_awaited_once()
            wait_for_restart.assert_awaited_once_with(0.5)

            retry_consumer.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        second.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_start_and_stop(self, kafka_config: KafkaClientConfig) -> None:
        """Cancellation propagates after its active generation stops."""
        retry_consumer = RetryConsumer(consumer_group="my-group", handler_map={}, config=kafka_config)
        poll_started = asyncio.Event()

        async def _blocking_records(
            _self: object = None,
        ) -> AsyncIterator[object]:
            poll_started.set()
            await asyncio.Event().wait()
            yield

        consumer = _mock_consumer()
        consumer.__aiter__ = _blocking_records
        with patch(
            "nohiki_kafka_client.consumer.retry_consumer.AIOKafkaConsumer",
            return_value=consumer,
        ):
            task = asyncio.create_task(retry_consumer.start())
            await poll_started.wait()
            retry_consumer.stop()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1.0)

        consumer.start.assert_awaited_once()
        consumer.stop.assert_awaited_once()
        assert retry_consumer._supervisor_task is None

    @pytest.mark.asyncio
    async def test_shutdown_cancels_owned_handler_before_consumer_stop(self, kafka_config: KafkaClientConfig) -> None:
        """Cancellation drains active retry work before closing its consumer."""
        handler_started = asyncio.Event()
        handler_cancelled = asyncio.Event()

        async def _handler(_message: object, _context: object) -> None:
            handler_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                handler_cancelled.set()

        retry_consumer = RetryConsumer(
            consumer_group="my-group",
            handler_map={"my-topic.v1": _handler_registration(AsyncMock(side_effect=_handler))},
            config=kafka_config,
        )
        consumer = _mock_consumer()

        async def _records(_self: object = None) -> AsyncIterator[object]:
            yield _retry_record()
            await asyncio.Event().wait()

        async def _stop() -> None:
            assert handler_cancelled.is_set()
            assert retry_consumer._inflight_tasks == set()

        consumer.__aiter__ = _records
        consumer.stop.side_effect = _stop
        with patch(
            "nohiki_kafka_client.consumer.retry_consumer.AIOKafkaConsumer",
            return_value=consumer,
        ):
            start_task = asyncio.create_task(retry_consumer.start())
            await handler_started.wait()
            retry_consumer.stop()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(start_task, timeout=1.0)

        consumer.stop.assert_awaited_once()
        assert retry_consumer._inflight_tasks == set()
        assert retry_consumer._consumer is None
        assert retry_consumer._supervisor_task is None

    @pytest.mark.asyncio
    async def test_unexpected_record_failure_cancels_generation_and_reaches_caller(
        self, kafka_config: KafkaClientConfig
    ) -> None:
        """A detached retry task failure cancels siblings before closing and propagating."""
        retry_consumer = RetryConsumer(consumer_group="my-group", handler_map={}, config=kafka_config)
        consumer = _mock_consumer()
        failing_record = _retry_record()
        sibling_record = _retry_record()
        sibling_record.partition = 1
        sibling_record.offset = 6
        sibling_started = asyncio.Event()
        sibling_cancelled = asyncio.Event()
        failure_message = "retry record task crashed"

        async def _records(_self: object = None) -> AsyncIterator[object]:
            yield failing_record
            yield sibling_record
            await asyncio.Event().wait()

        async def _process(record: MagicMock, _consumer: MagicMock) -> None:
            if record is failing_record:
                await sibling_started.wait()
                raise RuntimeError(failure_message)
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        async def _stop() -> None:
            assert sibling_cancelled.is_set()
            assert retry_consumer._inflight_tasks == set()

        consumer.__aiter__ = _records
        consumer.stop.side_effect = _stop
        with (
            patch(
                "nohiki_kafka_client.consumer.retry_consumer.AIOKafkaConsumer",
                return_value=consumer,
            ),
            patch.object(retry_consumer, "_process_retry_record", side_effect=_process),
            pytest.raises(RuntimeError, match="retry record task crashed"),
        ):
            await asyncio.wait_for(retry_consumer.start(), timeout=1.0)

        consumer.stop.assert_awaited_once()
        assert retry_consumer._consumer is None
        assert retry_consumer._supervisor_task is None

    @pytest.mark.asyncio
    async def test_poll_kafka_error_restarts_after_generation_cleanup(self, kafka_config: KafkaClientConfig) -> None:
        """A broker poll failure cannot permanently end retry processing."""
        retry_consumer = RetryConsumer(consumer_group="my-group", handler_map={}, config=kafka_config)
        first = _mock_consumer()
        second = _mock_consumer()
        second_started = asyncio.Event()
        second.start.side_effect = second_started.set

        poll_error = KafkaError("poll failed")

        async def _failed_poll(_self: object = None) -> AsyncIterator[object]:
            raise poll_error
            yield

        async def _blocking_poll(_self: object = None) -> AsyncIterator[object]:
            await asyncio.Event().wait()
            yield

        first.__aiter__ = _failed_poll
        second.__aiter__ = _blocking_poll
        with (
            patch(
                "nohiki_kafka_client.consumer.retry_consumer.AIOKafkaConsumer",
                side_effect=[first, second],
            ),
            patch.object(retry_consumer, "_wait_for_restart", new=AsyncMock(return_value=False)),
        ):
            task = asyncio.create_task(retry_consumer.start())
            await second_started.wait()
            assert not task.done()
            first.stop.assert_awaited_once()

            retry_consumer.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        second.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_normal_poll_exhaustion_restarts_instead_of_succeeding(self, kafka_config: KafkaClientConfig) -> None:
        """Unexpected iterator exhaustion is a restartable generation failure."""
        retry_consumer = RetryConsumer(consumer_group="my-group", handler_map={}, config=kafka_config)
        exhausted = _mock_consumer()
        replacement = _mock_consumer()
        replacement_started = asyncio.Event()
        replacement.start.side_effect = replacement_started.set

        async def _empty_poll(_self: object = None) -> AsyncIterator[object]:
            if False:
                yield

        async def _blocking_poll(_self: object = None) -> AsyncIterator[object]:
            await asyncio.Event().wait()
            yield

        exhausted.__aiter__ = _empty_poll
        replacement.__aiter__ = _blocking_poll
        with (
            patch(
                "nohiki_kafka_client.consumer.retry_consumer.AIOKafkaConsumer",
                side_effect=[exhausted, replacement],
            ),
            patch.object(retry_consumer, "_wait_for_restart", new=AsyncMock(return_value=False)),
        ):
            task = asyncio.create_task(retry_consumer.start())
            await replacement_started.wait()
            assert not task.done()
            exhausted.stop.assert_awaited_once()

            retry_consumer.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        replacement.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_repeated_startup_failures_use_capped_backoff_and_stay_observable(
        self, kafka_config: KafkaClientConfig
    ) -> None:
        """Repeated failures remain owned while restart delay caps at 30 seconds."""
        retry_consumer = RetryConsumer(consumer_group="my-group", handler_map={}, config=kafka_config)
        observed_backoffs: list[float] = []
        failures_observed = asyncio.Event()
        release_wait = asyncio.Event()
        consumers: list[MagicMock] = []

        def _consumer_factory(**_kwargs: object) -> MagicMock:
            consumer = _mock_consumer()
            consumer.start.side_effect = KafkaError("still unavailable")
            consumers.append(consumer)
            return consumer

        async def _wait(backoff: float) -> bool:
            observed_backoffs.append(backoff)
            if len(observed_backoffs) == 8:
                failures_observed.set()
                await release_wait.wait()
                return retry_consumer._shutdown_event.is_set()
            return False

        with (
            patch(
                "nohiki_kafka_client.consumer.retry_consumer.AIOKafkaConsumer",
                side_effect=_consumer_factory,
            ),
            patch.object(retry_consumer, "_wait_for_restart", side_effect=_wait),
        ):
            task = asyncio.create_task(retry_consumer.start())
            await failures_observed.wait()
            assert not task.done()
            assert observed_backoffs == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]
            assert len(consumers) == 8
            assert all(consumer.stop.await_count == 1 for consumer in consumers)

            retry_consumer.stop()
            release_wait.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_shutdown_interrupts_restart_backoff(self, kafka_config: KafkaClientConfig) -> None:
        """stop() releases a pending restart wait without wall-clock delay."""
        retry_consumer = RetryConsumer(consumer_group="my-group", handler_map={}, config=kafka_config)
        wait_task = asyncio.create_task(retry_consumer._wait_for_restart(30.0))
        await asyncio.sleep(0)
        assert not wait_task.done()

        retry_consumer.stop()

        assert await wait_task is True


class TestRetryConsumerProcessRecord:
    """Tests for _process_retry_record method."""

    @pytest.mark.asyncio
    async def test_skips_record_missing_original_topic(self, kafka_config: KafkaClientConfig) -> None:
        """Commits and returns when x-original-topic header is missing."""
        rc = RetryConsumer(
            consumer_group="my-group",
            handler_map={},
            config=kafka_config,
        )

        record = MagicMock()
        record.headers = []
        record.offset = 0
        record.partition = 0
        record.timestamp = 0
        record.value = b""
        record.key = None
        record.topic = "my-group.retry"

        rc._dlq_handler = MagicMock()
        rc._dlq_handler.handle_failure = AsyncMock(return_value=MagicMock(success=True, error=None))
        mock_consumer = _mock_consumer(TopicPartition(record.topic, record.partition))
        await rc._process_retry_record(record, mock_consumer)
        rc._dlq_handler.handle_failure.assert_awaited_once()
        mock_consumer.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_record_no_handler_found(self, kafka_config: KafkaClientConfig) -> None:
        """Commits and returns when no handler matches the original topic."""
        rc = RetryConsumer(
            consumer_group="my-group",
            handler_map={},
            config=kafka_config,
        )

        record = MagicMock()
        record.headers = [(b"x-original-topic", b"unknown-topic.v1")]
        record.offset = 0
        record.partition = 0
        record.timestamp = 0
        record.value = b""
        record.key = None
        record.topic = "my-group.retry"

        # Fix: headers need to be str key, bytes value tuples
        record.headers = [("x-original-topic", b"unknown-topic.v1")]

        rc._dlq_handler = MagicMock()
        rc._dlq_handler.handle_failure = AsyncMock(return_value=MagicMock(success=True, error=None))
        mock_consumer = _mock_consumer(TopicPartition(record.topic, record.partition))
        await rc._process_retry_record(record, mock_consumer)
        rc._dlq_handler.handle_failure.assert_awaited_once()
        mock_consumer.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatches_and_commits_on_success(self, kafka_config: KafkaClientConfig) -> None:
        """Dispatches to handler and commits on successful reprocessing."""
        mock_handler = AsyncMock()
        mock_handler.__name__ = "handle_thing"
        mock_handler.__module__ = "test"

        mock_msg_type = MagicMock()
        mock_msg_type.return_value.parse.return_value = MagicMock()

        registration = MagicMock()
        registration.message_type = mock_msg_type
        registration.handler_func = mock_handler

        rc = RetryConsumer(
            consumer_group="my-group",
            handler_map={"my-topic.v1": registration},
            config=kafka_config,
        )

        record = MagicMock()
        record.headers = [
            ("x-original-topic", b"my-topic.v1"),
            ("x-retry-count", b"1"),
            ("x-next-retry-at", b"0.0"),
        ]
        record.offset = 5
        record.partition = 0
        record.timestamp = 1000
        record.value = b"payload"
        record.key = b"key1"
        record.topic = "my-group.retry"

        mock_consumer = AsyncMock()
        await rc._process_retry_record(record, mock_consumer)

        mock_handler.assert_awaited_once()
        mock_consumer.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_dispatch_failure(self, kafka_config: KafkaClientConfig) -> None:
        """Routes to DLQ handler when dispatch raises an exception."""
        mock_handler = AsyncMock(side_effect=RuntimeError("Handler failed"))
        mock_handler.__name__ = "handle_thing"
        mock_handler.__module__ = "test"

        mock_msg_type = MagicMock()
        mock_msg_type.return_value.parse.return_value = MagicMock()

        registration = MagicMock()
        registration.message_type = mock_msg_type
        registration.handler_func = mock_handler

        rc = RetryConsumer(
            consumer_group="my-group",
            handler_map={"my-topic.v1": registration},
            config=kafka_config,
        )

        record = MagicMock()
        record.headers = [
            ("x-original-topic", b"my-topic.v1"),
            ("x-retry-count", b"1"),
            ("x-next-retry-at", b"0.0"),
        ]
        record.offset = 5
        record.partition = 0
        record.timestamp = 1000
        record.value = b"payload"
        record.key = None
        record.topic = "my-group.retry"

        mock_consumer = AsyncMock()

        mock_dlq = MagicMock()
        mock_dlq.handle_failure = AsyncMock(return_value=MagicMock(success=True))
        rc._dlq_handler = mock_dlq

        await rc._process_retry_record(record, mock_consumer)

        mock_dlq.handle_failure.assert_awaited_once()
        mock_consumer.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dlq_internal_failure_does_not_commit_retry_offset(self, kafka_config: KafkaClientConfig) -> None:
        """A failed retry-to-DLQ route leaves the retry record available for redelivery."""
        mock_handler = AsyncMock(side_effect=RuntimeError("handler failed"))
        mock_handler.__name__ = "handle_thing"
        mock_handler.__module__ = "test"
        mock_message_type = MagicMock()
        mock_message_type.return_value.parse.return_value = MagicMock()
        registration = MagicMock(message_type=mock_message_type, handler_func=mock_handler)
        rc = RetryConsumer(
            consumer_group="my-group",
            handler_map={"my-topic.v1": registration},
            config=kafka_config,
        )
        record = MagicMock(
            headers=[
                ("x-original-topic", b"my-topic.v1"),
                ("x-retry-count", b"1"),
                ("x-next-retry-at", b"0.0"),
            ],
            offset=5,
            partition=0,
            timestamp=1000,
            value=b"payload",
            key=None,
            topic="my-group.retry",
        )
        mock_consumer = _mock_consumer(TopicPartition(record.topic, record.partition))
        mock_dlq = MagicMock()
        mock_dlq.handle_failure = AsyncMock(return_value=MagicMock(success=False, error=OSError("DLQ unavailable")))
        rc._dlq_handler = mock_dlq

        await rc._process_retry_record(record, mock_consumer)

        mock_dlq.handle_failure.assert_awaited_once()
        mock_consumer.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("phase", ["backoff", "handler"])
    async def test_cancellation_is_not_classified_as_publishable_failure(
        self,
        kafka_config: KafkaClientConfig,
        phase: str,
    ) -> None:
        """Cancellation never commits or publishes after retry shutdown begins."""
        phase_started = asyncio.Event()

        async def _handler(_message: object, _context: object) -> None:
            if phase == "handler":
                phase_started.set()
                await asyncio.Event().wait()

        async def _backoff(_retry_at: float) -> None:
            phase_started.set()
            await asyncio.Event().wait()

        retry_consumer = RetryConsumer(
            consumer_group="my-group",
            handler_map={"my-topic.v1": _handler_registration(AsyncMock(side_effect=_handler))},
            config=kafka_config,
        )
        record = _retry_record(retry_at=9_999_999_999.0 if phase == "backoff" else 0.0)
        topic_partition = TopicPartition(record.topic, record.partition)
        consumer = _mock_consumer(topic_partition)
        retry_consumer._dlq_handler = MagicMock()
        retry_consumer._dlq_handler.handle_failure = AsyncMock()

        with patch(
            "nohiki_kafka_client.consumer.retry_consumer._apply_backoff",
            side_effect=_backoff,
        ):
            task = asyncio.create_task(retry_consumer._process_retry_record(record, consumer))
            await phase_started.wait()
            retry_consumer.stop()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        retry_consumer._dlq_handler.handle_failure.assert_not_awaited()
        consumer.commit.assert_not_awaited()
