"""Protoc invocation with betterproto2 plugin.

The compiler and protoc frontend are pinned so regeneration is reproducible.
They run under ``uvx`` because the compiler's transitive dependencies must
remain isolated from the workspace environment. The subprocess runs from a
temporary cwd so the compiler's bundled formatter does not discover the
workspace ``pyproject.toml``.
"""

import subprocess
import tempfile
from pathlib import Path

from .console import console

BETTERPROTO2_COMPILER_VERSION = "0.10.0"
GRPCIO_TOOLS_VERSION = "1.82.1"


def run_protoc(
    proto_files: list[Path],
    proto_dir: Path,
    deps_dir: Path,
    output_dir: Path,
) -> bool:
    """Run protoc with betterproto2 plugin to generate Python code.

    Uses a pinned compiler toolchain in an isolated environment.
    """
    if not proto_files:
        console.print("[yellow]No proto files found to generate[/yellow]")
        return True

    output_dir.mkdir(parents=True, exist_ok=True)

    # Run from a temp directory so betterproto2's internal ruff
    # doesn't discover our pyproject.toml with unsupported target-version
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                "uvx",
                "--from",
                f"betterproto2_compiler=={BETTERPROTO2_COMPILER_VERSION}",
                "--with",
                f"grpcio-tools=={GRPCIO_TOOLS_VERSION}",
                "python",
                "-m",
                "grpc_tools.protoc",
                f"-I{proto_dir.resolve()}",
                f"-I{deps_dir.resolve()}",
                f"--python_betterproto2_out={output_dir.resolve()}",
                *[str(p.resolve()) for p in proto_files],
            ],
            capture_output=True,
            text=True,
            check=False,
            cwd=tmpdir,
        )

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown error"
        console.print(f"[red]protoc failed:[/red] {error_msg}")
        return False
    return True
