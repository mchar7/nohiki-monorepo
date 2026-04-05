"""Tests for AutoKafkaClient lifecycle management with aiokafka."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import betterproto2
import pytest

if TYPE_CHECKING:
    from nohiki_kafka_client.client.auto_client import AutoKafkaClient
    from nohiki_kafka_client.handlers import MessageContext


@dataclass
class MockMessage(betterproto2.Message):
    """Mock betterproto2 message for testing."""

    value: str = ""


@pytest.fixture
def kafka_client() -> AutoKafkaClient:
    """Create a test Kafka client in testing mode."""
    from nohiki_kafka_client.client.auto_client import AutoKafkaClient
    from nohiki_kafka_client.config import KafkaClientConfig

    return AutoKafkaClient(
        KafkaClientConfig(bootstrap_servers="kafka:29092"),
        is_testing=True,
    )


class TestNoSignalHandlersInstalled:
    """Verify that AutoKafkaClient does not install signal handlers."""

    def test_no_signal_handlers_installed(self) -> None:
        """Verify no signal handlers are registered by the client."""
        import signal

        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        original_sigterm = signal.getsignal(signal.SIGTERM)
        original_sigint = signal.getsignal(signal.SIGINT)

        _client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )

        assert signal.getsignal(signal.SIGTERM) == original_sigterm
        assert signal.getsignal(signal.SIGINT) == original_sigint

    def test_no_atexit_handlers_registered(self) -> None:
        """Verify no atexit handlers are registered by the client."""
        import atexit

        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        with patch.object(atexit, "register") as mock_register:
            _client = AutoKafkaClient(
                KafkaClientConfig(bootstrap_servers="kafka:29092"),
                is_testing=False,
            )
            mock_register.assert_not_called()


class TestCloseMethod:
    """Tests for AutoKafkaClient.close() method."""

    @pytest.mark.asyncio
    async def test_close_without_consumers_or_producer(self, kafka_client: AutoKafkaClient) -> None:
        """Verify close() works when no consumers or producer started."""
        await kafka_client.close()
        assert kafka_client._shutdown_requested is True

    @pytest.mark.asyncio
    async def test_close_idempotent(self, kafka_client: AutoKafkaClient) -> None:
        """Verify calling close() multiple times is safe."""
        await kafka_client.close()
        await kafka_client.close()
        await kafka_client.close()
        assert kafka_client._shutdown_requested is True

    @pytest.mark.asyncio
    async def test_close_stops_consumers(self) -> None:
        """Verify close() signals shutdown and cancels consumer tasks."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        mock_consumer = MagicMock()
        mock_consumer.stop = MagicMock()
        client._consumers["test:group"] = mock_consumer

        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()
        mock_task.get_name.return_value = "test-task"
        client._consumer_tasks.append(mock_task)

        with patch("asyncio.gather", new_callable=AsyncMock) as mock_gather:
            await client.close()

        # Two-phase shutdown: stop() sets event, cancel() breaks iterator
        mock_consumer.stop.assert_called_once()
        # cancel() called in phase 1, then again in phase 2 force-cancel
        assert mock_task.cancel.call_count >= 1
        mock_gather.assert_awaited()

    @pytest.mark.asyncio
    async def test_close_closes_producer(self) -> None:
        """Verify close() closes the producer."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        mock_producer = AsyncMock()
        mock_producer.__aexit__ = AsyncMock()
        client._producer = mock_producer

        await client.close()

        mock_producer.__aexit__.assert_awaited_once_with(None, None, None)
        assert client._producer is None


class TestClientLifecycle:
    """Integration tests for client lifecycle."""

    @pytest.mark.asyncio
    async def test_publish_in_testing_mode(self, kafka_client: AutoKafkaClient) -> None:
        """Verify publish works in testing mode without real Kafka."""
        message = MockMessage(value="test")

        result = await kafka_client.publish("test.topic", message)

        assert result.topic == "test.topic"
        assert result.partition == 0
        assert result.offset == 0

    @pytest.mark.asyncio
    async def test_publish_raw_in_testing_mode(self, kafka_client: AutoKafkaClient) -> None:
        """Verify publish_raw works in testing mode without real Kafka."""
        result = await kafka_client.publish_raw("test.topic", b"raw bytes")

        assert result.topic == "test.topic"
        assert result.size_bytes == len(b"raw bytes")

    def test_handler_registration(self, kafka_client: AutoKafkaClient) -> None:
        """Verify handlers can be registered."""

        @kafka_client.message_handler("test.topic.v1", MockMessage, group_id="test-service-primary")
        async def handler(
            message: MockMessage, context: MessageContext
        ) -> None: ...  # Handler body empty for registration test

        assert len(kafka_client._handlers) == 1


class TestClientInitialization:
    """Tests for client initialization."""

    def test_client_initializes_with_testing_flag(self) -> None:
        """Verify client respects is_testing flag."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        assert client._is_testing is True

    def test_client_starts_without_producer_or_consumers(self) -> None:
        """Verify client starts in clean state."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        assert client._producer is None
        assert len(client._consumers) == 0
        assert len(client._consumer_tasks) == 0
        assert client._initialized is False
        assert client._consumers_started is False


class TestFlushMethod:
    """Tests for flush method."""

    @pytest.mark.asyncio
    async def test_flush_without_producer(self, kafka_client: AutoKafkaClient) -> None:
        """Verify flush() works when no producer exists."""
        await kafka_client.flush()

    @pytest.mark.asyncio
    async def test_flush_with_producer(self) -> None:
        """Verify flush() calls producer flush."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        mock_producer = MagicMock()
        mock_producer.flush = AsyncMock()
        client._producer = mock_producer

        await client.flush()

        mock_producer.flush.assert_awaited_once()


