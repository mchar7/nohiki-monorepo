"""Focused contracts for deterministic source scanners."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
import yaml
from ci_checks.app import app
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
from typer.testing import CliRunner

_ROOT = Path(__file__).resolve().parents[3]
_CI_PROJECT = tomllib.loads((_ROOT / "scripts" / "ci" / "pyproject.toml").read_text(encoding="utf-8"))
_ROOT_PROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
_LEFTHOOK_CONFIG = yaml.safe_load((_ROOT / "lefthook.yml").read_text(encoding="utf-8"))
_SEMGREP_OVERRIDES = (_ROOT / "semgrep-overrides.txt").read_text(encoding="utf-8").splitlines()
_DEADCODE_SWEEP = yaml.safe_load((_ROOT / ".github" / "workflows" / "deadcode-sweep.yml").read_text(encoding="utf-8"))


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _options(*, summary: Path | None = None) -> DeadCodeScanOptions:
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
        summary=summary,
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


def _valid_skylos_result(*, findings: list[dict[str, object]] | None = None) -> bytes:
    payload = {
        "unused_functions": findings or [],
        "unused_imports": [],
        "unused_classes": [],
        "unused_variables": [],
        "unused_parameters": [],
    }
    return json.dumps(payload).encode()


class _SkylosProcess:
    def __init__(self, returncode: int, stdout: bytes, stderr: bytes = b"") -> None:
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.killed = False

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, b"", "invalid or incomplete JSON"),
        (1, b"not-json", "invalid or incomplete JSON"),
        (1, _valid_skylos_result(), "without dead-code findings"),
        (2, _valid_skylos_result(), "exited with code 2"),
    ],
)
@pytest.mark.asyncio
async def test_deadcode_fails_closed_on_invalid_or_non_finding_scanner_results(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: bytes,
    expected: str,
) -> None:
    """No scanner error path may be reinterpreted as a clean result."""
    process = _SkylosProcess(returncode, stdout, b"scanner diagnostic")

    async def spawn(*_args: object, **_kwargs: object) -> _SkylosProcess:
        return process

    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    results = await deadcode_check.scan_scope(
        [Package(name="package", path=_ROOT, pkg_type=PackageType.OTHER)],
        _options(),
    )

    assert [(result.name, result.passed) for result in results] == [("scanner", False)]
    assert expected in results[0].error
    assert results[0].error.endswith("scanner diagnostic")
    assert not deadcode_check.render_results(results, fail_on_findings=False)


@pytest.mark.asyncio
async def test_deadcode_timeout_is_a_scanner_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bounded scan timeout must fail with captured stderr instead of a traceback."""

    class TimeoutProcess(_SkylosProcess):
        calls = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            self.calls += 1
            if self.calls == 1:
                await asyncio.sleep(60)
            return b"", b"timeout diagnostic"

    process = TimeoutProcess(1, b"")

    async def spawn(*_args: object, **_kwargs: object) -> TimeoutProcess:
        return process

    monkeypatch.setattr(deadcode_check, "SKYLOS_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    results = await deadcode_check.scan_scope(
        [Package(name="package", path=_ROOT, pkg_type=PackageType.OTHER)],
        _options(),
    )

    assert process.killed
    assert not results[0].passed
    assert "timed out" in results[0].error
    assert "timeout diagnostic" in results[0].error


