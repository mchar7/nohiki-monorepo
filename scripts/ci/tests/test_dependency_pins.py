from __future__ import annotations

import fnmatch
import json
import re
import shlex
import subprocess
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_DEPENDABOT = _ROOT / ".github" / "dependabot.yml"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_WORKFLOWS = _ROOT / ".github" / "workflows"
_FLAKE = _ROOT / "flake.nix"
_JUSTFILE = _ROOT / "Justfile"
_ROOT_PROJECT = _ROOT / "pyproject.toml"
_PACKAGE = _ROOT / "package.json"
_SCAFFOLD_DOCKERFILE = (
    _ROOT / "scripts" / "util" / "scaffold" / "src" / "nohiki_scaffold" / "templates" / "service" / "Dockerfile.j2"
)
_KAFKA_DOCKERFILE = _ROOT / "infra" / "k8s" / "kafka-connect" / "Dockerfile"
_ML_COMPUTE_DOCKERFILE = _ROOT / "backend" / "services" / "ml-compute-service" / "Dockerfile"
_KAFKA_README = _KAFKA_DOCKERFILE.parent / "smt" / "README.md"
_HELM_VALUES = _ROOT / "infra" / "k8s" / "helm" / "values.yaml"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE = re.compile(
    r"(?:FROM |--from=)(?P<ref>(?P<repository>[^:@\s]+(?:/[^:@\s]+)*):"
    r"(?P<version>[^@\s]+)@sha256:(?P<digest>[0-9a-f]{64}))"
)
_ACTION_USE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<action>[^@\s]+/[^@\s]+)@(?P<revision>[0-9a-f]{40})"
    r"\s+#\s+(?P<version>v\d+(?:\.\d+)*)\s*$"
)


@cache
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(_read_text(path))
    assert isinstance(value, dict), path
    return value


def test_all_workflow_actions_are_sha_pinned_with_version_comments() -> None:
    failures: list[str] = []
    uses_count = 0
    workflow_paths = sorted((*_WORKFLOWS.glob("*.yml"), *_WORKFLOWS.glob("*.yaml")))
    assert workflow_paths, "no workflow files discovered"

    for path in workflow_paths:
        for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
            if not re.match(r"^\s*(?:-\s*)?uses:", line):
                continue
            uses_count += 1
            if _ACTION_USE.fullmatch(line) is None:
                failures.append(f"{path.relative_to(_ROOT)}:{line_number}: {line.strip()}")

    assert uses_count, "no workflow action references discovered"
    assert not failures, "workflow actions must use full SHA pins with version comments:\n" + "\n".join(failures)


def test_workflow_checkouts_do_not_persist_credentials() -> None:
    workflow_paths = sorted((*_WORKFLOWS.glob("*.yml"), *_WORKFLOWS.glob("*.yaml")))
    missing = [
        f"{path.relative_to(_ROOT)}:{job_name}"
        for path in workflow_paths
        for job_name, job in _load_yaml(path)["jobs"].items()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and step.get("with", {}).get("persist-credentials") is not False
    ]

    assert not missing, f"checkout credentials persisted in read-only jobs: {missing}"


@cache
def _python_dockerfiles() -> tuple[Path, ...]:
    return tuple(
        sorted(
            [
                *_ROOT.glob("backend/services/*/Dockerfile"),
                *_ROOT.glob("backend/jobs/*/Dockerfile"),
                _ROOT / "infra" / "shared" / "qdrant-init" / "Dockerfile",
            ]
        )
    )


def _images(path: Path, repository: str) -> list[re.Match[str]]:
    return [match for match in _IMAGE.finditer(_read_text(path)) if match["repository"] == repository]


def _dependabot_entries() -> dict[str, list[dict[str, Any]]]:
    entries: dict[str, list[dict[str, Any]]] = {}
    for update in _load_yaml(_DEPENDABOT)["updates"]:
        entries.setdefault(update["package-ecosystem"], []).append(update)
    return entries


