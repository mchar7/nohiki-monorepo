"""Kafka lifecycle management for reliable service operation.

Provides:
- Startup readiness checks with configurable retries
- Consumer auto-reconnection on failures
- Health status tracking for container health checks
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from nohiki_observability import get_logger

from nohiki_kafka_client.admin import KafkaAdmin
from nohiki_kafka_client.config import KafkaClientConfig
from nohiki_kafka_client.utils.broker_check import check_broker_connectivity

logger = get_logger(__name__)

DEFAULT_STARTUP_TIMEOUT_SECONDS = 120
DEFAULT_STARTUP_RETRY_INTERVAL_SECONDS = 2
DEFAULT_HEALTH_CHECK_INTERVAL_SECONDS = 30
DEFAULT_RECONNECT_BACKOFF_SECONDS = 5
DEFAULT_MAX_RECONNECT_BACKOFF_SECONDS = 60


class KafkaConnectionState(StrEnum):
    """Kafka connection state for health reporting."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass(slots=True)
class KafkaHealthState:
    """Kafka health state for service health checks."""

    state: KafkaConnectionState = KafkaConnectionState.DISCONNECTED
    last_successful_connection: float | None = None
    last_error: str | None = None
    last_error_time: float | None = None
    consecutive_failures: int = 0
    broker_count: int = 0
    # Consumer health fields
    consumers_ready: bool = False
    handlers_registered: int = 0
    consumers_active: int = 0
    consumer_tasks_running: int = 0

    @property
    def is_healthy(self) -> bool:
        """Return True if Kafka is connected AND consumers are ready."""
        broker_ok = self.state == KafkaConnectionState.CONNECTED and self.broker_count > 0
        # If handlers are registered, consumers must be ready
        if self.handlers_registered > 0:
            return broker_ok and self.consumers_ready
        return broker_ok

    def to_dict(self) -> dict[str, str | int | float | bool | None]:
        """Convert to dictionary for health check response."""
        return {
            "state": self.state.value,
            "healthy": self.is_healthy,
            "last_successful_connection": self.last_successful_connection,
            "last_error": self.last_error,
            "last_error_time": self.last_error_time,
            "consecutive_failures": self.consecutive_failures,
            "broker_count": self.broker_count,
            "consumers_ready": self.consumers_ready,
            "handlers_registered": self.handlers_registered,
            "consumers_active": self.consumers_active,
            "consumer_tasks_running": self.consumer_tasks_running,
        }


@dataclass(slots=True)
class KafkaLifecycleConfig:
    """Configuration for Kafka lifecycle management."""

    startup_timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS
    startup_retry_interval_seconds: float = DEFAULT_STARTUP_RETRY_INTERVAL_SECONDS
    health_check_interval_seconds: float = DEFAULT_HEALTH_CHECK_INTERVAL_SECONDS
    reconnect_backoff_seconds: float = DEFAULT_RECONNECT_BACKOFF_SECONDS
    max_reconnect_backoff_seconds: float = DEFAULT_MAX_RECONNECT_BACKOFF_SECONDS
    fail_fast_on_startup: bool = False


_lifecycle_instance: list[KafkaLifecycleManager | None] = [None]