class TestDecoratorConfiguration:
    """Tests for decorator configuration methods."""

    def test_with_resilience_configuration(self, kafka_client: AutoKafkaClient) -> None:
        """Verify with_resilience decorator stores configuration."""

        @kafka_client.with_resilience(max_retries=5, strategy="log_only")
        @kafka_client.message_handler("test.topic.v1", MockMessage, group_id="test-service-primary")
        async def handler(
            message: MockMessage, context: MessageContext
        ) -> None: ...  # Handler body empty for config test

        handler_key = next(iter(kafka_client._handlers.keys()))
        registration = kafka_client._handlers[handler_key]
        assert registration.resilience_config is not None
        assert registration.resilience_config.max_retries == 5


class TestGetHealthState:
    """Tests for get_health_state method."""

    def test_health_state_no_handlers(self, kafka_client: AutoKafkaClient) -> None:
        """Health state with no handlers shows ready."""
        state = kafka_client.get_health_state()

        assert state["consumers_ready"] is True
        assert state["handlers_registered"] == 0
        assert state["consumers_active"] == 0
        assert state["shutdown_requested"] is False

    def test_health_state_with_handlers_not_started(self, kafka_client: AutoKafkaClient) -> None:
        """Health state with handlers but not started shows not ready."""

        @kafka_client.message_handler("test.topic.v1", MockMessage, group_id="test-group")
        async def handler(message: MockMessage, context: MessageContext) -> None: ...  # Handler body empty

        kafka_client._needs_consumers = True

        state = kafka_client.get_health_state()

        assert state["consumers_ready"] is False
        assert state["handlers_registered"] == 1


class TestEnsureInitialized:
    """Tests for _ensure_initialized method."""

    def test_ensure_initialized_sets_flag(self) -> None:
        """_ensure_initialized marks client as initialized."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        client._ensure_initialized()

        assert client._initialized is True

    def test_ensure_initialized_idempotent(self) -> None:
        """_ensure_initialized only initializes once."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        client._ensure_initialized()
        client._ensure_initialized()

        assert client._initialized is True


class TestSerializeMethod:
    """Tests for serialize method."""

    def test_serialize_returns_bytes(self) -> None:
        """Serialize returns bytes."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        with patch("nohiki_kafka_client.client.auto_client.DLQHandler"):
            client._ensure_initialized()

            mock_message = MagicMock(spec=betterproto2.Message)

            with patch("builtins.bytes", return_value=b"serialized"):
                result = client.serialize("test-topic", mock_message)

            assert result == b"serialized"


class TestStartConsumers:
    """Tests for start_consumers method."""

    def test_start_consumers_calls_auto_start(self, kafka_client: AutoKafkaClient) -> None:
        """start_consumers calls _auto_start_consumers."""
        with patch.object(kafka_client, "_auto_start_consumers") as mock_start:
            kafka_client.start_consumers()
            mock_start.assert_called_once()


class TestAutoStartConsumers:
    """Tests for _auto_start_consumers method."""

    def test_auto_start_creates_tasks(self) -> None:
        """_auto_start_consumers creates consumer tasks."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        async def handler(message: MockMessage, context: MessageContext) -> None: ...  # Handler body empty

        client._handlers["test.topic.v1:test-group:handler"] = HandlerRegistration(
            topic="test.topic.v1",
            message_type=MockMessage,
            group_id="test-group",
            handler_func=handler,
        )
        client._needs_consumers = True

        def mock_create_task_fn(coro: object, **_kwargs: object) -> MagicMock:
            close_method = getattr(coro, "close", None)
            if callable(close_method):
                close_method()
            return MagicMock()

        with (
            patch("nohiki_kafka_client.client.auto_client.DLQHandler"),
            patch("asyncio.create_task", side_effect=mock_create_task_fn) as mock_create_task,
        ):
            client._ensure_initialized()
            client._auto_start_consumers()

            assert client._consumers_started is True
            assert client._consumers_ready is False
            assert mock_create_task.call_count == 1

    def test_auto_start_skips_when_no_handlers(self, kafka_client: AutoKafkaClient) -> None:
        """_auto_start_consumers does nothing without handlers."""
        kafka_client._needs_consumers = True

        kafka_client._auto_start_consumers()

        assert kafka_client._consumers_started is False

    def test_auto_start_skips_when_already_started(self, kafka_client: AutoKafkaClient) -> None:
        """_auto_start_consumers does nothing when already started."""

        @kafka_client.message_handler("test.topic.v1", MockMessage, group_id="test-group")
        async def handler(message: MockMessage, context: MessageContext) -> None: ...  # Handler body empty

        kafka_client._needs_consumers = True
        kafka_client._consumers_started = True

        kafka_client._auto_start_consumers()

        assert len(kafka_client._consumer_tasks) == 0


