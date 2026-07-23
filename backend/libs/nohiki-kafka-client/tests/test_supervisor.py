"""tests for the consumer supervisor module."""

from __future__ import annotations

import asyncio
import time
import warnings
from unittest.mock import MagicMock

import betterproto2
import pytest
from aiokafka.errors import (
    CommitFailedError,
    ConsumerStoppedError,
    GroupAuthorizationFailedError,
    IllegalStateError,
    KafkaConnectionError,
    KafkaError,
    NodeNotReadyError,
    RequestTimedOutError,
    UnknownMemberIdError,
)
from nohiki_kafka_client.handlers import HandlerRegistration, MessageContext
from nohiki_kafka_client.supervision.supervisor import (
    COORDINATOR_MESSAGE_TERMS,
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_INITIAL_BACKOFF_SECONDS,
    DEFAULT_JITTER_FACTOR,
    DEFAULT_MAX_BACKOFF_SECONDS,
    DEFAULT_MAX_CONSECUTIVE_FAILURES,
    TRANSIENT_MESSAGE_TERMS,
    ConsumerMetrics,
    ConsumerState,
    ConsumerSupervisor,
    ErrorCategory,
    SupervisedConsumer,
    SupervisorConfig,
    _build_health_entry,
    _cancel_consumer,
    _cancel_tasks,
    _classify_by_message,
    _contains_any_term,
    _record_failure,
    _reset_for_start,
    _reset_on_success,
    calculate_backoff,
    classify_error,
    is_recoverable,
)


class MockProtoMessage(betterproto2.Message):
    """Mock protobuf message for testing."""

    value: str = ""


async def mock_handler(message: MockProtoMessage, context: MessageContext, /) -> None:
    """Mock message handler for testing."""


async def _complete_sleep(_delay: float) -> None:
    pass


