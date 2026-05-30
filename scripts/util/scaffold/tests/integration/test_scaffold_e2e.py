"""End-to-end scaffold plan/apply tests in a tmp repo.

Exercises build_plan + apply_plan against all 7 archetype factories,
asserting files land on disk and the root pyproject is edited
without corruption. No real ``uv sync`` is run; we trust the unit-level
checks plus the static invariants in ``tests/goldens`` for that layer.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from nohiki_scaffold.core.build import apply_plan, build_plan
from nohiki_scaffold.core.models import LibSpec, ServiceSpec

from ..goldens import factories

pytestmark = pytest.mark.integration


_SERVICE_FACTORIES: list[Callable[[], ServiceSpec]] = [
    factories.kafka_only_consumer,
    factories.kafka_only_producer,
    factories.http_only_producer,
    factories.http_and_kafka_ml,
]
_LIB_FACTORIES: list[Callable[[], LibSpec]] = [
    factories.plain_lib,
    factories.namespace_lib,
    factories.lib_with_testing,
]


@pytest.mark.parametrize("factory", _SERVICE_FACTORIES, ids=lambda f: f.__name__)
def test_service_plan_applies(factory: Callable[[], ServiceSpec], tmp_repo: Path) -> None:
    spec = factory()
    plan = build_plan(spec, repo_root=tmp_repo)
    apply_plan(plan, repo_root=tmp_repo, dry_run=False)

    target = tmp_repo / "backend" / "services" / spec.name
    assert target.is_dir()
    assert (target / "pyproject.toml").is_file()
    assert (target / "Dockerfile").is_file()
    assert (target / "src" / spec.module_name / "main.py").is_file()


@pytest.mark.parametrize("factory", _LIB_FACTORIES, ids=lambda f: f.__name__)
def test_lib_plan_applies(factory: Callable[[], LibSpec], tmp_repo: Path) -> None:
    spec = factory()
    plan = build_plan(spec, repo_root=tmp_repo)
    apply_plan(plan, repo_root=tmp_repo, dry_run=False)

    target = tmp_repo / "backend" / "libs" / spec.name
    assert target.is_dir()
    assert (target / "pyproject.toml").is_file()
    assert (target / "README.md").is_file()


def test_root_pyproject_retains_valid_toml(tmp_repo: Path) -> None:
    """Applying a plan must leave the root pyproject parseable as TOML."""
    spec = factories.plain_lib()
    plan = build_plan(spec, repo_root=tmp_repo)
    apply_plan(plan, repo_root=tmp_repo, dry_run=False)

    parsed = tomllib.loads((tmp_repo / "pyproject.toml").read_text(encoding="utf-8"))
    members = parsed["tool"]["uv"]["workspace"]["members"]
    assert any("nohiki-demo-util" in m for m in members)


def test_dry_run_does_not_touch_disk(tmp_repo: Path) -> None:
    spec = factories.plain_lib()
    plan = build_plan(spec, repo_root=tmp_repo)
    before = (tmp_repo / "pyproject.toml").read_text(encoding="utf-8")

    apply_plan(plan, repo_root=tmp_repo, dry_run=True)

    assert not (tmp_repo / "backend" / "libs" / spec.name).exists()
    assert (tmp_repo / "pyproject.toml").read_text(encoding="utf-8") == before