class TestAutoClientEnsureProducer:
    """Tests for _ensure_producer method."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
    async def test_ensure_producer_initializes_producer(self) -> None:
        """_ensure_producer creates and initializes producer."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )
        client._needs_producer = True

        mock_producer = AsyncMock()
        mock_producer.__aenter__ = AsyncMock(return_value=mock_producer)
        mock_producer.__aexit__ = AsyncMock()

        with patch("nohiki_kafka_client.client.auto_client.KafkaProducer") as mock_producer_cls:
            mock_producer_cls.return_value = mock_producer

            await client._ensure_producer()

            assert client._producer is mock_producer
            mock_producer.__aenter__.assert_called_once()

            client._initialized = True
            await client.close()

    @pytest.mark.asyncio
    async def test_ensure_producer_skips_when_not_needed(self) -> None:
        """_ensure_producer does nothing when producer not needed."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )
        client._needs_producer = False

        await client._ensure_producer()

        assert client._producer is None


class TestStartConsumerForGroup:
    """Tests for _start_consumer_for_group method."""

    @pytest.mark.asyncio
    async def test_start_consumer_registers_supervisor_and_spawns_tasks(self) -> None:
        """_start_consumer_for_group registers a supervised consumer and spawns tasks."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )

        async def handler(message: MockMessage, context: MessageContext) -> None: ...  # Handler body empty

        registration = HandlerRegistration(
            topic="test.topic.v1",
            message_type=MockMessage,
            group_id="test-group",
            handler_func=handler,
        )

        def mock_create_task_fn(coro: object, **_kwargs: object) -> MagicMock:
            close_method = getattr(coro, "close", None)
            if callable(close_method):
                close_method()
            mock = MagicMock()
            mock.done.return_value = False
            return mock

        with (
            patch("nohiki_kafka_client.client.auto_client.DLQHandler"),
            patch("nohiki_kafka_client.client.auto_client.KafkaConsumer"),
            patch("asyncio.create_task", side_effect=mock_create_task_fn),
            patch.object(client, "_ensure_producer", new_callable=AsyncMock),
        ):
            client._ensure_initialized()
            await client._start_consumer_for_group("test-group", [registration])

            # Two tasks spawned: supervised consumer + retry consumer
            assert len(client._consumer_tasks) == 2
            # Group registered with supervisor
            assert "test.topic.v1:test-group" in client._supervisor.get_all_consumers()

    @pytest.mark.asyncio
    async def test_start_consumer_spawns_supervised_and_retry_tasks(self) -> None:
        """_start_consumer_for_group creates exactly two tasks: supervised + retry."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        registration = HandlerRegistration(
            topic="test.topic.v1",
            message_type=MockMessage,
            group_id="test-group",
            handler_func=handler,
        )

        def mock_create_task_fn(coro: object, **_kwargs: object) -> MagicMock:
            close_method = getattr(coro, "close", None)
            if callable(close_method):
                close_method()
            mock = MagicMock()
            mock.done.return_value = False
            return mock

        with (
            patch("nohiki_kafka_client.client.auto_client.DLQHandler"),
            patch("nohiki_kafka_client.client.auto_client.KafkaConsumer"),
            patch.object(client, "_ensure_producer", new_callable=AsyncMock),
            patch("asyncio.create_task", side_effect=mock_create_task_fn),
        ):
            client._ensure_initialized()
            await client._start_consumer_for_group("test-group", [registration])

            # Two tasks: supervisor loop + retry consumer
            assert len(client._consumer_tasks) == 2


class TestMaybeAutoStart:
    """Tests for _maybe_auto_start method."""

    def test_maybe_auto_start_disabled(self) -> None:
        """_maybe_auto_start does nothing when auto_start disabled."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )
        client._config.auto_client.auto_start_consumers = False
        client._needs_consumers = True

        @client.message_handler("test.topic.v1", MockMessage, group_id="test-group")
        async def handler(message: MockMessage, context: MessageContext) -> None: ...  # Handler body empty

        with patch.object(client, "_auto_start_consumers") as mock_auto_start:
            client._maybe_auto_start()
            mock_auto_start.assert_not_called()


class TestAutoClientPublishMethods:
    """Tests for publish and publish_raw methods."""

    @pytest.mark.asyncio
    async def test_publish_in_non_testing_mode(self) -> None:
        """Publish initializes producer in non-testing mode."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )
        client._needs_producer = True

        mock_producer = AsyncMock()
        mock_producer.__aenter__ = AsyncMock(return_value=mock_producer)
        mock_producer.__aexit__ = AsyncMock()
        mock_producer.publish = AsyncMock(return_value=MagicMock())

        with patch("nohiki_kafka_client.client.auto_client.KafkaProducer") as mock_producer_cls:
            mock_producer_cls.return_value = mock_producer

            message = MockMessage(value="test")
            await client.publish("test.topic", message)

            mock_producer.publish.assert_awaited_once()

            await client.close()

    @pytest.mark.asyncio
    async def test_publish_raw_in_non_testing_mode(self) -> None:
        """publish_raw initializes producer in non-testing mode."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=False,
        )
        client._needs_producer = True

        mock_producer = AsyncMock()
        mock_producer.__aenter__ = AsyncMock(return_value=mock_producer)
        mock_producer.__aexit__ = AsyncMock()
        mock_producer.publish_raw = AsyncMock(return_value=MagicMock())

        with patch("nohiki_kafka_client.client.auto_client.KafkaProducer") as mock_producer_cls:
            mock_producer_cls.return_value = mock_producer

            await client.publish_raw("test.topic", b"raw bytes")

            mock_producer.publish_raw.assert_awaited_once()

            await client.close()


