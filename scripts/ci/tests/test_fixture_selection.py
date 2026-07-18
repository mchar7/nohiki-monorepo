"""Focused tests for unused-fixture scan path selection."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

import ci_checks.app as app_module
import pytest
from ci_checks.checks import fixtures
from ci_checks.core.packages import Package, PackageType
from typer.testing import CliRunner


class _Process(Protocol):
    returncode: int

    async def communicate(self) -> tuple[bytes, bytes]: ...


class _SuccessfulProcess:
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


class _HangingProcess:
    returncode: int | None = None

    def __init__(self) -> None:
        self.kill_called = False
        self.wait_called = False
        self.descendant_alive = True

    async def communicate(self) -> tuple[bytes, bytes]:
        await asyncio.sleep(60)
        return b"", b""

    def kill(self) -> None:
        self.kill_called = True
        self.descendant_alive = False
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_called = True
        return self.returncode or -9


class _ResultProcess:
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"== UNUSED FIXTURES ==\nvalue -- tests/test_sample.py:4\n", b""


def _package(root: Path, name: str = "example") -> Package:
    package_dir = root / name
    (package_dir / "tests").mkdir(parents=True)
    return Package(name=name, path=package_dir, pkg_type=PackageType.LIB)


def _capture_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[tuple[str, ...], dict[str, object]]]:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    async def create_subprocess_exec(*command: str, **kwargs: object) -> _SuccessfulProcess:
        calls.append((command, kwargs))
        return _SuccessfulProcess()

    monkeypatch.setattr(fixtures.asyncio, "create_subprocess_exec", create_subprocess_exec)
    return calls


def _command(calls: list[tuple[tuple[str, ...], dict[str, object]]]) -> tuple[str, ...]:
    assert len(calls) == 1
    return calls[0][0]


def test_manual_fixture_command_executes_scanner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package(tmp_path)
    scanners: list[object] = []

    async def fake_scan_parallel(
        packages: list[Package],
        scanner: object,
        workers: int,
        output_console: object,
        *,
        ci_mode: bool,
        ci_suffix: object,
    ) -> list[fixtures.FixtureResult]:
        del workers, output_console, ci_mode, ci_suffix
        assert packages == [package]
        scanners.append(scanner)
        return [fixtures.FixtureResult(name=package.name, passed=True)]

    def fake_load_packages(_scope: object, *, require_tests: bool) -> list[Package]:
        assert require_tests
        return [package]

    monkeypatch.setattr(app_module, "load_packages", fake_load_packages)
    monkeypatch.setattr(app_module, "scan_parallel", fake_scan_parallel)

    result = CliRunner().invoke(app_module.app, ["fixtures", "--scope", "all", "--ci"])

    assert result.exit_code == 0
    assert scanners == [fixtures.scan_package]


def test_folded_fixture_args_preserve_definition_scope_and_integration_exclusion(
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    fixture_module = package.tests_dir / "test_fixture.py"
    fixture_module.write_text("import pytest\n\n@pytest.fixture\ndef value():\n    return 1\n")
    integration_dir = package.tests_dir / "integration"
    integration_dir.mkdir()
    (integration_dir / "test_integration.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef remote_value():\n    return 2\n"
    )

    assert fixtures.fixture_report_args(package) == (
        "--unused-fixtures",
        "--unused-fixtures-context",
        str(fixture_module),
        "--unused-fixtures-ignore-path",
        str(integration_dir),
    )


async def test_fixture_free_package_passes_without_subprocess(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package(tmp_path)
    (package.tests_dir / "test_plain.py").write_text("def test_plain():\n    assert True\n")

    async def unexpected_subprocess(*_command: str, **_kwargs: object) -> _Process:
        pytest.fail("unexpected subprocess invocation")

    monkeypatch.setattr(fixtures.asyncio, "create_subprocess_exec", unexpected_subprocess)

    result = await fixtures.scan_package(package)

    assert result == fixtures.FixtureResult(name="example", passed=True)


async def test_sync_and_async_fixtures_select_sorted_defining_modules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    first = package.tests_dir / "test_a_sync.py"
    second = package.tests_dir / "test_z_async.py"
    first.write_text("import pytest\n\n@pytest.fixture\ndef value():\n    return 1\n")
    second.write_text("import pytest\n\n@pytest.fixture(scope='session')\nasync def client():\n    return object()\n")
    (package.tests_dir / "test_middle.py").write_text("def test_middle():\n    assert True\n")
    calls = _capture_subprocess(monkeypatch)

    await fixtures.scan_package(package)

    assert _command(calls) == (
        "uv",
        "run",
        "--no-sync",
        "--package",
        "example",
        "pytest",
        str(first),
        str(second),
        "-q",
        "--tb=no",
        "--no-header",
        "-m",
        "not integration and not requires_docker",
        "--unused-fixtures",
    )
    assert fixtures._PACKAGE_TIMEOUT_SECONDS == 600


async def test_bare_and_called_fixture_decorators_are_recognized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    bare = package.tests_dir / "test_bare.py"
    called = package.tests_dir / "test_called.py"
    bare.write_text("from pytest import fixture\n\n@fixture\ndef value():\n    return 1\n")
    called.write_text("from pytest import fixture\n\n@fixture()\nasync def client():\n    return object()\n")
    calls = _capture_subprocess(monkeypatch)

    await fixtures.scan_package(package)

    command = _command(calls)
    assert command[6:8] == (str(bare), str(called))


async def test_shared_fixture_modules_force_full_package_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _capture_subprocess(monkeypatch)

    for module_name in ("conftest.py", "helpers.py"):
        package = _package(tmp_path, module_name.removesuffix(".py"))
        (package.tests_dir / module_name).write_text(
            "import pytest\n\n@pytest.fixture\ndef shared_value():\n    return 1\n"
        )
        await fixtures.scan_package(package)

    assert [call[0][6] for call in calls] == [
        str(tmp_path / "conftest" / "tests"),
        str(tmp_path / "helpers" / "tests"),
    ]


async def test_syntax_error_fails_closed_to_full_package_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package(tmp_path)
    (package.tests_dir / "test_broken.py").write_text("def broken(:\n")
    calls = _capture_subprocess(monkeypatch)

    await fixtures.scan_package(package)

    assert _command(calls)[6] == str(package.tests_dir)


async def test_integration_directory_is_excluded_from_discovery_and_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    local = package.tests_dir / "test_local.py"
    local.write_text("import pytest\n\n@pytest.fixture\ndef value():\n    return 1\n")
    integration = package.tests_dir / "integration"
    integration.mkdir()
    (integration / "test_broken.py").write_text("def broken(:\n")
    calls = _capture_subprocess(monkeypatch)

    await fixtures.scan_package(package)

    assert _command(calls) == (
        "uv",
        "run",
        "--no-sync",
        "--package",
        "example",
        "pytest",
        str(local),
        "-q",
        "--tb=no",
        "--no-header",
        "-m",
        "not integration and not requires_docker",
        "--unused-fixtures",
        "--ignore",
        str(integration),
    )


async def test_scan_package_timeout_kills_and_reaps_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A timed-out scan must terminate the child and reap its descendants."""
    package = _package(tmp_path)
    (package.tests_dir / "test_sample.py").write_text("import pytest\n\n@pytest.fixture\ndef value():\n    return 1\n")
    process = _HangingProcess()

    async def create_subprocess_exec(*_command: str, **_kwargs: object) -> _HangingProcess:
        return process

    monkeypatch.setattr(fixtures.asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(fixtures, "_PACKAGE_TIMEOUT_SECONDS", 0.01)

    with pytest.raises(asyncio.TimeoutError):
        await fixtures.scan_package(package)

    assert process.kill_called is True
    assert process.wait_called is True
    assert process.descendant_alive is False


async def test_scan_package_timeout_cleanup_preserves_fixture_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Normal completion still parses unused fixture evidence after cleanup changes."""
    package = _package(tmp_path)
    (package.tests_dir / "test_sample.py").write_text("import pytest\n\n@pytest.fixture\ndef value():\n    return 1\n")
    process = _ResultProcess()

    async def create_subprocess_exec(*_command: str, **_kwargs: object) -> _ResultProcess:
        return process

    monkeypatch.setattr(fixtures.asyncio, "create_subprocess_exec", create_subprocess_exec)

    result = await fixtures.scan_package(package)

    assert result.passed is False
    assert result.test_failures is False
    assert result.fixtures == [fixtures.UnusedFixture(name="value", location="tests/test_sample.py:4")]
