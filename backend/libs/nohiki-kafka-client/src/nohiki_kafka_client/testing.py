"""Testing utilities for Kafka - testcontainer fixtures and helpers."""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

import pytest
from nohiki_test_utils import docker_daemon_available

if TYPE_CHECKING:
    from collections.abc import Generator

logger = logging.getLogger(__name__)

KAFKA_CONTAINER_IMAGE = "confluentinc/cp-kafka:8.0.1"


def _kafka_container_lifecycle() -> Generator[str]:
    """Manage the lifecycle of a Kafka testcontainer.

    Separated from the fixture so it can be unit-tested without pytest's
    fixture machinery.

    Yields:
        Kafka bootstrap server address (host:port).

    Raises:
        pytest.skip: If Docker daemon is unavailable or container fails to start.

    """
    from testcontainers.kafka import KafkaContainer

    if not docker_daemon_available():
        pytest.skip("Kafka container could not be started: Docker daemon unavailable")

    container = KafkaContainer(KAFKA_CONTAINER_IMAGE)
    container.with_kraft()  # KRaft mode required for Kafka 8.x (no ZooKeeper)
    container.with_env("KAFKA_AUTO_CREATE_TOPICS_ENABLE", "true")

    try:
        container.start()
        bootstrap_server = container.get_bootstrap_server()
        logger.info("Kafka test container started at %s", bootstrap_server)
        yield bootstrap_server
    except (RuntimeError, OSError) as exc:
        pytest.skip(f"Kafka container could not be started: {exc}")
    finally:
        with contextlib.suppress(Exception):
            container.stop()
            logger.info("Kafka test container stopped")


@pytest.fixture(scope="session")
def kafka_container() -> Generator[str]:
    """Session-scoped Kafka testcontainer fixture.

    Only ONE container is created per test session. Intentionally NOT imported
    in the top-level conftest to avoid spinning up a container for unit tests.

    Yields:
        Kafka bootstrap server address (host:port).

    """
    yield from _kafka_container_lifecycle()


def kafka_bootstrap_servers(kafka_container: str) -> str:
    """Provide Kafka bootstrap servers for testing.

    Args:
        kafka_container: Bootstrap server from kafka_container fixture.

    Returns:
        Kafka bootstrap servers string.

    """
    return kafka_container


def get_test_consumer_kwargs(
    bootstrap_servers: str,
    consumer_group: str = "test-group",
) -> dict[str, object]:
    """Create aiokafka consumer keyword arguments for integration testing.

    Args:
        bootstrap_servers: Kafka bootstrap servers address.
        consumer_group: Consumer group ID for tests.

    Returns:
        Keyword arguments dict suitable for ``AIOKafkaConsumer``.

    """
    return {
        "bootstrap_servers": bootstrap_servers,
        "group_id": consumer_group,
        "auto_offset_reset": "earliest",
        "enable_auto_commit": False,
    }


def get_test_producer_kwargs(bootstrap_servers: str) -> dict[str, object]:
    """Create aiokafka producer keyword arguments for integration testing.

    Args:
        bootstrap_servers: Kafka bootstrap servers address.

    Returns:
        Keyword arguments dict suitable for ``AIOKafkaProducer``.

    """
    return {
        "bootstrap_servers": bootstrap_servers,
        "acks": "all",
        "request_timeout_ms": 10000,
    }
