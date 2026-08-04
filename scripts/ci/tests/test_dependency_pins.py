from __future__ import annotations

import json
import re
import shlex
import subprocess
import tomllib
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import cast

from _documents import WorkflowJob, WorkflowStep, load_jsonc, load_mapping, load_workflow

_ROOT = Path(__file__).resolve().parents[3]
_RENOVATE = _ROOT / ".github" / "renovate.json5"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_WORKFLOWS = _ROOT / ".github" / "workflows"
_SETUP_CI = _ROOT / ".github" / "actions" / "setup-ci" / "action.yml"
_DEADCODE_SWEEP = _WORKFLOWS / "deadcode-sweep.yml"
_DIGEST_FRESHNESS = _WORKFLOWS / "digest-freshness.yml"
_AKS_DEPLOY = _WORKFLOWS / "cd_deploy-to-aks_nohiki.yml"
_WEEKLY_SWEEP = _WORKFLOWS / "weekly-sweep.yml"
_FLAKE = _ROOT / "flake.nix"
_UV_CONFIG = _ROOT / "toolchain" / "uv.toml"
_JUSTFILE = _ROOT / "Justfile"
_ROOT_PROJECT = _ROOT / "pyproject.toml"
_CI_PROJECT = _ROOT / "scripts" / "ci" / "pyproject.toml"
_SYNC_CI_ENVIRONMENT = _ROOT / "scripts" / "dev" / "sync-ci-environment.sh"
_SYNC_CI_DEADCODE = _ROOT / "scripts" / "dev" / "sync-ci-deadcode.sh"
_PACKAGE = _ROOT / "package.json"
_FRONTEND = _ROOT / "typescript" / "apps" / "frontend"
_FRONTEND_PACKAGE = _FRONTEND / "package.json"
_FRONTEND_DOCKERFILE = _FRONTEND / "Dockerfile"
_PLAYWRIGHT_RUNNER_DOCKERFILE = _FRONTEND / "Dockerfile.playwright-runner"
_SCAFFOLD_DOCKERFILE = (
    _ROOT / "scripts" / "util" / "scaffold" / "src" / "nohiki_scaffold" / "templates" / "service" / "Dockerfile.j2"
)
_KAFKA_DOCKERFILE = _ROOT / "infra" / "k8s" / "kafka-connect" / "Dockerfile"
_ML_COMPUTE_DOCKERFILE = _ROOT / "backend" / "services" / "ml-compute-service" / "Dockerfile"
_KAFKA_README = _KAFKA_DOCKERFILE.parent / "smt" / "README.md"
_HELM_VALUES = _ROOT / "infra" / "k8s" / "helm" / "values.yaml"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
# A digest-pinned helm tag keeps its version component: "<version>@sha256:<64 hex>".
_PINNED_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}@sha256:[0-9a-f]{64}")
_IMAGE = re.compile(
    r"(?:FROM |--from=)(?P<ref>(?P<repository>[^:@\s]+(?:/[^:@\s]+)*):"
    r"(?P<version>[^@\s]+)@sha256:(?P<digest>[0-9a-f]{64}))"
)
_ACTION_USE = re.compile(
    r"^\s*(?:-\s*)?uses:\s*(?P<action>[^@\s]+/[^@\s]+)@(?P<revision>[0-9a-f]{40})"
    r"\s+#\s+(?P<version>v\d+(?:\.\d+)*)\s*$"
)
_PINNED_NIX_INSTALLER = re.compile(r"^cachix/install-nix-action@[0-9a-f]{40}$")


@cache
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _workflow_jobs(path: Path) -> dict[str, WorkflowJob]:
    return load_workflow(path)["jobs"]


def _steps(job: WorkflowJob) -> list[WorkflowStep]:
    return job.get("steps", [])


def _setup_steps() -> list[WorkflowStep]:
    action = load_mapping(_SETUP_CI)
    runs = cast(dict[str, object], action["runs"])
    steps = runs["steps"]
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return cast(list[WorkflowStep], steps)


def test_all_workflow_actions_are_sha_pinned_with_version_comments() -> None:
    failures: list[str] = []
    pins_by_action: dict[str, set[str]] = {}
    workflow_paths = sorted((*_WORKFLOWS.glob("*.yml"), *_WORKFLOWS.glob("*.yaml")))
    action_paths = sorted(_ROOT.glob(".github/actions/*/action.yml"))
    checked_paths = (*workflow_paths, *action_paths)
    assert checked_paths, "no workflow or composite-action files discovered"

    for path in checked_paths:
        for line_number, line in enumerate(_read_text(path).splitlines(), start=1):
            if not re.match(r"^\s*(?:-\s*)?uses:", line):
                continue
            if "uses: ./" in line:
                continue
            match = _ACTION_USE.fullmatch(line)
            if match is None:
                failures.append(f"{path.relative_to(_ROOT)}:{line_number}: {line.strip()}")
                continue
            pins_by_action.setdefault(match["action"], set()).add(line[line.index("uses:") :])

    assert pins_by_action, "no external action references discovered"
    assert not failures, "workflow actions must use full SHA pins with version comments:\n" + "\n".join(failures)
    divergent = {action: sorted(pins) for action, pins in pins_by_action.items() if len(pins) != 1}
    assert not divergent, f"workflow action pins diverge by identity: {divergent}"


def test_nix_installers_share_the_canonical_bot_managed_pin() -> None:
    canonical = next(step for step in _setup_steps() if step.get("name") == "Install Nix").get("uses", "")
    assert _PINNED_NIX_INSTALLER.fullmatch(str(canonical))

    workflow_installers = {
        str(_DIGEST_FRESHNESS.relative_to(_ROOT)): next(
            step for step in _steps(_workflow_jobs(_DIGEST_FRESHNESS)["probe"]) if step.get("name") == "Install Nix"
        ).get("uses", ""),
        str(_AKS_DEPLOY.relative_to(_ROOT)): next(
            step for step in _steps(_workflow_jobs(_AKS_DEPLOY)["deploy-to-aks"]) if step.get("name") == "Install Nix"
        ).get("uses", ""),
    }
    assert workflow_installers == dict.fromkeys(workflow_installers, canonical)