def make_registration(
    topic: str = "test.entity.action.v1",
    group_id: str = "test-group",
) -> HandlerRegistration:
    """Create a HandlerRegistration for testing."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return HandlerRegistration(
            topic=topic,
            message_type=MockProtoMessage,
            handler_func=mock_handler,
            group_id=group_id,
        )


class TestErrorClassification:
    """Tests for error classification functions."""

    def test_classify_coordinator_errors(self) -> None:
        """Test classification of coordinator-related errors."""
        coordinator_errors = [
            NodeNotReadyError(),
            UnknownMemberIdError(),
            CommitFailedError(),
            IllegalStateError(),
        ]
        for error in coordinator_errors:
            assert classify_error(error) == ErrorCategory.COORDINATOR

    def test_classify_transient_errors(self) -> None:
        """Test classification of transient errors."""
        transient_errors = [
            KafkaConnectionError(),
            RequestTimedOutError(),
            OSError("connection reset"),
            TimeoutError("operation timed out"),
        ]
        for error in transient_errors:
            assert classify_error(error) == ErrorCategory.TRANSIENT

    def test_classify_auth_error(self) -> None:
        """Test classification of auth errors."""
        error = GroupAuthorizationFailedError()
        assert classify_error(error) == ErrorCategory.AUTH

    def test_classify_fatal_consumer_stopped(self) -> None:
        """Test classification of ConsumerStoppedError as fatal."""
        error = ConsumerStoppedError()
        assert classify_error(error) == ErrorCategory.FATAL

    def test_classify_generic_kafka_error_with_coordinator_message(self) -> None:
        """Test classification of KafkaError by message content."""
        error = KafkaError("Coordinator not available")
        assert classify_error(error) == ErrorCategory.COORDINATOR

    def test_classify_generic_kafka_error_with_heartbeat_message(self) -> None:
        """Test classification of KafkaError with heartbeat in message."""
        error = KafkaError("Heartbeat session timed out")
        assert classify_error(error) == ErrorCategory.COORDINATOR

    def test_classify_generic_kafka_error_with_rebalance_message(self) -> None:
        """Test classification of KafkaError with rebalance in message."""
        error = KafkaError("Group rebalance in progress")
        assert classify_error(error) == ErrorCategory.COORDINATOR

    def test_classify_generic_kafka_error_with_connection_message(self) -> None:
        """Test classification of KafkaError with connection in message."""
        error = KafkaError("Connection to broker lost")
        assert classify_error(error) == ErrorCategory.TRANSIENT

    def test_classify_generic_kafka_error_with_network_message(self) -> None:
        """Test classification of KafkaError with network in message."""
        error = KafkaError("Network error occurred")
        assert classify_error(error) == ErrorCategory.TRANSIENT

    def test_classify_unknown_error_as_fatal(self) -> None:
        """Test that unknown errors are classified as fatal."""
        error = ValueError("Unknown error")
        assert classify_error(error) == ErrorCategory.FATAL

    def test_classify_generic_kafka_error_unknown_message(self) -> None:
        """Test that KafkaError with unknown message is fatal."""
        error = KafkaError("Some unknown error message")
        assert classify_error(error) == ErrorCategory.FATAL


class TestClassifyByMessage:
    """Tests for _classify_by_message helper function."""

    def test_coordinator_term_detection(self) -> None:
        """Test detection of coordinator terms in error message."""
        for term in COORDINATOR_MESSAGE_TERMS:
            result = _classify_by_message(f"error with {term} issue")
            assert result == ErrorCategory.COORDINATOR

    def test_transient_term_detection(self) -> None:
        """Test detection of transient terms in error message."""
        for term in TRANSIENT_MESSAGE_TERMS:
            result = _classify_by_message(f"error with {term} issue")
            assert result == ErrorCategory.TRANSIENT

    def test_no_match_returns_fatal(self) -> None:
        """Test that no match returns fatal category."""
        result = _classify_by_message("completely unknown error message")
        assert result == ErrorCategory.FATAL


class TestContainsAnyTerm:
    """Tests for _contains_any_term helper function."""

    def test_contains_term(self) -> None:
        """Test positive match for term in text."""
        terms = frozenset({"error", "warning"})
        assert _contains_any_term("this is an error message", terms) is True

    def test_does_not_contain_term(self) -> None:
        """Test negative match when term not in text."""
        terms = frozenset({"error", "warning"})
        assert _contains_any_term("this is a success message", terms) is False

    def test_empty_terms(self) -> None:
        """Test with empty terms set."""
        terms: frozenset[str] = frozenset()
        assert _contains_any_term("any text", terms) is False


class TestIsRecoverable:
    """Tests for is_recoverable function."""

    def test_transient_is_recoverable(self) -> None:
        """Test that transient errors are recoverable."""
        assert is_recoverable(ErrorCategory.TRANSIENT) is True

    def test_coordinator_is_recoverable(self) -> None:
        """Test that coordinator errors are recoverable."""
        assert is_recoverable(ErrorCategory.COORDINATOR) is True

    def test_auth_not_recoverable(self) -> None:
        """Test that auth errors are not recoverable."""
        assert is_recoverable(ErrorCategory.AUTH) is False

    def test_fatal_not_recoverable(self) -> None:
        """Test that fatal errors are not recoverable."""
        assert is_recoverable(ErrorCategory.FATAL) is False


class TestCalculateBackoff:
    """Tests for calculate_backoff function."""

    def test_first_attempt_returns_initial_backoff(self) -> None:
        """Test that first attempt uses initial backoff."""
        config = SupervisorConfig(
            initial_backoff_seconds=1.0,
            max_backoff_seconds=60.0,
            jitter_factor=0.0,
        )
        result = calculate_backoff(0, config)
        assert result == pytest.approx(1.0)

    def test_backoff_increases_exponentially(self) -> None:
        """Test exponential backoff increase."""
        config = SupervisorConfig(
            initial_backoff_seconds=1.0,
            max_backoff_seconds=60.0,
            backoff_multiplier=2.0,
            jitter_factor=0.0,
        )
        result1 = calculate_backoff(1, config)
        result2 = calculate_backoff(2, config)
        assert result1 == pytest.approx(2.0)
        assert result2 == pytest.approx(4.0)

    def test_backoff_capped_at_max(self) -> None:
        """Test that backoff is capped at max value."""
        config = SupervisorConfig(
            initial_backoff_seconds=1.0,
            max_backoff_seconds=5.0,
            backoff_multiplier=2.0,
            jitter_factor=0.0,
        )
        result = calculate_backoff(10, config)
        assert result == pytest.approx(5.0)

    def test_backoff_includes_jitter(self) -> None:
        """Test that jitter is applied to backoff."""
        config = SupervisorConfig(
            initial_backoff_seconds=10.0,
            max_backoff_seconds=60.0,
            jitter_factor=0.2,
        )
        results = {calculate_backoff(1, config) for _ in range(20)}
        assert len(results) > 1

    def test_backoff_never_below_initial(self) -> None:
        """Test backoff never goes below initial value."""
        config = SupervisorConfig(
            initial_backoff_seconds=5.0,
            max_backoff_seconds=60.0,
            jitter_factor=0.5,
        )
        for _ in range(50):
            result = calculate_backoff(0, config)
            assert result >= config.initial_backoff_seconds


class TestSupervisorConfig:
    """Tests for SupervisorConfig dataclass."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = SupervisorConfig()
        assert config.initial_backoff_seconds == DEFAULT_INITIAL_BACKOFF_SECONDS
        assert config.max_backoff_seconds == DEFAULT_MAX_BACKOFF_SECONDS
        assert config.backoff_multiplier == DEFAULT_BACKOFF_MULTIPLIER
        assert config.jitter_factor == DEFAULT_JITTER_FACTOR
        assert config.max_consecutive_failures == DEFAULT_MAX_CONSECUTIVE_FAILURES

    def test_custom_values(self) -> None:
        """Test custom configuration values."""
        config = SupervisorConfig(
            initial_backoff_seconds=2.0,
            max_backoff_seconds=120.0,
            backoff_multiplier=3.0,
            jitter_factor=0.1,
            max_consecutive_failures=5,
        )
        assert config.initial_backoff_seconds == pytest.approx(2.0)
        assert config.max_backoff_seconds == pytest.approx(120.0)
        assert config.backoff_multiplier == pytest.approx(3.0)
        assert config.jitter_factor == pytest.approx(0.1)
        assert config.max_consecutive_failures == 5


