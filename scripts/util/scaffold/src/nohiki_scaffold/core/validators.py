"""Cross-cutting validators for fully-constructed specs.

Unlike the intrinsic checks in :mod:`nohiki_scaffold.core.models`
(which enforce regex/consistency at spec construction), these checks
need access to the repository filesystem: workspace membership lookup,
existing directory collision, etc.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nohiki_scaffold.core.models import LibSpec, ServiceSpec


def _load_workspace_members(repo_root: Path) -> frozenset[str]:
    """Read root pyproject and return the set of declared workspace member paths."""
    raw = (repo_root / "pyproject.toml").read_text()
    data = tomllib.loads(raw)
    members = data.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
    return frozenset(members)


def target_directory_for_service(repo_root: Path, spec: ServiceSpec) -> Path:
    """Return the absolute path where a service would be scaffolded."""
    return repo_root / "backend" / "services" / spec.name


def target_directory_for_lib(repo_root: Path, spec: LibSpec) -> Path:
    """Return the absolute path where a library would be scaffolded."""
    return repo_root / "backend" / "libs" / spec.name


def validate_service_spec(spec: ServiceSpec, repo_root: Path) -> list[str]:
    """Return a list of problem strings for a service spec against ``repo_root``.

    Empty list means no problems. Callers translate each entry into a
    CLI-user-visible error line.
    """
    problems: list[str] = []
    target = target_directory_for_service(repo_root, spec)
    members = _load_workspace_members(repo_root)
    relative = target.relative_to(repo_root).as_posix()
    if relative in members:
        problems.append(f"Workspace already has member {relative!r}")
    if target.exists():
        problems.append(f"Target directory {target} already exists")
    return problems


def validate_lib_spec(spec: LibSpec, repo_root: Path) -> list[str]:
    """Return a list of problem strings for a library spec against ``repo_root``."""
    problems: list[str] = []
    target = target_directory_for_lib(repo_root, spec)
    members = _load_workspace_members(repo_root)
    relative = target.relative_to(repo_root).as_posix()
    if relative in members:
        problems.append(f"Workspace already has member {relative!r}")
    if target.exists():
        problems.append(f"Target directory {target} already exists")
    return problems


__all__ = [
    "target_directory_for_lib",
    "target_directory_for_service",
    "validate_lib_spec",
    "validate_service_spec",
]