def test_digest_freshness_keeps_only_the_nix_store_cache() -> None:
    steps = _steps(_workflow_jobs(_DIGEST_FRESHNESS)["probe"])
    by_name = {step.get("name"): step for step in steps}

    assert "Cache uv downloads" not in by_name
    assert "Cache workspace virtual environment" not in by_name
    assert not any(str(step.get("uses", "")).startswith("actions/cache@") for step in steps)

    nix_store = by_name["Cache nix store"]
    assert str(nix_store["uses"]).startswith("nix-community/cache-nix-action@")
    assert nix_store["with"]["gc-max-store-size-linux"] == "0"

    workspace_sync = by_name["Install workspace (all packages + extras)"]
    assert "if" not in workspace_sync


def test_workflow_checkouts_do_not_persist_credentials() -> None:
    workflow_paths = sorted((*_WORKFLOWS.glob("*.yml"), *_WORKFLOWS.glob("*.yaml")))
    missing = [
        f"{path.relative_to(_ROOT)}:{job_name}"
        for path in workflow_paths
        for job_name, job in _workflow_jobs(path).items()
        for step in _steps(job)
        if str(step.get("uses", "")).startswith("actions/checkout@")
        and step.get("with", {}).get("persist-credentials") is not False
    ]

    assert not missing, f"checkout credentials persisted in read-only jobs: {missing}"


def test_workflow_runner_labels_are_explicitly_versioned_or_approved_self_hosted() -> None:
    failures: list[str] = []
    workflow_paths = sorted((*_WORKFLOWS.glob("*.yml"), *_WORKFLOWS.glob("*.yaml")))
    for path in workflow_paths:
        for job_name, job in _workflow_jobs(path).items():
            runs_on = job.get("runs-on")
            if runs_on is None or runs_on == ["self-hosted", "linux", "x64", "nohiki"]:
                continue
            if isinstance(runs_on, str) and (
                re.fullmatch(r"\$\{\{.+}}", runs_on) or re.fullmatch(r"(?:ubuntu|windows|macos)-\d+(?:\.\d+)*", runs_on)
            ):
                continue
            failures.append(f"{path.relative_to(_ROOT)}:{job_name}: {runs_on!r}")

    assert not failures, "workflow runner labels must be versioned or approved self-hosted labels:\n" + "\n".join(
        failures
    )


@cache
def _python_dockerfiles() -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in _ROOT.glob("**/Dockerfile*")
            if path.is_file() and "ghcr.io/astral-sh/uv:" in _read_text(path)
        )
    )


def _images(path: Path, repository: str) -> list[re.Match[str]]:
    return [match for match in _IMAGE.finditer(_read_text(path)) if match["repository"] == repository]


def _renovate_config() -> dict[str, object]:
    return load_jsonc(_RENOVATE)


def _version_declarations(
    sources: tuple[tuple[Path, re.Pattern[str]], ...],
) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for path, pattern in sources:
        text = _read_text(path)
        for match in pattern.finditer(text):
            line_number = text.count("\n", 0, match.start("version")) + 1
            declarations[f"{path.relative_to(_ROOT)}:{line_number}"] = match["version"]
    return declarations


def _assert_duplicate_versions_aligned(
    dependency: str,
    sources: tuple[tuple[Path, re.Pattern[str]], ...],
) -> None:
    declarations = _version_declarations(sources)
    assert declarations, f"no {dependency} declarations discovered"
    locations_by_version: dict[str, list[str]] = {}
    for location, version in declarations.items():
        locations_by_version.setdefault(version, []).append(location)
    assert len(locations_by_version) == 1, f"duplicate {dependency} pins disagree: {locations_by_version}"


def test_duplicate_pnpm_declarations_stay_aligned() -> None:
    version = r"(?P<version>\d+\.\d+\.\d+)"
    _assert_duplicate_versions_aligned(
        "pnpm",
        (
            (_PACKAGE, re.compile(rf'"packageManager"\s*:\s*"pnpm@{version}"')),
            (_FRONTEND_DOCKERFILE, re.compile(rf"\bpnpm@{version}\b")),
            (_PLAYWRIGHT_RUNNER_DOCKERFILE, re.compile(rf"\bpnpm@{version}\b")),
            (_FLAKE, re.compile(rf'pname\s*=\s*"pnpm";\s*version\s*=\s*"{version}"')),
            (_FLAKE, re.compile(rf"registry\.npmjs\.org/pnpm/-/pnpm-{version}\.tgz")),
        ),
    )


def test_duplicate_playwright_declarations_stay_aligned() -> None:
    version = r"(?P<version>\d+\.\d+\.\d+)"
    _assert_duplicate_versions_aligned(
        "Playwright",
        (
            (_FRONTEND_PACKAGE, re.compile(rf'"@playwright/test"\s*:\s*"[~^]?{version}"')),
            (
                _PLAYWRIGHT_RUNNER_DOCKERFILE,
                re.compile(rf"mcr\.microsoft\.com/playwright:v{version}-[^@\s]+@sha256:[0-9a-f]{{64}}"),
            ),
        ),
    )


def _workspace_member_names() -> set[str]:
    with _ROOT_PROJECT.open("rb") as project_file:
        root_project = tomllib.load(project_file)

    member_patterns = root_project["tool"]["uv"]["workspace"]["members"]
    assert isinstance(member_patterns, list)
    assert all(isinstance(pattern, str) for pattern in member_patterns)
    member_projects = {
        member / "pyproject.toml" for pattern in member_patterns for member in _ROOT.glob(cast(str, pattern))
    }
    assert all(project.is_file() for project in member_projects)

    names: set[str] = set()
    for member_project in member_projects:
        with member_project.open("rb") as project_file:
            name = tomllib.load(project_file)["project"]["name"]
        assert isinstance(name, str)
        names.add(name)

    assert len(names) == len(member_projects), "uv workspace package names must be unique"
    return names