class TestConsumerMetrics:
    """Tests for ConsumerMetrics dataclass."""

    def test_default_values(self) -> None:
        """Test default metrics values."""
        metrics = ConsumerMetrics()
        assert metrics.state == ConsumerState.STOPPED
        assert metrics.consecutive_failures == 0
        assert metrics.total_restarts == 0
        assert metrics.last_successful_consume is None
        assert metrics.last_error is None
        assert metrics.last_error_time is None
        assert metrics.last_error_category is None
        assert metrics.current_backoff_seconds == pytest.approx(0.0)
        assert metrics.started_at is None


class TestSupervisedConsumer:
    """Tests for SupervisedConsumer dataclass."""

    def test_consumer_key_format(self) -> None:
        """Test consumer key is correctly formatted."""
        registration = make_registration(topic="my.topic.v1", group_id="my-group")
        supervised = SupervisedConsumer(
            registration=registration,
            config=SupervisorConfig(),
        )
        assert supervised.consumer_key == "my.topic.v1:my-group"

    def test_default_metrics(self) -> None:
        """Test default metrics are created."""
        supervised = SupervisedConsumer(
            registration=make_registration(),
            config=SupervisorConfig(),
        )
        assert isinstance(supervised.metrics, ConsumerMetrics)

    def test_default_shutdown_event(self) -> None:
        """Test default shutdown event is created."""
        supervised = SupervisedConsumer(
            registration=make_registration(),
            config=SupervisorConfig(),
        )
        assert isinstance(supervised.shutdown_event, asyncio.Event)
        assert not supervised.shutdown_event.is_set()


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_build_health_entry(self) -> None:
        """Test _build_health_entry creates correct structure."""
        metrics = ConsumerMetrics(
            state=ConsumerState.RUNNING,
            consecutive_failures=2,
            total_restarts=5,
            last_error="Test error",
            last_error_category=ErrorCategory.TRANSIENT,
            current_backoff_seconds=3.5,
        )
        entry = _build_health_entry(metrics)

        assert entry["state"] == "running"
        assert entry["healthy"] is True
        assert entry["consecutive_failures"] == 2
        assert entry["total_restarts"] == 5
        assert entry["last_error"] == "Test error"
        assert entry["last_error_category"] == "transient"
        assert entry["current_backoff_seconds"] == pytest.approx(3.5)

    def test_build_health_entry_unhealthy(self) -> None:
        """Test _build_health_entry marks non-running as unhealthy."""
        metrics = ConsumerMetrics(state=ConsumerState.BACKOFF)
        entry = _build_health_entry(metrics)
        assert entry["healthy"] is False

    def test_build_health_entry_no_error_category(self) -> None:
        """Test _build_health_entry with no error category."""
        metrics = ConsumerMetrics()
        entry = _build_health_entry(metrics)
        assert entry["last_error_category"] is None

    def test_reset_for_start(self) -> None:
        """Test _reset_for_start sets correct state."""
        metrics = ConsumerMetrics(state=ConsumerState.STOPPED)
        _reset_for_start(metrics)
        assert metrics.state == ConsumerState.STARTING
        assert metrics.started_at is not None
        assert metrics.started_at <= time.time()

    def test_reset_on_success(self) -> None:
        """Test _reset_on_success clears failure counters."""
        metrics = ConsumerMetrics(
            consecutive_failures=5,
            current_backoff_seconds=30.0,
        )
        _reset_on_success(metrics)
        assert metrics.consecutive_failures == 0
        assert metrics.current_backoff_seconds == pytest.approx(0.0)

    def test_record_failure(self) -> None:
        """Test _record_failure updates metrics correctly."""
        metrics = ConsumerMetrics()
        error = OSError("Test connection error")

        _record_failure(metrics, error)

        assert metrics.consecutive_failures == 1
        assert metrics.last_error == "Test connection error"
        assert metrics.last_error_time is not None
        assert metrics.last_error_category == ErrorCategory.TRANSIENT

    def test_record_failure_increments(self) -> None:
        """Test _record_failure increments consecutive failures."""
        metrics = ConsumerMetrics(consecutive_failures=3)
        _record_failure(metrics, OSError("error"))
        assert metrics.consecutive_failures == 4