def _configured_directories(entry: dict[str, Any]) -> list[str]:
    directories = entry.get("directories")
    if directories is None:
        directories = [entry["directory"]]
    return [directory.removeprefix("/") or "." for directory in directories]


def _is_covered(relative_directory: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(relative_directory, pattern) for pattern in patterns)


def _assert_cpu_development_sync(command: str) -> None:
    tokens = shlex.split(command)
    assert tokens[:2] == ["uv", "sync"], tokens
    assert "--all-packages" in tokens, tokens
    assert "--all-extras" in tokens, tokens
    assert any(tokens[index : index + 2] == ["--no-extra", "cuda"] for index in range(len(tokens) - 1)), tokens
    assert not any(tokens[index : index + 2] == ["--extra", "cuda"] for index in range(len(tokens) - 1)), tokens


def test_cpu_development_syncs_exclude_cuda_while_gpu_image_opts_in() -> None:
    flake = _read_text(_FLAKE)
    base_hook = re.search(r"baseHook = ''(?P<body>.*?)'';", flake, re.DOTALL)
    assert base_hook, "flake.nix has no base development-shell hook"
    sync_pattern = r"^\s*(?:.*?\s--\s+)?(uv sync\b[^\n]*)"
    flake_syncs = re.findall(sync_pattern, base_hook["body"], re.MULTILINE)
    assert len(flake_syncs) == 1, flake_syncs

    justfile = _read_text(_JUSTFILE)
    sync_dev = re.search(r"^sync-dev:\n(?P<body>(?:[ \t]+[^\n]*\n?)+)", justfile, re.MULTILINE)
    assert sync_dev, "Justfile has no sync-dev recipe"
    just_syncs = re.findall(sync_pattern, sync_dev["body"], re.MULTILINE)
    assert len(just_syncs) == 1, just_syncs

    hosted_steps = (step for job in _load_yaml(_CHECKS)["jobs"].values() for step in job.get("steps", ()))
    install_steps = [step for step in hosted_steps if step.get("name") == "Install workspace (all packages + extras)"]
    assert install_steps

    workflow_syncs: list[str] = []
    for step in install_steps:
        step_syncs = re.findall(r"^\s*(uv sync\b[^\n]*)", str(step["run"]), re.MULTILINE)
        assert len(step_syncs) == 1, step["run"]
        workflow_syncs.extend(step_syncs)

    for command in (*flake_syncs, *just_syncs, *workflow_syncs):
        _assert_cpu_development_sync(command)

    dockerfile = _read_text(_ML_COMPUTE_DOCKERFILE)
    gpu_stage = re.search(
        r"^FROM\s+\S+\s+AS\s+sync-gpu\s*$\n(?P<body>.*?)(?=^FROM\s|\Z)",
        dockerfile,
        re.MULTILINE | re.DOTALL,
    )
    assert gpu_stage, "ml-compute Dockerfile has no sync-gpu stage"
    gpu_syncs = re.findall(r"^RUN\s+(uv sync\b[^\n]*)", gpu_stage["body"], re.MULTILINE)
    assert len(gpu_syncs) == 1, gpu_syncs
    gpu_tokens = shlex.split(gpu_syncs[0])
    assert any(gpu_tokens[index : index + 2] == ["--extra", "cuda"] for index in range(len(gpu_tokens) - 1)), gpu_tokens

    subprocess.run(
        [
            "uv",
            "sync",
            "--all-packages",
            "--all-extras",
            "--no-extra",
            "cuda",
            "--locked",
            "--dry-run",
        ],
        cwd=_ROOT,
        check=True,
    )


