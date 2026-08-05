from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import Counter
from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from ci_checks.checks.workflow import render_report_summary

_ROOT = Path(__file__).resolve().parents[3]
_FLAKE = _ROOT / "flake.nix"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_PACKAGE = _ROOT / "package.json"
_PNPM_LOCK = _ROOT / "pnpm-lock.yaml"
_LEFTHOOK = _ROOT / "lefthook.yml"
_LEFTHOOK_VERSION = "2.1.10"
_LEFTHOOK_NIX_SOURCE = {
    "pname": "lefthook",
    "version": _LEFTHOOK_VERSION,
    "revision": "8d9cfec5f52367af6374a5430b4e9568844856e5",
    "sourceHash": "sha256-GR97Z9wnM6z6gNIcf35leBGkhdj1d6OHQ9oFnaz3f1s=",
    "vendorHash": "sha256-G+v6ZqnkcFdPDzXlN89oqD7mOnHfq1tvIkFxdoVnBNo=",
}


@cache
def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(_read_text(path))
    assert isinstance(value, dict), path
    return value


def _python_mutator_run() -> str:
    commands = _load_yaml(_LEFTHOOK)["pre-commit"]["commands"]
    python_mutators = [
        command
        for command in commands.values()
        if isinstance(command, dict) and command.get("glob") == "*.py" and command.get("stage_fixed") is True
    ]
    assert len(python_mutators) == 1
    command = python_mutators[0]
    assert command["glob"] == "*.py"
    assert command["stage_fixed"] is True
    run = command["run"]
    assert isinstance(run, str)
    return run


def test_lefthook_serializes_scalable_staged_python_mutator() -> None:
    run = _python_mutator_run()

    assert "{staged_files}" not in run
    assert re.search(r"git\s+diff\s+--cached\b", run)
    assert "--name-only" in run
    assert re.search(r"(?:^|\s)-z(?:\s|$)", run)
    assert "--diff-filter=ACMR" in run
    assert "mktemp" in run
    assert "trap" in run

    check = "uv run --no-sync ruff check --fix --force-exclude"
    format_command = "uv run --no-sync ruff format --force-exclude"
    assert check in run
    assert format_command in run
    assert run.count("xargs -0 -r") == 2
    assert run.index(check) < run.index(format_command)


def test_lefthook_frontend_mutator_delegates_empty_sets_to_biome() -> None:
    """Biome tolerates an empty staged template after Lefthook expansion."""
    commands = _load_yaml(_LEFTHOOK)["pre-commit"]["commands"]
    frontend = commands["frontend-lint"]

    assert frontend["glob"] == [
        "*.{ts,tsx,js,jsx,mjs,css}",
        "typescript/apps/frontend/e2e/*.json",
        "typescript/apps/frontend/e2e/**/*.json",
    ]
    run = frontend["run"]
    assert isinstance(run, str)
    assert run.count("pnpm exec biome check --write --no-errors-on-unmatched {staged_files}") == 1
    assert "if [ -n" not in run

    stage_fixed = sorted(
        name for name, command in commands.items() if isinstance(command, dict) and command.get("stage_fixed") is True
    )
    assert stage_fixed == ["frontend-lint", "markdown-lint", "python-check-format"]


def test_lefthook_serializes_empty_safe_staged_markdown_mutator() -> None:
    command = _load_yaml(_LEFTHOOK)["pre-commit"]["commands"]["markdown-lint"]

    assert command["glob"] == ["*.md", ".markdownlint-cli2.jsonc", ".markdownlintignore", ".markdownlint.json"]
    assert command["stage_fixed"] is True
    run = command["run"]
    assert isinstance(run, str)
    assert "{staged_files}" not in run
    assert re.search(r"git\s+diff\s+--cached\b", run)
    assert "--name-only" in run
    assert re.search(r"(?:^|\s)-z(?:\s|$)", run)
    assert "--diff-filter=ACMR" in run
    assert "mktemp" in run
    assert "trap" in run
    for pathspec in (
        "':(glob)*.md'",
        "':(glob)**/*.md'",
        "'.markdownlint-cli2.jsonc'",
        "'.markdownlintignore'",
        "'.markdownlint.json'",
    ):
        assert pathspec in run
    assert run.count("xargs -0 -r") == 1
    assert "pnpm exec markdownlint-cli2 --fix --" in run


