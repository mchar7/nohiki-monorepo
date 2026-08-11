#!/usr/bin/env python3
"""Capture and deterministically assemble first-party image digests."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from ci_checks.core.image_inventory import (
    INVENTORY_PATH,
    ImageInventory,
    InventoryError,
    canonical_subset,
    load_inventory,
)

DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
SHA_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
REPOSITORY_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]*/[a-zA-Z0-9._-]+\Z")
OVERLAY_RE = re.compile(r" {4}(?P<image>\S+): (?P<digest>sha256:[0-9a-f]{64})\Z")
RECORD_KEYS = frozenset({"name", "image", "digest", "sourceSha", "workflowUrl"})


def fail(message: str) -> NoReturn:
    """Raise a digest contract validation error.

    Args:
        message: Human-readable contract violation.

    Raises:
        ValueError: Always.
    """
    raise ValueError(message)


def contract(inventory: Path, repository: str) -> tuple[ImageInventory, str]:
    """Load the canonical inventory and derive its production registry prefix.

    Args:
        inventory: Canonical inventory path.
        repository: GitHub ``owner/repo``.

    Returns:
        The validated inventory and its lowercase GHCR prefix.
    """
    try:
        loaded = load_inventory(inventory)
    except InventoryError as exc:
        fail(str(exc))
    if not REPOSITORY_RE.fullmatch(repository):
        fail("repository must be a canonical <owner>/<repo> value")
    return loaded, f"ghcr.io/{repository.lower()}"


def validate_metadata(source_sha: str, workflow_url: str, repository: str) -> None:
    """Validate the source revision and workflow-run provenance.

    Args:
        source_sha: Published source commit.
        workflow_url: Actions run URL that produced the digest.
        repository: GitHub ``owner/repo``.
    """
    if not SHA_RE.fullmatch(source_sha):
        fail("sourceSha must be exactly 40 hexadecimal characters")
    expected = f"https://github.com/{repository}/actions/runs/"
    if not workflow_url.startswith(expected) or not re.fullmatch(re.escape(expected) + r"[0-9]+", workflow_url):
        fail("workflowUrl must be an HTTPS Actions run URL for this repository")


def record(args: argparse.Namespace) -> None:
    """Validate and write one image digest record from the environment.

    Args:
        args: Parsed ``record`` arguments.
    """
    env = os.environ
    source_sha, workflow_url, repository = (
        env.get("SOURCE_SHA", ""),
        env.get("WORKFLOW_URL", ""),
        env.get("GITHUB_REPOSITORY", ""),
    )
    inventory, prefix = contract(args.inventory, repository)
    name, image, digest = (
        env.get("IMAGE_NAME", ""),
        env.get("IMAGE_REF", ""),
        env.get("IMAGE_DIGEST", ""),
    )
    if name not in inventory.names:
        fail("image name is not a canonical inventory entry")
    if image != f"{prefix}/{name}":
        fail("image ref is not the canonical production GHCR ref")
    if not DIGEST_RE.fullmatch(digest):
        fail("digest must be lowercase sha256 with 64 hexadecimal characters")
    validate_metadata(source_sha, workflow_url, repository)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "name": name,
                "image": image,
                "digest": digest,
                "sourceSha": source_sha.lower(),
                "workflowUrl": workflow_url,
            },
            sort_keys=True,
        )
        + "\n"
    )


def existing_digests(path: Path, inventory: ImageInventory) -> dict[str, str]:
    """Read the checked-in overlay and require one canonical digest per inventory name.

    Args:
        path: Existing overlay path.
        inventory: Validated inventory.

    Returns:
        Canonical name to digest for every inventory image.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read existing digest overlay {path}: {exc}")
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = OVERLAY_RE.fullmatch(line)
        if match is None:
            continue
        name = match["image"]
        if name not in inventory.names:
            fail(f"existing digest overlay has a noncanonical image name {name}")
        if name in found:
            fail(f"existing digest overlay repeats {name}")
        found[name] = match["digest"]
    missing = [name for name in inventory.names if name not in found]
    if missing:
        fail(f"existing digest overlay is missing digests for {missing}")
    return found


