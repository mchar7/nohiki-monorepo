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
    render_vendored_dockerfile,
    vendored_base_images,
)


def matrix(args: argparse.Namespace, inventory: ImageInventory) -> None:
    """Emit a routine, affected, or explicitly full build matrix.

    Args:
        args: Parsed ``matrix`` arguments.
        inventory: The validated inventory.
    """
    if args.full:
        names = list(inventory.names)
    elif args.artifact is None:
        names = list(inventory.product_names)
    else:
        try:
            names = list(read_affected_record(args.artifact, args.source_sha, inventory))
        except InventoryError as exc:
            sys.stderr.write(f"warning: {exc}; building every canonical image\n")
            names = list(inventory.names)
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


def bases(args: argparse.Namespace, inventory: ImageInventory) -> None:
    """Emit source, mirror tag, digest, and mirror reference for every OCI build input."""
    checkout = args.inventory.resolve().parents[2]
    for pin in vendored_base_images(inventory, checkout, args.mirror_root):
        sys.stdout.write(f"{pin.source}\t{pin.mirror_tag}\t{pin.digest}\t{pin.mirror_reference}\n")


def mirror_dockerfile(args: argparse.Namespace, inventory: ImageInventory) -> None:
    """Write one inventory Dockerfile with every pinned OCI input replaced by its owned mirror."""
    records = {record.name: record for record in inventory.images}
    try:
        record = records[args.name]
    except KeyError as exc:
        msg = f"unknown image name: {args.name}"
        raise InventoryError(msg) from exc
    checkout = args.inventory.resolve().parents[2]
    rendered = render_vendored_dockerfile(record, checkout, args.mirror_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


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
    selection = build.add_mutually_exclusive_group()
    selection.add_argument("--artifact", type=Path)
    selection.add_argument("--full", action="store_true")
    build.add_argument("--source-sha", default="")
    build.set_defaults(run=matrix)
    commands.add_parser("names", parents=[common]).set_defaults(run=names)
    commands.add_parser("specs", parents=[common]).set_defaults(run=specs)
    base_images = commands.add_parser("bases", parents=[common])
    base_images.add_argument("--mirror-root", required=True)
    base_images.set_defaults(run=bases)
    mirror = commands.add_parser("mirror-dockerfile", parents=[common])
    mirror.add_argument("--name", required=True)
    mirror.add_argument("--mirror-root", required=True)
    mirror.add_argument("--output", required=True, type=Path)
    mirror.set_defaults(run=mirror_dockerfile)
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