def test_python_workspace_installs_restore_the_exact_virtual_environment_cache() -> None:
    workflow = _load_yaml(_CHECKS)
    install_name = "Install workspace (all packages + extras)"
    cache_name = "Cache workspace virtual environment"
    # Consistency contract: one full-SHA actions/cache pin across every workflow.
    # The concrete SHA is deliberately not asserted; freshness belongs to the updater.
    cache_pins = {
        str(step["uses"])
        for path in sorted((_ROOT / ".github" / "workflows").glob("*.yml"))
        for job in _load_yaml(path)["jobs"].values()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/cache@")
    }
    assert len(cache_pins) == 1, f"actions/cache pins diverge across workflows: {sorted(cache_pins)}"
    cache_action = cache_pins.pop()
    assert re.fullmatch(r"actions/cache@[0-9a-f]{40}", cache_action), cache_action
    covered_jobs: set[str] = set()

    for job_name, job in workflow["jobs"].items():
        steps = job.get("steps", [])
        install_indexes = [index for index, step in enumerate(steps) if step.get("name") == install_name]
        if not install_indexes:
            continue
        assert len(install_indexes) == 1
        caches = [(index, step) for index, step in enumerate(steps) if step.get("name") == cache_name]
        assert len(caches) == 1
        cache_index, cache_step = caches[0]
        assert cache_index < install_indexes[0]
        assert cache_step["uses"] == cache_action
        cache_prefix = "venv-deadcode" if job_name == "hygiene" else "venv"
        cache_key = (
            f"{cache_prefix}-${{{{ runner.os }}}}-${{{{ runner.arch }}}}"
            "-${{ hashFiles('uv.lock', 'pyproject.toml', '.python-version', 'flake.nix', 'flake.lock') }}"
        )
        assert cache_step["with"] == {"path": ".venv", "key": cache_key}
        install_step = steps[install_indexes[0]]
        assert cache_step.get("if") == install_step.get("if")
        install_command = str(install_step["run"])
        assert ("--group deadcode" in install_command) == (job_name == "hygiene")
        if job_name == "hygiene":
            assert not any(step.get("name") == "Cache Skylos analysis" for step in steps)
        covered_jobs.add(job_name)

    assert covered_jobs == {
        "api-schema-freshness",
        "frontend-smoke",
        "hygiene",
        "otel-collector",
        "python-tests",
        "typecheck",
    }


def test_codeql_private_phase_trigger_contract() -> None:
    workflow = _load_yaml(_ROOT / ".github" / "workflows" / "codeql.yml")
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {
        "push": {"branches": ["main"]},
        "pull_request": {"branches": ["main"]},
        "workflow_dispatch": None,
    }, (
        "P7 public cutover must restore the weekly schedule alongside the "
        "push, pull_request, and workflow_dispatch triggers"
    )


def test_codeql_analysis_requires_public_repository_payload() -> None:
    workflow = _load_yaml(_ROOT / ".github" / "workflows" / "codeql.yml")
    assert workflow["jobs"]["analyze"]["if"] == (
        "${{ github.event.repository && github.event.repository.private == false }}"
    )


def test_codeql_sarif_permissions_are_least_privilege() -> None:
    workflow = _load_yaml(_ROOT / ".github" / "workflows" / "codeql.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["analyze"]["permissions"] == {
        "actions": "read",
        "contents": "read",
        "security-events": "write",
    }


