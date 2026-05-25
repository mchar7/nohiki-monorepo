"""Health check: critical services can import their required Python dependencies."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.config.thresholds import IMPORT_CHECK_TIMEOUT_SECONDS
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
    check_id="service_dependencies",
    name="Service Dependencies",
    category=CheckCategory.SERVICES,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"core_services"}),
    timeout_seconds=60.0,
    description="Verify critical services can import their required Python packages.",
)

_DEPS_BY_SERVICE: Final[dict[str, tuple[str, ...]]] = {
    "user-pref-service": ("nohiki_kafka_client", "nohiki_db_utils"),
    "job-ingest-enrichment-service": ("nohiki_kafka_client", "nohiki_llm_client"),
    "job-correlation-evaluation-service": (
        "nohiki_kafka_client",
        "nohiki_qdrant_client",
    ),
    "ml-compute-service": ("nohiki_ml_core", "nohiki_kafka_client"),
}


async def _check_service_imports(
    platform: Platform,
    svc: str,
    modules: tuple[str, ...],
) -> tuple[str, list[str]]:
    """Check module availability for a service using importlib.util.find_spec.

    Uses find_spec instead of import to avoid loading heavy ML dependencies
    (e.g., PyTorch) which can take 20+ seconds. find_spec checks if a module
    can be found without actually importing it.

    Args:
        platform: Active platform for exec_in_service calls.
        svc: Canonical service name.
        modules: Tuple of Python module names to check.

    Returns:
        Tuple of (service_name, list_of_missing_modules).
    """
    checks = " and ".join(f"__import__('importlib.util').util.find_spec('{m}') is not None" for m in modules)
    py_cmd = f"{checks} or exit(1)"
    code, _, _ = await asyncio.to_thread(
        platform.exec_in_service,
        svc,
        ["python", "-c", py_cmd],
        timeout=IMPORT_CHECK_TIMEOUT_SECONDS,
    )
    if code == 0:
        return (svc, [])
    failed: list[str] = []
    for module in modules:
        check = f"__import__('importlib.util').util.find_spec('{module}') is not None or exit(1)"
        single_code, _, _ = await asyncio.to_thread(
            platform.exec_in_service,
            svc,
            ["python", "-c", check],
            timeout=IMPORT_CHECK_TIMEOUT_SECONDS,
        )
        if single_code != 0:
            failed.append(module)
    return (svc, failed)


class ServiceDependenciesCheck(HealthCheck):
    """Verify critical Python dependencies are importable inside service containers."""

    @property
    def metadata(self) -> CheckMetadata:
        """Return check metadata."""
        return _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Run batched dependency import checks per service."""
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(_check_service_imports(platform, svc, deps)) for svc, deps in _DEPS_BY_SERVICE.items()
            ]

        failures: list[str] = []
        for task in tasks:
            svc, failed_modules = task.result()
            failures.extend(f"{svc}: missing {mod}" for mod in failed_modules)

        total_deps = sum(len(deps) for deps in _DEPS_BY_SERVICE.values())
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} missing service dependency/dependencies",
                details=tuple(failures),
                remediation_hint="Rebuild service images: just build <service>",
            )
        return self._make_result(
            CheckStatus.PASSED,
            f"All {total_deps} critical dependencies importable",
        )