def test_renovate_disables_workspace_and_fixed_skylos_lookups() -> None:
    rules = _renovate_config()["packageRules"]
    assert isinstance(rules, list)
    typed_rules = [rule for rule in rules if isinstance(rule, dict)]
    assert len(typed_rules) == len(rules)

    pypi_rules = [
        rule for rule in typed_rules if rule.get("enabled") is False and rule.get("matchDatasources") == ["pypi"]
    ]
    assert len(pypi_rules) == 1
    package_names = pypi_rules[0].get("matchPackageNames")
    assert isinstance(package_names, list)
    assert all(isinstance(name, str) for name in package_names)

    workspace_names = _workspace_member_names()
    configured_names = set(cast(list[str], package_names))
    assert configured_names == workspace_names, (
        f"workspace PyPI lookup rule is missing {sorted(workspace_names - configured_names)} "
        f"and has stale names {sorted(configured_names - workspace_names)}"
    )

    assert any(
        rule.get("enabled") is False
        and rule.get("matchDatasources") == ["git-refs"]
        and rule.get("matchPackageNames") == ["ssh://git@github.com/mchar7/skylos"]
        for rule in typed_rules
    )


def test_renovate_abandonment_suppression_is_limited_to_verified_false_positives() -> None:
    rules = _renovate_config()["packageRules"]
    assert isinstance(rules, list)
    threshold_rules = [rule for rule in rules if isinstance(rule, dict) and "abandonmentThreshold" in rule]
    assert len(threshold_rules) == 2

    finished_rules = [rule for rule in threshold_rules if rule.get("abandonmentThreshold") is None]
    finite_rules = [rule for rule in threshold_rules if rule.get("abandonmentThreshold") == "4 years"]
    assert len(finished_rules) == 1
    assert len(finite_rules) == 1

    finished_package_names = finished_rules[0].get("matchPackageNames")
    finite_package_names = finite_rules[0].get("matchPackageNames")
    assert isinstance(finished_package_names, list)
    assert isinstance(finite_package_names, list)
    assert all(isinstance(name, str) for name in [*finished_package_names, *finite_package_names])

    configured_finished_names = set(cast(list[str], finished_package_names))
    configured_finite_names = set(cast(list[str], finite_package_names))
    assert len(configured_finished_names) == len(finished_package_names)
    assert len(configured_finite_names) == len(finite_package_names)
    assert configured_finished_names == {
        "@codemirror/theme-one-dark",
        "clsx",
    }
    assert configured_finite_names == {
        "@dnd-kit/core",
        "@dnd-kit/sortable",
        "@dnd-kit/utilities",
        "@testing-library/user-event",
        "argon2-cffi",
        "class-variance-authority",
        "cmdk",
        "html2text",
        "jinja2",
        "pytest-timeout",
        "pytest-xdist",
        "python-jobspy",
        "semver",
        "vitest-axe",
    }
    suppressed_names = configured_finished_names | configured_finite_names
    assert suppressed_names.isdisjoint({"@microlabs/otel-cf-workers", "file-saver"})


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

    install_step = next(step for step in _setup_steps() if step.get("name") == "Install workspace (CI closure)")
    assert install_step["env"] == {"PAYLOAD": "${{ inputs.payload }}"}
    assert install_step["run"] == ('nix develop .#ci --command scripts/dev/sync-ci-environment.sh "$PAYLOAD"')
    ci_sync = _read_text(_SYNC_CI_ENVIRONMENT).replace("\\\n", " ")
    hosted_syncs: dict[str, list[str]] = {}
    for payload in ("python", "full"):
        branch = re.search(
            rf"^\s*{payload}\)\n(?P<body>.*?)(?=^\s*(?:python|full|\*)\))",
            ci_sync,
            re.MULTILINE | re.DOTALL,
        )
        assert branch, payload
        sync_line = next(line for line in branch["body"].splitlines() if "uv sync" in line)
        hosted_syncs[payload] = shlex.split(sync_line[sync_line.index("uv sync") :])
    assert hosted_syncs == {
        "python": [
            "uv",
            "sync",
            "--locked",
            "--all-packages",
            "--no-default-groups",
            "--group",
            "ci",
            "--no-install-package",
            "skylos",
            "-q",
        ],
        "full": [
            "uv",
            "sync",
            "--locked",
            "--package",
            "nohiki-monorepo",
            "--package",
            "ci-checks",
            "--package",
            "bff-service",
            "--package",
            "user-auth-service",
            "--no-default-groups",
            "--group",
            "ci",
            "--group",
            "deadcode",
            "--no-install-package",
            "skylos",
            "-q",
        ],
    }
    deadcode_sync_lines = _read_text(_SYNC_CI_DEADCODE).replace("\\\n", " ").splitlines()
    deadcode_sync = next(line[line.index("uv sync") :] for line in deadcode_sync_lines if "uv sync" in line)
    assert shlex.split(deadcode_sync) == [
        "uv",
        "sync",
        "--locked",
        "--package",
        "nohiki-monorepo",
        "--package",
        "ci-checks",
        "--package",
        "bff-service",
        "--package",
        "user-auth-service",
        "--no-default-groups",
        "--group",
        "ci",
        "--group",
        "deadcode",
        "-q",
    ]
    for command in (*flake_syncs, *just_syncs):
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
            "--no-default-groups",
            "--group",
            "dev",
            "--locked",
            "--dry-run",
        ],
        cwd=_ROOT,
        check=True,
    )


def test_ci_checks_container_test_group_covers_configured_pytest_runtime() -> None:
    with _CI_PROJECT.open("rb") as project_file:
        project = tomllib.load(project_file)

    assert project["dependency-groups"]["container-tests"] == [
        "pytest>=9.0.0",
        "pytest-asyncio>=1.3.0",
        "pytest-xdist>=3.8.0",
    ]


