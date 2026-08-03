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
    pod = summarized[0]
    container = pod["containers"][0]
    assert container["requests"]["memoryBytes"] == 64 * 1024**2
    assert container["usage"]["memoryBytes"] == 96 * 1024**2
    assert container["missingCpuLimit"] is True
    assert container["lastTermination"]["reason"] == "OOMKilled"
    assert "must-not-leak" not in repr(summarized)


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


def test_write_json_is_private_and_refuses_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "evidence.json"
    resource_probe.write_json(output, {"kind": "test"})

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        resource_probe.write_json(output, {"kind": "replacement"})


def test_capture_rejects_non_kind_context_before_any_cluster_call() -> None:
    args = argparse.Namespace(context="production", namespace=None)

    with pytest.raises(resource_probe.ProbeError, match="local kind"):
        resource_probe.capture(args)
