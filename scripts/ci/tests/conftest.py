from __future__ import annotations

import subprocess
from collections.abc import Iterator

import pytest
import yaml
from helm_test_utils import RenderCache


@pytest.fixture(scope="session")
def render_cache(tmp_path_factory: pytest.TempPathFactory) -> RenderCache:
    """Share Helm and Kustomize renders across tests and xdist workers."""
    base = tmp_path_factory.getbasetemp()
    session_directory = base.parent if base.name.startswith("popen-") else base
    return RenderCache(session_directory / "nohiki-render-cache")


# The hosted tests step exports these (checks.yml:528) and the gate CLI reads one as a
# typer `envvar=`, so an unscrubbed suite silently exercises CI's configuration instead of
# its own: the workspace sync is skipped and tests asserting sync behaviour never fire.
# Git's repository-discovery variables are scrubbed session-wide by the shared
# nohiki-test-utils plugin, which every package inherits; only this ci-checks-specific set
# is local.
_CI_RUNNER_ENV = (
    "CI_CHECKS_SKIP_WORKSPACE_SYNC",
    "CI_CHECKS_RUN_SUCCESS",
)


@pytest.fixture(scope="session", autouse=True)
def _scrub_ci_runner_env() -> Iterator[None]:
    patch = pytest.MonkeyPatch()
    for name in _CI_RUNNER_ENV:
        patch.delenv(name, raising=False)
    yield
    patch.undo()


@pytest.fixture(scope="session", autouse=True)
def _cache_manifest_subprocesses(render_cache: RenderCache) -> Iterator[None]:
    patch = pytest.MonkeyPatch()
    if yaml.__with_libyaml__:
        patch.setattr(yaml, "SafeLoader", yaml.CSafeLoader)
    patch.setattr(subprocess, "run", render_cache.run)
    yield
    patch.undo()