def test_root_lint_group_is_the_minimal_ruff_environment() -> None:
    with _ROOT_PROJECT.open("rb") as project_file:
        project = tomllib.load(project_file)

    assert project["dependency-groups"]["lint"] == ["ruff>=0.15.0"]


def test_complete_environment_uses_one_reconciled_cache_entry_per_payload() -> None:
    steps = _setup_steps()
    by_name = {step.get("name"): step for step in steps}
    restore = by_name["Restore complete CI environment"]
    sync = by_name["Install workspace (CI closure)"]
    node_install = by_name["Install Node dependencies"]
    save = by_name["Save complete CI environment"]

    restore_action, restore_separator, restore_ref = str(restore["uses"]).partition("@")
    save_action, save_separator, save_ref = str(save["uses"]).partition("@")
    assert (restore_action, save_action) == (
        "nix-community/cache-nix-action/restore",
        "nix-community/cache-nix-action/save",
    )
    assert restore_separator == save_separator == "@"
    assert restore_ref == save_ref
    # Two cache families, with the Python family split by payload. Python entries turn over on
    # flake/uv inputs and Node entries on pnpm inputs, so lanes restore only what they can invalidate.
    # Every input must still key exactly one entry: an input in neither goes stale unnoticed,
    # and one in both reinstates the coupling the split exists to remove.
    node_restore = by_name["Restore Node modules"]
    key = str(restore["with"]["primary-key"])
    node_key = str(node_restore["with"]["key"])
    payload_key_component = "${{ inputs.payload }}"
    assert payload_key_component in key
    assert payload_key_component in str(save["with"]["primary-key"])
    python_identity = (
        "flake.nix",
        "flake.lock",
        "uv.lock",
        "**/pyproject.toml",
        ".python-version",
        "scripts/dev/sync-ci-environment.sh",
    )
    node_identity = (
        "pnpm-lock.yaml",
        "pnpm-workspace.yaml",
        "package.json",
        "typescript/**/package.json",
    )
    for identity_input in python_identity:
        assert identity_input in key, identity_input
        assert identity_input not in node_key, identity_input
    for identity_input in node_identity:
        assert identity_input in node_key, identity_input
        assert identity_input not in key, identity_input
    # The composite's own text keys both: a change to either restore invalidates what it restores.
    assert ".github/actions/setup-ci/action.yml" in key
    assert ".github/actions/setup-ci/action.yml" in node_key
    assert "github.sha" not in key
    assert "github.sha" not in node_key
    lookup = by_name["Look up complete CI environment"]
    payload_prefix = "ci-ready-v1-${{ runner.os }}-${{ runner.arch }}-${{ inputs.payload }}-"
    assert restore["with"]["restore-prefixes-first-match"] == payload_prefix
    assert save["with"]["purge-prefixes"] == payload_prefix
    assert lookup["uses"] == restore["uses"]
    assert lookup["with"]["primary-key"] == restore["with"]["primary-key"]
    assert lookup["with"]["paths"] == restore["with"]["paths"]
    assert lookup["with"]["lookup-only"] is True

    # Each provisioning step is gated on the miss of the entry that would have supplied it, so
    # a hit on one entry never suppresses work the other entry failed to deliver.
    python_miss = "steps.ready-cache.outputs.hit-primary-key != 'true'"
    node_miss = "steps.node-modules-cache.outputs.cache-hit != 'true'"
    assert python_miss in str(sync["if"])
    assert python_miss in str(save["if"])
    assert node_miss in str(node_install["if"])
    assert node_miss in str(by_name["Save Node modules"]["if"])

    # A restored store still needs its bin directories on PATH: the consumers call the shell's
    # tools bare, and no cache entry carries a PATH. So the export runs on a hit as well.
    path_export = [step for step in steps if "PATH=%s" in str(step.get("run", ""))]
    assert len(path_export) == 1
    assert python_miss not in str(path_export[0]["if"])
    assert '"$(nix develop .#ci --command printenv PATH)" >> "$GITHUB_ENV"' in str(path_export[0]["run"])

    # The devShell out-link is what store collection is allowed to keep, so only the writer
    # needs it, and only when it is about to build and save a store.
    rooting = [step for step in steps if "--out-link" in str(step.get("run", ""))]
    assert len(rooting) == 1
    assert 'nix build .#devShells.x86_64-linux.ci --out-link "$RUNNER_TEMP/ci-shell"' in str(rooting[0]["run"])
    assert "inputs.save-ready-cache == 'true'" in str(rooting[0]["if"])
    assert python_miss in str(rooting[0]["if"])
    sync_command = str(sync["run"])
    assert "nix develop .#ci --command scripts/dev/sync-ci-environment.sh" in sync_command
    # The shared entry is restorable by any pull request from its base branch and no credential
    # is needed for that, so the closure it stores must hold no private source and the step that
    # builds it must hold no credential. Only `skylos` is private; its 32 public dependencies stay
    # in the shared closure so the private step has nothing left to fetch but the fork itself.
    assert "GIT_SSH_COMMAND" not in sync_command
    assert "SKYLOS" not in str(sync.get("env", {}))
    assert "--no-install-package skylos" in _read_text(_SYNC_CI_ENVIRONMENT)
    assert "--no-install-package" not in _read_text(_SYNC_CI_DEADCODE)
    skylos_install = by_name["Install Skylos from the pinned private fork"]
    assert steps.index(skylos_install) > steps.index(save)
    assert skylos_install["if"] == "inputs.skylos-cache == 'true'"
    skylos_command = str(skylos_install["run"])
    assert "nix develop .#ci --command scripts/dev/sync-ci-deadcode.sh" in skylos_command
    assert "trap 'rm -f" in skylos_command
    assert "GIT_SSH_COMMAND=" in skylos_command
    assert "GITHUB_ENV" not in skylos_command
    # A lane selected for the scan with no key configured must fail here, not at scanner spawn.
    assert 'test -n "$SKYLOS_DEPLOY_KEY"' in skylos_command
    secret_steps = [step for step in steps if "SKYLOS_DEPLOY_KEY" in str(step.get("env", {}))]
    assert secret_steps == [skylos_install]
    assert skylos_install["env"] == {"SKYLOS_DEPLOY_KEY": "${{ inputs.skylos-deploy-key }}"}
    assert all(
        "$RUNNER_TEMP/skylos_key" not in str(step.get("run", "")) for step in steps if step is not skylos_install
    )
    node_save = by_name["Save Node modules"]
    # Each entry is saved on its own producer succeeding. Coupling them would let a failed pnpm
    # install withhold a perfectly good store, which is what the split exists to stop.
    assert save["with"]["primary-key"] == restore["with"]["primary-key"]
    assert "steps.workspace-sync.outcome == 'success'" in str(save["if"])
    assert "steps.node-install.outcome == 'success'" not in str(save["if"])
    assert "steps.node-install.outcome == 'success'" in str(node_save["if"])
    assert "steps.workspace-sync.outcome == 'success'" not in str(node_save["if"])
    assert save["with"]["paths"] == restore["with"]["paths"]
    assert node_save["with"]["key"] == "${{ steps.node-modules-cache.outputs.cache-primary-key }}"
    assert node_save["with"]["path"] == node_restore["with"]["path"]

    names = {step.get("name") for step in steps}
    assert "Cache uv downloads" not in names
    assert "Restore workspace virtual environment" not in names
    assert "Cache lint virtual environment" not in names


