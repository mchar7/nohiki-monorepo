"""Tests for Kafka health probe."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_kafka_client.observability.health import KafkaCapability, KafkaHealthProbe


class TestKafkaCapability:
    """Tests for KafkaCapability enum."""

    def test_enum_values(self) -> None:
        """Verify all expected capabilities exist."""
        assert KafkaCapability.BROKER_CONNECTIVITY.value == "broker_connectivity"
        assert KafkaCapability.CONSUMER_READY.value == "consumer_ready"
        assert KafkaCapability.PRODUCER_READY.value == "producer_ready"


class TestKafkaHealthProbe:
    """Tests for KafkaHealthProbe."""

    def test_name_property(self) -> None:
        """Probe name is 'kafka'."""
        probe = KafkaHealthProbe("localhost:29092")
        assert probe.name == "kafka"

    def test_init_default_capabilities(self) -> None:
        """Default capabilities is BROKER_CONNECTIVITY."""
        probe = KafkaHealthProbe("localhost:29092")
        assert KafkaCapability.BROKER_CONNECTIVITY in probe._capabilities

    def test_init_custom_capabilities(self) -> None:
        """Custom capabilities are stored."""
        caps = {KafkaCapability.CONSUMER_READY, KafkaCapability.PRODUCER_READY}
        probe = KafkaHealthProbe("localhost:29092", capabilities=caps)
        assert probe._capabilities == caps

    @pytest.mark.asyncio
    async def test_check_broker_connectivity_failure(self) -> None:
        """Returns unhealthy when broker connection fails."""
        probe = KafkaHealthProbe(
            "invalid:9092",
            capabilities={KafkaCapability.BROKER_CONNECTIVITY},
            timeout_seconds=1.0,
        )
        broker_check = AsyncMock(return_value=(False, 0, "Connection refused"))

        with patch("nohiki_kafka_client.observability.health.check_broker_connectivity", broker_check):
            result = await probe.check()

        assert result.status.value == "unhealthy"
        assert result.message == "Connection refused"
        broker_check.assert_awaited_once_with("invalid:9092", timeout_seconds=1.0)

    @pytest.mark.asyncio
    async def test_check_consumer_ready_no_manager(self) -> None:
        """Consumer check returns healthy when no lifecycle manager."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.CONSUMER_READY},
        )
        ok, err = probe._check_consumer_ready()
        assert ok is True
        assert err is None

    @pytest.mark.asyncio
    async def test_check_producer_ready_no_client(self) -> None:
        """Producer check returns healthy when no client exists."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.PRODUCER_READY},
        )
        ok, err = probe._check_producer_ready()
        assert ok is True
        assert err is None

    @pytest.mark.asyncio
    async def test_check_exception_handling(self) -> None:
        """Returns unhealthy when exception raised during check."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.BROKER_CONNECTIVITY},
        )

        with patch(
            "nohiki_kafka_client.observability.health.KafkaHealthProbe._check_broker_connectivity",
            side_effect=RuntimeError("Test error"),
        ):
            result = await probe.check()
            assert result.status.value == "unhealthy"
            assert "Test error" in result.message

    def test_check_consumer_with_lifecycle_manager(self) -> None:
        """Consumer check uses lifecycle manager when provided."""
        mock_manager = MagicMock()
        mock_manager.health_state.handlers_registered = 2
        mock_manager.health_state.consumers_ready = True
        mock_manager.health_state.consumers_active = 2

        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.CONSUMER_READY},
            lifecycle_manager=mock_manager,
        )
        ok, _ = probe._check_consumer_ready()
        assert ok is True

    def test_check_consumer_not_ready(self) -> None:
        """Consumer check returns unhealthy when consumers not ready."""
        mock_manager = MagicMock()
        mock_manager.health_state.handlers_registered = 2
        mock_manager.health_state.consumers_ready = False
        mock_manager.health_state.consumers_active = 0

        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.CONSUMER_READY},
            lifecycle_manager=mock_manager,
        )
        ok, err = probe._check_consumer_ready()
        assert ok is False
        assert err is not None
        assert "not ready" in err.lower()

    @pytest.mark.asyncio
    async def test_check_all_capabilities_healthy(self) -> None:
        """Returns healthy when all capabilities pass."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.CONSUMER_READY, KafkaCapability.PRODUCER_READY},
        )
        result = await probe.check()
        assert result.is_healthy()
        assert result.details is not None
        assert "capabilities" in result.details

    @pytest.mark.asyncio
    async def test_check_consumer_failures_only(self) -> None:
        """Returns unhealthy when consumer check fails."""
        mock_manager = MagicMock()
        mock_manager.health_state.handlers_registered = 2
        mock_manager.health_state.consumers_ready = False
        mock_manager.health_state.consumers_active = 0

        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.CONSUMER_READY},
            lifecycle_manager=mock_manager,
        )

        result = await probe.check()
        assert result.status.value == "unhealthy"


class TestKafkaHealthProbeConnectivity:
    """Tests for connectivity check."""

    @pytest.mark.asyncio
    async def test_connectivity_check_no_brokers(self) -> None:
        """Connectivity check fails when no brokers."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.BROKER_CONNECTIVITY},
        )

        mock_producer = MagicMock()
        mock_producer.start = AsyncMock()
        mock_producer.stop = AsyncMock()
        mock_cluster = MagicMock()
        mock_cluster.brokers.return_value = []  # No brokers
        mock_producer.client.cluster = mock_cluster

        with patch("nohiki_kafka_client.utils.broker_check.AIOKafkaProducer", return_value=mock_producer):
            result = await probe.check()

        assert not result.is_healthy()
        assert "No brokers" in result.message

    @pytest.mark.asyncio
    async def test_connectivity_check_os_error(self) -> None:
        """Connectivity check handles OSError."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.BROKER_CONNECTIVITY},
        )

        with patch("nohiki_kafka_client.utils.broker_check.AIOKafkaProducer", side_effect=OSError("connection failed")):
            result = await probe.check()

        assert not result.is_healthy()


class TestKafkaHealthProbeProducerReady:
    """Tests for producer ready check."""

    @pytest.mark.asyncio
    async def test_producer_ready_when_not_initialized(self) -> None:
        """Producer check returns true when client not available."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.PRODUCER_READY},
        )

        with patch("nohiki_kafka_client.client.factory.get_kafka_client", return_value=None):
            result = await probe.check()

        assert result.is_healthy()

    @pytest.mark.asyncio
    async def test_producer_ready_when_initialized(self) -> None:
        """Producer check returns true when producer ready."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.PRODUCER_READY},
        )

        mock_client = MagicMock()
        mock_client.is_producer_ready.return_value = True

        with patch("nohiki_kafka_client.client.factory.get_kafka_client", return_value=mock_client):
            result = await probe.check()

        assert result.is_healthy()

    @pytest.mark.asyncio
    async def test_producer_not_ready(self) -> None:
        """Producer check returns false when producer not ready."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.PRODUCER_READY},
        )

        mock_client = MagicMock()
        mock_client.is_producer_ready.return_value = False

        with patch("nohiki_kafka_client.client.factory.get_kafka_client", return_value=mock_client):
            result = await probe.check()

        assert not result.is_healthy()


class TestKafkaHealthProbeConsumerReady:
    """Tests for consumer ready check."""

    @pytest.mark.asyncio
    async def test_consumer_ready_no_lifecycle_manager(self) -> None:
        """Consumer check returns true when lifecycle manager unavailable."""
        probe = KafkaHealthProbe(
            "localhost:29092",
            capabilities={KafkaCapability.CONSUMER_READY},
            lifecycle_manager=None,
        )

        with patch("nohiki_kafka_client.supervision.lifecycle.get_lifecycle_manager", side_effect=ImportError):
            result = await probe.check()

        assert result.is_healthy()
