"""End-to-end source and Helm contracts for production frontend delivery."""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import tarfile
import time
import urllib.parse
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND = _ROOT / "typescript" / "apps" / "frontend"
_DOCKERFILE = _FRONTEND / "Dockerfile"
_CADDYFILE = _FRONTEND / "Caddyfile"
_API_CLIENT = _FRONTEND / "src" / "shared" / "api" / "client.ts"
_CHART = _ROOT / "infra" / "k8s" / "helm"
_FRONTEND_CHART = _CHART / "charts" / "nohiki-frontend"
_BUILD_WORKFLOW = _ROOT / ".github" / "workflows" / "build-push.yml"
_CHECKS_WORKFLOW = _ROOT / ".github" / "workflows" / "checks.yml"
_IMAGE_INVENTORY = _ROOT / "infra" / "k8s" / "local" / "images.json"
_JUSTFILE = _ROOT / "Justfile"
_DOCKERIGNORE = _ROOT / ".dockerignore"
_LOCAL_PLATFORM = _ROOT / "infra" / "k8s" / "gitops" / "platform" / "local"
_FRONTEND_ARCHIVE = _CHART / "charts" / "nohiki-frontend-0.1.0.tgz"
_PROD_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_PROD_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_IMAGE_PREFIX = "ghcr.io/mchar7/nohiki-monorepo/"


def _matrix() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(_BUILD_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["build-push"]["strategy"]["matrix"]["include"]


def _digest_overlay(tmp_path: Path, environment: str) -> tuple[Path, str]:
    prefix = "localhost:5000/" if environment == "local" else _IMAGE_PREFIX
    digests = {f"{prefix}{entry['name']}": f"sha256:{index + 1:064x}" for index, entry in enumerate(_matrix())}
    overlay = tmp_path / f"values.{environment}.frontend-digests.yaml"
    overlay.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return overlay, digests[f"{prefix}frontend"]


def _render(values_name: str, tmp_path: Path) -> tuple[dict[str, Any], ...]:
    environment = values_name.removeprefix("values.").removesuffix(".yaml")
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{environment}",
        "--values",
        str(_CHART / values_name),
    ]
    if environment in {"local", "prod"}:
        overlay, _ = _digest_overlay(tmp_path, environment)
        if environment == "prod":
            command.extend(
                [
                    "--values",
                    str(_PROD_IDENTITY),
                    "--values",
                    str(_PROD_NETWORK),
                ]
            )
        command.extend(["--values", str(overlay)])
    command.extend(runtime_eso_args(environment))
    result = subprocess.run(command, cwd=_ROOT, check=True, capture_output=True, text=True)
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


@pytest.fixture(scope="session")
def frontend_renders(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[dict[str, Any], ...]]:
    render_dir = tmp_path_factory.mktemp("frontend-renders")
    return {
        values_name: _render(values_name, render_dir)
        for values_name in (
            "values.local.yaml",
            "values.staging.yaml",
            "values.prod.yaml",
        )
    }


def _named(documents: tuple[dict[str, Any], ...], kind: str, name: str) -> dict[str, Any]:
    matches = [
        document
        for document in documents
        if document.get("kind") == kind and document.get("metadata", {}).get("name") == name
    ]
    assert len(matches) == 1, f"expected one {kind} named {name}, got {len(matches)}"
    return matches[0]


