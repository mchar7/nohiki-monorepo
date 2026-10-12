"""The load harness carries no workspace package, so this lane runs its tests."""

import subprocess

from ci_checks.core.packages import REPO_ROOT


def test_load_probe_tests_run_through_the_shared_recipe() -> None:
    """`load-check` is a local-only recipe, so this lane is where these tests run in CI."""
    result = subprocess.run(
        ["just", "load-check-tests"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert " passed" in result.stdout
