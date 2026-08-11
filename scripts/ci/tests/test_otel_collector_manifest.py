from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_OBSERVABILITY = _ROOT / "infra" / "k8s" / "observability"
_COMPOSE = _ROOT / "infra" / "compose" / "docker-compose.yml"
_COMPOSE_CONFIG = _ROOT / "infra" / "compose" / "observability" / "otel" / "collector-config.yaml"
_COLLECTOR = _ROOT / "infra" / "k8s" / "observability" / "base" / "otel" / "collector.yaml"
_OVERLAYS = {
    "local": "http://nohiki-loki-gateway.nohiki.svc:80/otlp",
    "staging": "http://nohiki-loki-gateway.nohiki-staging.svc:80/otlp",
    "prod": "http://nohiki-loki-gateway.nohiki-prod.svc:80/otlp",
}


def _render(overlay: str) -> dict[str, Any]:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    if not shutil.which(command[0]):
        pytest.skip("kustomize or kubectl is required to render manifests")
    result = subprocess.run(
        [*command, str(_OBSERVABILITY / "overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    )
    for document in yaml.safe_load_all(result.stdout):
        if isinstance(document, dict) and document.get("kind") == "OpenTelemetryCollector":
            return document
    message = f"{overlay} render has no OpenTelemetryCollector"
    raise AssertionError(message)


def _collector_configs() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    rendered = []
    for overlay in _OVERLAYS:
        collector = _render(overlay)
        rendered.append((overlay, collector, collector["spec"]["config"]))
    return rendered


def test_tracked_production_dockerfiles_use_immutable_base_images() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "*Dockerfile"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert tracked

    mutable: list[str] = []
    for relative_path in tracked:
        stages: set[str] = set()
        args: dict[str, str] = {}
        for line in (_ROOT / relative_path).read_text(encoding="utf-8").splitlines():
            if argument := re.fullmatch(r"ARG ([A-Z0-9_]+)=(\S+)", line):
                args[argument[1]] = argument[2]
                continue
            if not line.startswith("FROM "):
                continue
            parts = line.split()
            image = parts[1]
            resolved = args.get(image.removeprefix("${").removesuffix("}"), image)
            if resolved != "scratch" and resolved not in stages and "@sha256:" not in resolved:
                mutable.append(f"{relative_path}: {line}")
            if len(parts) >= 4 and parts[-2].upper() == "AS":
                stages.add(parts[-1])

    assert not mutable, "Mutable production base images:\n" + "\n".join(mutable)


def test_compose_and_kubernetes_collectors_use_the_same_pinned_image() -> None:
    compose = yaml.safe_load(_COMPOSE.read_text(encoding="utf-8"))
    collector = yaml.safe_load(_COLLECTOR.read_text(encoding="utf-8"))

    compose_image = compose["services"]["nohiki-obs-otel-collector"]["image"]
    assert compose_image == collector["spec"]["image"]


def test_otel_collector_manifests_use_pinned_config() -> None:
    expected_image = yaml.safe_load(_COLLECTOR.read_text(encoding="utf-8"))["spec"]["image"]
    for overlay, collector, config in _collector_configs():
        assert collector["spec"]["image"] == expected_image, overlay

        exporters = config["exporters"]
        assert "loki" not in exporters, overlay
        assert exporters["otlphttp/loki"]["endpoint"] == _OVERLAYS[overlay]
        assert "default_labels_enabled" not in exporters["otlphttp/loki"], overlay
        assert config["service"]["pipelines"]["logs"]["exporters"] == ["otlphttp/loki"]

        metrics = config["service"]["telemetry"]["metrics"]
        assert "address" not in metrics, overlay
        prometheus = metrics["readers"][0]["pull"]["exporter"]["prometheus"]
        assert prometheus == {"host": "0.0.0.0", "port": 8888}, overlay  # noqa: S104 -- OTLP metrics must bind all pod interfaces.


def _validate_collector_config(image: str, config_path: Path) -> None:
    container = subprocess.run(
        [
            "docker",
            "create",
            image,
            "validate",
            "--config=/etc/otelcol-contrib/config.yaml",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    try:
        subprocess.run(
            [
                "docker",
                "cp",
                str(config_path.resolve()),
                f"{container}:/etc/otelcol-contrib/config.yaml",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["docker", "start", "--attach", container],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container],
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.mark.requires_docker
def test_otel_collector_rendered_configs_validate_with_pinned_binary(
    tmp_path: Path,
) -> None:
    if not shutil.which("docker"):
        pytest.skip("Docker integration is unavailable")
    available = subprocess.run(["docker", "info"], capture_output=True, text=True, check=False)
    if available.returncode != 0:
        pytest.skip("Docker integration is unavailable")
    image = yaml.safe_load(_COLLECTOR.read_text(encoding="utf-8"))["spec"]["image"]

    _validate_collector_config(image, _COMPOSE_CONFIG)

    for overlay, _, config in _collector_configs():
        config_path = tmp_path / f"{overlay}.yaml"
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        _validate_collector_config(image, config_path)
