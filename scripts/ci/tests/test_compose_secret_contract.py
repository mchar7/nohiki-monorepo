"""Regression coverage for Compose secret initialization and consumers."""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_COMPOSE = _REPOSITORY_ROOT / "infra" / "compose" / "docker-compose.yml"
_SECRET_INIT = "nohiki-infra-secrets-init"
_SECRET_COMPLETION = {"condition": "service_completed_successfully"}


@cache
def _compose() -> dict[str, Any]:
    return yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))


def _named_secret_mounts(service: dict[str, Any], secret_volumes: set[str]) -> list[str]:
    return [
        mount
        for mount in service.get("volumes", ())
        if isinstance(mount, str) and mount.partition(":")[0] in secret_volumes
    ]


def test_secret_initializer_is_one_shot_and_copies_every_secret_category() -> None:
    """Secret volumes are refreshed once, with no network or writable source access."""
    compose = _compose()
    initializer = compose["services"][_SECRET_INIT]
    mounts = set(initializer["volumes"])
    command = initializer["command"][0]
    categories = (
        "database",
        "redis",
        "s3",
        "s3-mlflow",
        "jwt",
        "oauth",
        "jsearch",
        "llm",
        "email",
        "qdrant",
    )

    assert initializer["restart"] == "no"
    assert initializer["network_mode"] == "none"
    assert initializer["read_only"] is True
    assert "no-new-privileges:true" in initializer["security_opt"]
    assert mounts == {
        *(f"../shared/secrets/{category}:/source/{category}:ro" for category in categories),
        *(f"nohiki-vol-secret-{category}:/target/{category}" for category in categories),
    }
    assert "gcp" not in command
    for category in categories:
        assert f"../shared/secrets/{category}:/source/{category}:ro" in mounts
        assert f"nohiki-vol-secret-{category}:/target/{category}" in mounts
        assert '"/target/$${category}"' in command
    assert 'find "/target/$${category}" -mindepth 1 -delete' in command
    assert 'cp -R "/source/$${category}/." "/target/$${category}/"' in command


def test_mlflow_uses_dedicated_s3_secret_source() -> None:
    """MLflow's S3 credentials come from its isolated source and target volume."""
    compose = _compose()
    initializer = compose["services"][_SECRET_INIT]
    mlflow = compose["services"]["nohiki-mlops-mlflow"]

    assert "../shared/secrets/s3-mlflow:/source/s3-mlflow:ro" in initializer["volumes"]
    assert "nohiki-vol-secret-s3-mlflow:/target/s3-mlflow" in initializer["volumes"]
    assert "nohiki-vol-secret-s3-mlflow:/run/secrets/s3:ro" in mlflow["volumes"]
    assert "nohiki-vol-secret-s3:/run/secrets/s3:ro" not in mlflow["volumes"]


def test_every_named_secret_consumer_waits_for_initializer() -> None:
    """No container can read a named secret volume before initialization succeeds."""
    compose = _compose()
    secret_volumes = {name for name in compose["volumes"] if name.startswith("nohiki-vol-") and "secret" in name}
    consumers = {
        name: mounts
        for name, service in compose["services"].items()
        if name != _SECRET_INIT and (mounts := _named_secret_mounts(service, secret_volumes))
    }

    assert consumers
    for service_name, mounts in consumers.items():
        dependency = compose["services"][service_name].get("depends_on", {}).get(_SECRET_INIT)
        assert dependency == _SECRET_COMPLETION, (service_name, mounts)
