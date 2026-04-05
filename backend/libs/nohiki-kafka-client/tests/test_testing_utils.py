"""Unit tests for testing utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestKafkaContainerImage:
    """Tests for KAFKA_CONTAINER_IMAGE constant."""

    def test_image_is_confluent_kafka(self) -> None:
        """Container image uses Confluent's cp-kafka."""
        from nohiki_kafka_client.testing import KAFKA_CONTAINER_IMAGE

        assert KAFKA_CONTAINER_IMAGE.startswith("confluentinc/cp-kafka:")

    def test_image_has_version_tag(self) -> None:
        """Container image specifies a pinned version tag."""
        from nohiki_kafka_client.testing import KAFKA_CONTAINER_IMAGE

        _, tag = KAFKA_CONTAINER_IMAGE.split(":")
        assert tag != "latest"


class TestGetTestConsumerKwargs:
    """Tests for get_test_consumer_kwargs function."""

    def test_returns_kwargs_dict(self) -> None:
        """get_test_consumer_kwargs returns aiokafka-compatible kwargs."""
        from nohiki_kafka_client.testing import get_test_consumer_kwargs

        kwargs = get_test_consumer_kwargs("localhost:29092")

        assert kwargs["bootstrap_servers"] == "localhost:29092"
        assert kwargs["group_id"] == "test-group"
        assert kwargs["auto_offset_reset"] == "earliest"
        assert kwargs["enable_auto_commit"] is False

    def test_custom_consumer_group(self) -> None:
        """get_test_consumer_kwargs accepts custom consumer group."""
        from nohiki_kafka_client.testing import get_test_consumer_kwargs

        kwargs = get_test_consumer_kwargs("localhost:29092", consumer_group="custom-group")

        assert kwargs["group_id"] == "custom-group"


class TestGetTestProducerKwargs:
    """Tests for get_test_producer_kwargs function."""

    def test_returns_kwargs_dict(self) -> None:
        """get_test_producer_kwargs returns aiokafka-compatible kwargs."""
        from nohiki_kafka_client.testing import get_test_producer_kwargs

        kwargs = get_test_producer_kwargs("localhost:29092")

        assert kwargs["bootstrap_servers"] == "localhost:29092"
        assert kwargs["acks"] == "all"
        assert kwargs["request_timeout_ms"] == 10000


class TestKafkaContainerFixture:
    """Tests for kafka_container pytest fixture with mocked Docker."""

    def test_happy_path_yields_bootstrap_server(self) -> None:
        """Lifecycle generator yields bootstrap server when Docker is available."""
        from nohiki_kafka_client.testing import _kafka_container_lifecycle

        mock_container = MagicMock()
        mock_container.get_bootstrap_server.return_value = "localhost:29092"

        with (
            patch("nohiki_kafka_client.testing.docker_daemon_available", return_value=True),
            patch(
                "testcontainers.kafka.KafkaContainer",
                return_value=mock_container,
            ),
        ):
            gen = _kafka_container_lifecycle()
            bootstrap = next(gen)

            assert bootstrap == "localhost:29092"
            mock_container.start.assert_called_once()

            with pytest.raises(StopIteration):
                next(gen)

            mock_container.stop.assert_called_once()

    def test_skips_when_docker_unavailable(self) -> None:
        """Lifecycle skips when Docker daemon is not available."""
        from nohiki_kafka_client.testing import _kafka_container_lifecycle

        with patch("nohiki_kafka_client.testing.docker_daemon_available", return_value=False):
            gen = _kafka_container_lifecycle()
            with pytest.raises(pytest.skip.Exception):
                next(gen)

    def test_skips_when_container_start_fails(self) -> None:
        """Lifecycle skips when container fails to start."""
        from nohiki_kafka_client.testing import _kafka_container_lifecycle

        mock_container = MagicMock()
        mock_container.start.side_effect = RuntimeError("Cannot connect to Docker")

        with (
            patch("nohiki_kafka_client.testing.docker_daemon_available", return_value=True),
            patch(
                "testcontainers.kafka.KafkaContainer",
                return_value=mock_container,
            ),
        ):
            gen = _kafka_container_lifecycle()
            with pytest.raises(pytest.skip.Exception):
                next(gen)
