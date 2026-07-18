"""Regression tests for immutable uv environments in fixture scans."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from ci_checks.checks.fixtures import scan_package
from ci_checks.core.packages import Package, PackageType


class _FixtureProcess:
    returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""


@pytest.mark.parametrize("pkg_type", [PackageType.OTHER, PackageType.SCRIPTS])
async def test_scan_package_uses_no_sync_for_workspace_and_scripts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pkg_type: PackageType
) -> None:
    """Fixture scans must not resynchronize the shared virtual environment."""
    package_path = tmp_path / pkg_type.value
    (package_path / "tests").mkdir(parents=True)
    (package_path / "tests" / "test_fixture_definitions.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef example_fixture() -> None:\n    return None\n",
        encoding="utf-8",
    )
    package = Package(name="example", path=package_path, pkg_type=pkg_type)
    commands: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*command: str, **kwargs: object) -> _FixtureProcess:
        del kwargs
        commands.append(command)
        return _FixtureProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await scan_package(package)

    assert commands
    selector = ("--directory", str(package_path)) if pkg_type is PackageType.SCRIPTS else ("--package", package.name)
    assert commands[0][:3] == ("uv", "run", "--no-sync")
    assert commands[0][3:5] == selector
