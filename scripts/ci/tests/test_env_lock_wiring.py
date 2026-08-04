"""Contract checks for environment-mutating and environment-consuming commands."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_LOCK_WRAPPER = "scripts/dev/env-lock.sh"
_LOCK_INVOCATION = (f"{_LOCK_WRAPPER} ", "{{ env_lock }} ")
_DEV_SYNC_SHAPE = "--all-packages --all-extras --no-extra cuda --group deadcode"


def _runs(value: object) -> list[str]:
    if isinstance(value, Mapping):
        runs: list[str] = []
        for key, item in value.items():
            if key == "run" and isinstance(item, str):
                runs.append(item)
            else:
                runs.extend(_runs(item))
        return runs
    if isinstance(value, list):
        return [run for item in value for run in _runs(item)]
    return []


def test_lefthook_environment_commands_use_shared_locks() -> None:
    config = yaml.safe_load((_ROOT / "lefthook.yml").read_text(encoding="utf-8"))

    for command in _runs(config):
        if "uv run" in command:
            assert f"{_LOCK_WRAPPER} shared venv --" in command
            assert "uv run --no-sync" in command
        if "pnpm" in command:
            assert f"{_LOCK_WRAPPER} shared node_modules --" in command


def test_justfile_environment_commands_use_mode_matching_locks() -> None:
    commands = [
        line.strip()
        for line in (_ROOT / "Justfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("    ") and not line.lstrip().startswith("#")
    ]

    sync_commands = [command for command in commands if "uv sync" in command]
    assert sync_commands
    for command in sync_commands:
        assert any(f"{invocation}exclusive venv --" in command for invocation in _LOCK_INVOCATION)

    for command in commands:
        if "uv run" in command:
            assert any(f"{invocation}shared venv --" in command for invocation in _LOCK_INVOCATION)
            assert "uv run --no-sync" in command
        if "pnpm" in command:
            assert any(f"{invocation}shared node_modules --" in command for invocation in _LOCK_INVOCATION)


def test_development_sync_shape_is_identical() -> None:
    justfile = (_ROOT / "Justfile").read_text(encoding="utf-8")
    flake = (_ROOT / "flake.nix").read_text(encoding="utf-8")
    just_syncs = [line for line in justfile.splitlines() if "uv sync" in line]
    flake_syncs = [line for line in flake.splitlines() if "uv sync" in line and _DEV_SYNC_SHAPE in line]

    assert len(just_syncs) == 2
    assert len(flake_syncs) == 1
    assert all(_DEV_SYNC_SHAPE in line for line in [*just_syncs, *flake_syncs])
    assert "--locked" in flake_syncs[0]


def test_prepush_gate_envelopes_every_phase() -> None:
    config = yaml.safe_load((_ROOT / "lefthook.yml").read_text(encoding="utf-8"))
    jobs = config["pre-push"]["jobs"]
    envelope = jobs[0]
    inactive_skip = [{"run": 'test "${NOHIKI_GATE_ACTIVE:-0}" != 1'}]

    assert envelope["skip"] == [{"run": 'test "${NOHIKI_GATE_ACTIVE:-0}" = 1'}]
    assert "scripts/dev/env-lock.sh gate pre-push --" in envelope["run"]
    assert "scripts/dev/test-run.sh gate --" in envelope["run"]
    assert "env NOHIKI_GATE_ACTIVE=1 lefthook run pre-push" in envelope["run"]
    assert all(phase["skip"] == inactive_skip for phase in jobs[1:])


def test_nested_lock_invocation_is_reentrant() -> None:
    wrapper = _ROOT / "scripts" / "dev" / "env-lock.sh"
    result = subprocess.run(
        [
            "timeout",
            "10",
            str(wrapper),
            "shared",
            "venv",
            "--",
            str(wrapper),
            "exclusive",
            "venv",
            "--",
            "true",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
    assert result.stderr == ""


def test_nested_gate_inherits_marker_and_bypasses_machine_lock(tmp_path: Path) -> None:
    wrapper = _ROOT / "scripts/dev/env-lock.sh"
    result = subprocess.run(
        [
            "timeout",
            "10",
            wrapper,
            "gate",
            "pre-push",
            "--",
            wrapper,
            "gate",
            "pre-push",
            "--",
            sys.executable,
            "-c",
            "print('nested')",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "XDG_RUNTIME_DIR": str(tmp_path),
            "NOHIKI_GATE_LOCK": "0",
        },
    )

    assert result.stdout == "nested\n"
    assert result.stderr == ""
    assert not (tmp_path / "nohiki-gates/pre-push.holder").exists()


def test_test_run_falls_through_when_oom_priority_is_unavailable(
    tmp_path: Path,
) -> None:
    choom = tmp_path / "choom"
    choom.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    choom.chmod(0o755)
    result = subprocess.run(
        [_ROOT / "scripts/dev/test-run.sh", sys.executable, "-c", "print('passed')"],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ | {"PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.stdout == "passed\n"
    assert result.stderr == ""


def test_test_run_requests_oom_priority_for_probe_and_test_process(
    tmp_path: Path,
) -> None:
    log = tmp_path / "choom.log"
    choom = tmp_path / "choom"
    choom.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CHOOM_LOG"\nshift 3\nexec "$@"\n',
        encoding="utf-8",
    )
    choom.chmod(0o755)
    result = subprocess.run(
        [_ROOT / "scripts/dev/test-run.sh", sys.executable, "-c", "print('passed')"],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "CHOOM_LOG": str(log),
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        },
    )

    invocations = log.read_text(encoding="utf-8").splitlines()
    assert invocations[0] == "-n 900 -- true"
    assert invocations[1].startswith(f"-n 900 -- {sys.executable} -c ")
    assert result.stdout == "passed\n"
    assert result.stderr == ""


def test_machine_gate_serializes_worktrees_and_reports_holder(tmp_path: Path) -> None:
    wrapper = _ROOT / "scripts/dev/env-lock.sh"
    release = tmp_path / "release"
    env = os.environ | {
        "XDG_RUNTIME_DIR": str(tmp_path),
        "NOHIKI_GATE_LOCK": "0",
        "NOHIKI_GATE_LOCK_TIMEOUT": "30",
        "NOHIKI_GATE_LOCK_NOTICE_INTERVAL": "1",
    }
    holder = subprocess.Popen(
        [
            wrapper,
            "gate",
            "pre-push",
            "--",
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path\n"
            "release = Path(sys.argv[1])\n"
            "while not release.exists(): time.sleep(0.01)",
            str(release),
        ],
        env=env,
    )
    holder_file = tmp_path / "nohiki-gates" / "pre-push.holder"
    deadline = time.monotonic() + 30
    while not holder_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert holder_file.exists()

    queue_log = tmp_path / "queue.log"
    with queue_log.open("w", encoding="utf-8") as stderr:
        waiter = subprocess.Popen(
            [wrapper, "gate", "pre-push", "--", sys.executable, "-c", "print('second')"],
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            env=env,
        )
        deadline = time.monotonic() + 30
        while "still queued after 1s" not in queue_log.read_text(encoding="utf-8") and time.monotonic() < deadline:
            time.sleep(0.01)
        queued_while_alive = queue_log.read_text(encoding="utf-8")
        assert "pre-push gate still queued after 1s: holder pid=" in queued_while_alive
        assert waiter.poll() is None
        release.touch()
        stdout, _ = waiter.communicate(timeout=30)

    assert holder.wait(timeout=30) == 0
    assert waiter.returncode == 0
    assert stdout == "second\n"
    queued = queue_log.read_text(encoding="utf-8")
    assert "pre-push gate queued: holder pid=" in queued
    assert f"worktree={_ROOT}" in queued


def test_machine_gate_wait_is_bounded(tmp_path: Path) -> None:
    wrapper = _ROOT / "scripts/dev/env-lock.sh"
    release = tmp_path / "release"
    holder_env = os.environ | {
        "XDG_RUNTIME_DIR": str(tmp_path),
        "NOHIKI_GATE_LOCK": "0",
    }
    holder = subprocess.Popen(
        [
            wrapper,
            "gate",
            "pre-push",
            "--",
            sys.executable,
            "-c",
            "import sys, time; from pathlib import Path\n"
            "release = Path(sys.argv[1])\n"
            "while not release.exists(): time.sleep(0.01)",
            str(release),
        ],
        env=holder_env,
    )
    holder_file = tmp_path / "nohiki-gates" / "pre-push.holder"
    deadline = time.monotonic() + 30
    while not holder_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert holder_file.exists()

    waiter = subprocess.run(
        [wrapper, "gate", "pre-push", "--", "true"],
        capture_output=True,
        check=False,
        text=True,
        env=holder_env | {"NOHIKI_GATE_LOCK_TIMEOUT": "0"},
    )
    assert waiter.returncode == 75
    assert "timed out after 0s" in waiter.stderr
    release.touch()
    assert holder.wait(timeout=30) == 0


def test_machine_gate_reclaims_stale_holder_metadata(tmp_path: Path) -> None:
    wrapper = _ROOT / "scripts/dev/env-lock.sh"
    lock_dir = tmp_path / "nohiki-gates"
    lock_dir.mkdir()
    holder_file = lock_dir / "pre-push.holder"
    holder_file.write_text("pid=999999999 worktree=/stale/worktree\n", encoding="utf-8")

    result = subprocess.run(
        [wrapper, "gate", "pre-push", "--", sys.executable, "-c", "print('reclaimed')"],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "XDG_RUNTIME_DIR": str(tmp_path),
            "NOHIKI_GATE_LOCK": "0",
        },
    )

    assert result.stdout == "reclaimed\n"
    assert "pre-push gate: reclaimed stale holder metadata pid=999999999" in result.stderr
    assert not holder_file.exists()


def test_gate_scope_falls_back_when_user_systemd_is_unavailable(tmp_path: Path) -> None:
    systemd_run = tmp_path / "systemd-run"
    systemd_run.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    systemd_run.chmod(0o755)
    result = subprocess.run(
        [
            _ROOT / "scripts/dev/test-run.sh",
            "gate",
            "--",
            sys.executable,
            "-c",
            "print('plain')",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=os.environ
        | {
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "NOHIKI_TEST_NPROC": "20",
        },
    )
    assert result.stdout == "plain\n"
    assert "systemd user scope unavailable; using plain execution" in result.stderr


def test_gate_workers_follow_effective_cgroup_quota(tmp_path: Path) -> None:
    cgroup = tmp_path / "cgroup"
    scope = cgroup / "user.slice" / "gate.scope"
    scope.mkdir(parents=True)
    (cgroup / "cpu.max").write_text("max 100000\n", encoding="utf-8")
    (cgroup / "user.slice" / "cpu.max").write_text("800000 100000\n", encoding="utf-8")
    (scope / "cpu.max").write_text("250000 100000\n", encoding="utf-8")
    env = os.environ | {
        "NOHIKI_TEST_NPROC": "20",
        "NOHIKI_TEST_CGROUP_ROOT": str(cgroup),
        "NOHIKI_TEST_CGROUP_PATH": "/user.slice/gate.scope",
    }

    workers = subprocess.run(
        [_ROOT / "scripts/dev/test-run.sh", "workers"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    bounded = subprocess.run(
        [
            _ROOT / "scripts/dev/test-run.sh",
            "gate-body",
            "--",
            sys.executable,
            "-c",
            (
                "import os; print(os.environ['NOHIKI_GATE_CPUS']); "
                "print(os.environ['NOHIKI_NIX_MAX_JOBS']); "
                "print(os.environ['NOHIKI_NIX_CORES'])"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert workers.stdout == "2\n"
    assert bounded.stdout == "2\n2\n1\n"
