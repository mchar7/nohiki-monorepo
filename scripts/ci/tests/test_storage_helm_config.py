"""Focused Helm regression coverage for native Azure Blob storage wiring."""

import re
import subprocess
from pathlib import Path

import yaml
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_HELM = _ROOT / "infra" / "k8s" / "helm"

# Loki 7.0.0 through 7.2.0 accepts read.initContainers but omits it from the
# non-legacy read Deployment. That Deployment self-heals after a cold-start exit.
_OBJECT_STORAGE_WAIT_WAIVERS = {"loki-read"}


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


def test_local_valkey_and_rustfs_claim_sizes_use_effective_chart_keys() -> None:
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            str(_HELM),
            "--namespace",
            "nohiki-local",
            "--values",
            str(_HELM / "values.local.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    claims = {
        (document["metadata"]["name"], claim["metadata"]["name"]): claim["spec"]["resources"]["requests"]["storage"]
        for document in yaml.safe_load_all(rendered)
        if isinstance(document, dict) and document.get("kind") == "StatefulSet"
        for claim in document["spec"].get("volumeClaimTemplates", [])
    }

    assert claims[("nohiki-valkey-primary", "valkey-data")] == "1Gi"
    assert claims[("nohiki-rustfs", "data")] == "2Gi"


def test_local_s3_consumers_wait_for_declared_rustfs_buckets() -> None:
    rendered = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            str(_HELM),
            "--namespace",
            "nohiki",
            "--values",
            str(_HELM / "values.local.yaml"),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    documents = [document for document in yaml.safe_load_all(rendered) if isinstance(document, dict)]
    bucket_job = next(
        document
        for document in documents
        if document.get("kind") == "Job"
        and document.get("metadata", {}).get("name", "").startswith("nohiki-rustfs-bucket-init-")
    )
    bucket_init = bucket_job["spec"]["template"]["spec"]["containers"][0]
    declared_buckets = set(re.findall(r'ensure_bucket "([^"]+)"', "\n".join(bucket_init["command"])))

    consumers: dict[str, tuple[dict[str, object], set[str]]] = {}
    for document in documents:
        if document.get("kind") not in {"DaemonSet", "Deployment", "StatefulSet"}:
            continue
        pod_spec = document["spec"]["template"]["spec"]
        application_buckets: set[str] = set()
        uses_observability_credentials = False
        for container in pod_spec.get("containers", []):
            env = {
                entry["name"]: entry["value"]
                for entry in container.get("env", [])
                if isinstance(entry, dict) and "name" in entry and "value" in entry
            }
            for name, endpoint in env.items():
                if name.endswith("_S3__ENDPOINT") and endpoint == "http://nohiki-rustfs:9000":
                    bucket = env.get(name.removesuffix("__ENDPOINT") + "__BUCKET")
                    assert bucket
                    application_buckets.add(bucket)
            uses_observability_credentials |= any(
                source.get("secretRef", {}).get("name") == "observability-storage-credentials"
                for source in container.get("envFrom", [])
                if isinstance(source, dict)
            )
        if application_buckets or uses_observability_credentials:
            consumers[document["metadata"]["name"]] = (pod_spec, application_buckets)

    assert len(consumers) == 20
    uncovered_consumers: set[str] = set()
    for workload_name, (pod_spec, application_buckets) in consumers.items():
        waits = [
            container
            for container in pod_spec.get("initContainers", [])
            if container.get("name") == "wait-for-object-storage"
        ]
        if not waits:
            uncovered_consumers.add(workload_name)
            continue
        assert len(waits) == 1, workload_name
        wait = waits[0]
        assert wait["image"] == bucket_init["image"]
        assert wait["securityContext"] == {
            "allowPrivilegeEscalation": False,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "runAsUser": 1000,
            "capabilities": {"drop": ["ALL"]},
        }
        assert wait["resources"]["requests"] == {"cpu": "10m", "memory": "32Mi"}
        assert wait["resources"]["limits"] == {"cpu": "100m", "memory": "128Mi"}

        command = "\n".join([*wait.get("command", []), *wait.get("args", [])])
        assert "s3api head-bucket" in command
        assert "max_attempts=60" in command
        assert 'if [ "$attempt" -eq "$max_attempts" ]' in command
        assert "exit 1" in command

        wait_env = {
            entry["name"]: entry["value"]
            for entry in wait.get("env", [])
            if isinstance(entry, dict) and "value" in entry
        }
        if application_buckets:
            wait_buckets = set(wait_env["S3_BUCKETS"].split())
            endpoint = wait_env["S3_ENDPOINT"]
            assert wait_buckets == application_buckets
        else:
            wait_buckets = set(wait["args"][-2].split())
            endpoint = wait["args"][-1]
        assert endpoint == "http://nohiki-rustfs:9000"
        assert wait_buckets
        assert wait_buckets <= declared_buckets
    tempo_workloads = {
        (document["kind"], document["metadata"]["name"])
        for document in documents
        if document.get("kind") in {"DaemonSet", "Deployment", "StatefulSet"}
        and document.get("metadata", {}).get("name", "").startswith("nohiki-tempo")
    }
    assert tempo_workloads == {("StatefulSet", "nohiki-tempo")}
    tempo_pod_spec = next(
        pod_spec for workload_name, (pod_spec, _) in consumers.items() if workload_name == "nohiki-tempo"
    )
    tempo_container = next(container for container in tempo_pod_spec["containers"] if container["name"] == "tempo")
    assert "-target=all" in tempo_container["args"]
    assert any(
        container.get("name") == "wait-for-object-storage" for container in tempo_pod_spec.get("initContainers", [])
    )
    assert uncovered_consumers == _OBJECT_STORAGE_WAIT_WAIVERS
