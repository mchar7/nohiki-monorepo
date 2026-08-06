"""Observability overlays must target the monolithic Tempo Service.

The in-repo chart exposes only ``nohiki-tempo`` / ``nohiki-tempo-headless``.
Overlays that still point at ``-distributor`` or ``-query-frontend`` hostnames
silently drop every trace after the collector hop.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_OBSERVABILITY = _ROOT / "infra" / "k8s" / "observability"
_OVERLAY_NAMESPACES = {
    "local": "nohiki",
    "dev": "nohiki-dev",
    "staging": "nohiki-staging",
    "prod": "nohiki-prod",
}
_FORBIDDEN_HOST_FRAGMENTS = ("-distributor", "-query-frontend")


def _overlay_text(overlay: str) -> str:
    return (_OBSERVABILITY / "overlays" / overlay / "kustomization.yaml").read_text(encoding="utf-8")


def _render_overlay(overlay: str) -> list[dict]:
    command = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    if not shutil.which(command[0]):
        pytest.skip("kustomize or kubectl is required to render manifests")
    result = subprocess.run(
        [*command, str(_OBSERVABILITY / "overlays" / overlay)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]


@pytest.mark.parametrize("overlay", sorted(_OVERLAY_NAMESPACES))
def test_overlay_patches_target_monolithic_tempo_service(overlay: str) -> None:
    """Patches must reference nohiki-tempo, never microservices hostnames."""
    text = _overlay_text(overlay)
    namespace = _OVERLAY_NAMESPACES[overlay]

    for fragment in _FORBIDDEN_HOST_FRAGMENTS:
        assert fragment not in text, f"{overlay}: forbidden hostname fragment {fragment!r}"

    expected_otlp = f"nohiki-tempo.{namespace}.svc:4317"
    expected_http = f"http://nohiki-tempo.{namespace}.svc:3200"
    assert expected_otlp in text, f"{overlay}: missing collector OTLP endpoint {expected_otlp}"
    assert expected_http in text, f"{overlay}: missing Grafana datasource URL {expected_http}"


@pytest.mark.parametrize("overlay", sorted(_OVERLAY_NAMESPACES))
def test_rendered_overlay_wires_tempo_to_real_service(overlay: str) -> None:
    """Rendered collector + Grafana datasource must resolve to nohiki-tempo."""
    namespace = _OVERLAY_NAMESPACES[overlay]
    docs = _render_overlay(overlay)

    collectors = [d for d in docs if d.get("kind") == "OpenTelemetryCollector"]
    assert len(collectors) == 1, overlay
    endpoint = collectors[0]["spec"]["config"]["exporters"]["otlp/tempo"]["endpoint"]
    assert endpoint == f"nohiki-tempo.{namespace}.svc:4317", overlay

    datasources = [
        d for d in docs if d.get("kind") == "GrafanaDatasource" and d.get("metadata", {}).get("name") == "tempo"
    ]
    assert len(datasources) == 1, overlay
    url = datasources[0]["spec"]["datasource"]["url"]
    assert url == f"http://nohiki-tempo.{namespace}.svc:3200", overlay

    rendered = yaml.safe_dump_all(docs)
    for fragment in _FORBIDDEN_HOST_FRAGMENTS:
        assert not re.search(re.escape(fragment), rendered), f"{overlay}: rendered still has {fragment}"
