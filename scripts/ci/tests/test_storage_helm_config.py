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
