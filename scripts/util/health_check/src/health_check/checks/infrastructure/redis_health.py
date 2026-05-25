"""Health check: Redis is healthy and not in a degraded state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import REDIS_PORT
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="redis_health",
    name="Redis Health",
    category=CheckCategory.INFRASTRUCTURE,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=20.0,
    description="Verify Redis is accepting connections and not loading its dataset.",
)

_REDIS_LOADING_INDICATOR: Final[str] = "loading:1"
_REDIS_LOG_SERVICES: Final[tuple[str, ...]] = ("bff-service", "doc-template-service")


def _parse_redis_info_failures(stdout: str) -> list[str]:
    """Extract failure signals from redis-cli INFO output."""
    if _REDIS_LOADING_INDICATOR in stdout:
        return ["Redis is loading dataset into memory (blocking writes)"]
    return []


def _redis_log_issues(svc: str, logs_lower: str) -> list[str]:
    """Detect Redis-related error patterns in a service's logs."""
    issues: list[str] = []
    if "redis is loading" in logs_lower:
        issues.append(f"{svc}: Redis loading state in logs")
    if "name or service not known" in logs_lower and "redis" in logs_lower:
        issues.append(f"{svc}: Redis DNS resolution failure")
    return issues


async def _check_managed_redis(platform: Platform) -> list[str]:
    """Check Redis by running INFO inside the container."""
    code, stdout, stderr = await asyncio.to_thread(
        platform.exec_in_service,
        "redis",
        ["redis-cli", "INFO", "server"],
        timeout=10,
    )
    if code != 0:
        return [f"Cannot connect to Redis: {(stderr or 'connection failed')[:120]}"]
    return _parse_redis_info_failures(stdout)


async def _check_service_logs(platform: Platform) -> list[str]:
    """Scan consumer service logs for Redis connectivity issues."""
    issues: list[str] = []
    for svc in _REDIS_LOG_SERVICES:
        logs = await asyncio.to_thread(platform.get_logs, svc, 100)
        issues.extend(_redis_log_issues(svc, logs.lower()))
    return issues


class RedisHealthCheck(HealthCheck):
    """Verify Redis is reachable, not loading, and not causing consumer errors."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the Redis health check."""
        is_k8s_host = platform.target == PlatformTarget.KUBERNETES and not platform.is_infra_managed()

        if is_k8s_host:
            ok = await asyncio.to_thread(platform.check_port, "localhost", REDIS_PORT)
            if not ok:
                return self._make_result(
                    CheckStatus.FAILED,
                    "Redis port not accessible",
                    details=("Redis port 6379 not accessible on host",),
                    remediation_hint="Ensure Redis is running on the host machine",
                )
            failures: list[str] = []
        else:
            failures = await _check_managed_redis(platform)

        if not failures:
            log_issues = await _check_service_logs(platform)
            failures.extend(log_issues)

        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"Redis has {len(failures)} issue(s)",
                details=tuple(failures),
                remediation_hint="Run: just logs redis - check for memory exhaustion or network issues",
            )
        return self._make_result(CheckStatus.PASSED, "Redis healthy and accepting connections")