class TestSingletonBehavior:
    """Tests for AutoKafkaClient singleton via factory functions."""

    def test_factory_sets_and_gets_global_instance(self) -> None:
        """_set_global_instance / _get_global_instance manage the singleton."""
        from nohiki_kafka_client.client.auto_client import (
            AutoKafkaClient,
            _get_global_instance,
            _global_instance,
            _set_global_instance,
        )
        from nohiki_kafka_client.config import KafkaClientConfig

        original = _global_instance[0]
        try:
            client = AutoKafkaClient(KafkaClientConfig(bootstrap_servers="kafka:29092"), is_testing=True)
            _set_global_instance(client)
            assert _get_global_instance() is client
        finally:
            _global_instance[0] = original

    def test_get_global_instance_returns_none_when_unset(self) -> None:
        """_get_global_instance returns None when no instance is set."""
        from nohiki_kafka_client.client.auto_client import (
            _get_global_instance,
            _global_instance,
        )

        original = _global_instance[0]
        try:
            _global_instance[0] = None
            assert _get_global_instance() is None
        finally:
            _global_instance[0] = original


class TestKafkaClientProperty:
    """Tests for kafka_client property."""

    def test_returns_self(self, kafka_client: AutoKafkaClient) -> None:
        """kafka_client property returns the instance itself."""
        assert kafka_client.kafka_client is kafka_client


class TestEnsureProducerEarlyReturns:
    """Tests for _ensure_producer early return and reinit paths."""

    @pytest.mark.asyncio
    async def test_returns_early_when_producer_ready(self) -> None:
        """_ensure_producer returns immediately when producer is already ready."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(KafkaClientConfig(bootstrap_servers="kafka:29092"), is_testing=True)
        mock_producer = MagicMock()
        mock_producer.is_ready.return_value = True
        client._producer = mock_producer
        client._producer_ready = True

        await client._ensure_producer()
        assert client._producer is mock_producer

    @pytest.mark.asyncio
    async def test_reinitializes_when_producer_not_ready(self) -> None:
        """_ensure_producer reinitializes when producer exists but internal producer is None."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(KafkaClientConfig(bootstrap_servers="kafka:29092"), is_testing=False)
        client._needs_producer = True

        stale_producer = MagicMock()
        stale_producer.is_ready.return_value = False
        client._producer = stale_producer
        client._producer_ready = True

        new_producer = AsyncMock()
        new_producer.__aenter__ = AsyncMock(return_value=new_producer)
        new_producer.is_ready.return_value = True

        with (
            patch("nohiki_kafka_client.client.auto_client.DLQHandler"),
            patch(
                "nohiki_kafka_client.client.auto_client.KafkaProducer",
                return_value=new_producer,
            ),
        ):
            await client._ensure_producer()

        assert client._producer is new_producer
        await client.close()