def _just_image_specs() -> set[tuple[str, str, str, str | None]]:
    value = subprocess.run(
        ["just", "--evaluate", "first_party_image_specs"],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    specs: set[tuple[str, str, str, str | None]] = set()
    for raw_spec in value.split():
        name, context, dockerfile, *build_arg = raw_spec.split("|")
        specs.add((name, context, dockerfile, build_arg[0] if build_arg else None))
    return specs


def _request(url: str) -> tuple[int, bytes, str]:
    parsed = urllib.parse.urlsplit(url)
    assert parsed.scheme == "http"
    assert parsed.hostname is not None
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        connection.request("GET", parsed.path)
        response = connection.getresponse()
        return response.status, response.read(), response.headers.get_content_type()
    finally:
        connection.close()


def _wait_for_http(runtime: str, container: str, url: str) -> tuple[int, bytes, str]:
    for _ in range(50):
        try:
            return _request(url)
        except ConnectionError, OSError, http.client.HTTPException:
            status = subprocess.run(
                [runtime, "inspect", "--format", "{{.State.Status}}", container],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert status == "running", subprocess.run(
                [runtime, "logs", container],
                capture_output=True,
                text=True,
                check=False,
            ).stderr
            time.sleep(0.1)
    message = f"container did not serve {url}"
    raise AssertionError(message)


@pytest.mark.requires_docker
def test_frontend_container_build_and_hardened_runtime_smoke() -> None:
    runtime = os.environ.get("CONTAINER_RUNTIME", "docker")
    suffix = uuid4().hex
    image = f"nohiki-frontend-smoke:{suffix}"
    network = f"nohiki-frontend-smoke-{suffix}"
    upstream = f"nohiki-frontend-upstream-{suffix}"
    frontend = f"nohiki-frontend-{suffix}"
    subprocess.run(
        [runtime, "build", "--file", str(_DOCKERFILE), "--tag", image, "."],
        cwd=_ROOT,
        check=True,
    )
    subprocess.run([runtime, "network", "create", network], check=True)
    try:
        subprocess.run(
            [
                runtime,
                "run",
                "--detach",
                "--name",
                upstream,
                "--network",
                network,
                "--user",
                "999:999",
                "--read-only",
                image,
                "caddy",
                "respond",
                "--listen",
                ":8081",
                "--body",
                "bounded-upstream-response",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                runtime,
                "run",
                "--detach",
                "--name",
                frontend,
                "--network",
                network,
                "--user",
                "999:999",
                "--read-only",
                "--env",
                f"BFF_UPSTREAM=http://{upstream}:8081",
                "--publish",
                "127.0.0.1::8080",
                image,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        port_output = subprocess.run(
            [runtime, "port", frontend, "8080/tcp"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        port = port_output.rsplit(":", maxsplit=1)[1]
        origin = f"http://127.0.0.1:{port}"
        assert _wait_for_http(runtime, frontend, f"{origin}/healthz") == (
            200,
            b"",
            "text/plain",
        )
        root = _request(f"{origin}/")
        deep_route = _request(f"{origin}/profiles/example/deep-link")
        assert root[0] == deep_route[0] == 200
        assert root[1] == deep_route[1]
        assert root[2] == deep_route[2] == "text/html"
        assert _request(f"{origin}/api/smoke") == (
            200,
            b"bounded-upstream-response",
            "text/plain",
        )
        runtime_user = subprocess.run(
            [runtime, "inspect", "--format", "{{.Config.User}}", frontend],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        read_only = subprocess.run(
            [
                runtime,
                "inspect",
                "--format",
                "{{.HostConfig.ReadonlyRootfs}}",
                frontend,
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert runtime_user == "999:999"
        assert read_only.lower() == "true"
    finally:
        subprocess.run(
            [runtime, "rm", "--force", frontend, upstream],
            check=False,
            capture_output=True,
        )
        subprocess.run([runtime, "network", "rm", network], check=False, capture_output=True)
        subprocess.run([runtime, "image", "rm", image], check=False, capture_output=True)


def test_build_context_keeps_runner_sources_and_excludes_typescript_artifacts() -> None:
    rules = [
        line.strip()
        for line in _DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    required_exclusions = {
        "**/node_modules/",
        "**/dist/",
        "**/.output/",
        "**/playwright-report/",
        "**/test-results/",
    }
    assert required_exclusions <= set(rules)
    assert all(not rule.startswith("!") for rule in required_exclusions)

    required_runner_sources = {
        "!tests/",
        "!tests/pyproject.toml",
        "!tests/api/",
        "!tests/api/**",
    }
    assert required_runner_sources <= set(rules)
    last_test_exclusion = max(rules.index("tests/"), rules.index("**/tests/"))
    assert all(rules.index(rule) > last_test_exclusion for rule in required_runner_sources)
    assert (_ROOT / "tests" / "pyproject.toml").is_file()
    assert (_ROOT / "tests" / "api" / "run_k8s_verification.py").is_file()


def test_frontend_image_is_a_pinned_multistage_non_root_static_build() -> None:
    dockerfile = _DOCKERFILE.read_text(encoding="utf-8")
    from_lines = re.findall(r"(?mi)^FROM\s+(\S+)(?:\s+AS\s+(\S+))?\s*$", dockerfile)

    assert len(from_lines) == 2, "frontend image must have one build stage and one runtime stage"
    assert all("@sha256:" in image for image, _ in from_lines), from_lines
    assert from_lines[0][1].lower() in {"build", "builder"}
    assert from_lines[1][1].lower() in {"runtime", "server"}
    assert re.search(r"(?m)^RUN\s+.*pnpm\s+(?:--filter\s+nohiki-frontend\s+)?build\b", dockerfile)
    assert re.search(r"(?mi)^COPY\s+--from=(?:build|builder)\s+\S*dist/?\s+\S+", dockerfile)
    assert re.search(
        r"(?m)^COPY\s+typescript/apps/frontend/Caddyfile\s+/etc/caddy/Caddyfile\s*$",
        dockerfile,
    )
    assert re.search(r"(?m)^USER\s+(?!0(?:\D|$))\d+(?::\d+)?\s*$", dockerfile)
    assert re.search(r"(?m)^EXPOSE\s+8080\s*$", dockerfile)
    assert re.search(
        r'(?m)^CMD\s+\["caddy",\s*"run",\s*"--config",\s*"/etc/caddy/Caddyfile"\]\s*$',
        dockerfile,
    )


def test_static_server_keeps_api_same_origin_and_has_health_and_spa_fallback() -> None:
    caddyfile = _CADDYFILE.read_text(encoding="utf-8")
    client = _API_CLIENT.read_text(encoding="utf-8")

    assert re.search(r"(?m)^:8080\s*\{", caddyfile)
    assert re.search(r"(?m)^\s*respond\s+/healthz\s+200\s*$", caddyfile)
    api_block = re.search(r"(?ms)^\s*handle\s+/api/\*\s*\{(?P<body>.*?)^\s*\}", caddyfile)
    assert api_block is not None
    assert re.search(r"(?m)^\s*reverse_proxy\s+\{\$BFF_UPSTREAM\}\s*$", api_block.group("body"))
    assert re.search(r"(?m)^\s*try_files\s+\{path\}\s+/index\.html\s*$", caddyfile)
    assert re.search(r"(?m)^\s*file_server\s*$", caddyfile)
    assert "VITE_API_BASE_URL" in client
    assert re.search(r"VITE_API_BASE_URL[^\n]*\?\?\s*''", client), (
        "production API calls must default to relative same-origin /api paths"
    )


def test_frontend_chart_is_an_enabled_source_dependency_with_canonical_image_name() -> None:
    umbrella = yaml.safe_load((_CHART / "Chart.yaml").read_text(encoding="utf-8"))
    dependencies = [dependency for dependency in umbrella["dependencies"] if dependency["name"] == "nohiki-frontend"]

    assert dependencies == [
        {
            "name": "nohiki-frontend",
            "version": "0.1.x",
            "repository": "file://./charts/nohiki-frontend",
            "condition": "frontend.enabled",
            "alias": "frontend",
        }
    ]
    assert (_FRONTEND_CHART / "Chart.yaml").is_file()
    assert (_FRONTEND_CHART / "values.yaml").is_file()
    assert (_FRONTEND_CHART / "templates" / "deployment.yaml").is_file()
    assert (_FRONTEND_CHART / "templates" / "service.yaml").is_file()
    values = yaml.safe_load((_FRONTEND_CHART / "values.yaml").read_text(encoding="utf-8"))
    assert values["enabled"] is True
    assert values["image"] == {"name": "frontend", "tag": ""}
    assert values["service"] == {
        "name": "frontend",
        "type": "ClusterIP",
        "port": 80,
        "targetPort": 8080,
    }


def test_frontend_chart_lock_and_archive_exactly_match_source() -> None:
    metadata = yaml.safe_load((_FRONTEND_CHART / "Chart.yaml").read_text(encoding="utf-8"))
    lock = yaml.safe_load((_CHART / "Chart.lock").read_text(encoding="utf-8"))
    assert [dependency for dependency in lock["dependencies"] if dependency["name"] == metadata["name"]] == [
        {
            "name": metadata["name"],
            "repository": "file://./charts/nohiki-frontend",
            "version": metadata["version"],
        }
    ]
    assert _FRONTEND_ARCHIVE.name == f"{metadata['name']}-{metadata['version']}.tgz"

    source_files = {
        path.relative_to(_FRONTEND_CHART).as_posix(): path.read_bytes()
        for path in _FRONTEND_CHART.rglob("*")
        if path.is_file()
    }
    with tarfile.open(_FRONTEND_ARCHIVE, mode="r:gz") as archive:
        prefix = f"{metadata['name']}/"
        archived_files = {
            member.name.removeprefix(prefix): extracted.read()
            for member in archive.getmembers()
            if member.isfile()
            and member.name.startswith(prefix)
            and (extracted := archive.extractfile(member)) is not None
        }
        archived_metadata = yaml.safe_load(archived_files["Chart.yaml"].decode("utf-8"))
    assert archived_metadata == metadata
    assert archived_files.keys() == source_files.keys()
    for name in source_files.keys() - {"Chart.yaml"}:
        assert archived_files[name] == source_files[name], name


def test_canonical_workflow_inventory_and_justfile_image_specs_are_equal() -> None:
    workflow_specs = {
        (
            entry["name"],
            entry.get("context", "."),
            entry["dockerfile"],
            entry.get("build_args"),
        )
        for entry in _matrix()
    }
    inventory = json.loads(_IMAGE_INVENTORY.read_text(encoding="utf-8"))
    inventory_specs = {
        (
            entry["name"],
            entry.get("context", "."),
            entry["dockerfile"],
            next(iter(entry.get("buildArgs", {}).items()), None),
        )
        for entry in inventory["images"]
    }
    normalized_inventory_specs = {
        (
            name,
            context,
            (Path(context) / dockerfile).as_posix(),
            f"{build_arg[0]}={build_arg[1]}" if build_arg else None,
        )
        for name, context, dockerfile, build_arg in inventory_specs
    }
    assert workflow_specs == normalized_inventory_specs == _just_image_specs()


def test_checks_workflow_docker_lane_runs_every_marked_contract() -> None:
    workflow = yaml.safe_load(_CHECKS_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["frontend-smoke"]["steps"]
    smoke_steps = [step for step in steps if step.get("name") == "Smoke production frontend container"]
    assert smoke_steps == [
        {
            "name": "Smoke production frontend container",
            "run": "nix develop .#ci --command uv run --no-sync pytest scripts/ci/tests -m requires_docker\n",
            "env": {"CONTAINER_RUNTIME": "docker"},
        }
    ]


def test_frontend_is_in_canonical_local_and_release_image_inventories() -> None:
    inventory = json.loads(_IMAGE_INVENTORY.read_text(encoding="utf-8"))
    inventory_rows = [entry for entry in inventory["images"] if entry["name"] == "frontend"]
    workflow_rows = [entry for entry in _matrix() if entry["name"] == "frontend"]

    assert inventory["schemaVersion"] == 1
    assert inventory_rows == [
        {
            "name": "frontend",
            "context": ".",
            "dockerfile": "typescript/apps/frontend/Dockerfile",
            "local": True,
        }
    ]
    assert workflow_rows == [
        {
            "name": "frontend",
            "context": ".",
            "dockerfile": "typescript/apps/frontend/Dockerfile",
        }
    ]


def test_local_helmrelease_requires_generated_digest_values_overlay() -> None:
    release = yaml.safe_load(
        (_ROOT / "infra/k8s/gitops/platform/base/helmrelease-platform.yaml").read_text(encoding="utf-8")
    )
    kustomization = yaml.safe_load((_LOCAL_PLATFORM / "kustomization.yaml").read_text(encoding="utf-8"))
    assert release["spec"]["chart"]["spec"]["valuesFiles"] == [
        "infra/k8s/helm/values.yaml",
        "infra/k8s/helm/values.local.yaml",
    ]
    assert kustomization["configMapGenerator"] == [
        {
            "name": "nohiki-image-digests",
            "namespace": "flux-system",
            "files": ["values.yaml=image-digests.values.yaml"],
        }
    ]
    patch = yaml.safe_load(kustomization["patches"][0]["patch"])
    assert patch == [
        {
            "op": "add",
            "path": "/spec/valuesFrom",
            "value": [
                {
                    "kind": "ConfigMap",
                    "name": "nohiki-image-digests",
                    "valuesKey": "values.yaml",
                    "optional": False,
                }
            ],
        }
    ]


@pytest.mark.parametrize(
    ("values_name", "expected_image", "expected_pull_policy"),
    [
        ("values.local.yaml", None, "IfNotPresent"),
        (
            "values.staging.yaml",
            "ghcr.io/mchar7/nohiki-monorepo/frontend:sha-933dda3",
            "IfNotPresent",
        ),
        ("values.prod.yaml", None, "IfNotPresent"),
    ],
)
def test_frontend_helm_workload_is_hardened_and_environment_identified(
    values_name: str,
    expected_image: str | None,
    expected_pull_policy: str,
    tmp_path: Path,
    frontend_renders: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = frontend_renders[values_name]
    deployment = _named(documents, "Deployment", "nohiki-frontend")
    service = _named(documents, "Service", "nohiki-frontend")
    pod = deployment["spec"]["template"]["spec"]
    assert len(pod["containers"]) == 1
    container = pod["containers"][0]

    if expected_image is None:
        environment = values_name.removeprefix("values.").removesuffix(".yaml")
        prefix = "localhost:5000/" if environment == "local" else _IMAGE_PREFIX
        _, digest = _digest_overlay(tmp_path, environment)
        expected_image = f"{prefix}frontend@{digest}"
        assert ":dev" not in expected_image
    assert container["image"] == expected_image
    assert container["imagePullPolicy"] == expected_pull_policy
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"] == {
        "runAsNonRoot": True,
        "runAsUser": 999,
        "runAsGroup": 999,
        "fsGroup": 999,
        "seccompProfile": {"type": "RuntimeDefault"},
    }
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    assert container["ports"] == [{"name": "http", "containerPort": 8080, "protocol": "TCP"}]
    assert container["livenessProbe"]["httpGet"] == {"path": "/healthz", "port": "http"}
    assert container["readinessProbe"]["httpGet"] == {
        "path": "/healthz",
        "port": "http",
    }
    assert container["resources"] == {
        "requests": {"cpu": "100m", "memory": "128Mi"},
        "limits": {"cpu": "500m", "memory": "256Mi"},
    }
    assert service["spec"] == {
        "type": "ClusterIP",
        "ports": [{"port": 80, "targetPort": "http", "protocol": "TCP", "name": "http"}],
        "selector": deployment["spec"]["selector"]["matchLabels"],
    }
    assert deployment["spec"]["template"]["metadata"]["labels"].items() >= service["spec"]["selector"].items()


@pytest.mark.parametrize("values_name", ["values.local.yaml", "values.staging.yaml", "values.prod.yaml"])
def test_frontend_gateway_route_resolves_to_the_rendered_service(
    values_name: str,
    frontend_renders: dict[str, tuple[dict[str, Any], ...]],
) -> None:
    documents = frontend_renders[values_name]
    gateway = _named(documents, "Gateway", "nohiki-gateway")
    route = _named(documents, "HTTPRoute", "nohiki-frontend-route")
    service = _named(documents, "Service", "nohiki-frontend")

    assert route["spec"]["parentRefs"] == [
        {
            "name": gateway["metadata"]["name"],
            "namespace": service["metadata"]["namespace"],
        }
    ]
    assert route["spec"]["rules"] == [
        {
            "matches": [{"path": {"type": "PathPrefix", "value": "/"}}],
            "backendRefs": [{"name": service["metadata"]["name"], "port": 80}],
        }
    ]