def test_python_and_uv_container_pins_match_scaffold_ci_and_nix() -> None:
    dockerfiles = _python_dockerfiles()
    assert dockerfiles, "no Python production Dockerfiles discovered"

    python_repository = "public.ecr.aws/docker/library/python"
    uv_repository = "ghcr.io/astral-sh/uv"
    scaffold_python = _images(_SCAFFOLD_DOCKERFILE, python_repository)
    scaffold_uv = _images(_SCAFFOLD_DOCKERFILE, uv_repository)
    assert len(scaffold_python) == 2
    assert len(scaffold_uv) == 1

    expected_python = (scaffold_python[0]["version"], scaffold_python[0]["digest"])
    expected_uv = (scaffold_uv[0]["version"], scaffold_uv[0]["digest"])
    mismatches: list[str] = []
    for dockerfile in dockerfiles:
        python_images = _images(dockerfile, python_repository)
        uv_images = _images(dockerfile, uv_repository)
        if [(match["version"], match["digest"]) for match in python_images] != [
            expected_python,
            expected_python,
        ]:
            mismatches.append(f"{dockerfile.relative_to(_ROOT)}: Python base does not match scaffold builder/runtime")
        if [(match["version"], match["digest"]) for match in uv_images] != [expected_uv]:
            mismatches.append(f"{dockerfile.relative_to(_ROOT)}: uv image does not match scaffold")
    assert not mismatches, "\n".join(mismatches)

    assert "env" not in _load_yaml(_CHECKS), "checks.yml must not re-pin toolchain versions beside the flake"
    python_version = expected_python[0].removesuffix("-slim")

    root_project = tomllib.loads(_read_text(_ROOT_PROJECT))
    python_minor = ".".join(python_version.split(".")[:2])
    assert root_project["project"]["requires-python"] == f">={python_minor}"
    assert tomllib.loads(_read_text(_ROOT / "uv.lock"))["requires-python"] == f">={python_minor}"

    flake = _read_text(_FLAKE)
    assert f"python = pkgs.python{python_minor.replace('.', '')};" in flake
    assert f'version = "{expected_uv[0]}";' in flake
    assert f"/download/{expected_uv[0]}/uv-${{uvRelease.target}}.tar.gz" in flake
    nix_digests = re.findall(r'sha256 = "([0-9a-f]+)";', flake)
    assert len(nix_digests) == 4
    assert all(_SHA256.fullmatch(digest) for digest in nix_digests)


def test_node_and_pnpm_toolchains_match_ci_nix_and_project_metadata() -> None:
    workflow = _load_yaml(_CHECKS)
    changes_steps = workflow["jobs"]["changes"]["steps"]
    commitlint_steps = workflow["jobs"]["commitlint"]["steps"]
    assert not any(step.get("name") == "Install Nix" for step in (*changes_steps, *commitlint_steps))

    setup_uv = next(step for step in changes_steps if step.get("name") == "Set up uv and Python")
    setup_pnpm = next(step for step in commitlint_steps if step.get("name") == "Install pnpm")
    setup_node = next(step for step in commitlint_steps if step.get("name") == "Set up Node")
    assert str(setup_uv["uses"]).startswith("astral-sh/setup-uv@")
    assert str(setup_pnpm["uses"]).startswith("pnpm/action-setup@")
    assert str(setup_node["uses"]).startswith("actions/setup-node@")
    assert "with" not in setup_pnpm

    package = json.loads(_read_text(_PACKAGE))
    pnpm_version = package["packageManager"].removeprefix("pnpm@")
    assert re.fullmatch(r"\d+\.\d+\.\d+", pnpm_version), package["packageManager"]

    frontend_dockerfiles = sorted((_ROOT / "typescript" / "apps" / "frontend").glob("Dockerfile*"))
    assert frontend_dockerfiles
    dockerfile_pnpm_pins = {
        dockerfile: re.findall(
            r"^RUN\s+npm\s+install\s+--global\s+pnpm@([^\s#]+)\s*$",
            _read_text(dockerfile),
            re.MULTILINE,
        )
        for dockerfile in frontend_dockerfiles
    }
    assert all(dockerfile_pnpm_pins.values()), dockerfile_pnpm_pins
    assert all(pin == pnpm_version for pins in dockerfile_pnpm_pins.values() for pin in pins), dockerfile_pnpm_pins

    node_floor = package["engines"]["node"].removeprefix(">=")
    assert re.fullmatch(r"\d+\.\d+\.\d+", node_floor), package["engines"]["node"]
    assert f"nodejs = pkgs.nodejs_{node_floor.split('.', 1)[0]};" in _read_text(_FLAKE)
    assert setup_node["with"] == {
        "node-version": node_floor.split(".", 1)[0],
        "cache": "pnpm",
    }
    uv_version = re.search(r'uvPackage.*?version = "([^"]+)";', _read_text(_FLAKE), re.DOTALL)
    assert uv_version
    python_version = _images(_SCAFFOLD_DOCKERFILE, "public.ecr.aws/docker/library/python")[0]["version"]
    assert setup_uv["with"] == {
        "version": uv_version[1],
        "python-version": python_version.removesuffix("-slim"),
        "enable-cache": True,
        "cache-dependency-glob": "uv.lock",
    }