def test_setup_cache_telemetry_uses_restore_outputs_and_matched_keys() -> None:
    action = load_mapping(_SETUP_CI)
    outputs = cast(dict[str, object], action["outputs"])
    assert outputs["cache-telemetry"] == {
        "description": "Observed cache outcomes and the keys that supplied restored content.",
        "value": "${{ steps.cache-telemetry.outputs.summary }}",
    }

    by_name = {step.get("name"): step for step in _setup_steps()}
    pnpm_restore = by_name["Restore pnpm store"]
    pnpm_save = by_name["Save pnpm store"]
    telemetry = by_name["Record observed cache outcomes"]
    assert str(pnpm_restore["uses"]).startswith("actions/cache/restore@")
    assert str(pnpm_save["uses"]).startswith("actions/cache/save@")
    assert pnpm_save["with"]["key"] == "${{ steps.pnpm-cache.outputs.cache-primary-key }}"

    env = telemetry["env"]
    assert env["READY_PARTIAL"] == "${{ steps.ready-cache.outputs.hit-first-match }}"
    assert "outputs.restored-key" in str(env["READY_KEY"])
    assert env["PNPM_KEY"] == "${{ steps.pnpm-cache.outputs.cache-matched-key }}"
    assert env["SKYLOS_KEY"] == "${{ steps.skylos-cache.outputs.cache-matched-key }}"
    command = str(telemetry["run"])
    for outcome in ("hit:", "partial:", "miss:none", "not-used:none"):
        assert outcome in command


def test_python_lint_steps_use_the_complete_workspace_environment() -> None:
    steps = _steps(_workflow_jobs(_CHECKS)["worker"])
    for step_name in ("Lint Python", "Check Python formatting"):
        lint_step = next(step for step in steps if step.get("name") == step_name)
        command = str(lint_step["run"])
        assert "export UV_PROJECT_ENVIRONMENT=.venv" in command
        assert ".venv-lint" not in command
        assert "uv run --no-sync" in command
        assert "ruff" in command


def test_worker_uses_the_pinned_skylos_fork_and_static_cache_identity() -> None:
    with _CI_PROJECT.open("rb") as project_file:
        project = tomllib.load(project_file)
    assert project["dependency-groups"]["deadcode"] == ["skylos==4.30.0"]
    assert project["tool"]["uv"]["sources"]["skylos"] == {
        "git": "ssh://git@github.com/mchar7/skylos",
        "rev": "32d0d3dd1eaa97595d45e83a08d7813eeac099a4",
    }

    with (_ROOT / "uv.lock").open("rb") as lock_file:
        lock = tomllib.load(lock_file)
    skylos = next(package for package in lock["package"] if package["name"] == "skylos")
    assert skylos["source"]["git"] == (
        "ssh://git@github.com/mchar7/skylos"
        "?rev=32d0d3dd1eaa97595d45e83a08d7813eeac099a4"
        "#32d0d3dd1eaa97595d45e83a08d7813eeac099a4"
    )

    setup_steps = _setup_steps()
    identity = next(step for step in setup_steps if step.get("name") == "Resolve Skylos cache identity")
    assert identity["env"] == {
        "BASE_SHA": "${{ inputs.base-sha }}",
        "HEAD_SHA": "${{ inputs.head-sha }}",
    }
    identity_command = str(identity["run"])
    assert 'git rev-parse --verify "${HEAD_SHA}^{tree}"' in identity_command
    assert 'git diff --name-only --no-renames "${BASE_SHA}..${HEAD_SHA}"' in identity_command
    assert "git hash-object --stdin" in identity_command

    restore = next(step for step in setup_steps if step.get("name") == "Restore Skylos static analysis cache")
    cache_inputs = cast(dict[str, object], restore["with"])
    assert cache_inputs["path"] == "${{ github.workspace }}/.skylos"
    key = str(cache_inputs["key"])
    assert key.startswith("skylos-static-v4-")
    reusability_fields = set(re.findall(r"\$\{\{\s*(.*?)\s*\}\}", key))
    assert reusability_fields == {
        "runner.os",
        "hashFiles('uv.lock')",
        "inputs.commit-class",
        "steps.skylos-cache-identity.outputs.scope-paths",
        "steps.skylos-cache-identity.outputs.head-tree",
    }
    per_commit_identifiers = (
        "github.sha",
        "github.event.before",
        "github.event.pull_request.base.sha",
        "inputs.base-sha",
        "inputs.head-sha",
    )
    assert all(identifier not in key for identifier in per_commit_identifiers)
    assert "restore-keys" not in cache_inputs
    assert str(restore["uses"]).startswith("actions/cache/restore@")

    worker = _workflow_jobs(_CHECKS)["worker"]
    setup = next(step for step in _steps(worker) if str(step.get("uses", "")).startswith("./.github/actions/setup-ci"))
    assert setup["with"]["commit-class"] == ("${{ needs.changes.outputs.commit_class }}")
    save = next(step for step in _steps(worker) if step.get("name") == "Save Skylos static analysis cache")
    assert str(save["uses"]).startswith("actions/cache/save@")


