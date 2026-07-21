"""Executable regression coverage for the portable local Kubernetes lifecycle."""

import os
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_JUSTFILE = _ROOT / "Justfile"
_LIFECYCLE = _ROOT / "infra" / "k8s" / "local" / "lifecycle.sh"
_CANONICAL_RECIPES = (
    "k8s-preflight-local",
    "k8s-bootstrap-local",
    "k8s-publish-local-images",
    "k8s-reconcile-local",
    "k8s-verify-local",
    "k8s-diagnostics-local",
    "k8s-factory-reset-local",
)

type LifecycleSandbox = tuple[Path, Path, dict[str, str]]


def _write_executable(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    path.chmod(0o755)


def _lifecycle_sandbox(tmp_path: Path) -> LifecycleSandbox:
    root = tmp_path / "repo"
    lifecycle = root / "infra" / "k8s" / "local" / "lifecycle.sh"
    lifecycle.parent.mkdir(parents=True)
    lifecycle.write_text(_LIFECYCLE.read_text(encoding="utf-8"), encoding="utf-8")
    lifecycle.chmod(0o755)

    log = tmp_path / "calls.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "flux",
        """#!/bin/sh
printf 'flux %s\\n' "$*" >> "$CALL_LOG"
if [ -n "${FLUX_FAIL_ON:-}" ]; then
    case "$*" in *"$FLUX_FAIL_ON"*) exit "${FLUX_FAIL_CODE:-71}" ;; esac
fi
""",
    )
    _write_executable(
        fake_bin / "kubectl",
        """#!/bin/sh
printf 'kubectl %s\\n' "$*" >> "$CALL_LOG"
case "$*" in *'config current-context'*) printf '%s\\n' "$K8S_LOCAL_CONTEXT" ;; esac
""",
    )
    _write_executable(
        fake_bin / "git",
        r"""#!/bin/sh
printf 'git %s\n' "$*" >> "$CALL_LOG"
case "$*" in
  'branch --show-current')
    printf '%s\n' "${GIT_BRANCH_ACTUAL:-$NOHIKI_RUNTIME_CONTROL_BRANCH}" ;;
  'rev-parse HEAD')
    if [ -f "$GIT_COMMITTED" ]; then
      printf '%s\n' 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
    else
      printf '%s\n' "$NOHIKI_REVIEWED_TOPIC_SHA"
    fi ;;
  'ls-remote --heads origin '*)
    remote_sha="${GIT_REMOTE_SHA:-$NOHIKI_REVIEWED_TOPIC_SHA}"
    remote_ref="refs/heads/$NOHIKI_RUNTIME_CONTROL_BRANCH"
    printf '%s\t%s\n' "$remote_sha" "$remote_ref" ;;
  'diff --name-only HEAD')
    if [ -n "${GIT_CHANGED_PATH:-}" ]; then printf '%s\n' "$GIT_CHANGED_PATH"; fi ;;
  'ls-files --others --exclude-standard') ;;
  'hash-object '*) printf '%s\n' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' ;;
  'diff --cached --name-only') printf '%s\n' 'infra/k8s/gitops/platform/local/image-digests.values.yaml' ;;
  'commit '*) : > "$GIT_COMMITTED" ;;
  'diff-tree '*) printf '%s\n' 'infra/k8s/gitops/platform/local/image-digests.values.yaml' ;;
esac
""",
    )
    _write_executable(
        fake_bin / "uv",
        """#!/bin/sh
printf 'uv %s\\n' "$*" >> "$CALL_LOG"
case "$*" in
  *'image_foundation.py build'*)
    if [ -n "${IMAGE_BUILD_EXIT:-}" ]; then exit "$IMAGE_BUILD_EXIT"; fi ;;
  *'image_foundation.py render-values'*) printf '%s\\n' 'images: {}' ;;
esac
""",
    )
    for name in ("helm", "kustomize"):
        _write_executable(
            fake_bin / name,
            '#!/bin/sh\nprintf \'%s %s\\n\' "$(basename "$0")" "$*" >> "$CALL_LOG"\n',
        )

    _write_executable(
        root / "infra" / "k8s" / "local" / "cluster_reset.py",
        """#!/bin/sh
printf 'cluster-reset-call\\n' >> "$CALL_LOG"
printf 'cluster-reset-arg <%s>\\n' "$@" >> "$CALL_LOG"
exit "${RESET_EXIT:-0}"
""",
    )
    image_helper = root / "infra" / "k8s" / "local" / "image_foundation.py"
    image_helper.write_text("# synthetic image helper\n", encoding="utf-8")
    (root / "infra" / "k8s" / "gitops" / "platform" / "local").mkdir(parents=True)

    env = os.environ | {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "CALL_LOG": str(log),
        "K8S_LOCAL_CONTEXT": "k3s-nohiki-test",
        "NOHIKI_RUNTIME_CONTROL_BRANCH": "runtime-control/local/portable-test",
        "NOHIKI_REVIEWED_TOPIC_SHA": "a" * 40,
        "GIT_COMMITTED": str(tmp_path / "git-committed"),
    }
    return lifecycle, log, env


@pytest.fixture(scope="module")
def lifecycle_sandbox(tmp_path_factory: pytest.TempPathFactory) -> LifecycleSandbox:
    return _lifecycle_sandbox(tmp_path_factory.mktemp("lifecycle"))


