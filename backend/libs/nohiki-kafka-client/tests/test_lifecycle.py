"""Unit tests for Kafka lifecycle management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_kafka_client.supervision.lifecycle import (
    KafkaConnectionState,
    KafkaHealthState,
    KafkaLifecycleConfig,
    KafkaLifecycleManager,
)


class _FakeClock:
    def __init__(self) -> None:
        self.elapsed = 0.0
        self.delays: list[float] = []

    def __call__(self) -> float:
        return self.elapsed

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        self.elapsed += delay


class TestKafkaConnectionState:
    """Tests for KafkaConnectionState enum."""

    def test_enum_values(self) -> None:
        """Enum has expected values."""
        assert KafkaConnectionState.DISCONNECTED.value == "disconnected"
        assert KafkaConnectionState.CONNECTING.value == "connecting"
        assert KafkaConnectionState.CONNECTED.value == "connected"
        assert KafkaConnectionState.RECONNECTING.value == "reconnecting"
        assert KafkaConnectionState.FAILED.value == "failed"


class TestKafkaHealthState:
    """Tests for KafkaHealthState dataclass."""

    def test_default_state(self) -> None:
        """Default state is disconnected."""
        state = KafkaHealthState()
        assert state.state == KafkaConnectionState.DISCONNECTED
        assert state.last_successful_connection is None
        assert state.last_error is None
        assert state.consecutive_failures == 0
        assert state.broker_count == 0
        assert state.consumers_ready is False
        assert state.handlers_registered == 0

    def test_is_healthy_when_connected_no_handlers(self) -> None:
        """is_healthy True when connected with brokers and no handlers."""
        state = KafkaHealthState(
            state=KafkaConnectionState.CONNECTED,
            broker_count=3,
            handlers_registered=0,
        )
        assert state.is_healthy is True

    def test_is_healthy_when_connected_with_ready_consumers(self) -> None:
        """is_healthy True when connected with ready consumers."""
        state = KafkaHealthState(
            state=KafkaConnectionState.CONNECTED,
            broker_count=3,
            handlers_registered=2,
            consumers_ready=True,
        )
        assert state.is_healthy is True

    def test_not_healthy_when_connected_consumers_not_ready(self) -> None:
        """is_healthy False when connected but consumers not ready."""
        state = KafkaHealthState(
            state=KafkaConnectionState.CONNECTED,
            broker_count=3,
            handlers_registered=2,
            consumers_ready=False,
        )
        assert state.is_healthy is False

    def test_not_healthy_when_disconnected(self) -> None:
        """is_healthy False when disconnected."""
        state = KafkaHealthState(state=KafkaConnectionState.DISCONNECTED)
        assert state.is_healthy is False

    def test_not_healthy_when_no_brokers(self) -> None:
        """is_healthy False when no brokers."""
        state = KafkaHealthState(
            state=KafkaConnectionState.CONNECTED,
            broker_count=0,
        )
        assert state.is_healthy is False

    def test_to_dict(self) -> None:
        """to_dict returns dictionary representation."""
        state = KafkaHealthState(
            state=KafkaConnectionState.CONNECTED,
            broker_count=3,
            handlers_registered=2,
            consumers_ready=True,
        )
        result = state.to_dict()
        assert result["state"] == "connected"
        assert result["healthy"] is True
        assert result["broker_count"] == 3
        assert result["handlers_registered"] == 2
        assert result["consumers_ready"] is True


class TestKafkaLifecycleConfig:
    """Tests for KafkaLifecycleConfig dataclass."""

    def test_default_config(self) -> None:
        """Default config has expected values."""
        config = KafkaLifecycleConfig()
        assert config.startup_timeout_seconds == 120
        assert config.startup_retry_interval_seconds == 2
        assert config.health_check_interval_seconds == 30
        assert config.reconnect_backoff_seconds == 5
        assert config.max_reconnect_backoff_seconds == 60
        assert config.fail_fast_on_startup is False

    def test_custom_config(self) -> None:
        """Can create config with custom values."""
        config = KafkaLifecycleConfig(
            startup_timeout_seconds=60,
            fail_fast_on_startup=True,
        )
        assert config.startup_timeout_seconds == 60
        assert config.fail_fast_on_startup is True


class TestKafkaLifecycleManager:
    """Tests for KafkaLifecycleManager."""

    def test_init_with_defaults(self) -> None:
        """Manager initializes with default config."""
        manager = KafkaLifecycleManager("localhost:29092")
        assert manager._bootstrap_servers == "localhost:29092"
        assert manager._config is not None
        assert manager._health_state is not None

    def test_init_with_custom_config(self) -> None:
        """Manager initializes with custom config."""
        config = KafkaLifecycleConfig(startup_timeout_seconds=30)
        manager = KafkaLifecycleManager("localhost:29092", config)
        assert manager._config.startup_timeout_seconds == 30

    def test_health_state_property(self) -> None:
        """health_state property returns current state."""
        manager = KafkaLifecycleManager("localhost:29092")
        state = manager.health_state
        assert isinstance(state, KafkaHealthState)
        assert state.state == KafkaConnectionState.DISCONNECTED

    def test_is_healthy_property(self) -> None:
        """is_healthy property returns health state."""
        manager = KafkaLifecycleManager("localhost:29092")
        assert manager.is_healthy is False

    def test_update_consumer_state(self) -> None:
        """update_consumer_state updates health state."""
        manager = KafkaLifecycleManager("localhost:29092")
        manager.update_consumer_state(
            consumers_ready=True,
            handlers_registered=3,
            consumers_active=2,
            consumer_tasks_running=2,
        )
        state = manager.health_state
        assert state.consumers_ready is True
        assert state.handlers_registered == 3
        assert state.consumers_active == 2
        assert state.consumer_tasks_running == 2

    @pytest.mark.asyncio
    async def test_check_connectivity_async_success(self) -> None:
        """_check_connectivity_async returns True with broker count on success."""
        manager = KafkaLifecycleManager("localhost:29092")

        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_cluster = MagicMock()
        mock_cluster.brokers.return_value = [MagicMock(), MagicMock()]
        mock_producer.client.cluster = mock_cluster

        with patch("nohiki_kafka_client.utils.broker_check.AIOKafkaProducer", return_value=mock_producer):
            connected, broker_count, error = await manager._check_connectivity_async()

            assert connected is True
            assert broker_count == 2
            assert error is None

    @pytest.mark.asyncio
    async def test_check_connectivity_async_no_brokers(self) -> None:
        """_check_connectivity_async returns False when no brokers."""
        manager = KafkaLifecycleManager("localhost:29092")

        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_cluster = MagicMock()
        mock_cluster.brokers.return_value = []
        mock_producer.client.cluster = mock_cluster

        with patch("nohiki_kafka_client.utils.broker_check.AIOKafkaProducer", return_value=mock_producer):
            connected, broker_count, error = await manager._check_connectivity_async()

            assert connected is False
            assert broker_count == 0
            assert error is not None

    @pytest.mark.asyncio
    async def test_check_connectivity_async_error(self) -> None:
        """_check_connectivity_async returns False on error."""
        with patch(
            "nohiki_kafka_client.utils.broker_check.AIOKafkaProducer", side_effect=OSError("Connection refused")
        ):
            manager = KafkaLifecycleManager("localhost:29092")
            connected, broker_count, error = await manager._check_connectivity_async()

            assert connected is False
            assert broker_count == 0
            assert error is not None

    @pytest.mark.asyncio
    async def test_check_connectivity_success(self) -> None:
        """check_connectivity updates state on success."""
        manager = KafkaLifecycleManager("localhost:29092")

        with patch(
            "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
            new_callable=AsyncMock,
            return_value=(True, 3, None),
        ):
            result = await manager.check_connectivity()

            assert result is True
            assert manager.health_state.state == KafkaConnectionState.CONNECTED
            assert manager.health_state.broker_count == 3

    @pytest.mark.asyncio
    async def test_check_connectivity_failure(self) -> None:
        """check_connectivity updates state on failure."""
        manager = KafkaLifecycleManager("localhost:29092")

        with patch(
            "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
            new_callable=AsyncMock,
            return_value=(False, 0, "Connection failed"),
        ):
            result = await manager.check_connectivity()

            assert result is False
            assert manager.health_state.state == KafkaConnectionState.CONNECTING
            assert manager.health_state.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_check_connectivity_reconnecting(self) -> None:
        """check_connectivity sets RECONNECTING when previously connected."""
        manager = KafkaLifecycleManager("localhost:29092")
        manager._health_state.state = KafkaConnectionState.CONNECTED

        with patch(
            "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
            new_callable=AsyncMock,
            return_value=(False, 0, "Connection lost"),
        ):
            result = await manager.check_connectivity()

            assert result is False
            assert manager.health_state.state == KafkaConnectionState.RECONNECTING

    @pytest.mark.asyncio
    async def test_wait_for_kafka_success(self) -> None:
        """wait_for_kafka returns True when Kafka becomes available."""
        config = KafkaLifecycleConfig(
            startup_timeout_seconds=5,
            startup_retry_interval_seconds=0.1,
        )
        manager = KafkaLifecycleManager("localhost:29092", config)

        with patch(
            "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
            new_callable=AsyncMock,
            return_value=(True, 3, None),
        ):
            result = await manager.wait_for_kafka()
            assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_kafka_timeout(self) -> None:
        """wait_for_kafka returns False on timeout."""
        config = KafkaLifecycleConfig(
            startup_timeout_seconds=0.2,
            startup_retry_interval_seconds=0.1,
        )
        clock = _FakeClock()
        manager = KafkaLifecycleManager("localhost:29092", config, monotonic=clock, sleep=clock.sleep)

        with patch(
            "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
            new_callable=AsyncMock,
            return_value=(False, 0, "Connection failed"),
        ):
            result = await manager.wait_for_kafka()
            assert result is False
            assert clock.delays == pytest.approx([0.1, 0.1])
            assert manager.health_state.state == KafkaConnectionState.FAILED

    @pytest.mark.asyncio
    async def test_wait_for_kafka_fail_fast(self) -> None:
        """wait_for_kafka raises when fail_fast_on_startup is True."""
        config = KafkaLifecycleConfig(
            startup_timeout_seconds=0.2,
            startup_retry_interval_seconds=0.1,
            fail_fast_on_startup=True,
        )
        clock = _FakeClock()
        manager = KafkaLifecycleManager("localhost:29092", config, monotonic=clock, sleep=clock.sleep)

        with (
            patch(
                "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
                new_callable=AsyncMock,
                return_value=(False, 0, "Connection failed"),
            ),
            pytest.raises(RuntimeError, match="unavailable"),
        ):
            await manager.wait_for_kafka()

        assert clock.delays == pytest.approx([0.1, 0.1])


class TestEnsureKafkaReady:
    """Tests for ensure_kafka_ready() convenience function."""

    @pytest.mark.asyncio
    async def test_without_required_topics(self) -> None:
        """ensure_kafka_ready succeeds without topic validation."""
        with patch(
            "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
            new_callable=AsyncMock,
            return_value=(True, 3, None),
        ):
            from nohiki_kafka_client.supervision.lifecycle import ensure_kafka_ready

            manager = await ensure_kafka_ready(
                "localhost:29092",
                timeout_seconds=5,
                retry_interval_seconds=0.1,
            )
            assert manager.is_healthy

    @pytest.mark.asyncio
    async def test_with_required_topics_all_present(self) -> None:
        """ensure_kafka_ready succeeds when all required topics exist."""
        mock_admin = AsyncMock()
        mock_admin.list_topics.return_value = ("topic-a", "topic-b", "__consumer_offsets")

        with (
            patch(
                "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
                new_callable=AsyncMock,
                return_value=(True, 3, None),
            ),
            patch(
                "nohiki_kafka_client.admin.KafkaAdmin",
            ) as mock_admin_cls,
        ):
            mock_admin_cls.return_value.__aenter__ = AsyncMock(return_value=mock_admin)
            mock_admin_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from nohiki_kafka_client.supervision.lifecycle import ensure_kafka_ready

            manager = await ensure_kafka_ready(
                "localhost:29092",
                timeout_seconds=5,
                retry_interval_seconds=0.1,
                required_topics=["topic-a", "topic-b"],
            )
            assert manager.is_healthy

    @pytest.mark.asyncio
    async def test_with_required_topics_missing(self) -> None:
        """ensure_kafka_ready raises when required topics are missing."""
        mock_admin = AsyncMock()
        mock_admin.list_topics.return_value = ("topic-a",)

        with (
            patch(
                "nohiki_kafka_client.supervision.lifecycle.check_broker_connectivity",
                new_callable=AsyncMock,
                return_value=(True, 3, None),
            ),
            patch(
                "nohiki_kafka_client.admin.KafkaAdmin",
            ) as mock_admin_cls,
        ):
            mock_admin_cls.return_value.__aenter__ = AsyncMock(return_value=mock_admin)
            mock_admin_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            from nohiki_kafka_client.supervision.lifecycle import ensure_kafka_ready

            with pytest.raises(RuntimeError, match="topic-b"):
                await ensure_kafka_ready(
                    "localhost:29092",
                    timeout_seconds=5,
                    retry_interval_seconds=0.1,
                    required_topics=["topic-a", "topic-b"],
                )