class TestInitializeAllConsumers:
    """Tests for _initialize_all_consumers method."""

    @pytest.mark.asyncio
    async def test_group_startup_failure_propagates_and_never_marks_ready(self) -> None:
        """Startup failure reaches the owner unchanged and keeps readiness false."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        registration = HandlerRegistration(
            topic="svc.entity.created.v1",
            message_type=MockMessage,
            group_id="g1",
            handler_func=handler,
        )
        client._handlers["startup-failure"] = registration
        client._needs_consumers = True
        failure = RuntimeError("group g1 failed")

        with patch.object(
            client,
            "_start_consumer_for_group",
            new_callable=AsyncMock,
            side_effect=failure,
        ):
            owner = client.start_consumers()
            assert owner is not None
            with pytest.raises(RuntimeError, match="group g1 failed") as raised:
                await client.wait_for_consumers()

        assert raised.value is failure
        state = client.get_health_state()
        assert state["consumers_ready"] is False
        assert state["consumer_failure"] == "group g1 failed"
        assert state["consumer_failure_type"] == "RuntimeError"
        assert state["consumer_tasks_running"] == 0

    @pytest.mark.asyncio
    async def test_fatal_startup_updates_lifecycle_readiness_probe(self) -> None:
        """A consumer owner failure makes the service readiness probe unhealthy."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration
        from nohiki_kafka_client.observability.health import (
            KafkaCapability,
            KafkaHealthProbe,
        )
        from nohiki_kafka_client.supervision.lifecycle import KafkaLifecycleManager

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )
        manager = KafkaLifecycleManager("kafka:29092")

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        registration = HandlerRegistration(
            topic="svc.entity.created.v1",
            message_type=MockMessage,
            group_id="g1",
            handler_func=handler,
        )
        client._handlers["readiness-failure"] = registration
        client._needs_consumers = True
        failure = RuntimeError("fatal consumer startup")

        with (
            patch(
                "nohiki_kafka_client.client.auto_client.get_lifecycle_manager",
                return_value=manager,
            ),
            patch.object(
                client,
                "_start_consumer_for_group",
                new_callable=AsyncMock,
                side_effect=failure,
            ),
        ):
            owner = client.start_consumers()
            assert owner is not None
            with pytest.raises(RuntimeError, match="fatal consumer startup"):
                await client.wait_for_consumers()

        assert manager.health_state.handlers_registered == 1
        assert manager.health_state.consumers_ready is False
        assert manager.health_state.consumer_tasks_running == 0

        probe = KafkaHealthProbe(
            "kafka:29092",
            capabilities={KafkaCapability.CONSUMER_READY},
            lifecycle_manager=manager,
        )
        result = await probe.check()
        assert result.status.value == "unhealthy"
        assert "not ready" in result.message.lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failing_role", ["supervised", "retry"])
    async def test_fatal_child_failure_is_owned_and_drains_live_siblings(
        self,
        failing_role: str,
    ) -> None:
        """Either consumer child can fail the generation without orphaning siblings."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        registration = HandlerRegistration(
            topic="svc.entity.created.v1",
            message_type=MockMessage,
            group_id="g1",
            handler_func=handler,
        )
        client._handlers["fatal-child"] = registration
        client._needs_consumers = True
        children_started = asyncio.Event()
        release_failure = asyncio.Event()
        sibling_cancelled = asyncio.Event()
        readiness_during_cancel: list[bool] = []
        failure = RuntimeError(f"{failing_role} child failed")

        async def failing_child() -> None:
            children_started.set()
            await release_failure.wait()
            raise failure

        async def live_sibling() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                readiness_during_cancel.append(client._consumers_ready)
                sibling_cancelled.set()

        async def mock_start(
            _group_id: str,
            _registrations: list[HandlerRegistration],
        ) -> None:
            failing_task = asyncio.create_task(
                failing_child(),
                name=f"kafka-consumer-g1-{failing_role}",
            )
            sibling_role = "retry" if failing_role == "supervised" else "supervised"
            sibling_task = asyncio.create_task(
                live_sibling(),
                name=f"kafka-consumer-g1-{sibling_role}",
            )
            client._consumer_tasks.extend((failing_task, sibling_task))

        with patch.object(client, "_start_consumer_for_group", side_effect=mock_start):
            owner = client.start_consumers()
            assert owner is not None
            await children_started.wait()
            await asyncio.sleep(0)
            assert client._consumers_ready is True
            release_failure.set()
            with pytest.raises(RuntimeError, match=f"{failing_role} child failed") as raised:
                await asyncio.wait_for(client.wait_for_consumers(), timeout=1.0)

        assert raised.value is failure
        assert sibling_cancelled.is_set()
        assert readiness_during_cancel == [False]
        state = client.get_health_state()
        assert state["consumers_ready"] is False
        assert state["consumer_failure"] == str(failure)
        assert state["consumer_failure_type"] == "RuntimeError"
        assert state["consumer_tasks_running"] == 0

    @pytest.mark.asyncio
    async def test_shutdown_cancellation_is_not_reported_as_fatal(self) -> None:
        """Expected shutdown drains the owner without publishing a false failure."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(
            KafkaClientConfig(bootstrap_servers="kafka:29092"),
            is_testing=True,
        )

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        registration = HandlerRegistration(
            topic="svc.entity.created.v1",
            message_type=MockMessage,
            group_id="g1",
            handler_func=handler,
        )
        client._handlers["shutdown"] = registration
        client._needs_consumers = True
        child_started = asyncio.Event()
        child_cancelled = asyncio.Event()

        async def child() -> None:
            child_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                child_cancelled.set()

        async def mock_start(
            _group_id: str,
            _registrations: list[HandlerRegistration],
        ) -> None:
            client._consumer_tasks.append(asyncio.create_task(child(), name="kafka-consumer-g1-supervised"))

        with patch.object(client, "_start_consumer_for_group", side_effect=mock_start):
            owner = client.start_consumers()
            assert owner is not None
            await child_started.wait()
            await client.stop_consumers(drain_timeout_seconds=1.0)
            await client.wait_for_consumers()

        assert child_cancelled.is_set()
        state = client.get_health_state()
        assert state["consumers_ready"] is False
        assert state["consumer_failure"] is None
        assert state["consumer_failure_type"] is None
        assert state["consumer_tasks_running"] == 0


class TestConsumerFailureSupervision:
    """Tests for the lifespan-facing consumer failure context manager."""

    @pytest.mark.asyncio
    async def test_fatal_owner_failure_interrupts_body_and_propagates_exact_error(
        self, kafka_client: AutoKafkaClient
    ) -> None:
        """A fatal owner task cancels suspended lifespan work and escapes in its group."""
        release_failure = asyncio.Event()
        body_cancelled = asyncio.Event()
        failure = RuntimeError("consumer generation failed")

        async def owner() -> None:
            await release_failure.wait()
            raise failure

        async def run_supervised_body() -> None:
            async with kafka_client.supervise_consumer_failures():
                release_failure.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    body_cancelled.set()

        owner_task = asyncio.create_task(owner(), name="kafka-consumer-owner")
        kafka_client._consumer_owner_task = owner_task
        kafka_client._consumer_tasks.append(owner_task)

        with pytest.raises(ExceptionGroup) as raised:
            await run_supervised_body()

        assert body_cancelled.is_set()
        assert raised.value.exceptions == (failure,)

    @pytest.mark.asyncio
    async def test_normal_exit_cancels_monitor_but_leaves_owner_live(self, kafka_client: AutoKafkaClient) -> None:
        """Leaving normally removes the monitor without cancelling its shielded owner."""
        owner_started = asyncio.Event()

        async def owner() -> None:
            owner_started.set()
            await asyncio.Event().wait()

        owner_task = asyncio.create_task(owner(), name="kafka-consumer-owner")
        kafka_client._consumer_owner_task = owner_task
        kafka_client._consumer_tasks.append(owner_task)
        await owner_started.wait()

        async with kafka_client.supervise_consumer_failures():
            pass

        assert not owner_task.done()
        assert kafka_client._consumer_failure is None
        assert not any(
            task.get_name().endswith("failure-monitor")
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
        )

        owner_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await owner_task

    @pytest.mark.asyncio
    async def test_enter_before_consumers_start_fails(self, kafka_client: AutoKafkaClient) -> None:
        """The context rejects use before a consumer owner exists."""
        from nohiki_kafka_client.exceptions import KafkaClientError

        with pytest.raises(
            KafkaClientError,
            match="Kafka consumers must be started before they can be supervised",
        ):
            async with kafka_client.supervise_consumer_failures():
                pytest.fail("supervision body must not run")

    @pytest.mark.asyncio
    async def test_shutdown_owner_cancellation_is_not_fatal(self, kafka_client: AutoKafkaClient) -> None:
        """Expected owner cancellation during shutdown does not fail the context."""
        owner_started = asyncio.Event()
        owner_cancelled = asyncio.Event()

        async def owner() -> None:
            owner_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                owner_cancelled.set()

        owner_task = asyncio.create_task(owner(), name="kafka-consumer-owner")
        kafka_client._consumer_owner_task = owner_task
        kafka_client._consumer_tasks.append(owner_task)
        await owner_started.wait()

        async with kafka_client.supervise_consumer_failures():
            kafka_client._shutdown_requested = True
            owner_task.cancel()
            await owner_cancelled.wait()

        assert owner_task.cancelled()
        assert kafka_client._consumer_failure is None


