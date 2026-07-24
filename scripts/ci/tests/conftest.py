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


# Git exports repository-discovery env vars (GIT_DIR, GIT_WORK_TREE, ...) to hooks;
# under a pre-push hook these override cwd-based discovery, so a scratch-repo `git init`
# would silently target the real repository and re-initialize it as bare. The scrub is
# SESSION-scoped so it runs before every fixture -- including module-scoped ones (e.g. the
# cluster-reset harness) that shell out to git during setup, which a function-scoped
# fixture would run too late to protect.
_GIT_DISCOVERY_ENV = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


@pytest.fixture(scope="session", autouse=True)
def _scrub_git_discovery_env() -> Iterator[None]:
    patch = pytest.MonkeyPatch()
    for name in _GIT_DISCOVERY_ENV:
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