class TestCancelFunctions:
    """Tests for async cancel helper functions."""

    @pytest.mark.asyncio
    async def test_cancel_consumer_sets_shutdown_event(self) -> None:
        """Test _cancel_consumer sets shutdown event."""
        supervised = SupervisedConsumer(
            registration=make_registration(),
            config=SupervisorConfig(),
        )
        await _cancel_consumer(supervised)
        assert supervised.shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_cancel_consumer_cancels_task(self) -> None:
        """Test _cancel_consumer cancels running task."""
        supervised = SupervisedConsumer(
            registration=make_registration(),
            config=SupervisorConfig(),
        )

        started = asyncio.Event()

        async def long_running() -> None:
            started.set()
            await asyncio.Event().wait()

        supervised.task = asyncio.create_task(long_running())
        await started.wait()

        await _cancel_consumer(supervised)

        assert supervised.task.done()
        assert supervised.task.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_consumer_no_task(self) -> None:
        """Test _cancel_consumer handles no task gracefully."""
        supervised = SupervisedConsumer(
            registration=make_registration(),
            config=SupervisorConfig(),
        )
        supervised.task = None
        await _cancel_consumer(supervised)
        assert supervised.shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_cancel_tasks_cancels_all(self) -> None:
        """Test _cancel_tasks cancels all tasks."""

        async def long_running(started: asyncio.Event) -> None:
            started.set()
            await asyncio.Event().wait()

        started_events = [asyncio.Event() for _ in range(3)]
        tasks = [asyncio.create_task(long_running(started)) for started in started_events]
        for started in started_events:
            await started.wait()

        await _cancel_tasks(tasks)

        for task in tasks:
            assert task.done()
            assert task.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_tasks_empty_list(self) -> None:
        """Test _cancel_tasks handles empty list."""
        await _cancel_tasks([])