def test_kafka_connect_build_and_remote_connector_pins_are_consistent() -> None:
    dockerfile = _read_text(_KAFKA_DOCKERFILE)
    readme = _read_text(_KAFKA_README)
    values = _load_yaml(_HELM_VALUES)["kafkaConnect"]["build"]

    gradle = _images(_KAFKA_DOCKERFILE, "gradle")
    debezium = _images(_KAFKA_DOCKERFILE, "quay.io/debezium/connect")
    assert len(gradle) == 1
    assert len(debezium) == 1
    gradle_ref = gradle[0]["ref"]
    assert readme.count(gradle_ref) == 3
    assert values["debeziumVersion"] == debezium[0]["version"]

    qdrant_version = re.search(r"^ARG QDRANT_CONNECTOR_VERSION=(\S+)$", dockerfile, re.MULTILINE)
    qdrant_digest = re.search(r"^ARG QDRANT_CONNECTOR_SHA256=(\S+)$", dockerfile, re.MULTILINE)
    assert qdrant_version
    assert qdrant_digest
    assert values["qdrantKafkaVersion"] == qdrant_version[1]
    assert _SHA256.fullmatch(qdrant_digest[1])
    assert dockerfile.index("sha256sum --check --strict qdrant-kafka.sha256") > dockerfile.index(
        "qdrant-kafka-${QDRANT_CONNECTOR_VERSION}.zip"
    )


def test_strimzi_and_kafka_versions_are_aligned() -> None:
    chart = _load_yaml(_ROOT / "infra/k8s/helm/Chart.yaml")
    lock = _load_yaml(_ROOT / "infra/k8s/helm/Chart.lock")
    for metadata in (chart, lock):
        strimzi = next(
            dependency for dependency in metadata["dependencies"] if dependency["name"] == "strimzi-kafka-operator"
        )
        assert strimzi["version"] == "1.1.0"

    values = _load_yaml(_HELM_VALUES)
    local = _load_yaml(_ROOT / "infra/k8s/helm/values.local.yaml")
    assert values["global"]["kafka"]["version"] == "4.3.0"
    assert values["kafkaCluster"]["version"] == "4.3.0"
    assert local["global"]["kafka"]["version"] == "4.3.0"
    assert local["kafkaCluster"]["version"] == "4.3.0"
    template = _read_text(_ROOT / "infra/k8s/helm/templates/strimzi-kafka-connect.yaml")
    assert '$glob.kafka.version | default "4.3.0"' in template


