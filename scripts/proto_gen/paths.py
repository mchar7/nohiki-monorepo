"""Path constants and file discovery for proto generation."""

from pathlib import Path
from typing import Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PROTO_DIR: Final[Path] = REPO_ROOT / "proto"
NOHIKI_PROTO_DIR: Final[Path] = PROTO_DIR / "nohiki"
OUTPUT_DIR: Final[Path] = REPO_ROOT / "backend" / "libs" / "nohiki-domain-models" / "src"
NOHIKI_OUTPUT_DIR: Final[Path] = OUTPUT_DIR / "nohiki"


def get_deps_cache_dir() -> Path:
    """Get XDG-compliant cache directory for proto dependencies."""
    xdg_cache = Path.home() / ".cache"
    return xdg_cache / "nohiki" / "proto_deps"


def discover_proto_files(proto_dir: Path) -> list[Path]:
    """Discover all .proto files in the given directory."""
    return sorted(proto_dir.rglob("*.proto"))


def discover_init_files(output_dir: Path) -> list[Path]:
    """Discover all __init__.py files in the generated output."""
    return sorted(output_dir.rglob("__init__.py"))
