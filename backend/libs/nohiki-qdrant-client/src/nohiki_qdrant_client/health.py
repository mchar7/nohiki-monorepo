"""Qdrant health probe for domain-owned health checking.

Implements the HealthProbe protocol for Qdrant vector database connectivity.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthProbeTimer,
    create_healthy_result,
    create_unhealthy_result,
)
from nohiki_observability import get_logger

if TYPE_CHECKING:
    from qdrant_client import AsyncQdrantClient

logger = get_logger(__name__)


class QdrantHealthProbe:
    """Health probe for Qdrant vector database connectivity.

    Implements the HealthProbe protocol for Qdrant health checking.
    Uses async Qdrant client for non-blocking health checks.
    """

    __slots__ = ("_client", "_collection_names", "_timeout_seconds")

    def __init__(
        self,
        client: AsyncQdrantClient,
        *,
        collection_names: list[str] | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        """Initialize Qdrant health probe.

        Args:
            client: Raw async Qdrant client for connectivity checks.
            collection_names: Optional list of collections to verify exist.
            timeout_seconds: Timeout for Qdrant operations.

        """
        self._client = client
        self._collection_names = collection_names
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Probe identifier."""
        return "qdrant"

    async def check(self) -> HealthProbeResult:
        """Verify Qdrant is reachable.

        Checks:
        1. Get collections list (verifies connectivity)
        2. (Optional) Verify required collections exist
        """
        with HealthProbeTimer() as timer:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    collections = await self._client.get_collections()
                    collection_names = [c.name for c in collections.collections]

                    if self._collection_names:
                        missing = set(self._collection_names) - set(collection_names)
                        if missing:
                            return create_unhealthy_result(
                                name=self.name,
                                message=f"Missing collections: {missing}",
                                latency_ms=timer.elapsed_ms,
                            )

                return create_healthy_result(
                    name=self.name,
                    message="Qdrant is healthy",
                    latency_ms=timer.elapsed_ms,
                    details={"collection_count": len(collection_names)},
                )

            except TimeoutError:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Qdrant health check timeout after {self._timeout_seconds}s",
                    latency_ms=timer.elapsed_ms,
                )
            except (OSError, RuntimeError) as e:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Qdrant connection failed: {e}",
                    latency_ms=timer.elapsed_ms,
                    details={"error": str(e), "error_type": type(e).__name__},
                )
            except Exception as e:
                logger.exception("Unexpected error during Qdrant health check")
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Unexpected Qdrant health check failure: {e}",
                    latency_ms=timer.elapsed_ms,
                )


async def ensure_qdrant_ready(
    client: AsyncQdrantClient,
    *,
    timeout_seconds: float = 30.0,
    retry_interval_seconds: float = 2.0,
    required_collections: list[str] | None = None,
) -> None:
    """Block startup until Qdrant is available.

    Args:
        client: Raw async Qdrant client.
        timeout_seconds: Maximum time to wait for Qdrant.
        retry_interval_seconds: Interval between retry attempts.
        required_collections: Optional collections that must exist.

    Raises:
        RuntimeError: If Qdrant is unavailable after timeout.

    """
    probe = QdrantHealthProbe(client, collection_names=required_collections)
    start_time = time.perf_counter()
    attempt = 0

    logger.info(
        "Waiting for Qdrant to become available",
        timeout_seconds=timeout_seconds,
    )

    while (time.perf_counter() - start_time) < timeout_seconds:
        attempt += 1
        result = await probe.check()

        if result.is_healthy():
            elapsed = time.perf_counter() - start_time
            logger.info(
                "Qdrant is available",
                elapsed_seconds=round(elapsed, 2),
                attempts=attempt,
            )
            return

        remaining = timeout_seconds - (time.perf_counter() - start_time)
        if remaining > 0:
            wait_time = min(retry_interval_seconds, remaining)
            logger.debug(
                "Qdrant not available, retrying",
                attempt=attempt,
                error=result.message,
                retry_in_seconds=wait_time,
            )
            await asyncio.sleep(wait_time)

    elapsed = time.perf_counter() - start_time
    msg = f"Qdrant unavailable after {elapsed:.1f}s ({attempt} attempts)"
    logger.error("Qdrant startup timeout", elapsed_seconds=round(elapsed, 2), attempts=attempt)
    raise RuntimeError(msg)