def test_ci_workflow_syncs_enforce_the_lock_without_frozen_aliases() -> None:
    sync_lines = [
        line.strip()
        for workflow_path in sorted(_WORKFLOWS.glob("*.yml"))
        for line in _read_text(workflow_path).splitlines()
        if "uv sync" in line
    ]

    assert sync_lines
    assert all("--locked" in line for line in sync_lines)
    assert all("--frozen" not in line for line in sync_lines)


def test_periodic_hygiene_workflows_are_absent() -> None:
    assert not _WEEKLY_SWEEP.exists()
    assert not _DEADCODE_SWEEP.exists()


def test_checks_jobs_have_bounded_guards() -> None:
    timeouts = {job_name: job.get("timeout-minutes") for job_name, job in _workflow_jobs(_CHECKS).items()}
    derived = "${{ fromJSON(needs.changes.outputs.worker_timeout_minutes) }}"
    for job_name in ("worker",):
        assert timeouts[job_name] == derived

    invalid = {
        job_name: timeout
        for job_name, timeout in timeouts.items()
        if timeout != derived and (not isinstance(timeout, int) or not 0 < timeout <= 30)
    }
    assert not invalid, f"checks jobs must have bounded timeout-minutes: {invalid}"


def test_codeql_private_phase_trigger_contract() -> None:
    workflow = load_workflow(_ROOT / ".github" / "workflows" / "codeql.yml")
    triggers = workflow.get("on")
    assert triggers == {
        "push": {"branches": ["main"]},
        "pull_request": {"branches": ["main"]},
        "workflow_dispatch": None,
    }, (
        "P7 public cutover must restore the weekly schedule alongside the "
        "push, pull_request, and workflow_dispatch triggers"
    )


def test_codeql_analysis_requires_public_repository_payload() -> None:
    analyze = _workflow_jobs(_ROOT / ".github" / "workflows" / "codeql.yml")["analyze"]
    assert analyze["if"] == ("${{ github.event.repository && github.event.repository.private == false }}")


def test_codeql_sarif_permissions_are_least_privilege() -> None:
    workflow = load_workflow(_ROOT / ".github" / "workflows" / "codeql.yml")
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["analyze"]["permissions"] == {
        "actions": "read",
        "contents": "read",
        "security-events": "write",
    }


