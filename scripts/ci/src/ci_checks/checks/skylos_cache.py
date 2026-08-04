"""Run Skylos with bounded cache retention."""

from __future__ import annotations

import os
import sys
from pathlib import Path

_STATIC_CACHE_RELATIVE = Path("cache/runs/v1/static")
# Two entries cover the current and prior inputs; a measured inner miss costs 196s versus a 9s hit.
_STATIC_CACHE_KEEP_ENTRIES = 2


def _prune_static_cache() -> None:
    """Keep only the two newest whole-result cache entries."""
    cache_root = Path(os.environ.get("SKYLOS_CACHE_DIR", Path.cwd() / ".skylos"))
    static_cache = cache_root / _STATIC_CACHE_RELATIVE
    entries = sorted(
        static_cache.glob("*.cache"),
        key=lambda entry: entry.stat().st_mtime_ns,
        reverse=True,
    )
    for entry in entries[_STATIC_CACHE_KEEP_ENTRIES:]:
        entry.unlink()


def main() -> None:
    """Run Skylos, then bound retained whole-result generations."""
    from skylos import cli

    try:
        cli.main()
    finally:
        try:
            _prune_static_cache()
        except OSError as exc:
            sys.stderr.write(f"Skylos static cache pruning failed: {exc}\n")
            raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
