"""Buf dependency management for proto generation."""

import subprocess
from pathlib import Path

from .console import console


def export_buf_dependencies(proto_dir: Path, deps_dir: Path) -> bool:
    """Export buf dependencies to a directory (buf export)."""
    deps_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["buf", "export", "-o", str(deps_dir)],
        cwd=proto_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        console.print(f"[red]buf export failed:[/red] {result.stderr}")
        return False
    return True


def fetch_dependencies(proto_dir: Path, deps_dir: Path) -> bool:
    """Export dependencies resolved by the committed buf.lock."""
    return export_buf_dependencies(proto_dir, deps_dir)