def test_python_and_uv_container_pins_match_scaffold_ci_and_nix() -> None:
    dockerfiles = _python_dockerfiles()
    assert dockerfiles, "no uv-bearing Dockerfiles discovered"

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
        uv_pins = [(match["version"], match["digest"]) for match in uv_images]
        if not uv_pins or any(pin != expected_uv for pin in uv_pins):
            mismatches.append(f"{dockerfile.relative_to(_ROOT)}: uv images do not match scaffold")
    assert not mismatches, "\n".join(mismatches)

    assert "env" not in load_workflow(_CHECKS), "checks.yml must not re-pin toolchain versions beside uv.toml"
    python_version = expected_python[0].removesuffix("-slim")

    root_project = tomllib.loads(_read_text(_ROOT_PROJECT))
    python_minor = ".".join(python_version.split(".")[:2])
    assert root_project["project"]["requires-python"] == f">={python_minor}"
    assert tomllib.loads(_read_text(_ROOT / "uv.lock"))["requires-python"] == f">={python_minor}"

    uv_config = tomllib.loads(_read_text(_UV_CONFIG))
    uv_version = uv_config.get("required-version")
    assert isinstance(uv_version, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", uv_version)
    assert uv_config == {"required-version": uv_version}
    assert expected_uv[0] == uv_version

    flake = _read_text(_FLAKE)
    assert "uvConfig = builtins.fromTOML (builtins.readFile ./toolchain/uv.toml);" in flake
    assert "value = uvConfig.required-version;" in flake
    assert 'uvVersion = "' not in flake
    expected_uv_url = (
        'url = "https://github.com/astral-sh/uv/releases/download/${uvVersion}/uv-${uvRelease.target}.tar.gz";'
    )
    assert expected_uv_url in flake
    nix_digests = re.findall(r'sha256 = "([0-9a-f]+)";', flake)
    assert len(nix_digests) == 4
    assert all(_SHA256.fullmatch(digest) for digest in nix_digests)


def test_node_and_pnpm_toolchains_match_ci_nix_and_project_metadata() -> None:
    jobs = _workflow_jobs(_CHECKS)
    changes_steps = _steps(jobs["changes"])
    assert not any(step.get("name") == "Install Nix" for step in changes_steps)

    setup_uv = next(step for step in changes_steps if step.get("name") == "Set up uv and Python")
    setup_pnpm = next(step for step in _setup_steps() if step.get("name") == "Install pnpm")
    setup_node = next(step for step in _setup_steps() if step.get("name") == "Set up Node")
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
    assert setup_node["with"] == {"node-version": node_floor}
    setup_steps = _setup_steps()
    names = [step.get("name") for step in setup_steps]
    resolver_index = names.index("Resolve pnpm store path")
    restore_index = names.index("Restore pnpm store")
    install_index = names.index("Install Node dependencies")
    save_index = names.index("Save pnpm store")
    assert names.index("Set up Node") < resolver_index < restore_index < install_index < save_index
    expected_pnpm_cache = setup_steps[restore_index]
    assert str(expected_pnpm_cache["uses"]).startswith("actions/cache/restore@")
    assert expected_pnpm_cache["with"]["key"] == (
        "pnpm-v2-${{ runner.os }}-${{ runner.arch }}-${{ hashFiles('pnpm-lock.yaml') }}"
    )
    assert setup_node["with"] == {"node-version": node_floor}

    worker_setup = next(step for step in _steps(jobs["worker"]) if step.get("name") == "Set up selected environments")
    assert worker_setup["uses"] == "./.github/actions/setup-ci"
    assert worker_setup["with"]["node"] == "${{ env.NODE_SETUP_SELECTED }}"
    uv_version_file = "toolchain/uv.toml"
    python_version = _images(_SCAFFOLD_DOCKERFILE, "public.ecr.aws/docker/library/python")[0]["version"]
    assert setup_uv["with"] == {
        "version-file": uv_version_file,
        "python-version": python_version.removesuffix("-slim"),
        "enable-cache": True,
        "cache-dependency-glob": "uv.lock",
    }

    workflow_paths = sorted((*_WORKFLOWS.glob("*.yml"), *_WORKFLOWS.glob("*.yaml")))
    uv_installers: list[tuple[Path, str, list[WorkflowStep], int]] = []
    for path in workflow_paths:
        assert "UV_VERSION" not in _read_text(path), f"{path.relative_to(_ROOT)} must not declare UV_VERSION"
        for job_name, job in _workflow_jobs(path).items():
            steps = _steps(job)
            uv_installers.extend(
                (path, job_name, steps, index)
                for index, step in enumerate(steps)
                if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
            )

    assert uv_installers, "no workflow uv installers discovered"
    for path, job_name, steps, setup_index in uv_installers:
        setup_step = steps[setup_index]
        location = f"{path.relative_to(_ROOT)}:{job_name}"
        setup_inputs = setup_step.get("with", {})
        assert setup_inputs.get("version-file") == uv_version_file, location
        assert "version" not in setup_inputs, location
        assert setup_inputs.get("enable-cache") is True, location
        assert setup_inputs.get("cache-dependency-glob") == "uv.lock", location
        assert any(
            index < setup_index and str(step.get("uses", "")).startswith("actions/checkout@")
            for index, step in enumerate(steps)
        ), location
        assert not any(step.get("id") == "uv-version" for step in steps), location


def test_kafka_connect_build_and_remote_connector_pins_are_consistent() -> None:
    dockerfile = _read_text(_KAFKA_DOCKERFILE)
    readme = _read_text(_KAFKA_README)
    helm_values = load_mapping(_HELM_VALUES)
    kafka_connect = helm_values["kafkaConnect"]
    assert isinstance(kafka_connect, dict)
    values = kafka_connect.get("build")
    assert isinstance(values, dict)

    gradle = _images(_KAFKA_DOCKERFILE, "gradle")
    debezium = _images(_KAFKA_DOCKERFILE, "quay.io/debezium/connect")
    assert len(gradle) == 1
    assert len(debezium) == 1
    gradle_ref = gradle[0]["ref"]
    assert readme.count(gradle_ref) == 3
    assert values.get("debeziumVersion") == debezium[0]["version"]

    qdrant_version = re.search(r"^ARG QDRANT_CONNECTOR_VERSION=(\S+)$", dockerfile, re.MULTILINE)
    qdrant_digest = re.search(r"^ARG QDRANT_CONNECTOR_SHA256=(\S+)$", dockerfile, re.MULTILINE)
    assert qdrant_version
    assert qdrant_digest
    assert values.get("qdrantKafkaVersion") == qdrant_version[1]
    assert _SHA256.fullmatch(qdrant_digest[1])
    assert dockerfile.index("sha256sum --check --strict qdrant-kafka.sha256") > dockerfile.index(
        "qdrant-kafka-${QDRANT_CONNECTOR_VERSION}.zip"
    )


def test_strimzi_and_kafka_versions_are_aligned() -> None:
    chart = load_mapping(_ROOT / "infra/k8s/helm/Chart.yaml")
    lock = load_mapping(_ROOT / "infra/k8s/helm/Chart.lock")
    strimzi_versions: list[str] = []
    for metadata in (chart, lock):
        dependencies = metadata["dependencies"]
        assert isinstance(dependencies, list)
        assert all(isinstance(dependency, dict) for dependency in dependencies)
        strimzi = next(
            dependency
            for dependency in dependencies
            if isinstance(dependency, dict) and dependency.get("name") == "strimzi-kafka-operator"
        )
        version = strimzi.get("version")
        assert isinstance(version, str)
        strimzi_versions.append(version)
    assert len(set(strimzi_versions)) == 1

    values = load_mapping(_HELM_VALUES)
    local = load_mapping(_ROOT / "infra/k8s/helm/values.local.yaml")
    for document in (values, local):
        global_values = document["global"]
        assert isinstance(global_values, dict)
        kafka = global_values.get("kafka")
        assert isinstance(kafka, dict)
        kafka_cluster = document["kafkaCluster"]
        assert isinstance(kafka_cluster, dict)
        assert kafka.get("version") == "4.3.0"
        assert kafka_cluster.get("version") == "4.3.0"
    template = _read_text(_ROOT / "infra/k8s/helm/templates/strimzi-kafka-connect.yaml")
    assert '$glob.kafka.version | default "4.3.0"' in template


def test_renovate_covers_required_dependency_ecosystems_and_policy() -> None:
    assert _RENOVATE.is_file()
    assert not (_ROOT / ".github" / "dependabot.yml").exists()

    config = _renovate_config()
    required_managers = {
        "npm",
        "pep621",
        "github-actions",
        "dockerfile",
        "docker-compose",
        "helmv3",
        "helm-values",
        "flux",
        "kubernetes",
        "nix",
        "custom.regex",
    }
    enabled_managers = config["enabledManagers"]
    assert isinstance(enabled_managers, list)
    assert all(isinstance(manager, str) for manager in enabled_managers)
    assert required_managers <= set(enabled_managers)
    assert config["nix"] == {"enabled": True}
    assert config["automerge"] is False
    assert config["minimumReleaseAge"] == "3 days"
    assert config["prConcurrentLimit"] == 2
    extends = config["extends"]
    assert isinstance(extends, list)
    assert all(isinstance(preset, str) for preset in extends)
    assert ":semanticCommitTypeAll(chore)" in extends
    assert config["ignorePaths"] == [
        "**/node_modules/**",
        "**/bower_components/**",
        "**/vendor/**",
        "**/examples/**",
        "**/__tests__/**",
        "**/test/**",
        "**/tests/**/!(Dockerfile.api-runner)",
        "**/__fixtures__/**",
    ]
    helm_values_manager = config["helm-values"]
    assert isinstance(helm_values_manager, dict)
    assert helm_values_manager.get("managerFilePatterns") == [
        r"/^infra\/k8s\/.+\/values\.ya?ml$/",
        r"/^infra\/k8s\/helm\/values\.local\.ya?ml$/",
    ]
    # A manager block is merged into the dependency config before packageRules run, so pinDigests declared
    # there cannot override docker:pinDigests inherited from config:best-practices.
    assert "pinDigests" not in helm_values_manager
    custom_managers = config["customManagers"]
    assert isinstance(custom_managers, list)
    assert all(isinstance(manager, dict) for manager in custom_managers)
    custom_by_dependency = {
        manager.get("depNameTemplate"): manager for manager in custom_managers if isinstance(manager, dict)
    }
    assert set(custom_by_dependency) == {"pnpm", "@playwright/test"}
    for manager in custom_by_dependency.values():
        assert manager.get("customType") == "regex"
        assert manager.get("datasourceTemplate") == "npm"
        assert isinstance(manager.get("managerFilePatterns"), list)
        match_strings = manager.get("matchStrings")
        assert isinstance(match_strings, list)
        assert match_strings
        assert all(isinstance(pattern, str) and "(?<currentValue>" in pattern for pattern in match_strings)

    rules = config["packageRules"]
    assert isinstance(rules, list)
    assert all(isinstance(rule, dict) for rule in rules)
    major_rule = next(rule for rule in rules if isinstance(rule, dict) and rule.get("matchUpdateTypes") == ["major"])
    assert major_rule.get("dependencyDashboardApproval") is True
    pin_rules = [rule for rule in rules if isinstance(rule, dict) and "pinDigests" in rule]
    assert len(pin_rules) == 1
    assert pin_rules[0].get("matchManagers") == ["helm-values"]
    assert pin_rules[0].get("pinDigests") is False
    parity_groups = {
        "pnpm": "pnpm version parity",
        "@playwright/test": "Playwright version parity",
    }
    for dependency, group_name in parity_groups.items():
        parity_rule = next(
            rule for rule in rules if isinstance(rule, dict) and rule.get("matchPackageNames") == [dependency]
        )
        assert parity_rule.get("groupName") == group_name

    grouped_ecosystems = (
        {"npm"},
        {"pep621"},
        {"github-actions"},
        {"dockerfile", "docker-compose"},
        {"helmv3", "helm-values", "flux", "kubernetes"},
        {"nix"},
    )
    for managers in grouped_ecosystems:
        rule = None
        for candidate in rules:
            assert isinstance(candidate, dict)
            match_managers = candidate.get("matchManagers", [])
            assert isinstance(match_managers, list)
            assert all(isinstance(manager, str) for manager in match_managers)
            if set(match_managers) == managers:
                rule = candidate
                break
        assert rule is not None
        match_update_types = rule.get("matchUpdateTypes")
        assert isinstance(match_update_types, list)
        assert all(isinstance(update_type, str) for update_type in match_update_types)
        assert {"minor", "patch"} <= set(match_update_types)
        assert rule.get("groupName")


def _helm_values_managed_files() -> list[Path]:
    """Files the Renovate `helm-values` manager matches, derived from that manager's own patterns."""
    manager = _renovate_config()["helm-values"]
    assert isinstance(manager, dict)
    patterns = manager.get("managerFilePatterns")
    assert isinstance(patterns, list)
    assert all(isinstance(pattern, str) for pattern in patterns)
    matchers = [re.compile(cast(str, pattern).strip("/")) for pattern in patterns]
    paths = [
        path
        for path in sorted((_ROOT / "infra" / "k8s").rglob("*.y*ml"))
        if any(matcher.search(path.relative_to(_ROOT).as_posix()) for matcher in matchers)
    ]
    assert paths, "no values files match the helm-values manager patterns"
    return paths


def _tagged_blocks(node: object, location: str) -> Iterator[tuple[str, dict[str, object]]]:
    if isinstance(node, dict):
        if "tag" in node:
            yield location or "<root>", cast(dict[str, object], node)
        for key, value in node.items():
            yield from _tagged_blocks(value, f"{location}.{key}" if location else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _tagged_blocks(value, f"{location}[{index}]")


def test_helm_values_image_tags_never_duplicate_a_sibling_digest_or_drop_their_version() -> None:
    """Guard the rendered shape, not the bot configuration, so a mispinned tag fails whatever pins it.

    Charts take either a self-contained `tag: <version>@sha256:<digest>` or a bare `tag:` beside a
    `digest:`/`sha:` key that the template appends itself. A digest written into the second shape's tag
    renders a double-digest reference, and a digest replacing the version renders a tag-less one.
    """
    failures: list[str] = []
    for path in _helm_values_managed_files():
        for location, block in _tagged_blocks(load_mapping(path), ""):
            tag = block.get("tag")
            if not isinstance(tag, str) or "@sha256:" not in tag:
                continue
            relative = path.relative_to(_ROOT)
            siblings = sorted(key for key in ("digest", "sha") if key in block)
            if siblings:
                failures.append(f"{relative}: {location}.tag carries a digest beside sibling {siblings}")
            if _PINNED_TAG.fullmatch(tag) is None:
                failures.append(f"{relative}: {location}.tag is not <version>@sha256:<digest>: {tag!r}")
    assert not failures, "\n".join(failures)


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
