"""Portable contracts for the one-time bootstrap and local lifecycle boundary.

Local Kubernetes operations have exactly seven public entrypoints:
``k8s-preflight-local``, ``k8s-bootstrap-local``,
``k8s-publish-local-images``, ``k8s-reconcile-local``, ``k8s-verify-local``,
``k8s-diagnostics-local``, and ``k8s-factory-reset-local``. Their shared
lifecycle authority is covered in
``scripts/ci/tests/test_local_lifecycle.py``; this module instead exercises
portable bootstrap boundaries that do not require a live cluster.

The bootstrap is a one-time operation with validate, dry-run, and execute
modes. It accepts only the reviewed local runtime-control identity, renders the
exact three-file Flux source in isolation, and refuses stale or ambiguous
state. Normal convergence belongs to the reconcile lifecycle command. Factory
reset confirmation is enforced after lifecycle dispatch by the reset authority,
not encoded into the Justfile delegation.

Run only these:
    uv run pytest infra/k8s/gitops/tests/test_portable_bootstrap.py -v
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
GITOPS_DIR = REPO_ROOT / "infra" / "k8s" / "gitops"
INSTALL_DIR = GITOPS_DIR / "install"
CLUSTERS_DIR = GITOPS_DIR / "clusters"
BOOTSTRAP_SCRIPT = INSTALL_DIR / "bootstrap.sh"
BOOTSTRAP_POLICY = INSTALL_DIR / "runtime-control-policy.sh"
SNAPSHOT_HELPER = INSTALL_DIR / "secure-snapshot.py"
LIFECYCLE_SCRIPT = REPO_ROOT / "infra" / "k8s" / "local" / "lifecycle.sh"
JUSTFILE = REPO_ROOT / "Justfile"
README = GITOPS_DIR / "README.md"
FLAKE = REPO_ROOT / "flake.nix"
RUNTIME_CONTROL_BRANCH = "runtime-control/local/portable-bootstrap"
DATA_LOSS_ACK = "I understand this permanently deletes local Nohiki data"

# The flux CLI is pinned in the flake devshell; nixpkgs (flake.lock) is the single
# source of truth for the version, so no volatile version literal lives in tracked docs.

# Bootstrap owner and repository coordinates stay operator-supplied. The
# runtime-control branch is independently bound to the reviewed local Git HEAD.


def _bootstrap() -> str:
    return BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")


def _justfile() -> str:
    return JUSTFILE.read_text(encoding="utf-8")


@dataclass(frozen=True)
class BootstrapSandbox:
    repo: Path
    script: Path
    calls: Path
    env: dict[str, str]


def _run(command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo: Path, *arguments: str) -> str:
    result = _run(["git", *arguments], cwd=repo, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\nset -eu\n{body}", encoding="utf-8")
    path.chmod(0o755)


def _bootstrap_sandbox(tmp_path: Path) -> BootstrapSandbox:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", RUNTIME_CONTROL_BRANCH)
    _git(repo, "config", "user.name", "Portable Bootstrap Test")
    _git(repo, "config", "user.email", "portable-bootstrap@example.invalid")

    install = repo / "infra" / "k8s" / "gitops" / "install"
    install.mkdir(parents=True)
    shutil.copy2(BOOTSTRAP_SCRIPT, install / BOOTSTRAP_SCRIPT.name)
    shutil.copy2(BOOTSTRAP_POLICY, install / BOOTSTRAP_POLICY.name)
    shutil.copy2(SNAPSHOT_HELPER, install / SNAPSHOT_HELPER.name)
    (repo / "infra" / "k8s" / "gitops" / "clusters" / "local").mkdir(parents=True)
    (repo / "reviewed.txt").write_text("reviewed bootstrap source\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "reviewed portable bootstrap source")
    reviewed_sha = _git(repo, "rev-parse", "HEAD")

    calls = tmp_path / "tool-calls.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "flux",
        """printf '%s\\n' "$*" >>"$BOOTSTRAP_CALLS"
case "$1 $2" in
  "install --export")
    [ "${FAKE_FLUX_MODE:-valid}" = missing-components ] ||
      printf 'apiVersion: v1\\nkind: List\\n'
    ;;
  "create source")
    printf 'apiVersion: source.toolkit.fluxcd.io/v1\\nkind: GitRepository\\n'
    ;;
  "create kustomization")
    printf '%s\\n' '---' 'apiVersion: kustomize.toolkit.fluxcd.io/v1' 'kind: Kustomization'
    ;;
  *) exit 64 ;;
