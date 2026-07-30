"""Focused contracts for deterministic source scanners."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import subprocess
import sys
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from _documents import load_mapping
from ci_checks.app import app
from ci_checks.checks import deadcode as deadcode_check
from ci_checks.checks.deadcode import (
    DeadCodeFinding,
    DeadCodeResult,
    DeadCodeScanOptions,
    SeverityLevel,
    _build_skylos_cmd,
    _collect_scan_paths,
    _resolve_skylos_jobs,
)
from ci_checks.core.packages import Package, PackageType
from typer.testing import CliRunner

_ROOT = Path(__file__).resolve().parents[3]


_CI_PROJECT = tomllib.loads((_ROOT / "scripts" / "ci" / "pyproject.toml").read_text(encoding="utf-8"))
_ROOT_PROJECT = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
_LEFTHOOK_CONFIG = load_mapping(_ROOT / "lefthook.yml")
_SEMGREP_OVERRIDES = (_ROOT / "semgrep-overrides.txt").read_text(encoding="utf-8").splitlines()
_DEADCODE_SWEEP = _ROOT / ".github" / "workflows" / "deadcode-sweep.yml"


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _options(
    *,
    summary: Path | None = None,
    include_tests: bool = False,
    no_provenance: bool = False,
) -> DeadCodeScanOptions:
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
        no_provenance=no_provenance,
        provenance_base=None,
        diff=None,
        diff_base=None,
        github=False,
        summary=summary,
        severity=SeverityLevel.HIGH,
        file_filter=None,
        limit=None,
        no_grep_verify=False,
        include_tests=include_tests,
        include_parameters=False,
    )


def test_skylos_jobs_resolution_honors_override_and_host_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skylos concurrency must follow an explicit override or the available host CPUs."""
    monkeypatch.setenv("SKYLOS_JOBS", "7")
    assert _resolve_skylos_jobs() == "7"

    monkeypatch.delenv("SKYLOS_JOBS")
    monkeypatch.setattr("ci_checks.checks.deadcode.os.process_cpu_count", lambda: 20)
    assert _resolve_skylos_jobs() == "20"

    monkeypatch.setattr("ci_checks.checks.deadcode.os.process_cpu_count", lambda: 0)
    assert _resolve_skylos_jobs() == "1"


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
    monkeypatch.setattr("ci_checks.checks.deadcode.os.process_cpu_count", lambda: 2)

    async def unexpected_spawn(*_args: object, **_kwargs: object) -> None:
        raise AssertionError

    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", unexpected_spawn)
    package = Package(name="package", path=_ROOT, pkg_type=PackageType.OTHER)

    results = await deadcode_check.scan_scope([package], _options())

    assert captured_extra == {
        "OTEL_SDK_DISABLED": "true",
        "SKYLOS_GREP_BUDGET": "120",
        "SKYLOS_CACHE_DIR": str(_ROOT / ".skylos"),
        "SKYLOS_JOBS": "2",
    }
    assert [(result.name, result.passed, result.error) for result in results] == [
        (
            "scanner-preflight",
            False,
            "ripgrep (rg) is required for deterministic Skylos grep verification",
        )
    ]