class TestConsumerSupervisor:
    """Tests for ConsumerSupervisor class."""

    def test_init_default_config(self) -> None:
        """Test supervisor initializes with default config."""
        supervisor = ConsumerSupervisor()
        assert supervisor._config.initial_backoff_seconds == DEFAULT_INITIAL_BACKOFF_SECONDS

    def test_init_custom_config(self) -> None:
        """Test supervisor initializes with custom config."""
        config = SupervisorConfig(initial_backoff_seconds=5.0)
        supervisor = ConsumerSupervisor(config)
        assert supervisor._config.initial_backoff_seconds == pytest.approx(5.0)

    def test_is_running_false_initially(self) -> None:
        """Test is_running is False initially."""
        supervisor = ConsumerSupervisor()
        assert supervisor.is_running is False

    def test_register_creates_supervised_consumer(self) -> None:
        """Test register creates and stores SupervisedConsumer."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()

        supervised = supervisor.register(registration)

        assert supervised.registration is registration
        assert supervised.consumer_key in supervisor._consumers

    def test_register_multiple_consumers(self) -> None:
        """Test registering multiple consumers."""
        supervisor = ConsumerSupervisor()

        reg1 = make_registration(topic="svc.entity.action1.v1", group_id="group1")
        reg2 = make_registration(topic="svc.entity.action2.v1", group_id="group2")

        supervised1 = supervisor.register(reg1)
        supervised2 = supervisor.register(reg2)

        assert len(supervisor._consumers) == 2
        assert supervised1.consumer_key != supervised2.consumer_key

    def test_get_consumer_existing(self) -> None:
        """Test get_consumer returns existing consumer."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        result = supervisor.get_consumer(supervised.consumer_key)
        assert result is supervised

    def test_get_consumer_not_found(self) -> None:
        """Test get_consumer returns None for missing key."""
        supervisor = ConsumerSupervisor()
        result = supervisor.get_consumer("nonexistent:key")
        assert result is None

    def test_get_all_consumers_returns_copy(self) -> None:
        """Test get_all_consumers returns shallow copy."""
        supervisor = ConsumerSupervisor()
        reg = make_registration()
        supervisor.register(reg)

        consumers = supervisor.get_all_consumers()
        consumers["new_key"] = MagicMock()

        assert "new_key" not in supervisor._consumers

    def test_get_health_summary(self) -> None:
        """Test get_health_summary returns health for all consumers."""
        supervisor = ConsumerSupervisor()

        reg1 = make_registration(topic="svc.entity.action1.v1", group_id="group1")
        reg2 = make_registration(topic="svc.entity.action2.v1", group_id="group2")

        sup1 = supervisor.register(reg1)
        sup2 = supervisor.register(reg2)

        sup1.metrics.state = ConsumerState.RUNNING
        sup2.metrics.state = ConsumerState.BACKOFF

        summary = supervisor.get_health_summary()

        assert len(summary) == 2
        assert summary[sup1.consumer_key]["healthy"] is True
        assert summary[sup2.consumer_key]["healthy"] is False


