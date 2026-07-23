"""Health check: platform services (MinIO, Qdrant, Gotenberg, Docling, Kafka Connect)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import (
    DOCLING_PORT,
    GOTENBERG_PORT,
    HTTP_CHECK_TIMEOUT_SECONDS,
    KAFKA_CONNECT_DEFAULT_PORT,
    QDRANT_PORT,
    RUSTFS_HOST_PORT,
)
from health_check.core.base import HealthCheck
from health_check.core.models import (
    CheckCategory,
    CheckMetadata,
    CheckResult,
    CheckStatus,
)
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="platform_services",
    name="Platform Services",
    category=CheckCategory.INFRASTRUCTURE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset(),
    timeout_seconds=30.0,
    description=("Verify HTTP health endpoints for RustFS, Qdrant, Gotenberg, Docling, Kafka Connect."),
)

_HTTP_TIMEOUT: Final[int] = int(HTTP_CHECK_TIMEOUT_SECONDS)


@dataclass(frozen=True, slots=True)
class _ServiceEndpoint:
    """A platform service with an HTTP health endpoint.

    Services with a host-accessible port set ``exec_service=None`` and use
    ``platform.curl()`` against ``url``.  Services that have no host port
    mapping set ``exec_service`` to their canonical name so the check runs
    ``curl`` inside the container via ``platform.exec_in_service()``.
    """

    name: str
    url: str
    exec_service: str | None = None


_COMPOSE_ENDPOINTS: Final[tuple[_ServiceEndpoint, ...]] = (
    _ServiceEndpoint("RustFS", f"http://localhost:{RUSTFS_HOST_PORT}/"),
    _ServiceEndpoint("Qdrant", f"http://localhost:{QDRANT_PORT}/readyz"),
    _ServiceEndpoint("Gotenberg", f"http://localhost:{GOTENBERG_PORT}/health"),
    _ServiceEndpoint("Docling", f"http://localhost:{DOCLING_PORT}/readyz"),
    _ServiceEndpoint("Kafka Connect", f"http://localhost:{KAFKA_CONNECT_DEFAULT_PORT}/"),
)

_KUBERNETES_ENDPOINTS: Final[tuple[_ServiceEndpoint, ...]] = (
    _ServiceEndpoint("RustFS", "http://rustfs:9000/"),
    _ServiceEndpoint("Qdrant", "http://qdrant:6333/readyz"),
    _ServiceEndpoint("Gotenberg", "http://gotenberg:3000/health"),
    _ServiceEndpoint("Docling", "http://docling:5001/readyz"),
    _ServiceEndpoint("Kafka Connect", "http://nohiki-connect-api:8083/"),
)


async def _probe_endpoint(platform: Platform, endpoint: _ServiceEndpoint) -> str | None:
    """Probe a single service HTTP health endpoint.

    Uses ``platform.curl()`` for services with a host-accessible port, and
    ``platform.exec_in_service()`` for services reachable only inside the
    container network.

    Args:
        platform: Active platform for HTTP / exec operations.
        endpoint: Service descriptor including name, URL, and optional exec target.

    Returns:
        Failure description string if unreachable, else ``None``.
    """
    if endpoint.exec_service is not None:
        code, _, stderr = await asyncio.to_thread(
            platform.exec_in_service,
            endpoint.exec_service,
            ["curl", "-sf", "--connect-timeout", "5", endpoint.url],
            timeout=_HTTP_TIMEOUT,
        )
    else:
        code, _, stderr = await asyncio.to_thread(platform.curl, endpoint.url, timeout=_HTTP_TIMEOUT)
    error = stderr.casefold()
    rustfs_forbidden = endpoint.name == "RustFS" and ("error: 403" in error or "403 forbidden" in error)
    if code != 0 and not rustfs_forbidden:
        return f"{endpoint.name}: unreachable at {endpoint.url}"
    return None


class PlatformServicesCheck(HealthCheck):
    """Verify HTTP health endpoints for all platform infrastructure services."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run all platform service HTTP health probes concurrently."""
        endpoints = _KUBERNETES_ENDPOINTS if platform.target is PlatformTarget.KUBERNETES else _COMPOSE_ENDPOINTS
        async with asyncio.TaskGroup() as tg:
            tasks = [tg.create_task(_probe_endpoint(platform, ep)) for ep in endpoints]

        failures = [msg for t in tasks if (msg := t.result()) is not None]

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)}/{len(endpoints)} platform service(s) unhealthy",
                details=tuple(failures),
                remediation_hint="Start the affected containers: just infra-up",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(endpoints)} platform services responding",
        )