def _valid_skylos_result(*, findings: Sequence[object] | None = None) -> bytes:
    payload = {
        "unused_functions": list(findings) if findings is not None else [],
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
    assert not deadcode_check.static_result_published(results)


@pytest.mark.parametrize(
    "finding",
    [
        None,
        "malformed",
        {},
        {"file": None},
        {"file": ""},
    ],
)
@pytest.mark.asyncio
async def test_deadcode_fails_closed_on_malformed_finding_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    finding: object,
) -> None:
    """Malformed scanner findings must never be interpreted as a clean result."""
    process = _SkylosProcess(0, _valid_skylos_result(findings=[finding]))

    async def spawn(*_args: object, **_kwargs: object) -> _SkylosProcess:
        return process

    summary = tmp_path / "summary.md"
    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    results = await deadcode_check.scan_scope(
        [Package(name="package", path=_ROOT, pkg_type=PackageType.OTHER)],
        _options(summary=summary),
    )

    assert [(result.name, result.passed) for result in results] == [("scanner", False)]
    assert "invalid or incomplete JSON" in results[0].error
    assert not deadcode_check.render_results(results, fail_on_findings=False)
    assert "- Verdict: **scanner failure**" in summary.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_deadcode_replaces_non_utf8_scanner_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Non-UTF-8 scanner bytes must reach the structured failure path."""
    process = _SkylosProcess(2, b"\xff", b"scanner diagnostic \xff")

    async def spawn(*_args: object, **_kwargs: object) -> _SkylosProcess:
        return process

    summary = tmp_path / "summary.md"
    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    results = await deadcode_check.scan_scope(
        [Package(name="package", path=_ROOT, pkg_type=PackageType.OTHER)],
        _options(summary=summary),
    )

    assert [(result.name, result.passed) for result in results] == [("scanner", False)]
    assert "invalid or incomplete JSON" in results[0].error
    assert "scanner diagnostic \ufffd" in results[0].error
    assert not deadcode_check.render_results(results, fail_on_findings=False)
    rendered = summary.read_text(encoding="utf-8")
    assert "- Verdict: **scanner failure**" in rendered
    assert "scanner diagnostic \ufffd" in rendered


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
    assert not deadcode_check.static_result_published(results)


@pytest.mark.parametrize(
    ("returncode", "findings"),
    [
        (0, []),
        (
            1,
            [
                {
                    "name": "dead_function",
                    "file": "scripts/ci/src/ci_checks/app.py",
                    "line": 1,
                    "confidence": 100,
                    "message": "unused",
                }
            ],
        ),
    ],
    ids=["clean", "findings"],
)
@pytest.mark.asyncio
async def test_static_result_publication_accepts_completed_parseable_analysis(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    findings: list[dict[str, object]],
) -> None:
    process = _SkylosProcess(returncode, _valid_skylos_result(findings=findings))

    async def spawn(*_args: object, **_kwargs: object) -> _SkylosProcess:
        return process

    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    results = await deadcode_check.scan_scope(
        [Package(name="package", path=_ROOT, pkg_type=PackageType.OTHER)],
        _options(),
    )

    assert deadcode_check.static_result_published(results)


def test_static_result_output_is_an_appended_workflow_fact(tmp_path: Path) -> None:
    github_output = tmp_path / "github-output"
    github_output.write_text("unrelated=value\n", encoding="utf-8")
    clean = [DeadCodeResult(name="package", passed=True)]
    aborted = [DeadCodeResult(name="scanner", passed=False, error="invalid or incomplete JSON")]

    deadcode_check.write_static_result_output(clean, github_output)
    deadcode_check.write_static_result_output(aborted, github_output)
    deadcode_check.write_static_result_output(clean, None)

    assert github_output.read_text(encoding="utf-8").splitlines() == [
        "unrelated=value",
        f"{deadcode_check.STATIC_RESULT_OUTPUT}=true",
        f"{deadcode_check.STATIC_RESULT_OUTPUT}=false",
    ]
    assert not deadcode_check.static_result_published([])


def test_deadcode_cli_publishes_the_predicate_to_github_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github_output = tmp_path / "github-output"

    async def aborted_scan(*_args: object, **_kwargs: object) -> list[DeadCodeResult]:
        return [DeadCodeResult(name="scanner", passed=False, error="invalid or incomplete JSON")]

    monkeypatch.setattr(deadcode_check, "scan_scope", aborted_scan)
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    result = CliRunner().invoke(app, ["deadcode", "--ci", "--fail"])

    assert result.exit_code == 1
    assert github_output.read_text(encoding="utf-8") == f"{deadcode_check.STATIC_RESULT_OUTPUT}=false\n"


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
    finding: dict[str, object] = {
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
    # A level-four heading so the block nests under the job's Results section instead of opening
    # a second top-level section beside the job heading.
    assert rendered.startswith("#### Dead code (Skylos)")
    assert "## Code hygiene" not in rendered
    assert f"- Version: `{expected_version}`" in rendered
    assert "Verdict: **findings**" in rendered
    assert (
        f"https://github.com/mchar7/nohiki-monorepo/blob/{'a' * 40}/scripts/ci/src/ci_checks/app.py#L53"
    ) in rendered


def test_deadcode_confidence_is_bounded() -> None:
    """Typer must reject confidence values outside Skylos' supported range."""
    assert CliRunner().invoke(app, ["deadcode", "--confidence", "-1"]).exit_code == 2
    assert CliRunner().invoke(app, ["deadcode", "--confidence", "101"]).exit_code == 2