esac
""",
    )
    for tool in ("kubectl", "pnpm", "age-keygen"):
        _write_executable(
            fake_bin / tool,
            f'printf \'{tool} %s\\n\' "$*" >>"$BOOTSTRAP_CALLS"\nexit 97\n',
        )

    environment = os.environ.copy()
    for name in ("GITHUB_REF", "GITHUB_REF_NAME", "GITHUB_HEAD_REF", "GITHUB_SHA"):
        environment.pop(name, None)
    environment |= {
        "PATH": f"{fake_bin}:{environment['PATH']}",
        "BOOTSTRAP_CALLS": str(calls),
        "NOHIKI_CLUSTER": "local",
        "NOHIKI_RUNTIME_CONTROL_BRANCH": RUNTIME_CONTROL_BRANCH,
        "NOHIKI_REVIEWED_TOPIC_SHA": reviewed_sha,
        "GITOPS_GITHUB_OWNER": "portable-owner",
        "GITOPS_GITHUB_REPOSITORY": "portable-repo",
    }
    return BootstrapSandbox(
        repo=repo,
        script=install / BOOTSTRAP_SCRIPT.name,
        calls=calls,
        env=environment,
    )


def _run_bootstrap(
    sandbox: BootstrapSandbox, mode: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return _run(
        ["bash", str(sandbox.script), mode],
        cwd=sandbox.repo,
        env=sandbox.env if env is None else env,
    )


# ------------------------------------------------------------------- native engine


def test_native_flux_replaces_the_committed_engine_manifest_and_installer() -> None:
    # The engine is installed by native `flux bootstrap`, so the committed manifest
    # and the custom checksum installer are gone.
    assert not (INSTALL_DIR / "components.yaml").exists(), "the committed engine manifest must be removed"
    assert not (INSTALL_DIR / "install-gitops.sh").exists(), "the custom installer must be removed"


def test_flux_cli_is_pinned_in_the_flake_devshell() -> None:
    # Pinned nixpkgs trails the required Flux release, so the flake pins the
    # downloaded CLI version and verifies every supported platform by SHA-256.
    source = FLAKE.read_text(encoding="utf-8")
    version = re.search(r'fluxVersion\s*=\s*"(?P<version>\d+\.\d+\.\d+)";', source)
    assert version, "flake.nix must pin a semantic Flux CLI version"
    checksums = re.findall(r'fluxSha256\s*=\s*"([0-9a-f]{64})";', source)
    assert len(checksums) == 4, "each supported platform must pin the Flux CLI release checksum"
    assert len(set(checksums)) == 4, "Flux CLI platform checksums must not be duplicated"
    block = re.search(
        r"k8sTools\s*=\s*with pkgs;\s*\[(.*?)\]",
        source,
        re.DOTALL,
    )
    assert block, "flake.nix must define a k8sTools package list"
    assert "fluxPackage" in block.group(1), "the k8s devshell must provide the checksum-pinned Flux CLI"


# ---------------------------------------------------------- bounded bootstrap CLI


def test_bootstrap_rejects_unsupported_modes_before_repository_or_tool_access(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "called"
    for tool in ("git", "flux", "kubectl", "pnpm"):
        _write_executable(fake_bin / tool, f"printf '{tool}\\n' >>\"$TOOL_MARKER\"\n")
    environment = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "TOOL_MARKER": str(marker),
    }

    result = _run(
        ["bash", str(BOOTSTRAP_SCRIPT), "--confirm"],
        cwd=REPO_ROOT,
        env=environment,
    )

    assert result.returncode == 2
    assert "--validate|--dry-run|--execute" in result.stderr
    assert not marker.exists(), "an unsupported mode crossed the bootstrap tool boundary"


def test_dry_run_renders_the_reviewed_local_flux_source_with_exact_arguments(
    tmp_path: Path,
) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)

    result = _run_bootstrap(sandbox, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert sandbox.calls.read_text(encoding="utf-8").splitlines() == [
        "install --export",
        "create source git flux-system "
        "--url=ssh://git@github.com/portable-owner/portable-repo.git "
        f"--branch={RUNTIME_CONTROL_BRANCH} --secret-ref=flux-system "
        "--interval=1m --export",
        "create kustomization flux-system --source=GitRepository/flux-system "
        "--path=./infra/k8s/gitops/clusters/local --prune=true "
        "--interval=10m --export",
    ]


def _emitted_sync_url(sandbox: BootstrapSandbox) -> str:
    result = _run_bootstrap(sandbox, "--dry-run")
    assert result.returncode == 0, result.stderr
    match = re.search(r"--url=(\S+)", sandbox.calls.read_text(encoding="utf-8"))
    assert match is not None, "the dry run did not emit a Flux sync URL"
    return match.group(1)


def _validate_origin(sandbox: BootstrapSandbox) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            "bash",
            "-c",
            f'source "{sandbox.script}"; validate_remote_origin "$1" "$2" "$3"',
            "bootstrap-validator",
            str(sandbox.repo),
            sandbox.env["GITOPS_GITHUB_OWNER"],
            sandbox.env["GITOPS_GITHUB_REPOSITORY"],
        ],
        cwd=sandbox.repo,
        env=sandbox.env,
    )


def test_emitted_sync_url_uses_the_ssh_scheme_flux_requires(tmp_path: Path) -> None:
    # Flux validates GitRepository .spec.url against ^(http|https|ssh)://.*$, so the scp-like
    # git@host:path form is rejected by the API server.
    url = _emitted_sync_url(_bootstrap_sandbox(tmp_path))

    assert url == "ssh://git@github.com/portable-owner/portable-repo.git", url


def test_origin_validator_accepts_the_sync_url_the_script_emits(tmp_path: Path) -> None:
    # Root-cause guard: the emitted sync URL and the accepted-origin set are one contract. If
    # either side moves alone, a worktree whose remote is exactly the Flux source is rejected.
    sandbox = _bootstrap_sandbox(tmp_path)
    _git(sandbox.repo, "remote", "add", "origin", _emitted_sync_url(sandbox))

    result = _validate_origin(sandbox)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/portable-owner/portable-repo.git",
        "git@github.com:portable-owner/portable-repo.git",
    ],
)
def test_origin_validator_still_accepts_operator_supplied_remote_forms(tmp_path: Path, origin: str) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    _git(sandbox.repo, "remote", "add", "origin", origin)

    result = _validate_origin(sandbox)

    assert result.returncode == 0, result.stderr


def test_origin_validator_rejects_a_foreign_remote(tmp_path: Path) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    _git(sandbox.repo, "remote", "add", "origin", "ssh://git@github.com/other-owner/portable-repo.git")

    result = _validate_origin(sandbox)

    assert result.returncode != 0
    assert "does not exactly match the declared GitHub owner/repository" in result.stderr


def test_bootstrap_rejects_nonlocal_cluster_before_flux_or_kubernetes_access(
    tmp_path: Path,
) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)

    result = _run_bootstrap(sandbox, "--validate", sandbox.env | {"NOHIKI_CLUSTER": "staging-aks"})

    assert result.returncode != 0
    assert "supports only NOHIKI_CLUSTER=local" in result.stderr
    assert not sandbox.calls.exists()


@pytest.mark.parametrize("missing", ["GITOPS_GITHUB_OWNER", "GITOPS_GITHUB_REPOSITORY"])
def test_dry_run_requires_each_github_coordinate_before_invoking_flux(tmp_path: Path, missing: str) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    environment = sandbox.env.copy()
    environment.pop(missing)

    result = _run_bootstrap(sandbox, "--dry-run", environment)

    assert result.returncode != 0
    assert f"{missing} is required (fail-closed)" in result.stderr
    assert not sandbox.calls.exists()


@pytest.mark.parametrize("coordinate", ["../other-owner", "repo name"])
def test_dry_run_rejects_unsafe_github_coordinates_before_invoking_flux(tmp_path: Path, coordinate: str) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    environment = sandbox.env | {"GITOPS_GITHUB_OWNER": coordinate}

    result = _run_bootstrap(sandbox, "--dry-run", environment)

    assert result.returncode != 0
    assert "contains unsupported characters" in result.stderr
    assert not sandbox.calls.exists()


def test_fork_bootstraps_against_its_own_repo_without_tracked_edits() -> None:
    # A fork supplies its own GITOPS_GITHUB_* coordinates; native flux commits the
    # generated flux-system sync manifests to the fork, so self-management tracks the
    # fork with no tracked-file edit. No committed cluster YAML pins a shared source
    # revision anymore (the shared base source was removed).
    text = _bootstrap()
    assert "GITOPS_GITHUB_OWNER" in text
    assert "GITOPS_GITHUB_REPOSITORY" in text
    assert "GITOPS_GITHUB_BRANCH" in text
    assert not (CLUSTERS_DIR / "base" / "source.yaml").exists(), (
        "the shared committed source is bootstrap-generated now"
    )


def test_dry_run_rejects_incomplete_generated_output_and_cleans_the_snapshot(
    tmp_path: Path,
) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    temporary_root = tmp_path / "bootstrap-tmp"
    temporary_root.mkdir()

    result = _run_bootstrap(
        sandbox,
        "--dry-run",
        sandbox.env | {"FAKE_FLUX_MODE": "missing-components", "TMPDIR": str(temporary_root)},
    )

    assert result.returncode != 0
    assert "gotk-components.yaml size is outside the accepted boundary" in result.stderr
    assert list(temporary_root.iterdir()) == []


def test_validate_is_read_only_and_requires_no_mutating_or_retired_credentials(
    tmp_path: Path,
) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    environment = sandbox.env.copy()
    for name in (
        "GITHUB_TOKEN",
        "GITOPS_GITHUB_OWNER",
        "GITOPS_GITHUB_REPOSITORY",
        "GITOPS_GITHUB_PERSONAL",
        "NOHIKI_IMAGE_REGISTRY",
        "NOHIKI_ESO_CLIENT_ID",
    ):
        environment.pop(name, None)

    result = _run_bootstrap(sandbox, "--validate", environment)

    assert result.returncode == 0, result.stderr
    assert "pristine Flux state accepted" in result.stdout
    assert not sandbox.calls.exists()


def test_completed_flux_state_refuses_a_second_bootstrap_before_tools(
    tmp_path: Path,
) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    flux_dir = sandbox.repo / "infra" / "k8s" / "gitops" / "clusters" / "local" / "flux-system"
    flux_dir.mkdir()
    for name in ("gotk-components.yaml", "gotk-sync.yaml", "kustomization.yaml"):
        (flux_dir / name).write_text(f"reviewed {name}\n", encoding="utf-8")

    result = _run_bootstrap(sandbox, "--validate")

    assert result.returncode != 0
    assert "already complete; use normal reconcile instead of bootstrap" in result.stderr
    assert not sandbox.calls.exists()


def test_symlinked_snapshot_helper_is_rejected_before_tools(
    tmp_path: Path,
) -> None:
    sandbox = _bootstrap_sandbox(tmp_path)
    helper = sandbox.script.with_name("secure-snapshot.py")
    helper.unlink()
    helper.symlink_to(SNAPSHOT_HELPER)

    result = _run_bootstrap(sandbox, "--validate")

    assert result.returncode != 0
    assert "secure snapshot helper is absent or unsafe" in result.stderr
    assert not sandbox.calls.exists()


# -------------------------------------------------------------- retired recipes


def test_gitops_install_recipe_is_removed() -> None:
    assert not re.search(r"^gitops-install( |:)", _justfile(), re.MULTILINE), (
        "gitops-install is retired under native flux"
    )


def test_factory_reset_confirmation_is_enforced_after_lifecycle_dispatch(
    tmp_path: Path,
) -> None:
    acknowledgement_arguments = (
        "--acknowledge-data-loss",
        DATA_LOSS_ACK,
        "--acknowledge-factory-reset",
        "wrong acknowledgement",
    )
    expected_error = "exact --acknowledge-factory-reset text is required"
    mode = "factory-reset"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "mutating-tool-called"
    for tool in ("kubectl", "flux", "git"):
        _write_executable(
            fake_bin / tool,
            f"printf '{tool}\\n' >>\"$RESET_TOOL_MARKER\"\nexit 99\n",
        )
    environment = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "RESET_TOOL_MARKER": str(marker),
    }
    arguments = [
        str(LIFECYCLE_SCRIPT),
        mode,
        "--expected-context",
        "reviewed-context",
        "--namespace",
        "nohiki",
        "--checkpoint",
        str(tmp_path / "checkpoint.json"),
        "--checkpoint-sha256",
        "0" * 64,
        "--destructive",
        *acknowledgement_arguments,
        "--owner-authorization",
        "I am the recorded owner portable-test",
        "--evidence-output",
        str(tmp_path / "transaction.json"),
    ]

    result = _run(arguments, cwd=REPO_ROOT, env=environment)

    assert result.returncode == 2
    assert expected_error in result.stderr
    assert not marker.exists(), "invalid reset confirmation reached a mutating tool"


def test_no_argo_recipe_or_path_remains() -> None:
    # The retired engine leaves no recipe, path, or reference behind. The tests
    # directory legitimately names the retired engine, so it is excluded.
    assert "argo" not in _justfile().lower(), "Justfile still references the retired engine"
    assert not (REPO_ROOT / "infra" / "k8s" / "argocd").exists(), "the argocd manifest tree must be deleted"
    tests_dir = Path(__file__).resolve().parent
    for path in GITOPS_DIR.rglob("*"):
        if path.is_file() and tests_dir not in path.parents:
            assert "argo" not in path.read_text(encoding="utf-8", errors="ignore").lower(), f"{path} references argo"


# --------------------------------------------------------------------- README


def test_readme_documents_native_k3s_registry_requirement() -> None:
    # The local contributor registry is served on localhost:5000; k3s must run on the
    # native host (not a VM or nested container) so cluster pods can pull from it.
    text = README.read_text(encoding="utf-8")
    assert "native host" in text, "README must document the native-host k3s requirement"
    assert "localhost:5000" in text, "README must name the localhost:5000 contributor registry"
