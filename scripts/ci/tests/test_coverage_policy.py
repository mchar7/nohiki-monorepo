"""Regression tests for coverage omit cancellation and the no-statements policy branch."""

from __future__ import annotations

import configparser
from pathlib import Path, PurePath

from ci_checks.checks.tests import (
    CoverageResult,
    FileCoverage,
    _check_exit_conditions,
    _coverage_meets_policy,
    _coverage_target,
    _omit_blanks_source,
    _root_coverage_values,
    _source_has_statements,
    _write_consolidated_coverage_config,
)
from ci_checks.checks.tests import (
    TestResult as RunnerTestResult,
)
from ci_checks.core.packages import Package, PackageType, Scope, load_packages
from coverage.files import GlobMatcher
from rich.console import Console

_DOMAIN_MODELS = "nohiki-domain-models"


def _selected_packages() -> list[Package]:
    return load_packages(Scope.ALL, require_tests=True)


def _written_omit(tmp_path: Path, packages: list[Package]) -> list[str]:
    config_path = tmp_path / "coverage.ini"
    _write_consolidated_coverage_config(config_path, packages)
    parser = configparser.ConfigParser()
    parser.read(config_path, encoding="utf-8")
    return [line for line in parser["run"]["omit"].splitlines() if line]


def _package(tmp_path: Path, name: str, src_dir: str) -> Package:
    path = tmp_path / name
    (path / src_dir).mkdir(parents=True)
    (path / "pyproject.toml").write_text(f'[tool.pytest.ini_options]\naddopts = "--cov={src_dir}"\n', encoding="utf-8")
    return Package(name=name, path=path, pkg_type=PackageType.LIB)


def test_omit_cancellation_fires_for_a_five_component_source_target() -> None:
    """A four-component omit must cancel against the five-component target it blanks."""
    packages = _selected_packages()
    domain_models = next(pkg for pkg in packages if pkg.name == _DOMAIN_MODELS)
    target = _coverage_target(domain_models)
    pattern = f"backend/libs/{_DOMAIN_MODELS}/*"

    assert pattern in _root_coverage_values("run", "omit")
    assert len(PurePath(target).parts) == len(PurePath(pattern).parts) + 1
    # The defect: PurePath.full_match stops a `*` at the separator, coverage.py does not.
    assert not PurePath(target).full_match(pattern)
    assert _omit_blanks_source(pattern, [target])


def test_written_config_drops_the_omit_that_blanks_a_selected_package(tmp_path: Path) -> None:
    packages = _selected_packages()
    omit = _written_omit(tmp_path, packages)

    assert f"backend/libs/{_DOMAIN_MODELS}/*" not in omit
    # Omits that hit no selected source target stay in force.
    assert {"*/tests/*", "*/__pycache__/*", "*/alembic/*"} <= set(omit)


def test_no_root_omit_survives_that_coverage_would_apply_to_a_selected_target(tmp_path: Path) -> None:
    """Mechanical sweep: every pattern coverage.py would apply to a target must be cancelled."""
    packages = _selected_packages()
    targets = [_coverage_target(pkg) for pkg in packages]
    survivors = _written_omit(tmp_path, packages)

    blanking = [
        (pattern, target) for pattern in survivors for target in targets if GlobMatcher([pattern]).match(target)
    ]
    assert blanking == []


def test_generated_output_stays_outside_the_measured_target() -> None:
    """The package scopes coverage to hand-written source; betterproto2 output is not measured."""
    domain_models = next(pkg for pkg in _selected_packages() if pkg.name == _DOMAIN_MODELS)
    target = _coverage_target(domain_models)

    assert target.endswith("src/nohiki_domain_utils")
    assert _source_has_statements(domain_models)


def test_blanked_package_does_not_report_pass() -> None:
    blanked = RunnerTestResult(name="blanked", passed=True, source_has_statements=True)

    assert not _coverage_meets_policy(blanked)
    assert _check_exit_conditions([blanked], strict=True, with_coverage=True)


def test_code_free_namespace_package_is_not_a_coverage_failure() -> None:
    namespace = RunnerTestResult(name="namespace", passed=True, source_has_statements=False)

    assert _coverage_meets_policy(namespace)
    assert not _check_exit_conditions([namespace], strict=True, with_coverage=True)


def test_measured_package_still_answers_to_its_gate() -> None:
    covered = CoverageResult(total_coverage=95.0, files=[FileCoverage(path="a.py", stmts=20, miss=1, cover=95.0)])
    thin = CoverageResult(total_coverage=10.0, files=[FileCoverage(path="a.py", stmts=20, miss=18, cover=10.0)])

    assert _coverage_meets_policy(
        RunnerTestResult(name="ok", passed=True, coverage=covered, pkg_type=PackageType.LIB, source_has_statements=True)
    )
    assert not _coverage_meets_policy(
        RunnerTestResult(name="thin", passed=True, coverage=thin, pkg_type=PackageType.LIB, source_has_statements=True)
    )


def test_source_has_statements_ignores_docstring_only_and_empty_modules(tmp_path: Path) -> None:
    pkg = _package(tmp_path, "ns-pkg", "src/ns_pkg")
    source = pkg.path / "src" / "ns_pkg"
    (source / "__init__.py").write_text('"""Namespace only."""\n', encoding="utf-8")
    (source / "blank.py").write_text("", encoding="utf-8")

    assert not _source_has_statements(pkg)

    (source / "real.py").write_text('"""Doc."""\n\nVALUE = 1\n', encoding="utf-8")
    assert _source_has_statements(pkg)


def test_blanked_package_is_reported_loudly() -> None:
    from ci_checks.checks.tests import display_coverage_summary

    console = Console(record=True, width=200)
    display_coverage_summary(
        [RunnerTestResult(name="blanked", passed=True, source_has_statements=True)],
        console,
    )
    output = console.export_text()

    assert "blanked" in output
    assert "coverage measured none" in output
