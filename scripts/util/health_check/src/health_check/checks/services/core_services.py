"""Health check: all core application services are healthy."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, Final

from health_check.checks._utils import any_group_has_members
from health_check.config.kafka import (
    DB_ERROR_PATTERNS,
    DB_TYPE_MISMATCH_PATTERNS,
    KAFKA_ERROR_PATTERNS,
    KAFKA_SUBSCRIPTION_INDICATORS,
    KAFKA_TRANSIENT_ERROR_PATTERNS,
)
from health_check.config.services import (
    CORE_SERVICES,
    KAFKA_CONSUMER_GROUPS,
    KAFKA_CONSUMER_SERVICES,
)
from health_check.config.thresholds import K8S_RESTART_THRESHOLD
from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget, ServiceInfo, ServiceStatus

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final[CheckMetadata] = CheckMetadata(
    check_id="core_services",
    name="Core Services",
    category=CheckCategory.SERVICES,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"infra_services"}),
    timeout_seconds=60.0,
    description="Verify all core application services are running and healthy.",
)

_RECENT_LOG_LINES: Final[int] = 50
_FULL_LOG_LINES: Final[int] = 200


def _status_failures(svc: str, info: ServiceInfo | None) -> list[str]:
    """Return failure messages from service status alone."""
    if info is None:
        return [f"{svc}: not found"]
    return [
        msg
        for condition, msg in [
            (info.status != ServiceStatus.HEALTHY, f"{svc}: {info.status.value}"),
            (info.restarts > K8S_RESTART_THRESHOLD, f"{svc}: excessive restarts ({info.restarts})"),
        ]
        if condition
    ]


def _module_errors(svc: str, logs: str) -> list[str]:
    """Detect Python import failures in logs."""
    if "ModuleNotFoundError" in logs or "No module named" in logs:
        return [f"{svc}: missing Python dependency"]
    return []


def _db_log_errors(svc: str, logs_lower: str) -> list[str]:
    """Detect database error patterns in logs."""
    failures: list[str] = []
    if any(p in logs_lower for p in DB_ERROR_PATTERNS):
        failures.append(f"{svc}: database connectivity issue")
    if any(re.search(p, logs_lower) for p in DB_TYPE_MISMATCH_PATTERNS):
        failures.append(f"{svc}: DATABASE TYPE MISMATCH (model/migration out of sync)")
    return failures


def _validation_errors(svc: str, logs: str) -> list[str]:
    """Detect validation and schema error patterns in logs."""
    if "ValidationError" in logs or "UnexpectedModelBehavior" in logs:
        return [f"{svc}: validation/schema error"]
    return []


def _recent_lines(logs_lower: str, n: int = _RECENT_LOG_LINES) -> str:
    """Return the last n lines of a log string."""
    lines = logs_lower.strip().split("\n")
    return "\n".join(lines[-n:]) if len(lines) > n else logs_lower


async def _is_kafka_error_real(
    svc: str,
    matched_pattern: str,
    logs_lower: str,
    platform: Platform,
) -> bool:
    """Determine whether a Kafka error in logs is a genuine failure.

    Transient errors (heartbeat, coordinator) are ignored when the service's
    consumer group has active members, indicating healthy operation despite
    occasional coordinator renegotiations.

    Args:
        svc: Canonical service name.
        matched_pattern: The error pattern found in logs.
        logs_lower: Full lowercase log content.
        platform: Active platform for Kafka queries.

    Returns:
        True if the error is real and should be reported.
    """
    if svc not in KAFKA_CONSUMER_SERVICES:
        return True
    if matched_pattern not in KAFKA_TRANSIENT_ERROR_PATTERNS:
        return True

    group_ids = KAFKA_CONSUMER_GROUPS.get(svc) or ()
    if not group_ids:
        return not any(ind in logs_lower for ind in KAFKA_SUBSCRIPTION_INDICATORS)

    return not await any_group_has_members(platform, tuple(group_ids))


async def _kafka_log_failures(svc: str, logs_lower: str, platform: Platform) -> list[str]:
    """Return failure messages from Kafka error patterns in recent logs."""
    recent = _recent_lines(logs_lower)
    matched = next((p for p in KAFKA_ERROR_PATTERNS if p in recent), None)
    if matched is None:
        return []
    if await _is_kafka_error_real(svc, matched, logs_lower, platform):
        return [f"{svc}: Kafka error ({matched})"]
    return []


async def _check_one_service(
    svc: str,
    info: ServiceInfo | None,
    platform: Platform,
) -> list[str]:
    """Gather all failure messages for a single service."""
    failures = _status_failures(svc, info)
    if info is None:
        return failures

    logs = await asyncio.to_thread(platform.get_logs, svc, _FULL_LOG_LINES)
    logs_lower = logs.lower()

    failures.extend(_module_errors(svc, logs))
    failures.extend(await _kafka_log_failures(svc, logs_lower, platform))
    failures.extend(_db_log_errors(svc, logs_lower))
    failures.extend(_validation_errors(svc, logs))
    return failures


class CoreServicesCheck(HealthCheck):
    """Verify all core application services are running and log-error-free."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run the core services health check."""
        statuses = await asyncio.to_thread(platform.get_service_statuses)

        async with asyncio.TaskGroup() as tg:
            tasks = {svc: tg.create_task(_check_one_service(svc, statuses.get(svc), platform)) for svc in CORE_SERVICES}

        failures = [msg for t in tasks.values() for msg in t.result()]
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} issue(s) across core services",
                details=tuple(failures),
                remediation_hint="Inspect failing service logs: just logs <service>",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {len(CORE_SERVICES)} core services healthy",
        )
