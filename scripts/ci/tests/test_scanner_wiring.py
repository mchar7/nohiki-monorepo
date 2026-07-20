"""Focused contracts for deterministic source scanners."""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
import yaml
from ci_checks.checks import deadcode as deadcode_check
from ci_checks.checks.deadcode import (
    DeadCodeFinding,
    DeadCodeResult,
    DeadCodeScanOptions,
    SeverityLevel,
    _build_skylos_cmd,
    _collect_scan_paths,
)
from ci_checks.core.packages import Package, PackageType

_ROOT = Path(__file__).resolve().parents[3]
_CI_PROJECT = tomllib.loads((_ROOT / "scripts" / "ci" / "pyproject.toml").read_text(encoding="utf-8"))
_LEFTHOOK_CONFIG = yaml.safe_load((_ROOT / "lefthook.yml").read_text(encoding="utf-8"))
_SEMGREP_OVERRIDES = (_ROOT / "semgrep-overrides.txt").read_text(encoding="utf-8").splitlines()
_DEADCODE_SWEEP = yaml.safe_load((_ROOT / ".github" / "workflows" / "deadcode-sweep.yml").read_text(encoding="utf-8"))


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _options() -> DeadCodeScanOptions:
    return DeadCodeScanOptions(
        confidence=80,
        llm=False,
        llm_model="",
        api_base=None,
        verify=False,
        trace=False,
        gate=False,
        strict=False,
        baseline=False,
        provenance=False,
        no_provenance=False,
        provenance_base=None,
        diff=None,
        diff_base=None,
        github=False,
        summary=False,
        severity=SeverityLevel.HIGH,
        file_filter=None,
        limit=None,
        no_grep_verify=False,
        include_tests=False,
        include_parameters=False,
    )