class TestEnsureProducerReady:
    """Tests for ensure_producer_ready method."""

    @pytest.mark.asyncio
    async def test_sets_needs_producer_and_calls_ensure(self) -> None:
        """ensure_producer_ready sets _needs_producer and calls _ensure_producer."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(KafkaClientConfig(bootstrap_servers="kafka:29092"), is_testing=True)

        with patch.object(client, "_ensure_producer", new_callable=AsyncMock) as mock_ensure:
            await client.ensure_producer_ready()

        assert client._needs_producer is True
        mock_ensure.assert_awaited_once()


class TestIsProducerReady:
    """Tests for is_producer_ready method."""

    def test_returns_false_when_no_producer(self, kafka_client: AutoKafkaClient) -> None:
        """is_producer_ready returns False when producer is None."""
        assert kafka_client.is_producer_ready() is False

    def test_returns_true_when_producer_and_initialized(self, kafka_client: AutoKafkaClient) -> None:
        """is_producer_ready returns True when producer exists and client initialized."""
        kafka_client._producer = MagicMock()
        kafka_client._initialized = True
        assert kafka_client.is_producer_ready() is True


class TestCleanupConsumerForGroup:
    """Tests for _cleanup_consumer_for_group method."""

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_group_is_noop(self, kafka_client: AutoKafkaClient) -> None:
        """_cleanup_consumer_for_group does nothing for unknown group."""
        await kafka_client._cleanup_consumer_for_group("nonexistent")

    @pytest.mark.asyncio
    async def test_cleanup_calls_aexit_and_removes(self, kafka_client: AutoKafkaClient) -> None:
        """_cleanup_consumer_for_group calls __aexit__ and removes from dict."""
        mock_consumer = AsyncMock()
        mock_consumer.__aexit__ = AsyncMock()
        kafka_client._consumers["test-group"] = mock_consumer

        await kafka_client._cleanup_consumer_for_group("test-group")

        mock_consumer.__aexit__.assert_awaited_once()
        assert "test-group" not in kafka_client._consumers

    @pytest.mark.asyncio
    async def test_cleanup_handles_exception(self, kafka_client: AutoKafkaClient) -> None:
        """_cleanup_consumer_for_group logs but doesn't raise on __aexit__ failure."""
        mock_consumer = AsyncMock()
        mock_consumer.__aexit__ = AsyncMock(side_effect=RuntimeError("cleanup failed"))
        kafka_client._consumers["test-group"] = mock_consumer

        await kafka_client._cleanup_consumer_for_group("test-group")
        assert "test-group" not in kafka_client._consumers


class TestSupervisorIntegration:
    """Tests for ConsumerSupervisor integration in AutoKafkaClient."""

    def test_supervisor_initialized_on_construction(self, kafka_client: AutoKafkaClient) -> None:
        """AutoKafkaClient initializes a ConsumerSupervisor on construction."""
        from nohiki_kafka_client.supervision.supervisor import ConsumerSupervisor

        assert isinstance(kafka_client._supervisor, ConsumerSupervisor)

    def test_health_state_includes_supervisor_summary(self, kafka_client: AutoKafkaClient) -> None:
        """get_health_state includes supervisor health summary."""
        state = kafka_client.get_health_state()

        assert "supervisor" in state
        assert isinstance(state["supervisor"], dict)

    @pytest.mark.asyncio
    async def test_stop_consumers_calls_supervisor_stop_all(self, kafka_client: AutoKafkaClient) -> None:
        """stop_consumers calls supervisor.stop_all() before task cancellation."""
        from nohiki_kafka_client.supervision.supervisor import ConsumerSupervisor

        mock_task = MagicMock()
        mock_task.done.return_value = True
        kafka_client._consumer_tasks.append(mock_task)

        mock_consumer = MagicMock()
        mock_consumer.stop = MagicMock()
        kafka_client._consumers["g1"] = mock_consumer

        # ConsumerSupervisor uses __slots__, so patch at the class level via the module
        with patch.object(ConsumerSupervisor, "stop_all", new_callable=AsyncMock) as mock_stop_all:
            await kafka_client.stop_consumers()

        mock_stop_all.assert_awaited_once()


