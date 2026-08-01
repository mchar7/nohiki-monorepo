"""Focused Helm regression coverage for native Azure Blob storage wiring."""

import subprocess
from pathlib import Path

import yaml
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_HELM = _ROOT / "infra" / "k8s" / "helm"


def test_production_storage_renders_native_azure_blob_provider(tmp_path: Path) -> None:
    production = yaml.safe_load((_HELM / "values.prod.yaml").read_text(encoding="utf-8"))
    storage = production["global"]["s3"]
    assert storage["provider"] == "azure_blob"
    assert storage["endpoint"].startswith("https://")

    values = tmp_path / "storage.yaml"
    values.write_text(
        yaml.safe_dump(
            {
                "global": {
                    "environment": "test",
                    "nohikiImage": {"registry": "example.test", "tag": "test"},
                    "s3": storage,
                    "postgres": {"host": "postgres", "port": 5432},
                    "kafka": {"dsn": "kafka:9092"},
                    "observability": {"otlpEndpoint": "http://otel:4317"},
                },
                "secrets": {"enabled": False},
            }
        ),
        encoding="utf-8",
    )
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "storage",
            str(_HELM),
            "--values",
            str(_HELM / "values.staging.yaml"),
            "--values",
            str(values),
            *runtime_eso_args("staging"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    deployment = next(
        document
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict)
        and document.get("kind") == "Deployment"
        and document.get("metadata", {}).get("name") == "storage-user-upload-service"
    )
    env = {
        entry["name"]: entry["value"]
        for entry in deployment["spec"]["template"]["spec"]["containers"][0]["env"]
        if "value" in entry
    }
    assert env["USER_UPLOAD_S3__PROVIDER"] == "azure_blob"
    assert env["USER_UPLOAD_S3__ENDPOINT"] == "https://nohikiprod.blob.core.windows.net"


def test_kafka_scaling_enablement_and_partition_limit_are_explicit() -> None:
    scalable = {
        "doc-content-service",
        "doc-process-service",
        "doc-template-service",
        "job-correlation-evaluation-service",
        "job-ingest-discovery-service",
        "job-query-composition-service",
        "job-storage-service",
        "ml-compute-service",
        "ml-gateway-service",
        "skill-graph-service",
        "user-entitlement-service",
        "user-pref-service",
        "user-upload-service",
    }
    excluded = {
        "job-ingest-enrichment-service",
        "job-ingest-schedule-service",
        "notification-service",
    }

    for values_name in ("values.dev.yaml", "values.staging.yaml"):
        values = yaml.safe_load((_HELM / values_name).read_text(encoding="utf-8"))
        assert {name for name in scalable if values[name]["scaling"]["enabled"]} == scalable
        assert {name for name in excluded if not values[name]["scaling"]["enabled"]} == excluded

    base = yaml.safe_load((_HELM / "values.yaml").read_text(encoding="utf-8"))
    partition_count = base["global"]["kafka"]["partitionCount"]
    assert partition_count == base["kafkaCluster"]["config"]["numPartitions"] == 3
    assert {name for name in excluded if base[name]["scaling"]["excluded"]} == excluded
