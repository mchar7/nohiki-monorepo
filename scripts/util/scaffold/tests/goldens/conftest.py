"""Render helpers for invariant tests."""

from __future__ import annotations

from pathlib import Path

from nohiki_scaffold.core.build import build_plan
from nohiki_scaffold.core.models import LibSpec, ServiceSpec


def render(spec: ServiceSpec | LibSpec, *, repo_root: Path | None = None) -> dict[str, str]:
    """Render a spec and return a dict mapping relative-path -> content.

    Paths are returned as POSIX-style strings relative to the repo root, so
    invariant tests can look up files by a stable key regardless of OS.
    """
    root = repo_root or Path("/tmp/scaffold-test-root")
    plan = build_plan(spec, repo_root=root)
    return {str(f.path.relative_to(root).as_posix()): f.content for f in plan.files}
