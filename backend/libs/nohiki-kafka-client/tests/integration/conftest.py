"""Pytest configuration for integration tests requiring a real Kafka broker."""

from __future__ import annotations

from nohiki_kafka_client.testing import (
    get_test_consumer_kwargs,
    get_test_producer_kwargs,
    kafka_bootstrap_servers,
    kafka_container,
)

__all__ = [
    "get_test_consumer_kwargs",
    "get_test_producer_kwargs",
    "kafka_bootstrap_servers",
    "kafka_container",
]