class TestMaybeAutoStartWithLoop:
    """Tests for _maybe_auto_start when event loop is running."""

    def test_schedules_auto_start_when_loop_running(self) -> None:
        """_maybe_auto_start schedules auto-start via call_soon_threadsafe."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(KafkaClientConfig(bootstrap_servers="kafka:29092"), is_testing=False)
        client._config.auto_client.auto_start_consumers = True
        client._needs_consumers = True

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        client._handlers["key"] = HandlerRegistration(
            topic="test.topic.v1",
            message_type=MockMessage,
            group_id="g1",
            handler_func=handler,
        )

        mock_loop = MagicMock()
        with patch("asyncio.get_running_loop", return_value=mock_loop):
            client._maybe_auto_start()

        mock_loop.call_soon_threadsafe.assert_called_once_with(client._schedule_auto_start)

    def test_no_running_loop_is_silent(self) -> None:
        """_maybe_auto_start silently handles RuntimeError when no loop."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig
        from nohiki_kafka_client.handlers import HandlerRegistration

        client = AutoKafkaClient(KafkaClientConfig(bootstrap_servers="kafka:29092"), is_testing=True)
        client._config.auto_client.auto_start_consumers = True
        client._needs_consumers = True

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        client._handlers["key"] = HandlerRegistration(
            topic="test.topic.v1",
            message_type=MockMessage,
            group_id="g1",
            handler_func=handler,
        )

        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            client._maybe_auto_start()


class TestScheduleAutoStart:
    """Tests for _schedule_auto_start method."""

    def test_delegates_to_auto_start_consumers(self, kafka_client: AutoKafkaClient) -> None:
        """_schedule_auto_start calls _auto_start_consumers."""
        with patch.object(kafka_client, "_auto_start_consumers") as mock_start:
            kafka_client._schedule_auto_start()
            mock_start.assert_called_once()


class TestPublishJson:
    """Tests for publish_json method."""

    @pytest.mark.asyncio
    async def test_publish_json_testing_mode(self, kafka_client: AutoKafkaClient) -> None:
        """publish_json returns mock metadata in testing mode."""
        result = await kafka_client.publish_json("test.topic", {"key": "value"})
        assert result.topic == "test.topic"

    @pytest.mark.asyncio
    async def test_publish_json_non_testing_mode(self) -> None:
        """publish_json delegates to producer.publish_json in non-testing mode."""
        from nohiki_kafka_client.client.auto_client import AutoKafkaClient
        from nohiki_kafka_client.config import KafkaClientConfig

        client = AutoKafkaClient(KafkaClientConfig(bootstrap_servers="kafka:29092"), is_testing=False)
        client._needs_producer = True

        mock_producer = AsyncMock()
        mock_producer.__aenter__ = AsyncMock(return_value=mock_producer)
        mock_producer.__aexit__ = AsyncMock()
        mock_producer.publish_json = AsyncMock(return_value=MagicMock())

        with patch("nohiki_kafka_client.client.auto_client.KafkaProducer") as mock_producer_cls:
            mock_producer_cls.return_value = mock_producer

            await client.publish_json("test.topic", {"key": "value"})
            mock_producer.publish_json.assert_awaited_once()

            await client.close()

    @pytest.mark.asyncio
    async def test_publish_json_raises_when_producer_none(self, kafka_client: AutoKafkaClient) -> None:
        """Publish_json raises KafkaClientError when producer fails to initialize."""
        from nohiki_kafka_client.exceptions import KafkaClientError

        kafka_client._is_testing = False

        with (
            patch.object(kafka_client, "_ensure_producer", new_callable=AsyncMock),
            pytest.raises(KafkaClientError, match="Producer not initialized"),
        ):
            await kafka_client.publish_json("test.topic", {"key": "value"})


class TestPublishProducerNoneGuard:
    """Tests for publish/publish_raw when producer is None after ensure."""

    @pytest.mark.asyncio
    async def test_publish_raises_when_producer_none(self, kafka_client: AutoKafkaClient) -> None:
        """Publish raises KafkaClientError when producer fails to initialize."""
        from nohiki_kafka_client.exceptions import KafkaClientError

        kafka_client._is_testing = False

        with (
            patch.object(kafka_client, "_ensure_producer", new_callable=AsyncMock),
            pytest.raises(KafkaClientError, match="Producer not initialized"),
        ):
            await kafka_client.publish("test.topic", MockMessage(value="test"))

    @pytest.mark.asyncio
    async def test_publish_raw_raises_when_producer_none(self, kafka_client: AutoKafkaClient) -> None:
        """Publish_raw raises KafkaClientError when producer fails to initialize."""
        from nohiki_kafka_client.exceptions import KafkaClientError

        kafka_client._is_testing = False

        with (
            patch.object(kafka_client, "_ensure_producer", new_callable=AsyncMock),
            pytest.raises(KafkaClientError, match="Producer not initialized"),
        ):
            await kafka_client.publish_raw("test.topic", b"raw")


