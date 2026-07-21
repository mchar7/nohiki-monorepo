#!/usr/bin/env python3
"""Emit canonical image inventory views for CI and local parity checks."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ci_checks.core.image_inventory import (
    image_names,
    load_inventory,
    matrix,
    read_affected_record,
)


def emit_matrix(args: argparse.Namespace) -> None:
    """Emit a GitHub matrix, failing closed to the full inventory."""
    images = load_inventory(args.inventory)
    selected: set[str] | None = None
    if args.artifact is not None:
        try:
            selected = read_affected_record(args.artifact, args.source_sha, images)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"warning: {exc}; building the full image inventory\n")
    rendered = matrix(images, selected)
    sys.stdout.write(json.dumps(rendered, separators=(",", ":")) + "\n")


def emit_names(args: argparse.Namespace) -> None:
    """Emit canonical names, one per line."""
    sys.stdout.write("\n".join(image_names(load_inventory(args.inventory))) + "\n")


def emit_specs(args: argparse.Namespace) -> None:
    """Emit tab-separated build specifications for Just recipes."""
    lines = [
        "\t".join(str(image[field]) for field in ("name", "context", "dockerfile", "build_args"))
        for image in load_inventory(args.inventory)
    ]
    sys.stdout.write("\n".join(lines) + "\n")


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--inventory",
        type=Path,
        default=Path(__file__).with_name("image_inventory.json"),
    )
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(required=True)
    matrix_parser = commands.add_parser("matrix", parents=[common])
    matrix_parser.add_argument("--artifact", type=Path)
    matrix_parser.add_argument("--source-sha", default="")
    matrix_parser.set_defaults(run=emit_matrix)
    names_parser = commands.add_parser("names", parents=[common])
    names_parser.set_defaults(run=emit_names)
    specs_parser = commands.add_parser("specs", parents=[common])
    specs_parser.set_defaults(run=emit_specs)
    return root


def main() -> int:
    """Run the selected inventory command."""
    args = parser().parse_args()
    try:
        args.run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