class TestConsumerSupervisorAsync:
    """Async tests for ConsumerSupervisor."""

    @pytest.mark.asyncio
    async def test_start_consumer_successful_run(self) -> None:
        """Test start_consumer with successful consumer run."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        call_count = 0

        async def mock_factory(_reg: HandlerRegistration) -> None:
            nonlocal call_count
            call_count += 1
            await asyncio.to_thread(supervised.shutdown_event.set)

        await supervisor.start_consumer(supervised, mock_factory)

        assert call_count == 1
        assert supervised.metrics.state == ConsumerState.STOPPED

    @pytest.mark.asyncio
    async def test_start_consumer_restarts_on_transient_error(self) -> None:
        """Test start_consumer restarts on transient error."""
        config = SupervisorConfig(
            initial_backoff_seconds=0.01,
            max_consecutive_failures=3,
        )
        supervisor = ConsumerSupervisor(config, sleep=_complete_sleep)
        registration = make_registration()
        supervised = supervisor.register(registration)

        call_count = 0

        async def mock_factory(_reg: HandlerRegistration) -> None:
            nonlocal call_count
            await asyncio.to_thread(lambda: None)
            call_count += 1
            if call_count < 3:
                conn_error_msg = "Connection lost"
                raise KafkaConnectionError(conn_error_msg)
            await asyncio.to_thread(supervised.shutdown_event.set)

        await supervisor.start_consumer(supervised, mock_factory)

        assert call_count == 3
        assert supervised.metrics.total_restarts == 2

    @pytest.mark.asyncio
    async def test_start_consumer_stops_on_fatal_error(self) -> None:
        """Test start_consumer stops on fatal error."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        async def mock_factory(_reg: HandlerRegistration) -> None:
            await asyncio.to_thread(lambda: None)
            raise ConsumerStoppedError

        await supervisor.start_consumer(supervised, mock_factory)

        assert supervised.metrics.state == ConsumerState.FAILED
        assert supervised.metrics.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_start_consumer_stops_on_auth_error(self) -> None:
        """Test start_consumer stops on auth error."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        async def mock_factory(_reg: HandlerRegistration) -> None:
            await asyncio.to_thread(lambda: None)
            raise GroupAuthorizationFailedError

        await supervisor.start_consumer(supervised, mock_factory)

        assert supervised.metrics.state == ConsumerState.FAILED
        assert supervised.metrics.last_error_category == ErrorCategory.AUTH

    @pytest.mark.asyncio
    async def test_start_consumer_propagates_non_kafka_failure_to_caller(self) -> None:
        """An unexpected consume-loop failure is observable instead of silently stopping."""
        supervisor = ConsumerSupervisor()
        supervised = supervisor.register(make_registration())
        failure = RuntimeError("record task crashed")

        async def mock_factory(_registration: HandlerRegistration) -> None:
            raise failure

        with pytest.raises(RuntimeError, match="record task crashed") as raised:
            await supervisor.start_consumer(supervised, mock_factory)

        assert raised.value is failure
        assert supervised.metrics.state == ConsumerState.FAILED
        assert supervised.metrics.consecutive_failures == 1
        assert supervised.metrics.last_error_category == ErrorCategory.FATAL

    @pytest.mark.asyncio
    async def test_start_consumer_stops_after_max_failures(self) -> None:
        """Test start_consumer stops after max consecutive failures."""
        config = SupervisorConfig(
            initial_backoff_seconds=0.01,
            max_consecutive_failures=3,
        )
        supervisor = ConsumerSupervisor(config, sleep=_complete_sleep)
        registration = make_registration()
        supervised = supervisor.register(registration)

        call_count = 0

        async def mock_factory(_reg: HandlerRegistration) -> None:
            nonlocal call_count
            call_count += 1
            conn_error_msg = "Connection lost"
            await asyncio.to_thread(lambda: None)
            raise KafkaConnectionError(conn_error_msg)

        await supervisor.start_consumer(supervised, mock_factory)

        assert call_count == 3
        assert supervised.metrics.state == ConsumerState.FAILED
        assert supervised.metrics.consecutive_failures == 3

    @pytest.mark.asyncio
    async def test_start_consumer_handles_cancelled_error(self) -> None:
        """Test start_consumer handles CancelledError properly."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        async def mock_factory(_reg: HandlerRegistration) -> None:
            await asyncio.to_thread(lambda: None)
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await supervisor.start_consumer(supervised, mock_factory)

        assert supervised.metrics.state == ConsumerState.STOPPED

    @pytest.mark.asyncio
    async def test_start_consumer_respects_shutdown_event(self) -> None:
        """Test start_consumer respects supervisor shutdown event."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        supervisor._shutdown_event.set()

        async def mock_factory(_reg: HandlerRegistration) -> None:
            fail_msg = "Factory should not be called"
            await asyncio.to_thread(lambda: None)
            pytest.fail(fail_msg)

        await supervisor.start_consumer(supervised, mock_factory)

    @pytest.mark.asyncio
    async def test_stop_consumer_by_key(self) -> None:
        """Test stop_consumer stops specific consumer."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        started = asyncio.Event()

        async def long_running() -> None:
            started.set()
            await asyncio.Event().wait()

        supervised.task = asyncio.create_task(long_running())
        await started.wait()

        await supervisor.stop_consumer(supervised.consumer_key)

        assert supervised.shutdown_event.is_set()
        assert supervised.task.done()

    @pytest.mark.asyncio
    async def test_stop_consumer_nonexistent_key(self) -> None:
        """Test stop_consumer handles nonexistent key."""
        supervisor = ConsumerSupervisor()
        await supervisor.stop_consumer("nonexistent:key")

    @pytest.mark.asyncio
    async def test_stop_all_stops_all_consumers(self) -> None:
        """Test stop_all stops all supervised consumers."""
        supervisor = ConsumerSupervisor()

        reg1 = make_registration(topic="svc.entity.action1.v1", group_id="group1")
        reg2 = make_registration(topic="svc.entity.action2.v1", group_id="group2")

        sup1 = supervisor.register(reg1)
        sup2 = supervisor.register(reg2)

        async def long_running(started: asyncio.Event) -> None:
            started.set()
            await asyncio.Event().wait()

        started1 = asyncio.Event()
        started2 = asyncio.Event()
        sup1.task = asyncio.create_task(long_running(started1))
        sup2.task = asyncio.create_task(long_running(started2))
        await started1.wait()
        await started2.wait()

        await supervisor.stop_all()

        assert supervisor._shutdown_event.is_set()
        assert sup1.shutdown_event.is_set()
        assert sup2.shutdown_event.is_set()
        assert sup1.task.done()
        assert sup2.task.done()

    @pytest.mark.asyncio
    async def test_stop_all_no_tasks(self) -> None:
        """Test stop_all handles consumers with no tasks."""
        supervisor = ConsumerSupervisor()
        reg = make_registration()
        supervisor.register(reg)

        await supervisor.stop_all()

        assert supervisor._shutdown_event.is_set()


