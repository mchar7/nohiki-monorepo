"""Required runtime artifact availability and semantic validation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Final

from health_check.core.base import HealthCheck
from health_check.core.models import CheckCategory, CheckMetadata, CheckResult, CheckStatus
from health_check.platform.models import PlatformTarget

if TYPE_CHECKING:
    from health_check.platform.protocol import Platform

_METADATA: Final = CheckMetadata(
    check_id="runtime_artifacts",
    name="Runtime Artifacts",
    category=CheckCategory.APPLICATION,
    platforms=frozenset({PlatformTarget.COMPOSE, PlatformTarget.KUBERNETES}),
    depends_on=frozenset({"core_services"}),
    description="Verify required manifest and model files exist and are semantically readable in consumers.",
)
_MANIFEST_SERVICES: Final = (
    "user-pref-service",
    "job-ingest-enrichment-service",
    "job-storage-service",
    "skill-graph-service",
    "job-correlation-evaluation-service",
    "ml-compute-service",
)
_MANIFEST: Final = "/app/data/config/semantic_representation_manifest.json"


async def _probe_manifest(platform: Platform, service: str) -> str | None:
    script = (
        "import json,sys; p=sys.argv[1]; d=json.load(open(p)); "
        "assert isinstance(d,dict) and d, 'root must be a non-empty object'"
    )
    code, _, stderr = await asyncio.to_thread(platform.exec_in_service, service, ["python", "-c", script, _MANIFEST])
    return None if code == 0 else f"{service}:{_MANIFEST}: missing or invalid JSON ({stderr[:120]})"


class RequiredRuntimeArtifactsCheck(HealthCheck):
    """Probe artifacts inside their actual consuming runtime."""

    metadata = _METADATA

    async def execute(self, platform: Platform) -> CheckResult:
        """Validate manifests inside each consuming runtime."""
        async with asyncio.TaskGroup() as tg:
            probes = [tg.create_task(_probe_manifest(platform, service)) for service in _MANIFEST_SERVICES]
        failures = tuple(issue for task in probes if (issue := task.result()) is not None)
        if failures:
            return self._make_result(
                CheckStatus.FAILED,
                f"{len(failures)} required runtime artifact probe(s) failed",
                details=failures,
                remediation_hint="Restore declared read-only mounts and rebuild/redeploy the affected service",
            )
        return self._make_result(CheckStatus.PASSED, f"All {len(probes)} required runtime artifacts valid")
