#!/usr/bin/env python3
"""Capture and deterministically assemble first-party image digests."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import NoReturn

DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
SHA_RE = re.compile(r"[0-9a-fA-F]{40}\Z")
REPOSITORY_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9-]*/[a-zA-Z0-9._-]+\Z")

sys.path.insert(0, str(Path(__file__).parent / "src"))

from ci_checks.core.image_inventory import image_names, load_inventory  # noqa: E402


def fail(message: str) -> NoReturn:
    """Raise a digest contract validation error."""
    raise ValueError(message)


def contract(inventory: Path, repository: str) -> tuple[list[str], str]:
    """Load canonical image names and derive their registry prefix."""
    names = sorted(image_names(load_inventory(inventory)))
    if not REPOSITORY_RE.fullmatch(repository):
        fail("repository must be a canonical <owner>/<repo> value")
    prefix = f"ghcr.io/{repository.lower()}"
    return names, prefix


def validate_metadata(source_sha: str, workflow_url: str, repository: str) -> None:
    """Validate the source revision and workflow-run provenance."""
    if not SHA_RE.fullmatch(source_sha):
        fail("sourceSha must be exactly 40 hexadecimal characters")
    expected = f"https://github.com/{repository}/actions/runs/"
    if not workflow_url.startswith(expected) or not re.fullmatch(re.escape(expected) + r"[0-9]+", workflow_url):
        fail("workflowUrl must be an HTTPS Actions run URL for this repository")


def record(args: argparse.Namespace) -> None:
    """Validate and write one image digest record from the environment."""
    env = os.environ
    source_sha, workflow_url, repository = (
        env.get("SOURCE_SHA", ""),
        env.get("WORKFLOW_URL", ""),
        env.get("GITHUB_REPOSITORY", ""),
    )
    names, prefix = contract(args.inventory, repository)
    name, image, digest = (
        env.get("IMAGE_NAME", ""),
        env.get("IMAGE_REF", ""),
        env.get("IMAGE_DIGEST", ""),
    )
    if name not in names:
        fail("image name is not an exact workflow matrix entry")
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


def assemble(args: argparse.Namespace) -> None:
    """Merge fresh affected-image records into the existing digest overlay."""
    names, prefix = contract(args.inventory, args.repository)
    try:
        selected_value = json.loads(args.affected)
    except json.JSONDecodeError as exc:
        fail(f"affected images are invalid JSON: {exc}")
    if (
        not isinstance(selected_value, list)
        or not all(isinstance(name, str) for name in selected_value)
        or len(selected_value) != len(set(selected_value))
    ):
        fail("affected images must be a unique JSON string list")
    affected = set(selected_value)
    if not affected <= set(names):
        fail(f"affected images are not canonical: {sorted(affected - set(names))}")

    existing: dict[str, str] = {}
    for line in args.existing.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"    ([^:]+): (sha256:[0-9a-f]{64})", line)
        if match is not None:
            existing[match.group(1)] = match.group(2)
    expected_refs = {f"{prefix}/{name}" for name in names}
    if set(existing) != expected_refs:
        fail("existing digest overlay does not exactly match the canonical inventory")

    files = sorted(args.records.rglob("*.json"))
    records: dict[str, dict[str, str]] = {}
    digests: set[str] = set()
    metadata: tuple[str, str] | None = None
    for path in files:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            fail(f"invalid JSON record {path}: {exc}")
        if (
            not isinstance(data, dict)
            or set(data) != {"name", "image", "digest", "sourceSha", "workflowUrl"}
            or not all(isinstance(value, str) for value in data.values())
        ):
            fail(f"record {path} has an invalid schema")
        name, digest = data["name"], data["digest"]
        if name not in names or data["image"] != f"{prefix}/{name}":
            fail(f"record {path} has a noncanonical image")
        if name in records:
            fail(f"duplicate record for {name}")
        if not DIGEST_RE.fullmatch(digest) or digest in digests:
            fail(f"record {path} has a malformed or duplicate digest")
        validate_metadata(data["sourceSha"], data["workflowUrl"], args.repository)
        current_metadata = (data["sourceSha"].lower(), data["workflowUrl"])
        if metadata is not None and current_metadata != metadata:
            fail("records do not share source metadata")
        metadata = current_metadata
        records[name], digests = data, digests | {digest}
    missing, extra = affected - set(records), set(records) - affected
    if missing or extra or len(files) != len(affected):
        fail(f"record set mismatch; missing={sorted(missing)}, extra={sorted(extra)}")

    composed = existing | {f"{prefix}/{name}": record["digest"] for name, record in records.items()}
    lines = [
        "# Generated by .github/workflows/build-push.yml; do not edit.",
        "global:",
        "  imageDigests:",
    ]
    lines.extend(f"    {reference}: {composed[reference]}" for reference in sorted(expected_refs))
    lines.append("")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines))


def parser() -> argparse.ArgumentParser:
    """Build the command-line parser for recording and assembling digests."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--inventory",
        type=Path,
        default=Path(__file__).with_name("image_inventory.json"),
    )
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("record", parents=[common])
    capture.add_argument("--output", type=Path, required=True)
    capture.set_defaults(run=record)
    aggregate = commands.add_parser("assemble", parents=[common])
    aggregate.add_argument("--records", type=Path, required=True)
    aggregate.add_argument("--existing", type=Path, required=True)
    aggregate.add_argument("--affected", required=True)
    aggregate.add_argument("--output", type=Path, required=True)
    aggregate.add_argument("--repository", required=True)
    aggregate.set_defaults(run=assemble)
    return root


def main() -> int:
    """Run the image digest command and return its process exit status."""
    try:
        args = parser().parse_args()
        args.run(args)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
