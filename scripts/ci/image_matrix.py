#!/usr/bin/env python3
"""Dependency-free canonical views over the release-image inventory.

Runs under a bare ``python3`` inside build-push, so the pure loader is reached by source path
rather than through an installed workspace package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ci_checks.core.image_inventory import (
    INVENTORY_PATH,
    ImageInventory,
    InventoryError,
    load_inventory,
    read_affected_record,
    render_matrix,
)


def matrix(args: argparse.Namespace, inventory: ImageInventory) -> None:
    """Emit the build matrix, falling back to the full set on any unusable record.

    Args:
        args: Parsed ``matrix`` arguments.
        inventory: The validated inventory.
    """
    names: list[str] | None = None
    if args.artifact is not None:
        try:
            names = list(read_affected_record(args.artifact, args.source_sha, inventory))
        except InventoryError as exc:
            sys.stderr.write(f"warning: {exc}; building every canonical image\n")
    sys.stdout.write(f"{json.dumps(render_matrix(inventory, names), separators=(',', ':'))}\n")


def names(_args: argparse.Namespace, inventory: ImageInventory) -> None:
    """Emit every canonical image name, one per declaration-ordered line.

    Args:
        _args: Parsed ``names`` arguments.
        inventory: The validated inventory.
    """
    for name in inventory.names:
        sys.stdout.write(f"{name}\n")


def specs(_args: argparse.Namespace, inventory: ImageInventory) -> None:
    """Emit tab-delimited name, context, dockerfile, and build args per image.

    Args:
        _args: Parsed ``specs`` arguments.
        inventory: The validated inventory.
    """
    for record in inventory.images:
        sys.stdout.write(f"{record.name}\t{record.context}\t{record.dockerfile}\t{record.build_args}\n")


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the inventory views.

    Returns:
        The configured argument parser.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("matrix", parents=[common])
    build.add_argument("--artifact", type=Path)
    build.add_argument("--source-sha", default="")
    build.set_defaults(run=matrix)
    commands.add_parser("names", parents=[common]).set_defaults(run=names)
    commands.add_parser("specs", parents=[common]).set_defaults(run=specs)
    return root


def main() -> int:
    """Run one inventory view and return its process exit status.

    Returns:
        Zero on success; two when the inventory authority itself is unusable.
    """
    root = parser()
    args = root.parse_args()
    if args.command == "matrix" and args.artifact is not None and not args.source_sha:
        root.error("--artifact requires --source-sha")
    try:
        args.run(args, load_inventory(args.inventory))
    except InventoryError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
