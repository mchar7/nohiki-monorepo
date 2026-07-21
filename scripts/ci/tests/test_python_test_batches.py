import tomllib
from collections import Counter
from pathlib import Path

import pytest
from ci_checks.core.change_gate import GateDecision
from ci_checks.core.change_gate import tests_matrix as build_tests_matrix
from ci_checks.core.packages import Package, PackageType, Scope, load_packages_with_deps
from ci_checks.core.test_batches import load_test_batches

_ROOT = Path(__file__).resolve().parents[3]
_BATCH_DATA = _ROOT / "scripts" / "ci" / "python-test-batches.toml"


def _weights() -> dict[str, int]:
    raw = tomllib.loads(_BATCH_DATA.read_text(encoding="utf-8"))["weights"]
    assert isinstance(raw, dict)
    assert all(isinstance(name, str) and isinstance(weight, int) and weight > 0 for name, weight in raw.items())
    return {name: weight for name, weight in raw.items() if isinstance(name, str) and isinstance(weight, int)}


def test_committed_batches_are_the_complete_greedy_lpt_partition() -> None:
    workspace = set(load_packages_with_deps(Scope.ALL))
    batches = load_test_batches()
    assigned = [package for batch in batches for package in batch.packages]
    weights = _weights()

    assert len(batches) == 3
    assert Counter(assigned) == Counter(dict.fromkeys(workspace, 1))
    assert set(weights) == workspace

    expected: list[tuple[list[str], int]] = [([], 0), ([], 0), ([], 0)]
    for package, weight in sorted(weights.items(), key=lambda item: (-item[1], item[0])):
        index = min(range(3), key=lambda candidate: (expected[candidate][1], candidate))
        packages, total = expected[index]
        expected[index] = ([*packages, package], total + weight)

    assert [set(batch.packages) for batch in batches] == [set(packages) for packages, _ in expected]
    totals = [sum(weights[package] for package in batch.packages) for batch in batches]
    assert max(totals) / min(totals) <= 1.2


def test_only_the_ci_checks_batch_requires_pnpm() -> None:
    batches = load_test_batches()
    assert [batch.needs_pnpm for batch in batches] == ["ci-checks" in batch.packages for batch in batches]


def test_matrix_fails_closed_when_a_workspace_package_is_unassigned(
    tmp_path: Path,
) -> None:
    packages = load_packages_with_deps(Scope.ALL)
    path = tmp_path / "new-package"
    path.mkdir()
    packages["new-package"] = Package("new-package", path, PackageType.OTHER)

    with pytest.raises(ValueError, match=r"missing=\['new-package'\]"):
        build_tests_matrix(GateDecision(full=True), packages)