@pytest.fixture
def sandbox(lifecycle_sandbox: LifecycleSandbox) -> LifecycleSandbox:
    lifecycle, log, env = lifecycle_sandbox
    log.unlink(missing_ok=True)
    Path(env["GIT_COMMITTED"]).unlink(missing_ok=True)
    (lifecycle.parents[3] / "infra/k8s/gitops/platform/local/image-digests.values.yaml").unlink(missing_ok=True)
    return lifecycle_sandbox


def _run_lifecycle(
    lifecycle: Path,
    *arguments: str,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(lifecycle), *arguments],
        cwd=lifecycle.parents[3],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _calls(log: Path) -> list[str]:
    if not log.exists():
        return []
    return log.read_text(encoding="utf-8").splitlines()


def test_preflight_rejects_extra_arguments_before_external_commands(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(lifecycle, "preflight", "unexpected", env=env)

    assert result.returncode != 0
    assert "preflight accepts no arguments" in result.stderr
    assert _calls(log) == []


def test_reconcile_source_failure_stops_before_any_stack_reconcile(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(
        lifecycle,
        "reconcile",
        env=env | {"FLUX_FAIL_ON": "source git", "FLUX_FAIL_CODE": "71"},
    )

    calls = _calls(log)
    assert result.returncode == 71
    assert calls[-1] == "flux reconcile source git flux-system --namespace flux-system"
    assert not any("reconcile kustomization" in call for call in calls)


def test_factory_reset_dispatch_preserves_mode_and_adversarial_arguments(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox
    tmp_path = log.parent
    marker = tmp_path / "shell-expanded"
    payload = f"--evidence-dir={tmp_path}/evidence;touch {marker}"

    result = _run_lifecycle(
        lifecycle,
        "factory-reset",
        "--dry-run",
        "--confirm=k3s-nohiki-test",
        payload,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert _calls(log) == [
        "cluster-reset-call",
        "cluster-reset-arg <factory-reset>",
        "cluster-reset-arg <--dry-run>",
        "cluster-reset-arg <--confirm=k3s-nohiki-test>",
        f"cluster-reset-arg <{payload}>",
    ]
    assert not marker.exists()


def test_publish_uses_configured_container_runtime_for_build_and_publish(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(
        lifecycle,
        "publish",
        env=env | {"CONTAINER_RUNTIME": "nerdctl"},
    )

    assert result.returncode == 0, result.stderr
    calls = _calls(log)
    assert "uv run python infra/k8s/local/image_foundation.py build --runtime nerdctl" in calls
    assert "uv run python infra/k8s/local/image_foundation.py publish --runtime nerdctl " in next(
        call for call in calls if "image_foundation.py publish" in call
    )
    assert not any("--runtime docker" in call or "--runtime podman" in call for call in calls)


def test_publish_build_failure_stops_before_publish_or_git_write(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(
        lifecycle,
        "publish",
        env=env | {"IMAGE_BUILD_EXIT": "79"},
    )

    calls = _calls(log)
    assert result.returncode == 79
    assert any("image_foundation.py build" in call for call in calls)
    assert not any("image_foundation.py publish" in call for call in calls)
    assert not any(call.startswith(("git add ", "git commit ", "git push ")) for call in calls)


def test_publish_rejects_unrelated_worktree_changes_before_build(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(
        lifecycle,
        "publish",
        env=env | {"GIT_CHANGED_PATH": "backend/unreviewed.py"},
    )

    assert result.returncode != 0
    assert "publish refuses unrelated worktree change: backend/unreviewed.py" in result.stderr
    assert not any("image_foundation.py build" in call for call in _calls(log))


def test_publish_rejects_remote_revision_drift_before_build(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(
        lifecycle,
        "publish",
        env=env | {"GIT_REMOTE_SHA": "b" * 40},
    )

    assert result.returncode != 0
    assert "remote runtime-control branch does not equal reviewed SHA" in result.stderr
    assert not any("image_foundation.py build" in call for call in _calls(log))


def test_reconcile_stack_failure_stops_before_wait_and_later_stacks(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(
        lifecycle,
        "reconcile",
        env=env
        | {
            "FLUX_FAIL_ON": "kustomization registry ",
            "FLUX_FAIL_CODE": "72",
        },
    )

    calls = _calls(log)
    assert result.returncode == 72
    failed = "flux reconcile kustomization registry --namespace flux-system"
    assert failed in calls
    assert not any("wait" in call and "kustomization/registry" in call for call in calls)
    assert not any("kustomization infrastructure" in call for call in calls)


def test_factory_reset_propagates_reset_authority_failure(
    sandbox: LifecycleSandbox,
) -> None:
    lifecycle, log, env = sandbox

    result = _run_lifecycle(
        lifecycle,
        "factory-reset",
        "--execute",
        "--confirm=k3s-nohiki-test",
        env=env | {"RESET_EXIT": "86"},
    )

    assert result.returncode == 86
    assert _calls(log) == [
        "cluster-reset-call",
        "cluster-reset-arg <factory-reset>",
        "cluster-reset-arg <--execute>",
        "cluster-reset-arg <--confirm=k3s-nohiki-test>",
    ]


def test_canonical_lifecycle_recipes_dry_run_without_workstation_escalation() -> None:
    rendered: list[str] = []
    for recipe in _CANONICAL_RECIPES:
        command = ["just", "--dry-run", "--justfile", str(_JUSTFILE), recipe]
        if recipe.endswith("reset-local"):
            command.append("--dry-run")
        result = subprocess.run(
            command,
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{recipe}: {result.stderr}"
        rendered.append(result.stdout)

    commands = "\n".join(rendered)
    for token in ("sudo", "systemctl", "k3s ctr"):
        assert token not in commands, token