class TestMessageHandlerMetadataApplication:
    """Tests for message_handler picking up pre-stored metadata.

    Decorator order matters: decorators below @message_handler run FIRST,
    storing metadata that @message_handler then reads during registration.
    """

    def test_applies_resilience_config_from_prestored_metadata(self, kafka_client: AutoKafkaClient) -> None:
        """message_handler reads resilience_config from metadata stored before registration."""

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        kafka_client.with_resilience(max_retries=7, strategy="log_only")(handler)
        kafka_client.message_handler("test.topic.v1", MockMessage, group_id="test-group")(handler)

        reg = next(iter(kafka_client._handlers.values()))
        assert reg.resilience_config is not None
        assert reg.resilience_config.max_retries == 7

    def test_applies_transactional_from_prestored_metadata(self, kafka_client: AutoKafkaClient) -> None:
        """message_handler reads is_transactional from metadata stored before registration."""

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        kafka_client.transactional(handler)
        kafka_client.message_handler("test.topic.v1", MockMessage, group_id="test-group")(handler)

        reg = next(iter(kafka_client._handlers.values()))
        assert reg.is_transactional is True


class TestTransactionalDecorator:
    """Tests for transactional decorator standalone behavior."""

    def test_transactional_stores_metadata(self, kafka_client: AutoKafkaClient) -> None:
        """@transactional stores is_transactional in handler metadata."""

        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        decorated = kafka_client.transactional(handler)
        assert decorated is handler
        assert kafka_client._handler_metadata[id(handler)].is_transactional is True

    def test_transactional_updates_existing_registration(self, kafka_client: AutoKafkaClient) -> None:
        """@transactional updates existing registration if handler already registered."""

        @kafka_client.message_handler("test.topic.v1", MockMessage, group_id="test-group")
        async def handler(message: MockMessage, context: MessageContext) -> None: ...

        kafka_client.transactional(handler)
        reg = next(iter(kafka_client._handlers.values()))
        assert reg.is_transactional is True


class TestCloseProducerException:
    """Tests for close() handling producer __aexit__ exceptions."""

    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
    async def test_close_handles_producer_cleanup_error(self, kafka_client: AutoKafkaClient) -> None:
        """close() catches KafkaClientError from producer __aexit__ and still cleans up."""
        from nohiki_kafka_client.exceptions import KafkaClientError

        mock_producer = AsyncMock()
        mock_producer.__aexit__ = AsyncMock(side_effect=KafkaClientError("cleanup error"))
        kafka_client._producer = mock_producer

        await kafka_client.close()

        assert kafka_client._producer is None
        assert kafka_client._producer_ready is False


class TestWaitForConsumerCatchup:
    """Tests for the public startup catch-up barrier."""

    @staticmethod
    def _register_group(client: AutoKafkaClient, group_id: str = "projection-group") -> None:
        registration = MagicMock()
        registration.group_id = group_id
        client._handlers["registration"] = registration
        client._consumers_started = True

    @pytest.mark.asyncio
    async def test_waits_for_delayed_consumer_and_assignment_then_keeps_static_snapshot(
        self, kafka_client: AutoKafkaClient
    ) -> None:
        self._register_group(kafka_client)
        consumer = MagicMock()
        consumer.snapshot_end_offsets = AsyncMock(side_effect=[None, {("events", 0): 5}])
        consumer.has_reached_offsets = AsyncMock(side_effect=[False, True])
        polls = 0

        async def advance(_delay: float) -> None:
            nonlocal polls
            polls += 1
            if polls == 1:
                kafka_client._consumers["projection-group"] = consumer

        with patch("nohiki_kafka_client.client.auto_client.asyncio.sleep", side_effect=advance):
            await kafka_client.wait_for_consumer_catchup("projection-group", 1)

        assert consumer.snapshot_end_offsets.await_count == 2
        assert consumer.has_reached_offsets.await_args_list == [
            (({("events", 0): 5},),),
            (({("events", 0): 5},),),
        ]

    @pytest.mark.asyncio
    async def test_uses_one_snapshot_even_if_broker_end_would_advance(self, kafka_client: AutoKafkaClient) -> None:
        self._register_group(kafka_client)
        consumer = MagicMock()
        consumer.snapshot_end_offsets = AsyncMock(return_value={("events", 0): 5})
        consumer.has_reached_offsets = AsyncMock(side_effect=[False, True])
        kafka_client._consumers["projection-group"] = consumer

        with patch(
            "nohiki_kafka_client.client.auto_client.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            await kafka_client.wait_for_consumer_catchup("projection-group", 1)

        consumer.snapshot_end_offsets.assert_awaited_once()
        assert all(call.args == ({("events", 0): 5},) for call in consumer.has_reached_offsets.await_args_list)

    @pytest.mark.asyncio
    async def test_rejects_unknown_and_stopped_groups(self, kafka_client: AutoKafkaClient) -> None:
        from nohiki_kafka_client.exceptions import KafkaClientError

        with pytest.raises(KafkaClientError, match="No consumer handlers registered"):
            await kafka_client.wait_for_consumer_catchup("unknown", 1)

        self._register_group(kafka_client)
        kafka_client._consumers_started = False
        with pytest.raises(KafkaClientError, match="consumers are stopped"):
            await kafka_client.wait_for_consumer_catchup("projection-group", 1)

    @pytest.mark.asyncio
    async def test_times_out_with_clear_group_failure(self, kafka_client: AutoKafkaClient) -> None:
        from nohiki_kafka_client.exceptions import KafkaClientError

        self._register_group(kafka_client)
        with pytest.raises(KafkaClientError, match=r"projection-group.*startup offset snapshot"):
            await kafka_client.wait_for_consumer_catchup("projection-group", 0.001)