class KafkaLifecycleManager:
    """Manages Kafka connection lifecycle for reliable service operation.

    Features:
    - Blocks startup until Kafka is available (configurable timeout)
    - Tracks connection health for container health checks
    - Provides reconnection utilities for consumer resilience
    """

    __slots__ = (
        "_bootstrap_servers",
        "_config",
        "_health_state",
        "_lock",
    )

    def __init__(
        self,
        bootstrap_servers: str,
        config: KafkaLifecycleConfig | None = None,
    ) -> None:
        """Initialize lifecycle manager.

        Args:
            bootstrap_servers: Kafka bootstrap servers address.
            config: Lifecycle configuration (timeouts, backoff, etc.).

        """
        self._bootstrap_servers = bootstrap_servers
        self._config = config or KafkaLifecycleConfig()
        self._health_state = KafkaHealthState()
        self._lock = asyncio.Lock()

    @property
    def health_state(self) -> KafkaHealthState:
        """Get current Kafka health state."""
        return self._health_state

    @property
    def is_healthy(self) -> bool:
        """Return True if Kafka is connected and healthy."""
        return self._health_state.is_healthy

    def update_consumer_state(
        self,
        *,
        consumers_ready: bool,
        handlers_registered: int,
        consumers_active: int,
        consumer_tasks_running: int,
    ) -> None:
        """Update consumer health state from kafka client."""
        self._health_state.consumers_ready = consumers_ready
        self._health_state.handlers_registered = handlers_registered
        self._health_state.consumers_active = consumers_active
        self._health_state.consumer_tasks_running = consumer_tasks_running

    async def _check_connectivity_async(self) -> tuple[bool, int, str | None]:
        """Check Kafka connectivity via the shared broker check utility.

        Returns:
            Tuple of ``(connected, broker_count, error_message)``.

        """
        return await check_broker_connectivity(self._bootstrap_servers)

    async def check_connectivity(self) -> bool:
        """Check Kafka connectivity asynchronously.

        Updates internal health state and returns connectivity status.
        """
        async with self._lock:
            connected, broker_count, error = await self._check_connectivity_async()

            now = time.time()

            if connected:
                self._health_state.state = KafkaConnectionState.CONNECTED
                self._health_state.last_successful_connection = now
                self._health_state.broker_count = broker_count
                self._health_state.consecutive_failures = 0
                self._health_state.last_error = None
                self._health_state.last_error_time = None
            else:
                match self._health_state.state:
                    case KafkaConnectionState.CONNECTED:
                        self._health_state.state = KafkaConnectionState.RECONNECTING
                    case KafkaConnectionState.DISCONNECTED:
                        self._health_state.state = KafkaConnectionState.CONNECTING
                    case _:
                        pass  # Keep RECONNECTING, CONNECTING, or FAILED as-is

                self._health_state.last_error = error
                self._health_state.last_error_time = now
                self._health_state.consecutive_failures += 1
                self._health_state.broker_count = 0

            return connected

    async def wait_for_kafka(self) -> bool:
        """Wait for Kafka to become available during startup.

        Blocks until Kafka is available or timeout is reached.
        Should be called during service startup before starting consumers.

        Returns:
            True if Kafka became available, False if timeout reached.

        Raises:
            RuntimeError: If fail_fast_on_startup is True and Kafka is unavailable.

        """
        self._health_state.state = KafkaConnectionState.CONNECTING

        start_time = time.perf_counter()
        timeout = self._config.startup_timeout_seconds
        retry_interval = self._config.startup_retry_interval_seconds

        logger.info(
            "Waiting for Kafka to become available",
            bootstrap_servers=self._bootstrap_servers,
            timeout_seconds=timeout,
        )

        attempt = 0
        while (time.perf_counter() - start_time) < timeout:
            attempt += 1
            connected = await self.check_connectivity()

            if connected:
                elapsed = time.perf_counter() - start_time
                logger.info(
                    "Kafka is available",
                    bootstrap_servers=self._bootstrap_servers,
                    broker_count=self._health_state.broker_count,
                    elapsed_seconds=round(elapsed, 2),
                    attempts=attempt,
                )
                return True

            remaining = timeout - (time.perf_counter() - start_time)
            if remaining > 0:
                wait_time = min(retry_interval, remaining)
                logger.debug(
                    "Kafka not available, retrying",
                    attempt=attempt,
                    error=self._health_state.last_error,
                    retry_in_seconds=wait_time,
                )
                await asyncio.sleep(wait_time)

        # Timeout reached
        elapsed = time.perf_counter() - start_time
        self._health_state.state = KafkaConnectionState.FAILED

        error_msg = f"Kafka unavailable after {elapsed:.1f}s ({attempt} attempts): {self._health_state.last_error}"
        logger.error(
            "Kafka startup timeout",
            bootstrap_servers=self._bootstrap_servers,
            elapsed_seconds=round(elapsed, 2),
            attempts=attempt,
            last_error=self._health_state.last_error,
        )

        if self._config.fail_fast_on_startup:
            raise RuntimeError(error_msg)

        return False

    def get_reconnect_backoff(self) -> float:
        """Get backoff duration for reconnection attempts.

        Uses exponential backoff capped at max_reconnect_backoff_seconds.
        """
        failures = self._health_state.consecutive_failures
        base = self._config.reconnect_backoff_seconds
        max_backoff = self._config.max_reconnect_backoff_seconds

        # Exponential backoff: base * 2^(failures-1), capped at max
        return min(base * (2 ** max(0, failures - 1)), max_backoff)


