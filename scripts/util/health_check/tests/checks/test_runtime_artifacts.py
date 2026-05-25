"""Behavior tests for required runtime artifacts."""

from __future__ import annotations

from health_check.checks.application.runtime_artifacts import RequiredRuntimeArtifactsCheck
from health_check.core.models import CheckStatus

from tests.conftest import MockPlatform


class _ArtifactPlatform(MockPlatform):
    def __init__(self, failures: dict[tuple[str, str], str] | None = None) -> None:
        super().__init__()
        self.failures = failures or {}
        self.calls: list[tuple[str, list[str]]] = []

    def exec_in_service(self, canonical_name: str, command: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
        self.calls.append((canonical_name, command))
        path = command[-1]
        if error := self.failures.get((canonical_name, path)):
            return (1, "", error)
        return (0, "", "")


async def test_job_storage_missing_manifest_names_consumer_and_remediation() -> None:
    path = "/app/data/config/semantic_representation_manifest.json"
    platform = _ArtifactPlatform({("job-storage-service", path): "No such file"})

    result = await RequiredRuntimeArtifactsCheck().execute(platform)

    assert result.status == CheckStatus.FAILED
    assert "1 required runtime artifact probe" in result.summary
    assert any("job-storage-service" in detail and path in detail for detail in result.details)
    assert any("missing or invalid JSON" in detail for detail in result.details)
    assert result.remediation_hint is not None
    assert "mount" in result.remediation_hint


async def test_invalid_manifest_is_detected_semantically_not_by_presence() -> None:
    path = "/app/data/config/semantic_representation_manifest.json"
    platform = _ArtifactPlatform({("job-storage-service", path): "root must be a non-empty object"})

    result = await RequiredRuntimeArtifactsCheck().execute(platform)

    assert result.status == CheckStatus.FAILED
    manifest_call = next(command for service, command in platform.calls if service == "job-storage-service")
    assert manifest_call[:2] == ["python", "-c"]
    assert "json.load" in manifest_call[2]


async def test_missing_manifest_names_exact_service_and_path() -> None:
    path = "/app/data/config/semantic_representation_manifest.json"
    result = await RequiredRuntimeArtifactsCheck().execute(
        _ArtifactPlatform({("job-correlation-evaluation-service", path): "missing"})
    )

    assert result.status == CheckStatus.FAILED
    assert result.details == (f"job-correlation-evaluation-service:{path}: missing or invalid JSON (missing)",)
    assert result.remediation_hint is not None


async def test_all_runtime_artifacts_valid_passes() -> None:
    platform = _ArtifactPlatform()
    result = await RequiredRuntimeArtifactsCheck().execute(platform)

    assert result.status == CheckStatus.PASSED
    assert "All 6" in result.summary
    assert len(platform.calls) == 6
    assert {service for service, _ in platform.calls} == {
        "user-pref-service",
        "job-ingest-enrichment-service",
        "job-storage-service",
        "skill-graph-service",
        "job-correlation-evaluation-service",
        "ml-compute-service",
    }
    assert {command[-1] for _, command in platform.calls} == {
        "/app/data/config/semantic_representation_manifest.json",
    }
