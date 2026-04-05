"""Kafka health probe for domain-owned health checking.

Implements the HealthProbe protocol for Kafka connectivity and consumer readiness.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from aiokafka.errors import KafkaError
from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthProbeTimer,
    create_healthy_result,
    create_unhealthy_result,
)
from nohiki_observability import get_logger

from nohiki_kafka_client.utils.broker_check import check_broker_connectivity

if TYPE_CHECKING:
    from nohiki_kafka_client.supervision.lifecycle import KafkaLifecycleManager

logger = get_logger(__name__)


class KafkaCapability(Enum):
    """Kafka capabilities to verify during health check."""

    BROKER_CONNECTIVITY = "broker_connectivity"
    CONSUMER_READY = "consumer_ready"
    PRODUCER_READY = "producer_ready"


class KafkaHealthProbe:
    """Health probe for Kafka connectivity and consumer/producer readiness.

    Implements the HealthProbe protocol for Kafka health checking.
    """

    __slots__ = (
        "_bootstrap_servers",
        "_capabilities",
        "_lifecycle_manager",
        "_timeout_seconds",
    )

    def __init__(
        self,
        bootstrap_servers: str,
        *,
        capabilities: set[KafkaCapability] | None = None,
        lifecycle_manager: KafkaLifecycleManager | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        """Initialize Kafka health probe.

        Args:
            bootstrap_servers: Kafka bootstrap servers.
            capabilities: Set of capabilities to verify. Defaults to BROKER_CONNECTIVITY.
            lifecycle_manager: Optional lifecycle manager for consumer state tracking.
            timeout_seconds: Timeout for broker connectivity check.

        """
        self._bootstrap_servers = bootstrap_servers
        self._capabilities = capabilities or {KafkaCapability.BROKER_CONNECTIVITY}
        self._lifecycle_manager = lifecycle_manager
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Probe identifier."""
        return "kafka"

    async def check(self) -> HealthProbeResult:
        """Execute Kafka health check based on required capabilities.

        Checks:
        - BROKER_CONNECTIVITY: AdminClient.list_topics()
        - CONSUMER_READY: Verify handlers registered + consumer tasks running
        - PRODUCER_READY: Verify producer is initialized
        """
        with HealthProbeTimer() as timer:
            try:
                results: dict[str, bool] = {}
                error_messages: list[str] = []

                if KafkaCapability.BROKER_CONNECTIVITY in self._capabilities:
                    broker_ok, _, broker_err = await self._check_broker_connectivity()
                    results["broker_connectivity"] = broker_ok
                    if not broker_ok:
                        error_messages.append(broker_err or "Broker connectivity failed")

                if KafkaCapability.CONSUMER_READY in self._capabilities:
                    consumer_ok, consumer_err = self._check_consumer_ready()
                    results["consumer_ready"] = consumer_ok
                    if not consumer_ok:
                        error_messages.append(consumer_err or "Consumer not ready")

                if KafkaCapability.PRODUCER_READY in self._capabilities:
                    producer_ok, producer_err = self._check_producer_ready()
                    results["producer_ready"] = producer_ok
                    if not producer_ok:
                        error_messages.append(producer_err or "Producer not ready")

                all_ok = all(results.values())

                if not all_ok:
                    return create_unhealthy_result(
                        name=self.name,
                        message="; ".join(error_messages),
                        latency_ms=timer.elapsed_ms,
                        details={"capabilities": results},
                    )

                return create_healthy_result(
                    name=self.name,
                    message="Kafka is healthy",
                    latency_ms=timer.elapsed_ms,
                    details={"capabilities": results},
                )

            except (KafkaError, OSError, RuntimeError, ValueError) as e:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Kafka health check failed: {e}",
                    latency_ms=timer.elapsed_ms,
                    details={"error": str(e), "error_type": type(e).__name__},
                )
            except Exception as e:
                logger.exception("Unexpected error during Kafka health check")
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Unexpected Kafka health check failure: {e}",
                    latency_ms=timer.elapsed_ms,
                )

    async def _check_broker_connectivity(self) -> tuple[bool, int, str | None]:
        """Check Kafka broker connectivity via the shared utility.

        Returns:
            Tuple of ``(connected, broker_count, error_message)``.

        """
        return await check_broker_connectivity(
            self._bootstrap_servers,
            timeout_seconds=self._timeout_seconds,
        )

    def _check_consumer_ready(self) -> tuple[bool, str | None]:
        """Check consumer readiness from lifecycle manager.

        Returns:
            Tuple of (ready, error_message).

        """
        if self._lifecycle_manager is None:
            try:
                from nohiki_kafka_client.supervision.lifecycle import get_lifecycle_manager  # noqa: PLC0415

                self._lifecycle_manager = get_lifecycle_manager()
            except RuntimeError, ImportError:
                return True, None

        if self._lifecycle_manager is None:
            return True, None

        state = self._lifecycle_manager.health_state
        if state.handlers_registered > 0 and not state.consumers_ready:
            return False, f"Consumers not ready: {state.handlers_registered} handlers, {state.consumers_active} active"

        return True, None

    def _check_producer_ready(self) -> tuple[bool, str | None]:
        """Check producer readiness.

        Returns:
            Tuple of (ready, error_message).

        """
        try:
            from nohiki_kafka_client.client.factory import get_kafka_client  # noqa: PLC0415

            client = get_kafka_client()
            if client is None:
                return True, None

            if not client.is_producer_ready():
                return False, "Producer not initialized"

        except RuntimeError, ImportError:
            pass

        return True, None
