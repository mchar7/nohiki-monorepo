"""Observability health probe for domain-owned health checking.

Implements the HealthProbe protocol for OpenTelemetry collector connectivity.
This is typically a degraded-mode check - observability failure shouldn't
prevent service operation but should be reported.
"""

from __future__ import annotations

import asyncio

from nohiki_common_exceptions import (
    HealthProbeResult,
    HealthProbeTimer,
    create_degraded_result,
    create_healthy_result,
)

from nohiki_observability.observability import get_logger

logger = get_logger(__name__)


class OTelHealthProbe:
    """Health probe for OpenTelemetry collector connectivity.

    Implements the HealthProbe protocol for observability health checking.
    Returns DEGRADED (not UNHEALTHY) on failure since observability issues
    shouldn't prevent service operation.
    """

    __slots__ = ("_otel_endpoint", "_timeout_seconds")

    def __init__(
        self,
        otel_endpoint: str | None,
        *,
        timeout_seconds: float = 2.0,
    ) -> None:
        """Initialize OTel health probe.

        Args:
            otel_endpoint: OTEL collector gRPC endpoint (e.g., "http://collector:4317").
            timeout_seconds: Timeout for connectivity check.

        """
        self._otel_endpoint = otel_endpoint
        self._timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Probe identifier."""
        return "otel_collector"

    async def check(self) -> HealthProbeResult:
        """Verify OTEL collector is reachable.

        Attempts a simple TCP connection to the gRPC port.
        Returns DEGRADED on failure (not UNHEALTHY) since observability
        issues shouldn't prevent service operation.
        """
        with HealthProbeTimer() as timer:
            if not self._otel_endpoint:
                return create_healthy_result(
                    name=self.name,
                    message="OTEL endpoint not configured (disabled)",
                    latency_ms=timer.elapsed_ms,
                    details={"configured": False},
                )

            try:
                host, port = self._parse_endpoint()

                async with asyncio.timeout(self._timeout_seconds):
                    _, writer = await asyncio.open_connection(host, port)
                    writer.close()
                    await writer.wait_closed()

                return create_healthy_result(
                    name=self.name,
                    message="OTEL collector is reachable",
                    latency_ms=timer.elapsed_ms,
                    details={"endpoint": self._otel_endpoint},
                )

            except TimeoutError:
                return create_degraded_result(
                    name=self.name,
                    message=f"OTEL collector timeout after {self._timeout_seconds}s",
                    latency_ms=timer.elapsed_ms,
                    details={"endpoint": self._otel_endpoint},
                )
            except OSError as e:
                return create_degraded_result(
                    name=self.name,
                    message=f"OTEL collector unreachable: {e}",
                    latency_ms=timer.elapsed_ms,
                    details={
                        "endpoint": self._otel_endpoint,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
            except ValueError as e:
                return create_degraded_result(
                    name=self.name,
                    message=f"Invalid OTEL endpoint configuration: {e}",
                    latency_ms=timer.elapsed_ms,
                    details={
                        "endpoint": self._otel_endpoint,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )

    def _parse_endpoint(self) -> tuple[str, int]:
        """Parse endpoint URL into host and port."""
        endpoint = self._otel_endpoint or ""

        endpoint = endpoint.replace("http://", "").replace("https://", "")

        if ":" in endpoint:
            host, port_str = endpoint.rsplit(":", 1)
            return host, int(port_str)

        return endpoint, 4317
