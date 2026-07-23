"""S3 health probe for domain-owned health checking.

Implements the HealthProbe protocol for S3 connectivity and bucket access.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthProbeTimer,
    create_healthy_result,
    create_unhealthy_result,
)
from nohiki_observability import get_logger

from .exceptions import S3ConnectionError, S3PermissionError

if TYPE_CHECKING:
    from .client import S3Client

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProbeTiming:
    """Timing dependencies for a startup probe retry loop."""

    clock: Callable[[], float] = time.perf_counter
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


class S3Capability(Enum):
    """S3 capabilities to verify during health check."""

    BUCKET_ACCESS = "bucket_access"
    READ = "read"
    WRITE = "write"


class S3HealthProbe:
    """Health probe for S3 connectivity and bucket access.

    Implements the HealthProbe protocol for S3 health checking.
    """

    __slots__ = (
        "_capabilities",
        "_health_check_key",
        "_s3_client",
        "_timeout_seconds",
    )

    def __init__(
        self,
        s3_client: S3Client,
        *,
        capabilities: set[S3Capability] | None = None,
        health_check_key: str = "__health_probe__",
        timeout_seconds: float = 10.0,
    ) -> None:
        """Initialize S3 health probe.

        Args:
            s3_client: S3Client instance.
            capabilities: Set of capabilities to verify. Defaults to BUCKET_ACCESS.
            health_check_key: Key to use for read/write tests.
            timeout_seconds: Timeout for S3 operations.

        """
        self._s3_client = s3_client
        self._capabilities = capabilities or {S3Capability.BUCKET_ACCESS}
        self._health_check_key = health_check_key
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Probe identifier."""
        return "s3"

    async def _check_all_capabilities(self) -> tuple[dict[str, bool], list[str]]:
        """Verify all requested S3 capabilities."""
        results: dict[str, bool] = {}
        error_messages: list[str] = []

        if S3Capability.BUCKET_ACCESS in self._capabilities:
            bucket_ok, bucket_err = await self._check_bucket_access()
            results["bucket_access"] = bucket_ok
            if not bucket_ok:
                error_messages.append(bucket_err or "Bucket access failed")

        if S3Capability.READ in self._capabilities:
            read_ok, read_err = await self._check_read()
            results["read"] = read_ok
            if not read_ok:
                error_messages.append(read_err or "Read access failed")

        if S3Capability.WRITE in self._capabilities:
            write_ok, write_err = await self._check_write()
            results["write"] = write_ok
            if not write_ok:
                error_messages.append(write_err or "Write access failed")

        return results, error_messages

    async def check(self) -> HealthProbeResult:
        """Execute S3 health check based on required capabilities.

        Checks:
        - BUCKET_ACCESS: head_bucket to verify bucket exists and credentials work
        - READ: head_object or list_objects_v2 with limit=1
        - WRITE: put_object + delete_object cycle
        """
        with HealthProbeTimer() as timer:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    results, error_messages = await self._check_all_capabilities()

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
                    message="S3 is healthy",
                    latency_ms=timer.elapsed_ms,
                    details={"capabilities": results},
                )

            except TimeoutError:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"S3 health check timeout after {self._timeout_seconds}s",
                    latency_ms=timer.elapsed_ms,
                )
            except (OSError, RuntimeError) as e:
                return create_unhealthy_result(
                    name=self.name,
                    message=f"S3 connection failed: {e}",
                    latency_ms=timer.elapsed_ms,
                    details={"error": str(e), "error_type": type(e).__name__},
                )
            except Exception as e:
                logger.exception("Unexpected error during S3 health check")
                return create_unhealthy_result(
                    name=self.name,
                    message=f"Unexpected S3 health check failure: {e}",
                    latency_ms=timer.elapsed_ms,
                )

    async def _check_bucket_access(self) -> tuple[bool, str | None]:
        """Check bucket exists and is accessible via head_bucket."""
        try:
            await self._s3_client.check_bucket_access()
        except S3PermissionError as e:
            return False, f"Bucket permission denied: {e}"
        except S3ConnectionError as e:
            return False, f"Bucket connection failed: {e}"
        except OSError as e:
            return False, f"Bucket access failed: {e}"
        else:
            return True, None

    async def _check_read(self) -> tuple[bool, str | None]:
        """Check read access by listing objects with limit=1."""
        try:
            await self._s3_client.list_objects_sample(max_keys=1)
        except S3PermissionError as e:
            return False, f"Read permission denied: {e}"
        except S3ConnectionError as e:
            return False, f"Read connection failed: {e}"
        except OSError as e:
            return False, f"Read access failed: {e}"
        else:
            return True, None

    async def _check_write(self) -> tuple[bool, str | None]:
        """Check write access by put/delete cycle."""
        try:
            test_data = f"health_probe_{time.time()}".encode()
            await self._s3_client.put_object(
                key=self._health_check_key,
                data=test_data,
                content_type="text/plain",
            )
            await self._s3_client.delete_object(key=self._health_check_key)
        except S3PermissionError as e:
            return False, f"Write permission denied: {e}"
        except S3ConnectionError as e:
            return False, f"Write connection failed: {e}"
        except OSError as e:
            return False, f"Write access failed: {e}"
        else:
            return True, None


async def ensure_s3_ready(
    s3_client: S3Client,
    *,
    timeout_seconds: float = 30.0,
    retry_interval_seconds: float = 2.0,
    timing: ProbeTiming | None = None,
) -> None:
    """Block startup until S3 is available.

    Args:
        s3_client: S3Client instance.
        timeout_seconds: Maximum time to wait for S3.
        retry_interval_seconds: Interval between retry attempts.
        timing: Optional timing dependencies for deterministic retry control.

    Raises:
        RuntimeError: If S3 is unavailable after timeout.

    """
    timing = ProbeTiming() if timing is None else timing
    probe = S3HealthProbe(s3_client, capabilities={S3Capability.BUCKET_ACCESS})
    start_time = timing.clock()
    attempt = 0

    logger.info(
        "Waiting for S3 to become available",
        timeout_seconds=timeout_seconds,
    )

    while (timing.clock() - start_time) < timeout_seconds:
        attempt += 1
        result = await probe.check()

        if result.is_healthy():
            elapsed = timing.clock() - start_time
            logger.info(
                "S3 is available",
                elapsed_seconds=round(elapsed, 2),
                attempts=attempt,
            )
            return

        remaining = timeout_seconds - (timing.clock() - start_time)
        if remaining > 0:
            wait_time = min(retry_interval_seconds, remaining)
            logger.debug(
                "S3 not available, retrying",
                attempt=attempt,
                error=result.message,
                retry_in_seconds=wait_time,
            )
            await timing.sleep(wait_time)

    elapsed = timing.clock() - start_time
    msg = f"S3 unavailable after {elapsed:.1f}s ({attempt} attempts)"
    logger.error("S3 startup timeout", elapsed_seconds=round(elapsed, 2), attempts=attempt)
    raise RuntimeError(msg)
