"""Shared broker connectivity check used by health probes and lifecycle management."""

from __future__ import annotations

import asyncio

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError
from nohiki_observability import get_logger

logger = get_logger(__name__)

DEFAULT_BROKER_CHECK_TIMEOUT_SECONDS = 5.0


async def check_broker_connectivity(
    bootstrap_servers: str,
    timeout_seconds: float = DEFAULT_BROKER_CHECK_TIMEOUT_SECONDS,
) -> tuple[bool, int, str | None]:
    """Check Kafka broker connectivity by creating a temporary producer.

    Creates an ``AIOKafkaProducer``, connects to the cluster, inspects
    broker metadata, then tears down.
    This is a one-shot probe. No long-lived connections are kept.

    Args:
        bootstrap_servers: Kafka bootstrap servers address.
        timeout_seconds: Maximum time to wait for connection.

    Returns:
        Tuple of ``(connected, broker_count, error_message)``.

    """
    producer: AIOKafkaProducer | None = None
    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            request_timeout_ms=int(timeout_seconds * 1000),
        )
        await asyncio.wait_for(producer.start(), timeout=timeout_seconds)

        cluster = producer.client.cluster
        broker_count = len(cluster.brokers())

        if broker_count == 0:
            logger.warning("No brokers available")
            return False, 0, "No brokers available"

    except (KafkaError, OSError) as e:
        logger.warning("Kafka connectivity check failed", error=str(e))
        return False, 0, f"Connectivity check failed: {e}"
    else:
        return True, broker_count, None
    finally:
        if producer is not None:
            await producer.stop()