class TestBackoffWaiting:
    """Tests for backoff waiting behavior."""

    @pytest.mark.asyncio
    async def test_wait_backoff_completes_on_timeout(self) -> None:
        """Test _wait_backoff completes after timeout."""
        config = SupervisorConfig(initial_backoff_seconds=0.05, jitter_factor=0.0)
        delays: list[float] = []

        async def record_sleep(delay: float) -> None:
            delays.append(delay)

        supervisor = ConsumerSupervisor(config, sleep=record_sleep)
        registration = make_registration()
        supervised = supervisor.register(registration)
        supervised.metrics.consecutive_failures = 1

        result = await supervisor._wait_backoff(supervised)

        assert result is False
        assert delays == pytest.approx([0.1])
        assert supervised.metrics.state == ConsumerState.RECONNECTING
        assert supervised.metrics.total_restarts == 1

    @pytest.mark.asyncio
    async def test_wait_backoff_returns_early_on_shutdown(self) -> None:
        """Test _wait_backoff returns early when shutdown requested."""
        config = SupervisorConfig(initial_backoff_seconds=10.0, jitter_factor=0.0)
        sleep_started = asyncio.Event()

        async def pending_sleep(_delay: float) -> None:
            sleep_started.set()
            await asyncio.Event().wait()

        supervisor = ConsumerSupervisor(config, sleep=pending_sleep)
        registration = make_registration()
        supervised = supervisor.register(registration)
        supervised.metrics.consecutive_failures = 1

        backoff_task = asyncio.create_task(supervisor._wait_backoff(supervised))
        await sleep_started.wait()
        supervised.shutdown_event.set()
        result = await backoff_task

        assert result is True