def test_deadcode_inputs_are_the_tracked_repository_python_closure(
    tmp_path: Path,
) -> None:
    """Ignored worktree artifacts cannot alter the complete analysis graph."""
    _run_git(tmp_path, "init", "--quiet")
    selected_file = tmp_path / "selected" / "src" / "live.py"
    unselected_file = tmp_path / "unselected" / "src" / "caller.py"
    selected_test = tmp_path / "selected" / "tests" / "test_live.py"
    for path in (selected_file, unselected_file, selected_test):
        path.parent.mkdir(parents=True)
        path.write_text("pass\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("__pycache__/\nselected/src/generated/\n", encoding="utf-8")
    _run_git(tmp_path, "add", ".")

    clean_inputs = _collect_scan_paths(repo_root=tmp_path)
    (selected_file.parent / "__pycache__").mkdir()
    (selected_file.parent / "__pycache__" / "cache.py").write_text("pass\n", encoding="utf-8")
    (selected_file.parent / "generated").mkdir()
    (selected_file.parent / "generated" / "output.py").write_text("pass\n", encoding="utf-8")
    (selected_file.parent / "scratch.py").write_text("pass\n", encoding="utf-8")

    assert (
        clean_inputs
        == _collect_scan_paths(repo_root=tmp_path)
        == [
            "selected/src/live.py",
            "selected/tests/test_live.py",
            "unselected/src/caller.py",
        ]
    )


def test_deadcode_inputs_exclude_only_generated_domain_model_packages(
    tmp_path: Path,
) -> None:
    """Generated protobuf packages stay excluded while maintained support code is scanned."""
    _run_git(tmp_path, "init", "--quiet")
    package_root = tmp_path / "backend" / "libs" / "nohiki-domain-models"
    src = package_root / "src"
    generated_header = "# Generated by the protocol buffer compiler.  DO NOT EDIT!\n"

    generated_model = src / "nohiki" / "user" / "v1" / "__init__.py"
    generated_model.parent.mkdir(parents=True)
    generated_model.write_text(f"{generated_header}class GeneratedModel:\n    pass\n", encoding="utf-8")
    generated_namespace = src / "nohiki" / "user" / "__init__.py"
    generated_namespace.write_text("", encoding="utf-8")
    generated_google = src / "nohiki_proto_google" / "protobuf" / "__init__.py"
    generated_google.parent.mkdir(parents=True)
    generated_google.write_text(f"{generated_header}class GeneratedTimestamp:\n    pass\n", encoding="utf-8")

    maintained_utils = src / "nohiki_domain_utils" / "enum_adapter.py"
    maintained_utils.parent.mkdir(parents=True)
    maintained_utils.write_text("def parse_enum_string() -> None:\n    pass\n", encoding="utf-8")
    maintained_pool = src / "message_pool" / "__init__.py"
    maintained_pool.parent.mkdir(parents=True)
    maintained_pool.write_text("default_message_pool = object()\n", encoding="utf-8")

    unrelated = tmp_path / "other-package" / "src" / "other.py"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("def other() -> None:\n    pass\n", encoding="utf-8")
    _run_git(tmp_path, "add", ".")

    assert _collect_scan_paths(repo_root=tmp_path) == [
        "backend/libs/nohiki-domain-models/src/message_pool/__init__.py",
        "backend/libs/nohiki-domain-models/src/nohiki_domain_utils/enum_adapter.py",
        "other-package/src/other.py",
    ]


@pytest.mark.asyncio
async def test_deadcode_selection_includes_unselected_caller_and_filters_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Selection must preserve the full call graph while limiting reported packages."""
    _run_git(tmp_path, "init", "--quiet")
    selected_root = tmp_path / "selected"
    definition = selected_root / "src" / "selected_pkg" / "api.py"
    definition.parent.mkdir(parents=True)
    definition.write_text(
        "def used_across_package_boundary() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    caller = tmp_path / "unselected" / "src" / "unselected_pkg" / "consumer.py"
    caller.parent.mkdir(parents=True)
    caller.write_text(
        "from selected_pkg.api import used_across_package_boundary\n\nRESULT = used_across_package_boundary()\n",
        encoding="utf-8",
    )
    _run_git(tmp_path, "add", ".")

    findings: list[object] = [
        {
            "name": "selected_dead",
            "file": "selected/src/selected_pkg/api.py",
            "line": 1,
            "confidence": 100,
            "message": "unused",
        },
        {
            "name": "unselected_dead",
            "file": "unselected/src/unselected_pkg/consumer.py",
            "line": 1,
            "confidence": 100,
            "message": "unused",
        },
    ]
    process = _SkylosProcess(1, _valid_skylos_result(findings=findings))
    command: tuple[object, ...] = ()

    async def spawn(*args: object, **_kwargs: object) -> _SkylosProcess:
        nonlocal command
        command = args
        return process

    monkeypatch.setattr(deadcode_check, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    results = await deadcode_check.scan_scope(
        [Package(name="selected", path=selected_root, pkg_type=PackageType.OTHER)],
        _options(),
    )

    assert list(command[3 : command.index("--json")]) == [
        "selected/src/selected_pkg/api.py",
        "unselected/src/unselected_pkg/consumer.py",
    ]
    assert [result.name for result in results] == ["selected"]
    assert [finding.name for finding in results[0].findings] == ["selected_dead"]


@pytest.mark.requires_skylos
@pytest.mark.asyncio
async def test_deadcode_skylos_keeps_selected_definition_used_only_by_unselected_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller outside reporting scope must remain visible to the real call graph."""
    _run_git(tmp_path, "init", "--quiet")
    selected_root = tmp_path / "selected"
    definition = selected_root / "src" / "selected_pkg" / "api.py"
    definition.parent.mkdir(parents=True)
    definition.write_text(
        "def used_across_package_boundary() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    caller = tmp_path / "unselected" / "src" / "unselected_pkg" / "consumer.py"
    caller.parent.mkdir(parents=True)
    caller.write_text(
        "from selected_pkg.api import used_across_package_boundary\n\nRESULT = used_across_package_boundary()\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text("[tool.skylos.whitelist]\nnames = []\n", encoding="utf-8")
    _run_git(tmp_path, "add", ".")

    monkeypatch.setattr(deadcode_check, "REPO_ROOT", tmp_path)

    results = await deadcode_check.scan_scope(
        [Package(name="selected", path=selected_root, pkg_type=PackageType.OTHER)],
        _options(no_provenance=True),
    )

    assert [result.name for result in results] == ["selected"]
    assert results[0].error == ""
    assert "used_across_package_boundary" not in {finding.name for finding in results[0].findings}


@pytest.mark.asyncio
async def test_deadcode_selection_scans_full_closure_and_reports_only_selected_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reporting scope and test filtering must not narrow scanner inputs."""
    _run_git(tmp_path, "init", "--quiet")
    selected_root = tmp_path / "selected"
    paths = (
        selected_root / "src" / "definition.py",
        selected_root / "tests" / "test_definition.py",
        tmp_path / "unselected" / "src" / "unused.py",
    )
    for path in paths:
        path.parent.mkdir(parents=True)
        path.write_text("pass\n", encoding="utf-8")
    _run_git(tmp_path, "add", ".")

    findings: list[object] = [
        {
            "name": "selected_dead",
            "file": "selected/src/definition.py",
            "line": 1,
            "confidence": 100,
            "message": "unused",
        },
        {
            "name": "selected_test_dead",
            "file": "selected/tests/test_definition.py",
            "line": 1,
            "confidence": 100,
            "message": "unused",
        },
        {
            "name": "unselected_dead",
            "file": "unselected/src/unused.py",
            "line": 1,
            "confidence": 100,
            "message": "unused",
        },
    ]
    process = _SkylosProcess(1, _valid_skylos_result(findings=findings))
    command: tuple[object, ...] = ()

    async def spawn(*args: object, **_kwargs: object) -> _SkylosProcess:
        nonlocal command
        command = args
        return process

    monkeypatch.setattr(deadcode_check, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(deadcode_check.shutil, "which", lambda *_args, **_kwargs: "/bin/rg")
    monkeypatch.setattr(deadcode_check.asyncio, "create_subprocess_exec", spawn)

    results = await deadcode_check.scan_scope(
        [Package(name="selected", path=selected_root, pkg_type=PackageType.OTHER)],
        _options(include_tests=False),
    )

    assert list(command[3 : command.index("--json")]) == [
        "selected/src/definition.py",
        "selected/tests/test_definition.py",
        "unselected/src/unused.py",
    ]
    assert [result.name for result in results] == ["selected"]
    assert [finding.name for finding in results[0].findings] == ["selected_dead"]


@pytest.mark.requires_skylos
@pytest.mark.asyncio
async def test_deadcode_skylos_reports_only_selected_maintained_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real analyzer may report only maintained files in the selected package."""
    _run_git(tmp_path, "init", "--quiet")
    selected_root = tmp_path / "selected"
    sources = {
        selected_root / "src" / "definition.py": "def selected_dead() -> int:\n    return 1\n",
        selected_root / "tests" / "test_definition.py": "def selected_test_dead() -> int:\n    return 1\n",
        tmp_path / "unselected" / "src" / "unused.py": "def unselected_dead() -> int:\n    return 1\n",
    }
    for path, source in sources.items():
        path.parent.mkdir(parents=True)
        path.write_text(source, encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[tool.skylos.whitelist]\nnames = []\n", encoding="utf-8")
    _run_git(tmp_path, "add", ".")

    monkeypatch.setattr(deadcode_check, "REPO_ROOT", tmp_path)

    results = await deadcode_check.scan_scope(
        [Package(name="selected", path=selected_root, pkg_type=PackageType.OTHER)],
        _options(include_tests=False, no_provenance=True),
    )

    assert [result.name for result in results] == ["selected"]
    assert results[0].error == ""
    assert [finding.name for finding in results[0].findings] == ["selected_dead"]


def test_deadcode_command_uses_pinned_fork_static_cache_offline() -> None:
    """The scanner must use the locked fork, stay offline, and cache the whole graph."""
    command = _build_skylos_cmd(
        ["package/src/live.py"],
        _options(),
    )

    assert command[:3] == [sys.executable, "-m", "ci_checks.checks.skylos_cache"]
    assert command[3 : command.index("--json")] == ["package/src/live.py"]
    assert _CI_PROJECT["dependency-groups"]["deadcode"] == ["skylos==4.30.0"]
    assert _CI_PROJECT["tool"]["uv"]["sources"]["skylos"] == {
        "git": "ssh://git@github.com/mchar7/skylos",
        "rev": "6c9e3f1d84c1cc312f8e69c91b348a896d61b0b2",
    }
    assert "uvx" not in command
    cache_index = command.index("--cache-static")
    assert command[cache_index : cache_index + 3] == [
        "--cache-static",
        "--cache-static-tier",
        "content",
    ]
    # Name-only baseline fingerprints suppress globally; the clean corpus needs no baseline.
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
    tool = _ROOT_PROJECT["tool"]
    assert isinstance(tool, dict)
    skylos = tool["skylos"]
    assert isinstance(skylos, dict)
    whitelist = skylos["whitelist"]
    assert isinstance(whitelist, dict)
    overrides = skylos["overrides"]
    assert isinstance(overrides, dict)
    override_paths: list[str] = []
    patterns: list[str] = []
    for path, rules in overrides.items():
        assert isinstance(path, str)
        assert isinstance(rules, dict)
        override_paths.append(path)
        rule_patterns = rules["whitelist"]
        assert isinstance(rule_patterns, list)
        for pattern in rule_patterns:
            assert isinstance(pattern, str)
            patterns.append(pattern)

    assert whitelist.get("names") == []
    assert not whitelist.get("documented")
    assert all("*" not in path and "?" not in path and "[" not in path for path in override_paths)
    assert all((_ROOT / path).is_file() for path in override_paths)
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


def test_periodic_deadcode_sweep_is_absent() -> None:
    """Dead-code violations must be caught at the PR gate, not by periodic work."""
    assert not _DEADCODE_SWEEP.exists()


def test_deadcode_gate_disables_history_provenance() -> None:
    """A clean gate verdict cannot depend on refs absent from a shallow clone."""
    pre_push = _LEFTHOOK_CONFIG["pre-push"]
    assert isinstance(pre_push, Mapping)
    groups = pre_push.get("jobs")
    assert isinstance(groups, list)
    deadcode_commands: list[str] = []
    for group in groups:
        assert isinstance(group, Mapping)
        grouped = group.get("group")
        if not isinstance(grouped, Mapping):
            continue
        jobs = grouped.get("jobs")
        assert isinstance(jobs, list)
        for job in jobs:
            assert isinstance(job, Mapping)
            if job.get("name") == "deadcode":
                command = job.get("run")
                assert isinstance(command, str)
                deadcode_commands.append(command)

    assert len(deadcode_commands) == 1
    assert deadcode_commands[0].endswith("--no-provenance")


def test_semgrep_uses_pinned_sovereign_host_runtime() -> None:
    """The uv scanner must not inherit Nix libraries or contact Semgrep services."""
    pre_push = _LEFTHOOK_CONFIG["pre-push"]
    assert isinstance(pre_push, Mapping)
    groups = pre_push.get("jobs")
    assert isinstance(groups, list)
    semgrep_commands: list[str] = []
    for group in groups:
        assert isinstance(group, Mapping)
        grouped = group.get("group")
        if not isinstance(grouped, Mapping):
            continue
        jobs = grouped.get("jobs")
        assert isinstance(jobs, list)
        for job in jobs:
            assert isinstance(job, Mapping)
            if job.get("name") == "semgrep":
                command = job.get("run")
                assert isinstance(command, str)
                semgrep_commands.append(command)
    overrides = _SEMGREP_OVERRIDES
    assert len(semgrep_commands) == 1
    command = semgrep_commands[0]
    assert command.startswith("env -u LD_LIBRARY_PATH uvx --override ")
    assert "--metrics=off" in command
    assert "--disable-version-check" in command
    assert overrides == ["semgrep==1.170.0", "ruamel-yaml-clib>=0.2.15"]