def _write_fake_uv(bin_dir: Path) -> None:
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "with open(os.environ['FAKE_UV_RECORD'], 'a', encoding='utf-8') as stream:\n"
        "    json.dump(sys.argv[1:], stream)\n"
        "    stream.write('\\n')\n"
        "if os.environ.get('FAIL_RUFF_CHECK') and sys.argv[1:5] == ['run', '--no-sync', 'ruff', 'check']:\n"
        "    raise SystemExit(23)\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)


def _run_python_mutator(
    repo: Path,
    run: str,
    record: Path,
    *,
    fail_check: bool = False,
) -> subprocess.CompletedProcess[str]:
    bin_dir = repo / ".fake-bin"
    bin_dir.mkdir(exist_ok=True)
    _write_fake_uv(bin_dir)
    wrapper = repo / "scripts" / "dev" / "env-lock.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(_ROOT / "scripts" / "dev" / "env-lock.sh", wrapper)
    wrapper.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["FAKE_UV_RECORD"] = str(record)
    if fail_check:
        env["FAIL_RUFF_CHECK"] = "1"
    else:
        env.pop("FAIL_RUFF_CHECK", None)
    return subprocess.run(
        ["sh", "-eu", "-c", run],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _recorded_paths(record: Path) -> dict[str, list[str]]:
    expected_prefixes = {
        "check": ["run", "--no-sync", "ruff", "check", "--fix", "--force-exclude", "--"],
        "format": ["run", "--no-sync", "ruff", "format", "--force-exclude", "--"],
    }
    paths = {phase: [] for phase in expected_prefixes}
    for line in record.read_text(encoding="utf-8").splitlines():
        args = json.loads(line)
        assert isinstance(args, list), args
        assert all(isinstance(arg, str) for arg in args), args
        assert args[:3] == ["run", "--no-sync", "ruff"], args
        command = args[3] if len(args) > 3 else None
        assert command in expected_prefixes, args
        prefix = expected_prefixes[command]
        assert args[: len(prefix)] == prefix, args
        assert len(args) > len(prefix), args
        paths[command].extend(args[len(prefix) :])
    return paths


def test_lefthook_python_mutator_handles_large_nul_safe_inventory(
    tmp_path: Path,
) -> None:
    run = _python_mutator_run()
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    deleted = repo / "deleted.py"
    deleted.write_text("print('deleted')\n", encoding="utf-8")
    subprocess.run(["git", "add", "deleted.py"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-qm",
            "base",
        ],
        cwd=repo,
        check=True,
    )
    deleted.unlink()
    eligible: set[str] = {"-dash.py", "eligible/space name.py", "eligible/new\nline.py"}
    for relative in eligible:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")
    for index in range(506):
        relative = f"eligible/{index:05d}-{'x' * 240}.py"
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")
        eligible.add(relative)
    native_excluded = {
        "src/alembic/generated.py",
        "src/nohiki-domain-models/model.py",
    }
    not_forwarded = {"src/not-python.txt", "deleted.py"}
    for relative in (native_excluded | not_forwarded) - {"deleted.py"}:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x = 1\n", encoding="utf-8")
    eligible.update(native_excluded)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    record = repo / "uv-record.jsonl"
    result = _run_python_mutator(repo, run, record)
    assert result.returncode == 0, result.stderr
    assert len(record.read_text(encoding="utf-8").splitlines()) >= 4
    recorded = _recorded_paths(record)
    expected = Counter(eligible)
    assert Counter(recorded["check"]) == expected
    assert Counter(recorded["format"]) == expected
    assert set(recorded["check"]).isdisjoint(not_forwarded)

    record.write_text("", encoding="utf-8")
    failed = _run_python_mutator(repo, run, record, fail_check=True)
    assert failed.returncode != 0
    failed_recorded = _recorded_paths(record)
    assert failed_recorded["check"]
    assert not failed_recorded["format"]


def _nix_eval(*args: str) -> str:
    result = subprocess.run(
        ["nix", "eval", *args],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_lefthook_version_is_exact_across_project_metadata() -> None:
    package_version = json.loads(_PACKAGE.read_text(encoding="utf-8"))["devDependencies"]["lefthook"]
    lock = _load_yaml(_PNPM_LOCK)
    lock_entry = lock["importers"]["."]["devDependencies"]["lefthook"]
    configured_version = str(_load_yaml(_LEFTHOOK)["min_version"])
    flake_version = re.search(r'lefthookVersion\s*=\s*"([^"]+)";', _read_text(_FLAKE))

    assert flake_version, "flake.nix must declare lefthookVersion"
    versions = {
        "flake.nix": flake_version[1],
        "lefthook.yml": configured_version,
        "package.json": package_version,
        "pnpm-lock.yaml specifier": lock_entry["specifier"],
        "pnpm-lock.yaml resolved version": lock_entry["version"],
    }
    assert versions == dict.fromkeys(versions, _LEFTHOOK_VERSION), versions

    for section in ("packages", "snapshots"):
        lefthook_keys = [key for key in lock[section] if key.startswith("lefthook")]
        assert lefthook_keys, f"pnpm-lock.yaml {section} has no lefthook entries"
        assert all(key.endswith(f"@{_LEFTHOOK_VERSION}") for key in lefthook_keys), (
            f"pnpm-lock.yaml {section} contains stale lefthook entries: {lefthook_keys}"
        )


@pytest.mark.skipif(shutil.which("nix") is None, reason="Nix is required to evaluate flake attributes")
def test_lefthook_nix_attribute_evaluates_to_verified_source() -> None:
    system = _nix_eval("--raw", "--impure", "--expr", "builtins.currentSystem")
    package = _nix_eval(
        "--json",
        "--no-write-lock-file",
        f".#packages.{system}.lefthook",
        "--apply",
        (
            "pkg: { inherit (pkg) pname version; revision = pkg.src.rev; "
            "sourceHash = pkg.src.outputHash; vendorHash = pkg.goModules.outputHash; }"
        ),
    )

    assert json.loads(package) == _LEFTHOOK_NIX_SOURCE


def test_standard_ci_worker_checks_flake_and_ci_shell_lefthook_version() -> None:
    standard_job = _load_yaml(_CHECKS)["jobs"]["worker"]
    flat = [inner for step in standard_job["steps"] for inner in step.get("parallel", [step])]
    steps = {step.get("name"): step for step in flat}
    commands = "\n".join(str(step.get("run", "")) for step in flat)
    lefthook_step = steps["Check Lefthook version"]

    assert lefthook_step["env"]["LEFTHOOK_VERSION"] == _LEFTHOOK_VERSION
    assert steps["Check flake"]["run"] == "nix develop .#ci --command just nix-check"
    report = render_report_summary(
        "worker",
        {
            "CACHE_OUTCOMES": "",
            "CONTAINER_SELECTED": "false",
            "FLAG_NIX": "true",
            "JOB_STARTED": "100",
            "SMOKE": "false",
            "UNIQUE_STARTED": "120",
            "UNIT": "frontend",
        },
        now=140,
    )
    assert "- `nix flake check; lefthook version`" in report
    assert re.search(
        r"\bnix\s+develop\s+\.\#ci\s+--command\s+lefthook\s+version\b",
        commands,
    )
    assert re.search(
        r'test\s+"\$actual"\s*=\s*"\$LEFTHOOK_VERSION"',
        commands,
    )


def test_flake_has_no_imperative_or_unpinned_lefthook_path() -> None:
    flake = _read_text(_FLAKE)
    core_tools = re.search(r"coreTools\s*=.*?\[(?P<body>.*?)\];", flake, re.DOTALL)

    assert core_tools, "flake.nix must define coreTools"
    assert re.search(r"^\s*lefthookPackage\s*(?:#.*)?$", core_tools["body"], re.MULTILINE)
    assert not re.search(r"^\s*lefthook\s*(?:#.*)?$", core_tools["body"], re.MULTILINE)
    assert "pkgs.lefthook" not in flake
    assert not re.search(r"\bgo\s+install\b[^\n]*lefthook", flake, re.IGNORECASE)
    assert not re.search(r"\b(?:curl|wget)\b[^\n]*lefthook", flake, re.IGNORECASE)
    assert not re.search(r"PATH=.*node_modules/\.bin", flake)
