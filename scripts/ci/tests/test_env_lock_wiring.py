"""Contract checks for environment-mutating and environment-consuming commands."""

from __future__ import annotations

import os
import re
import shutil
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
_ZERO_SHA = "0" * 40


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _prepush_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-q", "-b", "main")
    _git(repository, "config", "user.name", "Test Owner")
    _git(repository, "config", "user.email", "owner@example.invalid")
    (repository / "tracked.txt").write_text("validated\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "fixture")
    validated_sha = _git(repository, "rev-parse", "HEAD")
    _git(repository, "update-ref", "refs/remotes/origin/main", validated_sha)

    dev_scripts = repository / "scripts/dev"
    dev_scripts.mkdir(parents=True)
    shutil.copy2(_ROOT / "scripts/dev/prepush-gate.sh", dev_scripts)
    mirror = dev_scripts / "secrets-mirror.sh"
    mirror.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mirror.chmod(0o755)
    return repository, validated_sha


def _run_prepush_gate(
    repository: Path,
    local_sha: str,
    *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [repository / "scripts/dev/prepush-gate.sh", "origin", "https://example.invalid/repository.git"],
        cwd=repository,
        input=f"refs/heads/runtime-control {local_sha} refs/heads/runtime-control {_ZERO_SHA}\n",
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


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
    assert "scripts/dev/prepush-gate.sh" in envelope["run"]
    # Git hands the ref pairs to the hook on standard input, and Lefthook gives a
    # job an empty stdin unless the job asks for it. Without this key the
    # envelope cannot tell which commit is being published.
    assert envelope["use_stdin"] is True
    assert all(inactive_skip[0] in phase["skip"] for phase in jobs[1:])

    # The mirror tripwire must run before the lock, resource scope, and
    # re-entrant pass so a sparse checkout cannot refresh destructively.
    gate = (_ROOT / "scripts" / "dev" / "prepush-gate.sh").read_text(encoding="utf-8")
    chain = (
        "scripts/dev/secrets-mirror.sh",
        "scripts/dev/env-lock.sh gate pre-push --",
        "scripts/dev/test-run.sh gate --",
        "env NOHIKI_GATE_ACTIVE=1",
        "lefthook run pre-push --no-auto-install",
    )
    offset = -1
    for fragment in chain:
        found = gate.find(fragment, offset + 1)
        assert found > offset, f"{fragment!r} missing from prepush-gate.sh or out of order"
        offset = found


def test_prepush_gate_cannot_report_success_having_inspected_nothing() -> None:
    """An empty push selection skips every job and exits zero; that must not pass.

    Lefthook picks pre-push files with `git diff --name-only HEAD @{push}`. When
    that resolves empty it skips unglobbed jobs too, so the gate reports success
    having run nothing. The envelope requires an unglobbed liveness job to have
    run, which is exactly the condition that job cannot satisfy when the
    selection is empty.
    """
    config = yaml.safe_load((_ROOT / "lefthook.yml").read_text(encoding="utf-8"))
    jobs = config["pre-push"]["jobs"]
    liveness = [job for job in jobs if job.get("name") == "gate-liveness"]

    assert len(liveness) == 1, "pre-push must define exactly one gate-liveness job"
    assert "glob" not in liveness[0], "the liveness job must not be glob-filtered"
    assert "NOHIKI_GATE_LIVENESS" in liveness[0]["run"]

    gate = (_ROOT / "scripts" / "dev" / "prepush-gate.sh").read_text(encoding="utf-8")
    assert 'if [ ! -e "$liveness" ]; then' in gate
    assert "inspected nothing" in gate


def test_prepush_gate_refuses_to_examine_a_tree_it_is_not_publishing() -> None:
    """The gate must not check one tree while git publishes another.

    `git push origin <rev>:refs/heads/x` from a parked checkout makes the jobs
    examine the worktree while git publishes <rev>, so they pass without ever
    reading the published code. The envelope compares trees rather than commit
    identity, which keeps `git push origin HEAD:refs/heads/x` and a detached
    HEAD on the tip working.
    """
    gate = (_ROOT / "scripts" / "dev" / "prepush-gate.sh").read_text(encoding="utf-8")

    assert "refusing to gate" in gate
    assert "HEAD^{tree}" in gate
    assert "${local_sha}^{tree}" in gate


def test_prepush_gate_passes_tip_already_validated_on_origin_main(tmp_path: Path) -> None:
    repository, validated_sha = _prepush_repository(tmp_path)

    result = _run_prepush_gate(repository, validated_sha)

    assert result.returncode == 0
    assert (
        "pre-push gate: passing refs/heads/runtime-control without checks; "
        f"merge-base with validated origin/main equals outgoing tip {validated_sha} "
        f"(origin/main {validated_sha}), so there are no commits beyond origin/main"
    ) in result.stderr
    assert "inspected nothing" not in result.stderr


def test_prepush_gate_keeps_beyond_main_push_fail_closed(tmp_path: Path) -> None:
    repository, _ = _prepush_repository(tmp_path)
    (repository / "tracked.txt").write_text("unvalidated\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-qm", "one commit beyond main")
    local_sha = _git(repository, "rev-parse", "HEAD")

    calls = tmp_path / "gate-calls"
    env_lock = repository / "scripts/dev/env-lock.sh"
    env_lock.write_text(
        '#!/bin/sh\nprintf "env-lock\\n" >> "$GATE_CALLS"\nshift 2\nshift\nexec "$@"\n',
        encoding="utf-8",
    )
    env_lock.chmod(0o755)
    test_run = repository / "scripts/dev/test-run.sh"
    test_run.write_text(
        '#!/bin/sh\nprintf "test-run\\n" >> "$GATE_CALLS"\nshift 2\nexec "$@"\n',
        encoding="utf-8",
    )
    test_run.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    lefthook = bindir / "lefthook"
    lefthook.write_text(
        '#!/bin/sh\nprintf "lefthook\\n" >> "$GATE_CALLS"\nexit 0\n',
        encoding="utf-8",
    )
    lefthook.chmod(0o755)

    result = _run_prepush_gate(
        repository,
        local_sha,
        env=os.environ
        | {
            "GATE_CALLS": str(calls),
            "PATH": f"{bindir}:{os.environ['PATH']}",
        },
    )

    assert result.returncode == 1
    assert calls.read_text(encoding="utf-8") == "env-lock\ntest-run\nlefthook\n"
    assert "pre-push gate: FAILED, the gate inspected nothing." in result.stderr


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
    assert "took slot 1 of 2 with no wait" in result.stderr
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


_GATE_BODY = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "trace = Path(sys.argv[1])\n"
    "with trace.open('a') as fh:\n"
    "    fh.write(f'{time.monotonic():.5f} ENTER\\n')\n"
    "time.sleep(float(sys.argv[2]))\n"
    "with trace.open('a') as fh:\n"
    "    fh.write(f'{time.monotonic():.5f} EXIT\\n')\n"
)


def _gate_env(tmp_path: Path, **extra: str) -> dict[str, str]:
    return (
        os.environ
        | {
            "XDG_RUNTIME_DIR": str(tmp_path),
            "NOHIKI_GATE_LOCK": "0",
            "NOHIKI_GATE_LOCK_POLL_INTERVAL": "1",
            "NOHIKI_GATE_LOCK_NOTICE_INTERVAL": "2",
            "NOHIKI_GATE_LOCK_TIMEOUT": "120",
            "NOHIKI_GATE_ESTIMATED_SECONDS": "10",
            "NOHIKI_GATE_SLOTS": "2",
        }
        | extra
    )


def _hold_gate(tmp_path: Path, trace: Path, seconds: float, **extra: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            _ROOT / "scripts/dev/env-lock.sh",
            "gate",
            "pre-push",
            "--",
            sys.executable,
            "-c",
            _GATE_BODY,
            str(trace),
            str(seconds),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=_gate_env(tmp_path, **extra),
    )


def _queue_waiter(tmp_path: Path, log: Path, **extra: str) -> subprocess.Popen[str]:
    with log.open("w", encoding="utf-8") as stderr:
        return subprocess.Popen(
            [_ROOT / "scripts/dev/env-lock.sh", "gate", "pre-push", "--", "true"],
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            text=True,
            env=_gate_env(tmp_path, **extra),
        )


def _await_slots_taken(trace: Path, count: int) -> None:
    deadline = time.monotonic() + 60
    while trace.read_text(encoding="utf-8").count("ENTER") < count and time.monotonic() < deadline:
        time.sleep(0.02)
    assert trace.read_text(encoding="utf-8").count("ENTER") == count


def _reap(processes: list[subprocess.Popen[str]]) -> None:
    for process in processes:
        process.kill()
        process.wait(timeout=60)
        if process.stderr is not None:
            process.stderr.close()


def _peak_overlap(trace: Path) -> int:
    events = sorted(
        (float(stamp), 1 if kind == "ENTER" else -1)
        for stamp, kind in (line.split() for line in trace.read_text(encoding="utf-8").splitlines())
    )
    current = peak = 0
    for _, delta in events:
        current += delta
        peak = max(peak, current)
    return peak


def test_machine_gate_admits_exactly_its_slot_count(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.touch()
    runs = [_hold_gate(tmp_path, trace, 2.0) for _ in range(5)]
    stderrs = [run.communicate()[1] for run in runs]

    assert [run.returncode for run in runs] == [0] * 5
    # The bound is the point of the lock: never more than two gate bodies at once, and
    # never fewer than two either, or the semaphore has degenerated back into a mutex.
    assert _peak_overlap(trace) == 2
    taken = sorted(int(match) for text in stderrs for match in re.findall(r"took slot (\d+) of 2", text))
    # Which process wins which slot is a kernel scheduling race, so the exact distribution
    # is not a contract. The contract is that every slot is in range and both are used.
    assert all(1 <= s <= 2 for s in taken)
    assert 1 in taken
    assert 2 in taken


def test_machine_gate_reports_queue_depth_and_estimated_wait(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.touch()
    holders = [_hold_gate(tmp_path, trace, 300.0) for _ in range(2)]
    _await_slots_taken(trace, 2)

    # Waiters join one at a time, each observed announcing itself before the next starts,
    # so the reported depth is checkable rather than racy.
    announcements: list[tuple[int, int]] = []
    waiters: list[subprocess.Popen[str]] = []
    for index in range(3):
        log = tmp_path / f"waiter{index}.err"
        waiters.append(_queue_waiter(tmp_path, log))
        deadline = time.monotonic() + 60
        match = None
        while match is None and time.monotonic() < deadline:
            match = re.search(
                r"queue depth (\d+) including you; estimated wait ~(\d+)s",
                log.read_text(encoding="utf-8"),
            )
            time.sleep(0.02)
        assert match is not None, f"waiter {index} never reported its queue position"
        announcements.append((int(match.group(1)), int(match.group(2))))
        assert f"worktree={_ROOT}" in log.read_text(encoding="utf-8")

    _reap(holders)
    for waiter in waiters:
        assert waiter.wait(timeout=120) == 0

    # depth counts live waiters; the estimate is ceil(depth / slots) * the per-gate estimate.
    assert announcements == [(1, 10), (2, 10), (3, 20)]


def test_machine_gate_queue_loop_fails_at_a_human_scale_timeout(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.touch()
    holders = [_hold_gate(tmp_path, trace, 300.0) for _ in range(2)]
    _await_slots_taken(trace, 2)

    started = time.monotonic()
    waiter = subprocess.run(
        [_ROOT / "scripts/dev/env-lock.sh", "gate", "pre-push", "--", "true"],
        capture_output=True,
        check=False,
        text=True,
        env=_gate_env(tmp_path, NOHIKI_GATE_LOCK_TIMEOUT="3"),
    )
    elapsed = time.monotonic() - started
    _reap(holders)

    assert waiter.returncode == 75
    assert "timed out after 3s with all 2 slots busy" in waiter.stderr
    assert "broken, not busy" in waiter.stderr
    assert elapsed < 30, f"the queue loop overshot its own timeout by {elapsed - 3:.1f}s"


def test_machine_gate_queue_loop_refuses_to_run_unserialised(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.touch()
    holders = [_hold_gate(tmp_path, trace, 300.0) for _ in range(2)]
    _await_slots_taken(trace, 2)

    log = tmp_path / "waiter.err"
    waiter = _queue_waiter(tmp_path, log)
    waiters_dir = tmp_path / "nohiki-gates" / "waiters"
    deadline = time.monotonic() + 60
    while not (waiters_dir.is_dir() and any(waiters_dir.iterdir())) and time.monotonic() < deadline:
        time.sleep(0.02)
    shutil.rmtree(tmp_path / "nohiki-gates")
    assert waiter.wait(timeout=60) == 70
    _reap(holders)

    assert "disappeared while queued; refusing to run unserialised" in log.read_text(encoding="utf-8")


def test_machine_gate_slot_releases_when_its_holder_is_killed(tmp_path: Path) -> None:
    trace = tmp_path / "trace"
    trace.touch()
    victims = [_hold_gate(tmp_path, trace, 600.0) for _ in range(2)]
    _await_slots_taken(trace, 2)
    lock_dir = tmp_path / "nohiki-gates"
    assert sorted(path.name for path in lock_dir.glob("*.holder")) == [
        "pre-push.holder",
        "pre-push.slot2.holder",
    ]

    _reap(victims)

    # SIGKILL runs no trap, so the metadata is deliberately stale here. The flock is not:
    # the body runs with fd 9 closed, so the kernel drops the lock with the holder shell.
    started = time.monotonic()
    recovered = subprocess.run(
        [_ROOT / "scripts/dev/env-lock.sh", "gate", "pre-push", "--", "echo", "recovered"],
        capture_output=True,
        check=True,
        text=True,
        env=_gate_env(tmp_path),
    )
    elapsed = time.monotonic() - started

    assert recovered.stdout == "recovered\n"
    assert "queued" not in recovered.stderr
    assert elapsed < 10, f"a killed holder wedged its slot for {elapsed:.1f}s"
    assert "reclaimed stale holder metadata" in recovered.stderr
    assert list(lock_dir.glob("*.holder")) == []


def test_machine_gate_slot_one_interlocks_with_the_pre_semaphore_lock(tmp_path: Path) -> None:
    """Worktrees lag across many commits, so a single-mutex holder must still exclude us.

    Modelled on a real collision: a scratch probe held /run/user/1000/nohiki-gates/pre-push.lock
    through the pre-semaphore wrapper while a publication queued behind it. Had slot 1 been
    renamed, the two would have contended on nothing and the machine would have carried one
    gate more than the bound.
    """
    lock_dir = tmp_path / "nohiki-gates"
    lock_dir.mkdir()
    legacy_lock = lock_dir / "pre-push.lock"
    trace = tmp_path / "trace"
    trace.touch()

    # Exactly what the pre-semaphore wrapper did: flock -x on pre-push.lock, then the body.
    legacy = subprocess.Popen(
        ["flock", "-x", str(legacy_lock), "sleep", "600"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        probe = subprocess.run(["flock", "-n", "-x", str(legacy_lock), "true"], check=False)
        if probe.returncode != 0:
            break
        time.sleep(0.02)
    assert probe.returncode != 0, "the legacy holder never acquired pre-push.lock"

    # One slot is now unavailable, so a single gate still runs and takes slot 2.
    admitted = _hold_gate(tmp_path, trace, 0.2)
    admitted_stderr = admitted.communicate()[1]
    assert admitted.returncode == 0
    assert "took slot 2 of 2" in admitted_stderr

    # And the bound holds across the two implementations: with slot 2 also taken, the
    # third arrival queues rather than becoming a third machine-wide gate.
    holder = _hold_gate(tmp_path, trace, 600.0)
    _await_slots_taken(trace, 2)
    blocked = subprocess.run(
        [_ROOT / "scripts/dev/env-lock.sh", "gate", "pre-push", "--", "true"],
        capture_output=True,
        check=False,
        text=True,
        env=_gate_env(tmp_path, NOHIKI_GATE_LOCK_TIMEOUT="3"),
    )
    _reap([holder])
    legacy.kill()
    legacy.wait(timeout=60)

    assert blocked.returncode == 75
    assert "all 2 slots busy" in blocked.stderr


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
