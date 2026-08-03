from __future__ import annotations

import argparse
import stat
from pathlib import Path

import pytest

from scripts.load import resource_probe


def test_quantity_parsers_cover_declared_and_live_units() -> None:
    assert resource_probe.parse_memory_bytes("256Mi") == 256 * 1024**2
    assert resource_probe.parse_memory_bytes("1.5Gi") == 3 * 1024**3 // 2
    assert resource_probe.parse_cpu_nanocores("250m") == 250_000_000
    assert resource_probe.parse_cpu_nanocores("91342n") == 91_342
    with pytest.raises(resource_probe.ProbeError, match="unsupported memory quantity"):
        resource_probe.parse_memory_bytes("12Zi")


def test_pod_summary_preserves_resource_and_oom_evidence_without_env() -> None:
    pods = {
        "items": [
            {
                "metadata": {
                    "name": "worker-abc",
                    "namespace": "nohiki",
                    "ownerReferences": [{"controller": True, "kind": "ReplicaSet", "name": "worker-123"}],
                },
                "spec": {
                    "nodeName": "nohiki-control-plane",
                    "containers": [
                        {
                            "name": "worker",
                            "image": "registry/worker:trial",
                            "env": [{"name": "SECRET", "value": "must-not-leak"}],
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "64Mi"},
                                "limits": {"memory": "128Mi"},
                            },
                        }
                    ],
                },
                "status": {
                    "phase": "Running",
                    "qosClass": "Burstable",
                    "containerStatuses": [
                        {
                            "name": "worker",
                            "imageID": "registry/worker@sha256:abc",
                            "ready": True,
                            "restartCount": 1,
                            "state": {"running": {"startedAt": "2026-08-02T10:00:00Z"}},
                            "lastState": {
                                "terminated": {
                                    "exitCode": 137,
                                    "finishedAt": "2026-08-02T09:59:00Z",
                                    "reason": "OOMKilled",
                                    "signal": 9,
                                }
                            },
                        }
                    ],
                },
            }
        ]
    }
    metrics = {
        "items": [
            {
                "metadata": {"name": "worker-abc", "namespace": "nohiki"},
                "containers": [{"name": "worker", "usage": {"cpu": "91342n", "memory": "96Mi"}}],
            }
        ]
    }

    summarized = resource_probe.summarize_pods(pods, metrics)

    assert len(summarized) == 1
    pod = resource_probe.require_object(summarized[0], "pod")
    containers = resource_probe.list_at(pod, "containers")
    container = resource_probe.require_object(containers[0], "container")
    requests = resource_probe.object_at(container, "requests")
    usage = resource_probe.object_at(container, "usage")
    termination = resource_probe.object_at(container, "lastTermination")
    assert requests["memoryBytes"] == 64 * 1024**2
    assert usage["memoryBytes"] == 96 * 1024**2
    assert container["missingCpuLimit"] is True
    assert termination["reason"] == "OOMKilled"
    assert "must-not-leak" not in repr(summarized)


def test_workload_state_uses_controller_specific_fields() -> None:
    assert resource_probe.workload_state(
        "DaemonSet",
        {},
        {
            "desiredNumberScheduled": 3,
            "currentNumberScheduled": 2,
            "numberReady": 1,
            "numberAvailable": 1,
        },
    ) == {"available": 1, "current": 2, "desired": 3, "ready": 1}
    assert resource_probe.workload_state(
        "Job",
        {"completions": 2},
        {"active": 1, "failed": 0, "ready": 1, "succeeded": 1},
    ) == {"active": 1, "desired": 2, "failed": 0, "ready": 1, "succeeded": 1}
    assert resource_probe.workload_state(
        "CronJob",
        {"schedule": "0 * * * *", "suspend": True},
        {"active": [{"name": "run"}], "lastScheduleTime": "2026-08-02T10:00:00Z"},
    ) == {
        "active": 1,
        "lastScheduleTime": "2026-08-02T10:00:00Z",
        "schedule": "0 * * * *",
        "suspended": True,
    }


def test_usage_distributions_report_high_water_and_nearest_rank() -> None:
    def point(memory: int, cpu: int) -> dict[str, object]:
        return {
            "pods": [
                {
                    "namespace": "nohiki",
                    "name": "worker-abc",
                    "containers": [
                        {
                            "name": "worker",
                            "usage": {"memoryBytes": memory, "cpuNanocores": cpu},
                        }
                    ],
                }
            ]
        }

    distributions = resource_probe.usage_distributions(
        [point(10, 100), point(20, 200), point(30, 300), point(100, 400)]
    )

    assert distributions == [
        {
            "container": "worker",
            "cpuNanocores": {"highWater": 400, "p50": 200, "p95": 400, "samples": 4},
            "memoryBytes": {"highWater": 100, "p50": 20, "p95": 100, "samples": 4},
            "namespace": "nohiki",
            "pod": "worker-abc",
        }
    ]


def test_write_all_retries_partial_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    chunks: list[bytes] = []

    def partial_write(_descriptor: int, remaining: memoryview) -> int:
        written = min(2, len(remaining))
        chunks.append(bytes(remaining[:written]))
        return written

    monkeypatch.setattr(resource_probe.os, "write", partial_write)

    resource_probe.write_all(7, b"abcdef")

    assert b"".join(chunks) == b"abcdef"
    assert len(chunks) == 3


def test_write_json_is_private_and_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    resource_probe.write_json(output, {"kind": "test"})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        resource_probe.write_json(output, {"kind": "replacement"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0.0, -1.0])
def test_sampling_rejects_non_finite_or_non_positive_values(value: float) -> None:
    args = argparse.Namespace(duration_seconds=value, interval_seconds=1.0)

    with pytest.raises(resource_probe.ProbeError, match="must be positive"):
        resource_probe.validate_sampling_args(args)


def test_capture_rejects_non_kind_context_before_any_cluster_call() -> None:
    args = argparse.Namespace(context="production", namespace=None)

    with pytest.raises(resource_probe.ProbeError, match="kind-nohiki"):
        resource_probe.capture(args)