def test_dependabot_covers_every_active_dependency_ecosystem_and_root() -> None:
    entries = _dependabot_entries()
    required = {
        "github-actions",
        "uv",
        "npm",
        "docker",
        "docker-compose",
        "helm",
        "terraform",
    }
    assert required <= entries.keys()

    assert _configured_directories(entries["github-actions"][0]) == ["."]
    assert _configured_directories(entries["npm"][0]) == ["."]

    root_project = tomllib.loads(_read_text(_ROOT_PROJECT))
    workspace_members = set(root_project["tool"]["uv"]["workspace"]["members"])
    all_python_roots = {
        str(path.parent.relative_to(_ROOT))
        for path in _ROOT.glob("**/pyproject.toml")
        if not any(part.startswith(".") or part == "node_modules" for part in path.relative_to(_ROOT).parts)
    }
    standalone_python_roots = all_python_roots - workspace_members - {"."}
    uv_patterns = [pattern for entry in entries["uv"] for pattern in _configured_directories(entry)]
    assert "." in uv_patterns
    assert not (
        uncovered_uv := sorted(root for root in standalone_python_roots if not _is_covered(root, uv_patterns))
    ), f"Dependabot uv coverage is missing standalone projects: {uncovered_uv}"

    docker_roots = {
        str(path.parent.relative_to(_ROOT))
        for path in [
            *_ROOT.glob("backend/services/*/Dockerfile"),
            *_ROOT.glob("backend/jobs/*/Dockerfile"),
            _KAFKA_DOCKERFILE,
            _ROOT / "infra" / "shared" / "qdrant-init" / "Dockerfile",
        ]
    }
    docker_patterns = [pattern for entry in entries["docker"] for pattern in _configured_directories(entry)]
    assert docker_roots
    assert not (uncovered := sorted(root for root in docker_roots if not _is_covered(root, docker_patterns))), (
        f"Dependabot docker coverage is missing: {uncovered}"
    )

    ecosystem_roots = {
        "docker-compose": {
            str(path.parent.relative_to(_ROOT)) for path in (_ROOT / "infra" / "compose").glob("docker-compose*.yml")
        },
        "helm": {str((_ROOT / "infra" / "k8s" / "helm").relative_to(_ROOT))},
        "terraform": {str(path.parent.relative_to(_ROOT)) for path in (_ROOT / "infra" / "terraform").glob("*.tf")},
    }
    for ecosystem, roots in ecosystem_roots.items():
        patterns = [pattern for entry in entries[ecosystem] for pattern in _configured_directories(entry)]
        assert roots
        assert all(_is_covered(root, patterns) for root in roots), (
            f"{ecosystem}: roots={sorted(roots)}, patterns={patterns}"
        )


def test_dependabot_batches_every_ecosystem_on_the_same_weekly_schedule() -> None:
    entries = _dependabot_entries()
    updates = [update for ecosystem_entries in entries.values() for update in ecosystem_entries]
    assert updates

    for update in updates:
        assert update["schedule"] == {"interval": "weekly", "day": "monday"}
        assert update["rebase-strategy"] == "disabled"
        groups = update["groups"]
        assert len(groups) == 1
        assert next(iter(groups.values())) == {"patterns": ["*"]}


def test_remote_kubernetes_manifests_are_versioned_and_checksum_verified_before_apply() -> None:
    installers = sorted((_ROOT / "infra" / "k8s").glob("*/install/*.sh"))
    remote_installers = []
    for installer in installers:
        script = _read_text(installer)
        urls = re.findall(
            r'^readonly ([A-Z0-9_]+)_URL="(https://[^"\n]+\.yaml)"$',
            script,
            re.MULTILINE,
        )
        if not urls:
            continue
        remote_installers.append(installer)
        for prefix, url in urls:
            version_names = re.findall(r"\$\{([A-Z0-9_]+_VERSION)\}", url)
            checksum_name = f"{prefix}_SHA256"
            checksum = re.search(rf'^readonly {checksum_name}="([0-9a-f]+)"$', script, re.MULTILINE)
            assert len(version_names) == 1, f"{installer}: manifest URL must contain one version pin"
            version = re.search(rf'^readonly {version_names[0]}="([^"]+)"$', script, re.MULTILINE)
            assert version, f"{installer}: manifest URL has no version declaration"
            assert checksum, f"{installer}: missing SHA-256 declaration"
            assert _SHA256.fullmatch(checksum[1]), f"{installer}: missing exact SHA-256"
            verify = script.index(f'"${{{checksum_name}}}"')
            apply_command = re.search(r"^kubectl apply\b", script, re.MULTILINE)
            assert apply_command, f"{installer}: downloaded manifest is never applied"
            apply = apply_command.start()
            assert verify < apply, f"{installer}: manifest is applied before checksum verification"
