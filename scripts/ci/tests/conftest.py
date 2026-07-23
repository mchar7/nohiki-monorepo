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


# Hook-time git exports (GIT_DIR, GIT_INDEX_FILE, ...) override cwd-based
# repository discovery, so scratch-repo git calls in tests would silently
# target the real repository when the suite runs inside a lefthook hook.
_GIT_DISCOVERY_ENV = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
)


@pytest.fixture(autouse=True)
def _scrub_git_discovery_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _GIT_DISCOVERY_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session", autouse=True)
def _cache_manifest_subprocesses(render_cache: RenderCache) -> Iterator[None]:
    patch = pytest.MonkeyPatch()
    if yaml.__with_libyaml__:
        patch.setattr(yaml, "SafeLoader", yaml.CSafeLoader)
    patch.setattr(subprocess, "run", render_cache.run)
    yield
    patch.undo()