@pytest.mark.asyncio
async def test_deadcode_fails_closed_without_ripgrep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skylos must fail closed and receive enough bounded verification time."""
    captured_extra: Mapping[str, str] | None = None

    def capture_env(*, extra: Mapping[str, str]) -> dict[str, str]:
        nonlocal captured_extra
        captured_extra = extra
        return {"PATH": ""}

    monkeypatch.setattr(deadcode_check, "sanitized_python_env", capture_env)
    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: None)

    async def unexpected_spawn(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", unexpected_spawn)
    package = Package(name="package", path=_ROOT, pkg_type=PackageType.OTHER)

    results = await deadcode_check.scan_scope([package], _options())

    assert captured_extra == {"OTEL_SDK_DISABLED": "true", "SKYLOS_GREP_BUDGET": "120"}
    assert [(result.name, result.passed, result.error) for result in results] == [
        (
            "scanner-preflight",
            False,
            "ripgrep (rg) is required for deterministic Skylos grep verification",
        )
    ]


def test_deadcode_inputs_ignore_local_caches_and_generated_outputs(
    tmp_path: Path,
) -> None:
    """Ignored worktree artifacts cannot add references or suppress findings."""
    _run_git(tmp_path, "init", "--quiet")
    package_root = tmp_path / "package"
    src = package_root / "src"
    src.mkdir(parents=True)
    (tmp_path / ".gitignore").write_text("__pycache__/\npackage/src/generated/\n", encoding="utf-8")
    (src / "live.py").write_text("def live() -> None:\n    pass\n", encoding="utf-8")
    _run_git(tmp_path, "add", ".gitignore", "package/src/live.py")
    package = Package(name="package", path=package_root, pkg_type=PackageType.OTHER)

    clean_inputs = _collect_scan_paths([package], include_tests=False, repo_root=tmp_path)
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "cache.py").write_text("live()\n", encoding="utf-8")
    (src / "generated").mkdir()
    (src / "generated" / "output.py").write_text("live()\n", encoding="utf-8")
    (src / "scratch.py").write_text("live()\n", encoding="utf-8")

    local_inputs = _collect_scan_paths([package], include_tests=False, repo_root=tmp_path)

    assert clean_inputs == local_inputs == ["package/src/live.py"]
    assert _collect_scan_paths([], include_tests=False, repo_root=tmp_path) == []

    generated_root = tmp_path / "backend" / "libs" / "nohiki-domain-models"
    generated_src = generated_root / "src"
    generated_src.mkdir(parents=True)
    (generated_src / "models.py").write_text("class GeneratedModel:\n    pass\n", encoding="utf-8")
    _run_git(tmp_path, "add", "backend/libs/nohiki-domain-models/src/models.py")
    generated = Package(name="nohiki-domain-models", path=generated_root, pkg_type=PackageType.LIB)
    assert _collect_scan_paths([generated], include_tests=False, repo_root=tmp_path) == []


def test_deadcode_command_uses_locked_skylos_offline_whole_graph() -> None:
    """The scanner must use the workspace lock, stay offline, and verify the whole graph."""
    command = _build_skylos_cmd(
        ["package/src/live.py"],
        _options(),
    )

    assert command[:3] == [sys.executable, "-m", "skylos.cli"]
    assert len(deadcode_dependencies := _CI_PROJECT["dependency-groups"]["deadcode"]) == 1
    assert re.fullmatch(r"skylos==\d+\.\d+\.\d+", deadcode_dependencies[0])
    assert "uvx" not in command
    assert "--cache" not in command
    # name-only baseline fingerprints suppress globally; the clean corpus needs no baseline
    assert "--baseline" not in command
    assert "--no-upload" in command
    assert "--diff" not in command
    assert "--no-grep-verify" not in command


def test_deadcode_baseline_gate_passes_known_findings_and_fails_new_findings() -> None:
    """Skylos baseline filtering must feed fail-on-findings without reinterpretation."""
    baselined = DeadCodeResult(name="package", passed=True)
    new = DeadCodeResult(
        name="package",
        passed=False,
        findings=[
            DeadCodeFinding(
                name="new_dead_function",
                file="package/src/live.py",
                line=1,
                kind="function",
                confidence=100,
                message="unused",
            )
        ],
    )

    assert deadcode_check.render_results([baselined], fail_on_findings=True)
    assert not deadcode_check.render_results([new], fail_on_findings=True)


def test_weekly_deadcode_sweep_keeps_full_grep_verification() -> None:
    """The scheduled safety net must retain the expensive full-corpus verifier."""
    jobs = cast("Mapping[str, object]", cast("Mapping[str, object]", _DEADCODE_SWEEP)["jobs"])
    sweep = cast("Mapping[str, object]", jobs["sweep"])
    steps = cast("list[Mapping[str, object]]", sweep["steps"])
    scan = next(step for step in steps if step.get("id") == "scan")
    command = cast("str", scan["run"])

    assert "--scope all" in command
    assert "--baseline" not in command
    assert "--no-grep-verify" not in command

    assert not any(step.get("name") == "Cache Skylos analysis" for step in steps)

    install = next(step for step in steps if step.get("name") == "Install workspace (all packages + extras)")
    assert "--group deadcode" in cast("str", install["run"])


def test_deadcode_gate_disables_history_provenance() -> None:
    """A clean gate verdict cannot depend on refs absent from a shallow clone."""
    pre_push = cast("Mapping[str, object]", _LEFTHOOK_CONFIG)["pre-push"]
    groups = cast("list[object]", cast("Mapping[str, object]", pre_push)["jobs"])
    deadcode_jobs = [
        cast("Mapping[str, object]", job)
        for group in groups
        if isinstance(group, dict) and isinstance(group.get("group"), dict)
        for job in cast("Mapping[str, object]", group["group"]).get("jobs", [])
        if isinstance(job, dict) and job.get("name") == "deadcode"
    ]

    assert len(deadcode_jobs) == 1
    assert cast("str", deadcode_jobs[0]["run"]).endswith("--no-provenance")


def test_semgrep_uses_pinned_host_runtime() -> None:
    """The uv scanner must not inherit Nix's dynamic-library search path."""
    pre_push = cast("Mapping[str, object]", _LEFTHOOK_CONFIG)["pre-push"]
    jobs = cast("Mapping[str, object]", pre_push)["jobs"]
    semgrep_jobs = [
        cast("Mapping[str, object]", job)
        for group in cast("list[object]", jobs)
        if isinstance(group, dict) and isinstance(group.get("group"), dict)
        for job in cast("Mapping[str, object]", group["group"]).get("jobs", [])
        if isinstance(job, dict) and job.get("name") == "semgrep"
    ]
    overrides = _SEMGREP_OVERRIDES

    assert len(semgrep_jobs) == 1
    assert cast("str", semgrep_jobs[0]["run"]).startswith("env -u LD_LIBRARY_PATH uvx --override ")
    assert overrides == ["semgrep==1.170.0", "ruamel-yaml-clib>=0.2.15"]
