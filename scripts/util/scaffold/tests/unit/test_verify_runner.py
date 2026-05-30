"""Unit tests for the verify runner.

Real subprocess invocations are mocked; only the orchestration logic is
exercised here. Full subprocess exercise happens in integration tests.
"""

from __future__ import annotations

import dataclasses
import subprocess
from pathlib import Path

import pytest
from nohiki_scaffold.core.build import BuildPlan
from nohiki_scaffold.core.features import KafkaRole, ServiceShape, VerifyMode
from nohiki_scaffold.core.models import (
    DatabaseOptions,
    KafkaOptions,
    LibSpec,
    MLOptions,
    RedisOptions,
    S3Options,
    ServiceSpec,
)
from nohiki_scaffold.verify.runner import (
    CheckResult,
    VerifyResult,
    _resolve_package_path,
    run_verify,
)


def _lib_spec() -> LibSpec:
    return LibSpec(
        name="nohiki-demo",
        description="demo",
        owner="platform",
        module_name="nohiki_demo",
    )


def _service_spec() -> ServiceSpec:
    return ServiceSpec(
        name="demo-service",
        friendly_name="Demo",
        description="demo",
        owner="platform",
        shape=ServiceShape.KAFKA_ONLY,
        env_prefix="DEMO_",
        module_name="demo_service",
        database=DatabaseOptions(),
        redis=RedisOptions(),
        kafka=KafkaOptions(role=KafkaRole.CONSUMER_ONLY),
        s3=S3Options(),
        ml=MLOptions(),
    )


def _empty_plan(spec: LibSpec | ServiceSpec) -> BuildPlan:
    return BuildPlan(spec=spec, files=(), root_edits=(), hints=())


class TestResolvePackagePath:
    def test_lib(self) -> None:
        repo_root = Path("/tmp/repo")
        plan = _empty_plan(_lib_spec())
        assert _resolve_package_path(plan, repo_root) == repo_root / "backend" / "libs" / "nohiki-demo"

    def test_service(self) -> None:
        repo_root = Path("/tmp/repo")
        plan = _empty_plan(_service_spec())
        assert _resolve_package_path(plan, repo_root) == repo_root / "backend" / "services" / "demo-service"


class TestRunVerifyMode:
    def test_none_short_circuits(self) -> None:
        result = run_verify(_empty_plan(_lib_spec()), mode=VerifyMode.NONE, repo_root=Path("/tmp"))
        assert result.passed is True
        assert result.checks == ()

    def test_default_invokes_five_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_verify(_empty_plan(_lib_spec()), mode=VerifyMode.DEFAULT, repo_root=Path("/tmp/repo"))
        assert result.passed is True
        assert len(result.checks) == 5
        assert {c.name for c in result.checks} == {"uv sync", "ruff check", "ruff format", "ty check", "pytest collect"}

    def test_full_invokes_pytest_not_collect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_verify(_empty_plan(_lib_spec()), mode=VerifyMode.FULL, repo_root=Path("/tmp/repo"))
        names = {c.name for c in result.checks}
        assert "pytest" in names
        assert "pytest collect" not in names

    def test_first_failure_does_not_abort_remainder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        returncodes = iter([1, 0, 0, 0, 0])

        def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, returncode=next(returncodes), stdout="", stderr="err")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_verify(_empty_plan(_lib_spec()), mode=VerifyMode.DEFAULT, repo_root=Path("/tmp/repo"))
        assert result.passed is False
        assert len(result.checks) == 5
        assert "uv sync" in result.failures

    def test_missing_uv_executable_records_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            msg = "uv"
            raise FileNotFoundError(msg)

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_verify(_empty_plan(_lib_spec()), mode=VerifyMode.DEFAULT, repo_root=Path("/tmp/repo"))
        assert result.passed is False
        assert all(c.passed is False for c in result.checks)


class TestVerifyResultDataclass:
    def test_is_frozen(self) -> None:
        result = VerifyResult(mode=VerifyMode.NONE, passed=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(result, "passed", False)  # noqa: B010

    def test_check_result_fields(self) -> None:
        cr = CheckResult(name="ruff", passed=True, stdout="", stderr="", duration_s=0.1)
        assert cr.name == "ruff"
        assert cr.duration_s == pytest.approx(0.1)