def fresh_digests(
    directory: Path,
    affected: Sequence[str],
    inventory: ImageInventory,
    prefix: str,
    repository: str,
) -> dict[str, str]:
    """Read the uploaded digest records and require exactly one per affected image.

    Args:
        directory: Directory holding the downloaded record files.
        affected: Canonical names this run rebuilt.
        inventory: Validated inventory.
        prefix: Canonical GHCR prefix.
        repository: GitHub ``owner/repo`` every record must be provenanced to.

    Returns:
        Canonical name to freshly published digest.
    """
    files = sorted(directory.rglob("*.json")) if directory.is_dir() else []
    if not files and affected:
        fail("no digest records found")
    records: dict[str, str] = {}
    digests: set[str] = set()
    metadata: tuple[str, str] | None = None
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"invalid JSON record {path}: {exc}")
        if not isinstance(data, dict) or set(data) != RECORD_KEYS or not all(isinstance(v, str) for v in data.values()):
            fail(f"record {path} has an invalid schema")
        name, digest = str(data["name"]), str(data["digest"])
        if name not in inventory.names or data["image"] != f"{prefix}/{name}":
            fail(f"record {path} has a noncanonical image")
        if name in records:
            fail(f"duplicate record for {name}")
        if not DIGEST_RE.fullmatch(digest) or digest in digests:
            fail(f"record {path} has a malformed or duplicate digest")
        validate_metadata(str(data["sourceSha"]), str(data["workflowUrl"]), repository)
        current = (str(data["sourceSha"]).lower(), str(data["workflowUrl"]))
        if metadata is not None and current != metadata:
            fail("records do not share source metadata")
        metadata, records[name], digests = current, digest, digests | {digest}
    expected = set(affected)
    missing, extra = sorted(expected - set(records)), sorted(set(records) - expected)
    if missing or extra:
        fail(f"record set mismatch; missing={missing}, extra={extra}")
    return records


def assemble(args: argparse.Namespace) -> None:
    """Validate digest records and assemble the deployment values file.

    Args:
        args: Parsed ``assemble`` arguments.
    """
    inventory, prefix = contract(args.inventory, args.repository)
    carried: dict[str, str] = {}
    if args.affected is None:
        affected = list(inventory.names)
    else:
        try:
            affected = list(canonical_subset(json.loads(args.affected), inventory, label="affected image selection"))
        except json.JSONDecodeError as exc:
            fail(f"affected image selection is not valid JSON: {exc}")
        except InventoryError as exc:
            fail(str(exc))
        if args.existing is None:
            fail("--affected requires --existing to carry unaffected digests forward")
        carried = existing_digests(args.existing, inventory)
    published = fresh_digests(args.records, affected, inventory, prefix, args.repository)
    selected = set(affected)
    lines = [
        "# Generated by .github/workflows/build-push.yml; do not edit.",
        "global:",
        "  imageDigests:",
    ]
    lines.extend(
        f"    {name}: {published[name] if name in selected else carried[name]}" for name in sorted(inventory.names)
    )
    lines.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines))


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser for recording and assembling digests.

    Returns:
        The configured argument parser.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("record", parents=[common])
    capture.add_argument("--output", type=Path, required=True)
    capture.set_defaults(run=record)
    aggregate = commands.add_parser("assemble", parents=[common])
    aggregate.add_argument("--records", type=Path, required=True)
    aggregate.add_argument("--existing", type=Path)
    aggregate.add_argument("--affected")
    aggregate.add_argument("--output", type=Path, required=True)
    aggregate.add_argument("--repository", required=True)
    aggregate.set_defaults(run=assemble)
    return root


def main() -> int:
    """Run the image digest command and return its process exit status.

    Returns:
        Zero on success, two on any contract or I/O failure.
    """
    try:
        args = parser().parse_args()
        args.run(args)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