class TestConsumerStateTransitions:
    """Tests for consumer state transitions during supervision."""

    @pytest.mark.asyncio
    async def test_state_transitions_on_successful_run(self) -> None:
        """Test state transitions during successful consumer run."""
        supervisor = ConsumerSupervisor()
        registration = make_registration()
        supervised = supervisor.register(registration)

        states_observed: list[ConsumerState] = []

        async def mock_factory(_reg: HandlerRegistration) -> None:
            states_observed.append(supervised.metrics.state)
            await asyncio.to_thread(supervised.shutdown_event.set)

        await supervisor.start_consumer(supervised, mock_factory)

        assert ConsumerState.RUNNING in states_observed
        assert supervised.metrics.state == ConsumerState.STOPPED

    @pytest.mark.asyncio
    async def test_state_transitions_on_error_and_recovery(self) -> None:
        """Test state transitions during error and recovery."""
        config = SupervisorConfig(initial_backoff_seconds=0.01)
        supervisor = ConsumerSupervisor(config, sleep=_complete_sleep)
        registration = make_registration()
        supervised = supervisor.register(registration)

        call_count = 0
        states_observed: list[ConsumerState] = []

        async def mock_factory(_reg: HandlerRegistration) -> None:
            nonlocal call_count
            await asyncio.to_thread(lambda: None)
            call_count += 1
            states_observed.append(supervised.metrics.state)
            if call_count < 2:
                error_msg = "error"
                raise KafkaConnectionError(error_msg)
            await asyncio.to_thread(supervised.shutdown_event.set)

        await supervisor.start_consumer(supervised, mock_factory)

        assert ConsumerState.RUNNING in states_observed
        assert supervised.metrics.state == ConsumerState.STOPPED


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_os_error_is_recoverable(self) -> None:
        """Test that OSError is treated as recoverable."""
        config = SupervisorConfig(
            initial_backoff_seconds=0.01,
            max_consecutive_failures=2,
        )
        supervisor = ConsumerSupervisor(config, sleep=_complete_sleep)
        registration = make_registration()
        supervised = supervisor.register(registration)

        call_count = 0

        async def mock_factory(_reg: HandlerRegistration) -> None:
            nonlocal call_count
            await asyncio.to_thread(lambda: None)
            call_count += 1
            if call_count < 2:
                os_error_msg = "Connection reset by peer"
                raise OSError(os_error_msg)
            await asyncio.to_thread(supervised.shutdown_event.set)

        await supervisor.start_consumer(supervised, mock_factory)

        assert call_count == 2
        assert supervised.metrics.total_restarts == 1

    @pytest.mark.asyncio
    async def test_multiple_error_types_in_sequence(self) -> None:
        """Test handling of different error types in sequence."""
        config = SupervisorConfig(
            initial_backoff_seconds=0.01,
            max_consecutive_failures=5,
        )
        supervisor = ConsumerSupervisor(config, sleep=_complete_sleep)
        registration = make_registration()
        supervised = supervisor.register(registration)

        errors = [
            KafkaConnectionError("conn error"),
            NodeNotReadyError(),
            RequestTimedOutError(),
        ]
        call_count = 0

        async def mock_factory(_reg: HandlerRegistration) -> None:
            nonlocal call_count
            await asyncio.to_thread(lambda: None)
            if call_count < len(errors):
                error = errors[call_count]
                call_count += 1
                raise error
            await asyncio.to_thread(supervised.shutdown_event.set)

        await supervisor.start_consumer(supervised, mock_factory)

        assert call_count == len(errors)
        assert supervised.metrics.total_restarts == len(errors)

    def test_consumer_key_with_special_characters(self) -> None:
        """Test consumer key handles topics with dots."""
        registration = make_registration(
            topic="job.ingest.discovery.requested.v1",
            group_id="job-ingest-schedule-discovery-primary",
        )
        supervised = SupervisedConsumer(
            registration=registration,
            config=SupervisorConfig(),
        )
        expected = "job.ingest.discovery.requested.v1:job-ingest-schedule-discovery-primary"
        assert supervised.consumer_key == expected
