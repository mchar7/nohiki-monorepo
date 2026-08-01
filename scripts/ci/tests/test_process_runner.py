"""Black-box regressions for asynchronous package test execution."""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path

import pytest
from ci_checks.checks import tests as test_runner
from ci_checks.core.packages import Package, PackageType


@pytest.mark.asyncio
async def test_run_package_tests_drains_large_stdout_and_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A long pytest line and noisy stderr must not deadlock or lose evidence."""
    package_path = tmp_path / "package"
    (package_path / "tests").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stdout.write('PASSED ' + 'o' * 70000 + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write('diagnostic ' + 'e' * 70000 + '\\n')\n"
        "sys.stderr.flush()\n"
        "raise SystemExit(7)\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    monkeypatch.setattr(test_runner, "sanitized_python_env", lambda *, extra=None, **_k: environment | (extra or {}))

    progress: list[int] = []
    result = await test_runner.run_package_tests(
        Package(name="synthetic-package", path=package_path, pkg_type=PackageType.SCRIPTS),
        markers="",
        extra_args=(),
        with_coverage=False,
        progress_callback=progress.append,
    )

    assert result.passed is False
    assert result.output.startswith("PASSED ")
    assert "diagnostic " in result.output
    assert "PASSED " + "o" * 70000 + "\n" in result.output
    assert "diagnostic " + "e" * 70000 + "\n" in result.output
    assert progress == [1]


@pytest.mark.asyncio
async def test_run_package_tests_timeout_kills_and_reaps_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The watchdog kills and reaps a child holding both output pipes open."""
    package_path = tmp_path / "package"
    (package_path / "tests").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    pid_file = tmp_path / "child.pid"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        "Path(os.environ['CHILD_PID_FILE']).write_text(str(os.getpid()))\n"
        "print('child-started', flush=True)\n"
        "print('child-diagnostic', file=sys.stderr, flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["CHILD_PID_FILE"] = str(pid_file)
    monkeypatch.setattr(test_runner, "sanitized_python_env", lambda *, extra=None, **_k: environment | (extra or {}))
    child_started = asyncio.Event()
    watchdog_fired = asyncio.Event()

    async def controlled_watchdog(_: asyncio.subprocess.Process) -> None:
        await child_started.wait()
        watchdog_fired.set()
        raise TimeoutError

    monkeypatch.setattr(test_runner, "_wait_for_package_process", controlled_watchdog)

    child_pid: int | None = None
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                test_runner.run_package_tests(
                    Package(
                        name="synthetic-timeout",
                        path=package_path,
                        pkg_type=PackageType.SCRIPTS,
                    ),
                    markers="",
                    extra_args=(),
                    with_coverage=False,
                    progress_callback=lambda _: child_started.set(),
                ),
                timeout=30.0,
            )
        assert watchdog_fired.is_set()
        child_pid = int(pid_file.read_text(encoding="utf-8"))

        with pytest.raises(ProcessLookupError):
            os.kill(child_pid, 0)
    finally:
        if child_pid is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child_pid, 9)
