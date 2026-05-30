"""Tests for filesystem-aware spec validators."""

from __future__ import annotations

from pathlib import Path

import pytest
from nohiki_scaffold.core.features import KafkaRole, ServiceShape
from nohiki_scaffold.core.models import (
    DatabaseOptions,
    KafkaOptions,
    LibSpec,
    MLOptions,
    RedisOptions,
    S3Options,
    ServiceSpec,
)
from nohiki_scaffold.core.validators import (
    target_directory_for_lib,
    target_directory_for_service,
    validate_lib_spec,
    validate_service_spec,
)

_MINIMAL_ROOT_PYPROJECT = """\
[project]
name = "monorepo"
version = "0.0.0"

[tool.uv.workspace]
members = [
    "backend/services/existing-service",
    "backend/libs/nohiki-existing-lib",
]
"""


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Create a minimal fake monorepo root with one pre-existing member."""
    (tmp_path / "pyproject.toml").write_text(_MINIMAL_ROOT_PYPROJECT)
    (tmp_path / "backend" / "services" / "existing-service").mkdir(parents=True)
    (tmp_path / "backend" / "libs" / "nohiki-existing-lib").mkdir(parents=True)
    return tmp_path


def _service_spec(name: str) -> ServiceSpec:
    return ServiceSpec(
        name=name,
        friendly_name="Demo",
        description="",
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


def _lib_spec(name: str) -> LibSpec:
    return LibSpec(name=name, module_name=name.replace("-", "_"), description="x", owner="platform")


def test_service_target_directory(fake_repo: Path) -> None:
    spec = _service_spec("new-service")
    assert target_directory_for_service(fake_repo, spec) == fake_repo / "backend/services/new-service"


def test_service_collision_detected(fake_repo: Path) -> None:
    spec = _service_spec("existing-service")
    problems = validate_service_spec(spec, fake_repo)
    assert any("Workspace already has member" in p for p in problems)
    assert any("already exists" in p for p in problems)


def test_service_fresh_spec_has_no_problems(fake_repo: Path) -> None:
    spec = _service_spec("brand-new-service")
    assert validate_service_spec(spec, fake_repo) == []


def test_lib_collision_detected(fake_repo: Path) -> None:
    spec = _lib_spec("nohiki-existing-lib")
    problems = validate_lib_spec(spec, fake_repo)
    assert any("Workspace already has member" in p for p in problems)


def test_lib_target_directory(fake_repo: Path) -> None:
    spec = _lib_spec("nohiki-new-lib")
    assert target_directory_for_lib(fake_repo, spec) == fake_repo / "backend/libs/nohiki-new-lib"
    assert validate_lib_spec(spec, fake_repo) == []
