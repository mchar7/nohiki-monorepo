"""Executable policy tests for the bounded one-time Flux bootstrap."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[4]
_POLICY = _ROOT / "infra" / "k8s" / "gitops" / "install" / "runtime-control-policy.sh"
_BOOTSTRAP = _ROOT / "infra" / "k8s" / "gitops" / "install" / "bootstrap.sh"
_BRANCH = "runtime-control/local/reviewed-16.6"
_ALLOWED_OUTPUTS = frozenset({"gotk-components.yaml", "gotk-sync.yaml", "kustomization.yaml"})
_WORKFLOW_IDENTITY_VARIABLES = (
    "GITHUB_REF",
    "GITHUB_REF_NAME",
    "GITHUB_HEAD_REF",
    "GITHUB_SHA",
)


def _sanitized_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in _WORKFLOW_IDENTITY_VARIABLES:
        environment.pop(name, None)
    return environment


def _run(
    command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)


def _git(repo: Path, *args: str) -> str:
    result = _run(["git", *args], cwd=repo)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _make_repo(tmp_path: Path, branch: str = _BRANCH) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "user.name", "Flux Boundary Test")
    _git(repo, "config", "user.email", "flux-boundary@example.invalid")
    (repo / "reviewed.txt").write_text("reviewed\n", encoding="utf-8")
    _git(repo, "add", "reviewed.txt")
    _git(repo, "commit", "-m", "reviewed runtime-control input")
    return repo, _git(repo, "rev-parse", "HEAD")


def _call_policy(
    function_call: str, *, env: dict[str, str] | None = None, stdin: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "$1"; {function_call}', "bash", str(_POLICY)],
        env=os.environ | (env or {}),
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def _identity(repo: Path, sha: str, **overrides: str) -> subprocess.CompletedProcess[str]:
    env = {
        "NOHIKI_RUNTIME_CONTROL_BRANCH": _BRANCH,
        "NOHIKI_REVIEWED_TOPIC_SHA": sha,
        "GITOPS_GITHUB_BRANCH": _BRANCH,
    }
    env.update(overrides)
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; validate_runtime_control_identity "$2"',
            "bash",
            str(_POLICY),
            str(repo),
        ],
        env=_sanitized_environment() | env,
        capture_output=True,
        text=True,
        check=False,
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _bootstrap_repo(tmp_path: Path) -> tuple[Path, str, Path]:
    repo, sha = _make_repo(tmp_path)
    install = repo / "infra" / "k8s" / "gitops" / "install"
    install.mkdir(parents=True)
    shutil.copy2(_BOOTSTRAP, install / "bootstrap.sh")
    shutil.copy2(_POLICY, install / "runtime-control-policy.sh")
    shutil.copy2(_BOOTSTRAP.with_name("secure-snapshot.py"), install / "secure-snapshot.py")
    (repo / "infra" / "k8s" / "gitops" / "clusters" / "local").mkdir(parents=True)
    _git(repo, "add", "infra")
    _git(repo, "commit", "-m", "add bounded bootstrap")
    sha = _git(repo, "rev-parse", "HEAD")
    calls = tmp_path / "calls.log"
    return repo, sha, calls


def _bootstrap_env(sha: str, calls: Path, fake_bin: Path | None = None) -> dict[str, str]:
    env = _sanitized_environment() | {
        "NOHIKI_CLUSTER": "local",
        "NOHIKI_RUNTIME_CONTROL_BRANCH": _BRANCH,
        "NOHIKI_REVIEWED_TOPIC_SHA": sha,
        "GITHUB_TOKEN": "github-token-must-never-appear",
        "SOPS_AGE_KEY_FILE": "/age-key-must-never-appear",
        "GITOPS_GITHUB_OWNER": "reviewed-owner",
        "GITOPS_GITHUB_REPOSITORY": "reviewed-repository",
        "GITOPS_GITHUB_BRANCH": _BRANCH,
        "GITOPS_GITHUB_PERSONAL": "false",
        "TEST_CALLS": str(calls),
    }
    if fake_bin is not None:
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
    return env


def _generate_age_identity(path: Path) -> str:
    generated = _run(["age-keygen", "-o", str(path)])
    assert generated.returncode == 0, generated.stderr
    recipient = _run(["age-keygen", "-y", str(path)])
    assert recipient.returncode == 0, recipient.stderr
    return recipient.stdout.strip()


def _execute_fixture(
    tmp_path: Path,
    *,
    switch_context: bool = False,
    replace_age: bool = False,
    replace_flux: bool = False,
    replace_kubeconfig: bool = False,
    age_state: str = "reviewed",
    inject_shared_index: bool = False,
    inject_head_change: bool = False,
    install_hook: bool = False,
    hook_mutates_flux: bool = False,
    advance_ref_before_push: bool = False,
    replace_bound_snapshots: bool = False,
    flux_failure: bool = False,
    flux_remote_write: bool = False,
) -> tuple[Path, str, subprocess.CompletedProcess[str], Path, Path, Path, bytes, Path]:
    repo, sha, calls = _bootstrap_repo(tmp_path)
    _git(
        repo,
        "remote",
        "add",
        "origin",
        "https://github.com/reviewed-owner/reviewed-repository.git",
    )
    calls.touch()
    fake_bin = tmp_path / "execute-bin"
    fake_bin.mkdir()
    kubeconfig = tmp_path / "source-kubeconfig"
    kubeconfig.write_text(
        "apiVersion: v1\ncurrent-context: reviewed-context\n"
        "clusters:\n- cluster:\n    server: https://reviewed.invalid\n"
        "users:\n- user:\n    token: reviewed-token\n",
        encoding="utf-8",
    )
    kubeconfig.chmod(0o600)
    replacement_kubeconfig = tmp_path / "replacement-kubeconfig"
    replacement_kubeconfig.write_text(
        "apiVersion: v1\ncurrent-context: reviewed-context\n"
        "clusters:\n- cluster:\n    server: https://attacker.invalid\n"
        "users:\n- user:\n    token: attacker-token\n",
        encoding="utf-8",
    )
    replacement_kubeconfig.chmod(0o600)
    kubeconfig_swap_marker = tmp_path / "kubeconfig-swap-triggered"
    used_kubeconfig = tmp_path / "used-kubeconfig"
    reviewed_age_key = tmp_path / "reviewed.age.agekey"
    reviewed_recipient = _generate_age_identity(reviewed_age_key)
    (repo / ".sops.yaml").write_text(
        "creation_rules:\n"
        "  - path_regex: infra/k8s/gitops/secrets/local/.*\\.sops\\.yaml$\n"
        "    encrypted_regex: ^(data|stringData)$\n"
        f"    age: {reviewed_recipient}\n",
        encoding="utf-8",
    )
    _git(repo, "add", ".sops.yaml")
    _git(repo, "commit", "-m", "bind reviewed Age recipient")
    sha = _git(repo, "rev-parse", "HEAD")
    if age_state == "reviewed":
        age_key = reviewed_age_key
    elif age_state == "unrelated":
        age_key = tmp_path / "unrelated.age.agekey"
        _generate_age_identity(age_key)
    else:
        age_key = tmp_path / "invalid.age.agekey"
        age_key.write_text("not-an-age-identity\n", encoding="ascii")
        age_key.chmod(0o600)
    expected_age = reviewed_age_key.read_bytes()
    swap_age_key = tmp_path / "swap.age.agekey"
    _generate_age_identity(swap_age_key)
    applied_age = tmp_path / "applied-age"
    race_marker = tmp_path / "flux-race-triggered"
    bootstrap_tmp = tmp_path / "bootstrap-tmp"
    bootstrap_tmp.mkdir()
    shared_index_marker = tmp_path / "shared-index-triggered"
    head_race_marker = tmp_path / "head-race-triggered"
    push_race_marker = tmp_path / "push-race-triggered"
    push_args = tmp_path / "push-args"
    remote_state = tmp_path / "remote-state"
    remote_state.write_text(f"{sha}\n", encoding="ascii")
    gate_env = tmp_path / "gate-env"
    bound_age_swap_marker = tmp_path / "bound-age-swap-triggered"
    applied_age_swap_marker = tmp_path / "applied-age-swap-triggered"
    bound_kube_swap_marker = tmp_path / "bound-kube-swap-triggered"
    age_keygen_used = tmp_path / "age-keygen-used"
    flux_kubeconfig_used = tmp_path / "flux-kubeconfig-used"
    hook_index = tmp_path / "hook-index"
    if install_hook:
        hook = repo / ".git/hooks/pre-commit"
        _write_executable(
            hook,
            'printf \'%s\\n\' "${GIT_INDEX_FILE:-}" >"$HOOK_INDEX"\n'
            'if [ "${HOOK_MUTATES_FLUX:-0}" = 1 ]; then\n'
            '  target="infra/k8s/gitops/clusters/local/flux-system/gotk-components.yaml"\n'
            "  printf 'hook replacement\\n' >\"$target\"\n"
            '  git add -- "$target"\n'
            "fi\n",
        )

    real_git = shutil.which("git")
    assert real_git is not None
    _write_executable(
        fake_bin / "git",
        'if [ "${INJECT_SHARED_INDEX:-0}" = 1 ] && [ ! -e "$SHARED_INDEX_MARKER" ]; then\n'
        '  case " $* " in *" ls-remote "*)\n'
        "    printf 'ambient staged entry\\n' >\"$TEST_REPO/ambient.txt\"\n"
        '    env -u GIT_INDEX_FILE "$REAL_GIT" -C "$TEST_REPO" add -- ambient.txt\n'
        '    : >"$SHARED_INDEX_MARKER" ;;\n'
        "  esac\n"
        "fi\n"
        'if [ "${INJECT_HEAD_CHANGE:-0}" = 1 ] && [ ! -e "$HEAD_RACE_MARKER" ]; then\n'
        '  case " $* " in *" commit "*|*" update-ref "*)\n'
        '    old="$("$REAL_GIT" -C "$TEST_REPO" rev-parse HEAD)"\n'
        '    tree="$("$REAL_GIT" -C "$TEST_REPO" write-tree)"\n'
        '    concurrent="$(\n'
        "      printf 'concurrent mutation\\n' |\n"
        '        "$REAL_GIT" -C "$TEST_REPO" commit-tree "$tree" -p "$old"\n'
        '    )"\n'
        '    "$REAL_GIT" -C "$TEST_REPO" update-ref "refs/heads/$NOHIKI_RUNTIME_CONTROL_BRANCH" "$concurrent" "$old"\n'
        '    : >"$HEAD_RACE_MARKER" ;;\n'
        "  esac\n"
        "fi\n"
        'case " $* " in\n'
        '  *" ls-remote "*)\n'
        "    printf 'git ls-remote runtime-control\\n' >>\"$TEST_CALLS\"\n"
        '    sha="$(cat -- "$REMOTE_STATE")"\n'
        '    printf \'%s\\trefs/heads/%s\\n\' "$sha" "$NOHIKI_RUNTIME_CONTROL_BRANCH"\n'
        "    exit 0 ;;\n"
        '  *" push origin "*)\n'
        "    printf 'git push runtime-control\\n' >>\"$TEST_CALLS\"\n"
        '    printf \'%s\\n\' "$*" >"$PUSH_ARGS"\n'
        "    for refspec do :; done\n"
        '    if [ "${ADVANCE_REF_BEFORE_PUSH:-0}" = 1 ]; then\n'
        '      old="$("$REAL_GIT" -C "$TEST_REPO" rev-parse HEAD)"\n'
        '      tree="$("$REAL_GIT" -C "$TEST_REPO" rev-parse "${old}^{tree}")"\n'
        "      concurrent=\"$(printf 'post-update mutation\\n' |\n"
        '        "$REAL_GIT" -C "$TEST_REPO" commit-tree "$tree" -p "$old")"\n'
        '      "$REAL_GIT" -C "$TEST_REPO" update-ref \
'
        '        "refs/heads/$NOHIKI_RUNTIME_CONTROL_BRANCH" "$concurrent" "$old"\n'
        '      : >"$PUSH_RACE_MARKER"\n'
        "    fi\n"
        '    source_ref="${refspec%%:*}"\n'
        '    "$REAL_GIT" -C "$TEST_REPO" rev-parse "$source_ref" >"$REMOTE_STATE"\n'
        "    exit 0 ;;\n"
        "esac\n"
        'if [ "${RACE_FLUX:-0}" = 1 ] && [ "$1" = -C ] &&\n'
        '  [ "${3:-}" = hash-object ] && [ "${4:-}" = -w ] &&\n'
        '  [ ! -e "$RACE_MARKER" ]; then\n'
        '  for target in "$BOOTSTRAP_TMP_PARENT"/*/flux-output/gotk-components.yaml; do\n'
        '    [ -f "$target" ] && printf \'unreviewed replacement\\n\' >"$target"\n'
        "  done\n"
        '  : >"$RACE_MARKER"\n'
        "fi\n"
        'exec "$REAL_GIT" "$@"\n',
    )
    real_age_keygen = shutil.which("age-keygen")
    assert real_age_keygen is not None
    _write_executable(
        fake_bin / "age-keygen",
        'if [ "${1:-}" = -y ] && [ "${REPLACE_BOUND_SNAPSHOTS:-0}" = 1 ]; then\n'
        '  cp -- "$SWAP_AGE_KEY" "$2" 2>/dev/null || :\n'
        '  : >"$BOUND_AGE_SWAP_MARKER"\n'
        "fi\n"
        'if [ "${1:-}" = -y ]; then\n'
        '  if cmp -s -- "$2" "$REVIEWED_AGE_KEY"; then\n'
        "    printf 'reviewed\\n' >\"$AGE_KEYGEN_USED\"\n"
        "  else\n"
        "    printf 'other\\n' >\"$AGE_KEYGEN_USED\"\n"
        "  fi\n"
        "fi\n"
        'exec "$REAL_AGE_KEYGEN" "$@"\n',
    )
    _write_executable(
        fake_bin / "pnpm",
        'printf \'pnpm %s\\n\' "$*" >>"$TEST_CALLS"\n'
        "{\n"
        "  printf 'token=%s\\n' \"${GITHUB_TOKEN+x}\"\n"
        "  printf 'age=%s\\n' \"${SOPS_AGE_KEY_FILE+x}\"\n"
        "  printf 'kubeconfig=%s\\n' \"${KUBECONFIG+x}\"\n"
        "  printf 'bootstrap_kube=%s\\n' \"${BOOTSTRAP_KUBECONFIG+x}\"\n"
        "  printf 'bootstrap_source=%s\\n' \"${BOOTSTRAP_KUBECONFIG_SOURCE+x}\"\n"
        "  printf 'bootstrap_age=%s\\n' \"${BOOTSTRAP_AGE_KEY+x}\"\n"
        "  printf 'index=%s\\n' \"${GIT_INDEX_FILE:-}\"\n"
        '} >"$GATE_ENV"\n',
    )
    _write_executable(
        fake_bin / "flux",
        'printf \'flux %s\\n\' "$*" >>"$TEST_CALLS"\n'
        'case "$1 $2" in\n'
        "  'install --export') printf 'validated-components\\n' ;;\n"
        "  'create source') printf 'validated-source\\n' ;;\n"
        "  'create kustomization') printf 'validated-kustomization\\n' ;;\n"
        "  *)\n"
        "    for argument do\n"
        '      case "$argument" in --kubeconfig=*) selected="${argument#*=}" ;; esac\n'
        "    done\n"
        '    if [ "${REPLACE_BOUND_SNAPSHOTS:-0}" = 1 ]; then\n'
        '      cp -- "$REPLACEMENT_KUBECONFIG" "$selected" 2>/dev/null || :\n'
        '      : >"$BOUND_KUBE_SWAP_MARKER"\n'
        "    fi\n"
        '    if cmp -s -- "$selected" "$USED_KUBECONFIG"; then\n'
        "      printf 'reviewed\\n' >\"$FLUX_KUBECONFIG_USED\"\n"
        "    else\n"
        "      printf 'other\\n' >\"$FLUX_KUBECONFIG_USED\"\n"
        "    fi\n"
        '    if [ "${REPLACE_AGE:-0}" = 1 ]; then\n'
        "      printf 'AGE-SECRET-KEY-1REPLACEMENT-FIXTURE\\n' >\"$SOPS_AGE_KEY_FILE\"\n"
        "    fi\n"
        '    if [ "${FLUX_REMOTE_WRITE:-0}" = 1 ]; then\n'
        "      printf '0000000000000000000000000000000000000000\\n' >\"$REMOTE_STATE\"\n"
        "    fi\n"
        '    if [ "${FLUX_FAILURE:-0}" = 1 ]; then\n'
        "      printf 'flux-bootstrap-private-output\\n' >&2\n"
        "      exit 67\n"
        "    fi\n"
        "    exit 0 ;;\n"
        "esac\n",
    )
    _write_executable(
        fake_bin / "kubectl",
        'printf \'kubectl %s\\n\' "$*" >>"$TEST_CALLS"\n'
        'case "$*" in\n'
        '  *" config current-context")\n'
        '    if [ "${SWITCH_CONTEXT:-0}" = 1 ]; then\n'
        "      printf 'other-context\\n'\n"
        "    else\n"
        "      printf 'reviewed-context\\n'\n"
        "    fi\n"
        '    if [ "${REPLACE_KUBECONFIG:-0}" = 1 ] &&\n'
        '      [ ! -e "$KUBECONFIG_SWAP_MARKER" ]; then\n'
        '      cp -- "$REPLACEMENT_KUBECONFIG" "$KUBECONFIG"\n'
        '      : >"$KUBECONFIG_SWAP_MARKER"\n'
        "    fi ;;\n"
        '  *" config view --raw --flatten --minify")\n'
        "    for argument do\n"
        '      case "$argument" in --kubeconfig=*) selected="${argument#*=}" ;; esac\n'
        "    done\n"
        '    cat -- "$selected" ;;\n'
        '  *" get namespace flux-system --ignore-not-found -o name")\n'
        "    for argument do\n"
        '      case "$argument" in --kubeconfig=*) selected="${argument#*=}" ;; esac\n'
        "    done\n"
        '    cp -- "$selected" "$USED_KUBECONFIG" ;;\n'
        '  *" create namespace flux-system --dry-run=client -o yaml")\n'
        "    printf 'apiVersion: v1\\nkind: Namespace\\nmetadata:\\n  name: flux-system\\n' ;;\n"
        '  *" create secret generic flux-sops "*)\n'
        "    for argument do\n"
        '      case "$argument" in\n'
        "        --from-file=age.agekey=*)\n"
        '          selected_age="${argument#--from-file=age.agekey=}" ;;\n'
        "      esac\n"
        "    done\n"
        '    if [ "${REPLACE_BOUND_SNAPSHOTS:-0}" = 1 ]; then\n'
        '      cp -- "$SWAP_AGE_KEY" "$selected_age" 2>/dev/null || :\n'
        '      : >"$APPLIED_AGE_SWAP_MARKER"\n'
        "    fi\n"
        '    cp -- "$selected_age" "$APPLIED_AGE"\n'
        "    printf 'apiVersion: v1\\nkind: Secret\\n' ;;\n"
        '  *" apply -f -") cat >/dev/null ;;\n'
        "  *) exit 65 ;;\n"
        "esac\n",
    )

    env = _bootstrap_env(sha, calls, fake_bin) | {
        "ADVANCE_REF_BEFORE_PUSH": "1" if advance_ref_before_push else "0",
        "APPLIED_AGE": str(applied_age),
        "BOOTSTRAP_TMP_PARENT": str(bootstrap_tmp),
        "GATE_ENV": str(gate_env),
        "HEAD_RACE_MARKER": str(head_race_marker),
        "HOOK_INDEX": str(hook_index),
        "HOOK_MUTATES_FLUX": "1" if hook_mutates_flux else "0",
        "INJECT_HEAD_CHANGE": "1" if inject_head_change else "0",
        "INJECT_SHARED_INDEX": "1" if inject_shared_index else "0",
        "K8S_LOCAL_CONTEXT": "reviewed-context",
        "KUBECONFIG": str(kubeconfig),
        "KUBECONFIG_SWAP_MARKER": str(kubeconfig_swap_marker),
        "REAL_GIT": real_git,
        "AGE_KEYGEN_USED": str(age_keygen_used),
        "APPLIED_AGE_SWAP_MARKER": str(applied_age_swap_marker),
        "BOUND_AGE_SWAP_MARKER": str(bound_age_swap_marker),
        "BOUND_KUBE_SWAP_MARKER": str(bound_kube_swap_marker),
        "FLUX_KUBECONFIG_USED": str(flux_kubeconfig_used),
        "FLUX_FAILURE": "1" if flux_failure else "0",
        "FLUX_REMOTE_WRITE": "1" if flux_remote_write else "0",
        "RACE_FLUX": "1" if replace_flux else "0",
        "RACE_MARKER": str(race_marker),
        "REPLACE_AGE": "1" if replace_age else "0",
        "REPLACE_KUBECONFIG": "1" if replace_kubeconfig else "0",
        "REPLACEMENT_KUBECONFIG": str(replacement_kubeconfig),
        "PUSH_ARGS": str(push_args),
        "PUSH_RACE_MARKER": str(push_race_marker),
        "REMOTE_STATE": str(remote_state),
        "REAL_AGE_KEYGEN": real_age_keygen,
        "REPLACE_BOUND_SNAPSHOTS": "1" if replace_bound_snapshots else "0",
        "REVIEWED_AGE_KEY": str(reviewed_age_key),
        "SWAP_AGE_KEY": str(swap_age_key),
        "SOPS_AGE_KEY_FILE": str(age_key),
        "SHARED_INDEX_MARKER": str(shared_index_marker),
        "SWITCH_CONTEXT": "1" if switch_context else "0",
        "TEST_REPO": str(repo),
        "TMPDIR": str(bootstrap_tmp),
        "USED_KUBECONFIG": str(used_kubeconfig),
    }
    (tmp_path / "shared-index-before").write_bytes((repo / ".git/index").read_bytes())
    script = repo / "infra" / "k8s" / "gitops" / "install" / "bootstrap.sh"
    result = _run(["bash", str(script), "--execute"], cwd=repo, env=env)
    return (
        repo,
        sha,
        result,
        calls,
        applied_age,
        race_marker,
        expected_age,
        used_kubeconfig,
    )


def test_context_switch_fails_before_any_cluster_or_git_mutation(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, calls, applied_age, _, _, _ = _execute_fixture(tmp_path, switch_context=True)

    assert result.returncode != 0
    assert "K8S_LOCAL_CONTEXT must exactly equal" in result.stderr
    invocations = calls.read_text(encoding="utf-8").splitlines()
    assert len(invocations) == 2
    assert invocations[0] == "pnpm exec lefthook run pre-commit --force"
    assert invocations[1].endswith(" config current-context")
    assert _git(repo, "rev-parse", "HEAD") == before_sha
    assert not applied_age.exists()
    assert list((tmp_path / "bootstrap-tmp").iterdir()) == []


def test_every_cluster_call_uses_the_bound_context_and_private_kubeconfig(
    tmp_path: Path,
) -> None:
    _, _, result, calls, _, _, _, _ = _execute_fixture(tmp_path)
    assert result.returncode == 0, result.stderr

    invocations = calls.read_text(encoding="utf-8").splitlines()
    bootstrap_call = next(line for line in invocations if "flux --kubeconfig=" in line)
    snapshot_argument = bootstrap_call.split()[1]
    snapshot = Path(snapshot_argument.removeprefix("--kubeconfig="))
    binding = f"--kubeconfig={snapshot} --context=reviewed-context"
    assert binding in bootstrap_call
    source_discovery = next(
        call
        for call in invocations
        if call.startswith("kubectl ") and call.endswith(" config current-context") and " --context=" not in call
    )
    for call in invocations:
        if call == source_discovery or " --export" in call:
            continue
        if call.startswith(("flux ", "kubectl ")):
            assert binding in call
    assert snapshot.as_posix().startswith("/proc/self/fd/")
    assert str(tmp_path) not in snapshot.as_posix()
    assert list((tmp_path / "bootstrap-tmp").iterdir()) == []


def test_kubeconfig_path_replacement_cannot_change_bound_cluster_bytes(
    tmp_path: Path,
) -> None:
    _, _, result, _, _, _, _, used_kubeconfig = _execute_fixture(tmp_path, replace_kubeconfig=True)

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "kubeconfig-swap-triggered").exists()
    used = used_kubeconfig.read_text(encoding="utf-8")
    assert "https://reviewed.invalid" in used
    assert "reviewed-token" in used
    assert "attacker.invalid" not in used
    assert "attacker-token" not in used


@pytest.mark.parametrize("age_state", ["invalid", "unrelated"])
def test_invalid_or_unrelated_age_identity_fails_before_mutation(tmp_path: Path, age_state: str) -> None:
    repo, before_sha, result, calls, applied_age, _, _, _ = _execute_fixture(tmp_path, age_state=age_state)

    assert result.returncode != 0
    invocations = calls.read_text(encoding="utf-8")
    assert " get namespace " not in invocations
    assert "flux " not in invocations
    assert _git(repo, "rev-parse", "HEAD") == before_sha
    assert not applied_age.exists()


def test_age_path_replacement_cannot_change_applied_snapshot_bytes(
    tmp_path: Path,
) -> None:
    _, _, result, _, applied_age, _, expected_age, _ = _execute_fixture(tmp_path, replace_age=True)

    assert result.returncode == 0, result.stderr
    assert applied_age.read_bytes() == expected_age


def test_consumer_path_swaps_cannot_change_bound_kubeconfig_or_age_bytes(
    tmp_path: Path,
) -> None:
    _, _, result, _, applied_age, _, expected_age, used_kubeconfig = _execute_fixture(
        tmp_path, replace_bound_snapshots=True
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / "bound-age-swap-triggered").exists()
    assert (tmp_path / "bound-kube-swap-triggered").exists()
    assert (tmp_path / "applied-age-swap-triggered").exists()
    assert (tmp_path / "age-keygen-used").read_text(encoding="ascii") == "reviewed\n"
    assert (tmp_path / "flux-kubeconfig-used").read_text(encoding="ascii") == "reviewed\n"
    assert applied_age.read_bytes() == expected_age
    assert b"https://reviewed.invalid" in used_kubeconfig.read_bytes()


def test_flux_file_replacement_cannot_change_the_committed_validated_blob(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, _, _, race_marker, _, _ = _execute_fixture(tmp_path, replace_flux=True)

    assert race_marker.exists(), "the validation-to-stage replacement was not injected"
    after_sha = _git(repo, "rev-parse", "HEAD")
    if after_sha != before_sha:
        committed = _git(
            repo,
            "show",
            f"{after_sha}:infra/k8s/gitops/clusters/local/flux-system/gotk-components.yaml",
        )
        assert committed == "validated-components"
    else:
        assert result.returncode != 0


def _assert_exact_bootstrap_commit(repo: Path, before_sha: str) -> None:
    after_sha = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "rev-parse", f"{after_sha}^") == before_sha
    changed = _git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", after_sha).splitlines()
    assert changed == [
        "infra/k8s/gitops/clusters/local/flux-system/gotk-components.yaml",
        "infra/k8s/gitops/clusters/local/flux-system/gotk-sync.yaml",
        "infra/k8s/gitops/clusters/local/flux-system/kustomization.yaml",
    ]


def test_arbitrary_local_hooks_never_execute_and_commit_exact_three_blob_tree(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, _, _, _, _, _ = _execute_fixture(tmp_path, install_hook=True)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "hook-index").exists()
    gate = (tmp_path / "gate-env").read_text(encoding="utf-8").splitlines()
    assert gate[:6] == [
        "token=",
        "age=",
        "kubeconfig=",
        "bootstrap_kube=",
        "bootstrap_source=",
        "bootstrap_age=",
    ]
    assert gate[6].startswith("index=")
    assert gate[6] != "index="
    _assert_exact_bootstrap_commit(repo, before_sha)


def test_concurrent_shared_index_entry_cannot_enter_bootstrap_commit(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, _, _, _, _, _ = _execute_fixture(tmp_path, inject_shared_index=True)

    assert (tmp_path / "shared-index-triggered").exists()
    assert result.returncode != 0
    assert _git(repo, "rev-parse", "HEAD") == before_sha
    assert not (tmp_path / "push-args").exists()


def test_hook_staged_path_replacement_is_never_executed(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, _, _, _, _, _ = _execute_fixture(tmp_path, install_hook=True, hook_mutates_flux=True)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "hook-index").exists()
    _assert_exact_bootstrap_commit(repo, before_sha)
    committed = _git(
        repo,
        "show",
        "HEAD:infra/k8s/gitops/clusters/local/flux-system/gotk-components.yaml",
    )
    assert committed == "validated-components"


def test_success_materializes_exact_validated_index_and_pristine_worktree(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, _, _, _, _, _ = _execute_fixture(tmp_path)

    assert result.returncode == 0, result.stderr
    assert _git(repo, "write-tree") == _git(repo, "rev-parse", "HEAD^{tree}")
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == ""
    _assert_exact_bootstrap_commit(repo, before_sha)


def test_post_update_ref_advance_cannot_change_explicit_pushed_sha(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, _, applied_age, _, _, _ = _execute_fixture(tmp_path, advance_ref_before_push=True)

    assert (tmp_path / "push-race-triggered").exists()
    assert result.returncode == 0, result.stderr
    assert _git(repo, "log", "-1", "--format=%s") == "post-update mutation"
    pushed_sha = _git(repo, "rev-parse", "HEAD^")
    assert _git(repo, "rev-parse", f"{pushed_sha}^") == before_sha
    push = (tmp_path / "push-args").read_text(encoding="utf-8")
    branch_ref = f"refs/heads/{_BRANCH}"
    assert f"{pushed_sha}:{branch_ref}" in push
    assert f"{branch_ref}:{branch_ref}" not in push
    assert (tmp_path / "remote-state").read_text(encoding="ascii").strip() == pushed_sha
    assert applied_age.exists()


def test_expected_old_ref_transaction_fails_safely_on_concurrent_head_change(
    tmp_path: Path,
) -> None:
    repo, before_sha, result, calls, applied_age, _, _, _ = _execute_fixture(tmp_path, inject_head_change=True)

    assert (tmp_path / "head-race-triggered").exists()
    assert result.returncode != 0
    assert _git(repo, "log", "-1", "--format=%s") == "concurrent mutation"
    assert _git(repo, "rev-parse", "HEAD^") == before_sha
    invocations = calls.read_text(encoding="utf-8")
    assert "flux --kubeconfig=" not in invocations
    assert " create secret generic flux-sops " not in invocations
    assert not applied_age.exists()


def test_execute_orders_review_push_trust_root_bootstrap_and_remote_verification(
    tmp_path: Path,
) -> None:
    _, _, result, calls, applied_age, _, _, _ = _execute_fixture(tmp_path)

    assert result.returncode == 0, result.stderr
    invocations = calls.read_text(encoding="utf-8").splitlines()
    absent = next(i for i, call in enumerate(invocations) if " get namespace flux-system " in call)
    push = invocations.index("git push runtime-control")
    remote_checks = [i for i, call in enumerate(invocations) if call == "git ls-remote runtime-control"]
    namespace = next(
        i
        for i, call in enumerate(invocations)
        if call.endswith(" create namespace flux-system --dry-run=client -o yaml")
    )
    age = next(i for i, call in enumerate(invocations) if " create secret generic flux-sops -n flux-system " in call)
    flux = next(i for i, call in enumerate(invocations) if " bootstrap github " in f" {call} ")

    assert len(remote_checks) == 3
    assert absent < push < remote_checks[1] < namespace < age < flux < remote_checks[2]
    assert applied_age.exists()
    assert result.stdout.endswith(
        "Flux one-time bootstrap completed; use normal reconcile for all subsequent convergence.\n"
    )
    assert "Flux bootstrap before Git SHA:" in result.stdout
    assert "Flux bootstrap after Git SHA:" in result.stdout
    assert "github-token-must-never-appear" not in result.stdout + result.stderr


def test_flux_failure_leaves_seeded_trust_root_and_withholds_command_output(
    tmp_path: Path,
) -> None:
    _, _, result, calls, applied_age, _, _, _ = _execute_fixture(tmp_path, flux_failure=True)

    assert result.returncode != 0
    assert result.stderr == (
        "Error: Flux cluster bootstrap failed; command output was withheld to protect credentials.\n"
    )
    assert "flux-bootstrap-private-output" not in result.stdout + result.stderr
    invocations = calls.read_text(encoding="utf-8")
    assert " create namespace flux-system --dry-run=client -o yaml" in invocations
    assert " create secret generic flux-sops -n flux-system " in invocations
    assert applied_age.exists()
    assert invocations.count("git ls-remote runtime-control") == 2


def test_flux_remote_write_is_rejected_after_trust_root_bootstrap(
    tmp_path: Path,
) -> None:
    _, _, result, calls, applied_age, _, _, _ = _execute_fixture(tmp_path, flux_remote_write=True)

    assert result.returncode != 0
    assert result.stderr == ("Error: Flux attempted an unreviewed Git write outside the pre-generated commit.\n")
    assert "Flux one-time bootstrap completed" not in result.stdout
    assert applied_age.exists()
    assert calls.read_text(encoding="utf-8").count("git ls-remote runtime-control") == 3


def test_reviewed_runtime_control_identity_is_the_only_accepted_identity(
    tmp_path: Path,
) -> None:
    repo, sha = _make_repo(tmp_path)
    result = _identity(repo, sha)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


def test_synthetic_environments_discard_ambient_workflow_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in _WORKFLOW_IDENTITY_VARIABLES:
        monkeypatch.setenv(name, "ambient-workflow-identity")
    repo, sha = _make_repo(tmp_path)

    result = _identity(repo, sha)
    assert result.returncode == 0, result.stderr
    environment = _bootstrap_env(sha, tmp_path / "calls")
    assert not (set(_WORKFLOW_IDENTITY_VARIABLES) & environment.keys())


@pytest.mark.parametrize(
    ("branch", "declared_branch"),
    [
        ("main", "main"),
        ("integration/remediation-clean", "integration/remediation-clean"),
        ("topic/flux-bootstrap", "topic/flux-bootstrap"),
        ("refs/pull/123/merge", "refs/pull/123/merge"),
        (_BRANCH, "runtime-control/local/Uppercase"),
    ],
)
def test_protected_topic_pr_and_invalid_runtime_control_branches_are_rejected(
    tmp_path: Path, branch: str, declared_branch: str
) -> None:
    repo, sha = _make_repo(tmp_path, branch)
    result = _identity(
        repo,
        sha,
        NOHIKI_RUNTIME_CONTROL_BRANCH=declared_branch,
        GITOPS_GITHUB_BRANCH=declared_branch,
    )
    assert result.returncode != 0
    assert "Error:" in result.stderr


def test_detached_head_missing_identity_and_unreviewed_sha_are_rejected(
    tmp_path: Path,
) -> None:
    repo, sha = _make_repo(tmp_path)
    _git(repo, "checkout", "--detach", sha)
    detached = _identity(repo, sha)
    assert detached.returncode != 0
    assert "detached HEAD is forbidden" in detached.stderr

    _git(repo, "checkout", _BRANCH)
    missing_branch = _identity(repo, sha, NOHIKI_RUNTIME_CONTROL_BRANCH="")
    assert missing_branch.returncode != 0
    assert "NOHIKI_RUNTIME_CONTROL_BRANCH is required" in missing_branch.stderr

    missing = _identity(repo, sha, NOHIKI_REVIEWED_TOPIC_SHA="")
    assert missing.returncode != 0
    assert "NOHIKI_REVIEWED_TOPIC_SHA is required" in missing.stderr

    wrong_sha = _identity(repo, "0" * 40)
    assert wrong_sha.returncode != 0
    assert "current HEAD does not equal NOHIKI_REVIEWED_TOPIC_SHA" in wrong_sha.stderr


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("GITHUB_REF", "refs/pull/123/merge"),
        ("GITHUB_REF_NAME", "main"),
        ("GITHUB_HEAD_REF", "topic/unreviewed"),
        ("GITHUB_SHA", "0" * 40),
    ],
)
def test_workflow_identity_mismatches_are_rejected(tmp_path: Path, name: str, value: str) -> None:
    repo, sha = _make_repo(tmp_path)
    result = _identity(repo, sha, **{name: value})
    assert result.returncode != 0
    assert name in result.stderr


def test_flux_state_accepts_only_absent_or_the_exact_three_regular_files(
    tmp_path: Path,
) -> None:
    flux_dir = tmp_path / "flux-system"
    absent = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; classify_flux_state "$2"',
            "bash",
            str(_POLICY),
            str(flux_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert absent.returncode == 0
    assert absent.stdout == "absent\n"

    flux_dir.mkdir()
    for name in _ALLOWED_OUTPUTS:
        (flux_dir / name).write_text(f"{name}\n", encoding="utf-8")
    complete = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; classify_flux_state "$2"; validate_flux_output_allowlist "$2"',
            "bash",
            str(_POLICY),
            str(flux_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert complete.returncode == 0, complete.stderr
    assert complete.stdout == "complete\n"


@pytest.mark.parametrize("mutation", ["partial", "unknown", "directory", "symlink"])
def test_partial_unknown_and_nonregular_flux_state_fail_closed(tmp_path: Path, mutation: str) -> None:
    flux_dir = tmp_path / "flux-system"
    flux_dir.mkdir()
    if mutation == "partial":
        (flux_dir / "gotk-components.yaml").write_text("components\n", encoding="utf-8")
    else:
        for name in _ALLOWED_OUTPUTS:
            (flux_dir / name).write_text(f"{name}\n", encoding="utf-8")
        if mutation == "unknown":
            (flux_dir / "extra.yaml").write_text("unknown\n", encoding="utf-8")
        elif mutation == "directory":
            (flux_dir / "nested").mkdir()
        else:
            (flux_dir / "gotk-sync.yaml").unlink()
            (flux_dir / "gotk-sync.yaml").symlink_to(flux_dir / "gotk-components.yaml")
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; classify_flux_state "$2"',
            "bash",
            str(_POLICY),
            str(flux_dir),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Error:" in result.stderr


def test_generated_diff_keeps_provenance_but_redacts_all_content() -> None:
    source_line = "github-token-must-never-appear"
    replacement_line = "age-fixture-value"
    raw = (
        "diff --git a/gotk-sync.yaml b/gotk-sync.yaml\n"
        "index 1111111..2222222 100644\n"
        "--- a/gotk-sync.yaml\n"
        "+++ b/gotk-sync.yaml\n"
        "@@ -1 +1 @@\n"
        f"-{source_line}\n+{replacement_line}\n context-secret\n"
    )
    result = _call_policy("redact_generated_diff", stdin=raw)
    assert result.returncode == 0, result.stderr
    assert "diff --git a/gotk-sync.yaml b/gotk-sync.yaml" in result.stdout
    assert "@@ -1 +1 @@" in result.stdout
    assert source_line not in result.stdout
    assert replacement_line not in result.stdout
    assert result.stdout.count("<redacted generated line>") == 2
    assert "<redacted context line>" in result.stdout


def test_execute_path_records_before_after_shas_and_only_redacted_diff() -> None:
    text = _BOOTSTRAP.read_text(encoding="utf-8")
    before = "printf 'Flux bootstrap before Git SHA: %s\\n' \"${before_sha}\""
    after = "printf 'Flux bootstrap after Git SHA: %s\\n' \"${after_sha}\""
    private_diff = 'GIT_INDEX_FILE="${private_index}" git -C "${repo}" diff --cached --no-ext-diff --no-color --'
    redacted_pathspec = '"${generated_paths[@]}" | redact_generated_diff'
    assert before in text
    assert private_diff in text
    assert redacted_pathspec in text
    assert after in text
    assert text.index(before) < text.index(private_diff)
    assert text.index(private_diff) < text.index(redacted_pathspec) < text.index(after)
    assert '>"${bootstrap_log}" 2>&1' in text


@pytest.mark.parametrize("mode", ["--validate", "--dry-run"])
@pytest.mark.parametrize("dirty_state", ["tracked", "untracked"])
def test_nonmutating_modes_reject_dirty_reviewed_sources_before_tools(
    tmp_path: Path, mode: str, dirty_state: str
) -> None:
    repo, sha, calls = _bootstrap_repo(tmp_path)
    if dirty_state == "tracked":
        (repo / "reviewed.txt").write_text("changed after review\n", encoding="utf-8")
    else:
        (repo / "unreviewed.txt").write_text("not reviewed\n", encoding="utf-8")

    script = repo / "infra" / "k8s" / "gitops" / "install" / "bootstrap.sh"
    result = _run(
        ["bash", str(script), mode],
        cwd=repo,
        env=_bootstrap_env(sha, calls),
    )

    assert result.returncode != 0
    assert "Flux bootstrap requires a pristine reviewed worktree" in result.stderr
    assert not calls.exists()


@pytest.mark.parametrize("mode", ["--validate", "--dry-run"])
def test_nonmutating_modes_write_no_git_bytes_or_kubernetes_state(tmp_path: Path, mode: str) -> None:
    repo, sha, calls = _bootstrap_repo(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(
        fake_bin / "flux",
        'printf \'%s\\n\' "$*" >>"$TEST_CALLS"\n'
        'case "$1 $2" in\n'
        "  'install --export') printf '%s\\n' 'apiVersion: v1' 'kind: List' ;;\n"
        "  'create source') printf '%s\\n' 'apiVersion: source.toolkit.fluxcd.io/v1' 'kind: GitRepository' ;;\n"
        "  'create kustomization')\n"
        "    printf '%s\\n' '---' 'apiVersion: kustomize.toolkit.fluxcd.io/v1' 'kind: Kustomization' ;;\n"
        "  *) exit 64 ;;\n"
        "esac\n",
    )
    _write_executable(fake_bin / "kubectl", 'printf "%s\\n" "$*" >>"$TEST_CALLS"\nexit 97\n')

    before_head = _git(repo, "rev-parse", "HEAD")
    before_tree = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    script = repo / "infra" / "k8s" / "gitops" / "install" / "bootstrap.sh"
    result = _run(
        ["bash", str(script), mode],
        cwd=repo,
        env=_bootstrap_env(sha, calls, fake_bin),
    )
    assert result.returncode == 0, result.stderr
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert _git(repo, "status", "--porcelain=v1", "--untracked-files=all") == before_tree
    invocations = calls.read_text(encoding="utf-8") if calls.exists() else ""
    assert "kubectl" not in invocations
    assert "bootstrap github" not in invocations
    if mode == "--validate":
        assert invocations == ""
        assert "bootstrap validation: runtime-control identity and pristine Flux state accepted" in result.stdout
    else:
        assert {line.split()[0] for line in invocations.splitlines()} == {
            "install",
            "create",
        }
        assert (
            "bootstrap dry-run: exact Flux output allowlist accepted; no Git or Kubernetes writes performed"
            in result.stdout
        )
    combined = result.stdout + result.stderr
    assert "github-token-must-never-appear" not in combined
    assert "age-key-must-never-appear" not in combined