def get_lifecycle_manager() -> KafkaLifecycleManager:
    """Get the global lifecycle manager instance.

    Raises:
        RuntimeError: If the lifecycle manager has not been initialized.

    """
    if (instance := _lifecycle_instance[0]) is None:
        msg = "KafkaLifecycleManager not initialized. Call init_lifecycle_manager() first."
        raise RuntimeError(msg)
    return instance


def init_lifecycle_manager(
    bootstrap_servers: str,
    config: KafkaLifecycleConfig | None = None,
) -> KafkaLifecycleManager:
    """Initialize the global lifecycle manager singleton.

    Should be called once during service startup.

    Args:
        bootstrap_servers: Kafka bootstrap servers address.
        config: Lifecycle configuration.

    Returns:
        The initialized lifecycle manager.

    """
    manager = KafkaLifecycleManager(bootstrap_servers, config)
    _lifecycle_instance[0] = manager
    return manager


async def ensure_kafka_ready(
    bootstrap_servers: str,
    timeout_seconds: float = DEFAULT_STARTUP_TIMEOUT_SECONDS,
    retry_interval_seconds: float = DEFAULT_STARTUP_RETRY_INTERVAL_SECONDS,
    *,
    required_topics: Sequence[str] | None = None,
) -> KafkaLifecycleManager:
    """Ensure Kafka is ready during service startup.

    Creates lifecycle manager and waits for Kafka connectivity.
    Optionally validates that all required topics exist.

    Args:
        bootstrap_servers: Kafka bootstrap servers.
        timeout_seconds: Maximum time to wait for Kafka.
        retry_interval_seconds: Interval between retry attempts.
        required_topics: If provided, verify these topics exist after
            connectivity is established.  Raises if any are missing.

    Returns:
        Initialized KafkaLifecycleManager.

    Raises:
        RuntimeError: If Kafka is unavailable after timeout or required
            topics are missing.

    """
    config = KafkaLifecycleConfig(
        startup_timeout_seconds=timeout_seconds,
        startup_retry_interval_seconds=retry_interval_seconds,
        fail_fast_on_startup=True,
    )

    manager = init_lifecycle_manager(bootstrap_servers, config)
    await manager.wait_for_kafka()

    if required_topics:
        await _validate_required_topics(bootstrap_servers, required_topics)

    return manager


async def _validate_required_topics(
    bootstrap_servers: str,
    required_topics: Sequence[str],
) -> None:
    """Verify that all required topics exist on the Kafka cluster.

    Uses a short-lived :class:`KafkaAdmin` connection to list topics
    and compare against the required set.

    Args:
        bootstrap_servers: Kafka bootstrap servers address.
        required_topics: Topic names that must exist.

    Raises:
        RuntimeError: If any required topics are missing.

    """
    config = KafkaClientConfig(bootstrap_servers=bootstrap_servers)
    async with KafkaAdmin(config) as admin:
        existing = frozenset(await admin.list_topics(include_internal=True))

    missing = sorted(name for name in required_topics if name not in existing)
    if missing:
        msg = f"Required Kafka topics missing ({len(missing)}): {', '.join(missing)}"
        raise RuntimeError(msg)

    logger.info(
        "All required topics verified",
        topic_count=len(required_topics),
    )