@pytest.mark.parametrize(
    ("installed_version", "expected_version"),
    [("4.30.0", "4.30.0"), (None, "unknown")],
)
@pytest.mark.asyncio
async def test_deadcode_summary_uses_sha_pinned_finding_links(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    installed_version: str | None,
    expected_version: str,
) -> None:
    """The lane summary must bind every source link to the analyzed commit."""
    finding = {
        "name": "dead_symbol",
        "file": "scripts/ci/src/ci_checks/app.py",
        "line": 53,
        "type": "function",
        "confidence": 100,
        "message": "unused",
    }
    process = _SkylosProcess(1, _valid_skylos_result(findings=[finding]))

    async def spawn(*_args: object, **_kwargs: object) -> _SkylosProcess:
        return process

    summary = tmp_path / "summary.md"

    def version_lookup(distribution: str) -> str:
        if installed_version is None:
            raise deadcode_check.importlib.metadata.PackageNotFoundError(distribution)
        return installed_version

    monkeypatch.setattr(deadcode_check.importlib.metadata, "version", version_lookup)
    monkeypatch.setenv("GITHUB_REPOSITORY", "mchar7/nohiki-monorepo")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    await deadcode_check.scan_scope(
        [
            Package(
                name="ci-checks",
                path=_ROOT / "scripts" / "ci",
                pkg_type=PackageType.OTHER,
            )
        ],
        _options(summary=summary),
    )

    rendered = summary.read_text(encoding="utf-8")
    assert "## Code hygiene\n\n### Dead code (Skylos)" in rendered
    assert f"- Version: `{expected_version}`" in rendered
    assert "Verdict: **findings**" in rendered
    assert (
        f"https://github.com/mchar7/nohiki-monorepo/blob/{'a' * 40}/scripts/ci/src/ci_checks/app.py#L53"
    ) in rendered


def test_deadcode_confidence_is_bounded() -> None:
    """Typer must reject confidence values outside Skylos' supported range."""
    assert CliRunner().invoke(app, ["deadcode", "--confidence", "-1"]).exit_code == 2
    assert CliRunner().invoke(app, ["deadcode", "--confidence", "101"]).exit_code == 2


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
    assert "--summary" not in command
    assert "--diff" not in command
    assert "--no-grep-verify" not in command


def test_deadcode_whitelist_is_path_scoped_and_collision_safe() -> None:
    """Every former global exception must match only its defining file."""
    expected_names = {
        "K8sDeploymentRolloutCheck",
        "KubernetesPlatformContractsCheck",
        "aclose",
        "generate",
        "get_profile",
        "handle",
        "initiate_upload",
        "list_profiles",
        "matches",
        "predict",
        "record_error",
        "record_orphan_completion",
        "record_request",
        "reset_cache",
        "version_callback",
        "_execute_function",
        "_generate_content",
        "_handle_circuit_open",
        "_handle_exception",
        "_handle_failure",
        "_handle_success",
        "_log_pipeline_start",
        "_profile_to_detail",
        "_validate_shape_kafka_consistency",
        "_validate_strings",
        "_validate_topic_naming",
        "_validate_topic_name",
    }
    skylos = cast("dict[str, object]", cast("dict[str, object]", _ROOT_PROJECT["tool"])["skylos"])
    whitelist = cast("dict[str, object]", skylos["whitelist"])
    overrides = cast("dict[str, dict[str, list[str]]]", skylos["overrides"])
    patterns = [pattern for rules in overrides.values() for pattern in rules["whitelist"]]

    assert whitelist.get("names") == []
    assert not whitelist.get("documented")
    assert all("*" not in path and "?" not in path and "[" not in path for path in overrides)
    assert all((_ROOT / path).is_file() for path in overrides)
    assert {
        name for name in expected_names if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)
    } == expected_names
    assert all(sum(fnmatch.fnmatchcase(name, pattern) for name in expected_names) == 1 for pattern in patterns)


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
    assert '--summary "$GITHUB_STEP_SUMMARY"' in command
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


def test_semgrep_uses_pinned_sovereign_host_runtime() -> None:
    """The uv scanner must not inherit Nix libraries or contact Semgrep services."""
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
    command = cast("str", semgrep_jobs[0]["run"])
    assert command.startswith("env -u LD_LIBRARY_PATH uvx --override ")
    assert "--metrics=off" in command
    assert "--disable-version-check" in command
    assert overrides == ["semgrep==1.170.0", "ruamel-yaml-clib>=0.2.15"]
