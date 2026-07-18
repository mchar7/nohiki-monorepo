#!/usr/bin/env python3
"""Validate and atomically write Helm release provenance."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

_EXPECTED_REPOSITORY = "mchar7/nohiki-monorepo"
_SOURCE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIGEST = re.compile(r"sha256:([0-9a-f]{64})\Z")
_PACKAGE_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CERTIFICATE_IDENTITY = (
    "https://github.com/mchar7/nohiki-monorepo/.github/workflows/release-helm-charts.yml@refs/heads/main"
)
_CERTIFICATE_ISSUER = "https://token.actions.githubusercontent.com"


def _repository(value: str) -> str:
    if value != _EXPECTED_REPOSITORY:
        message = f"repository must be exactly {_EXPECTED_REPOSITORY}"
        raise argparse.ArgumentTypeError(message)
    return value


def _source_sha(value: str) -> str:
    if _SOURCE_SHA.fullmatch(value) is None:
        message = "source SHA must be 40 lowercase hexadecimal characters"
        raise argparse.ArgumentTypeError(message)
    return value


def _digest(value: str) -> str:
    match = _DIGEST.fullmatch(value)
    if match is None or set(match.group(1)) == {"0"}:
        message = "digest must be a nonzero lowercase sha256 digest"
        raise argparse.ArgumentTypeError(message)
    return value


def _package_sha256(value: str) -> str:
    if _PACKAGE_SHA256.fullmatch(value) is None or set(value) == {"0"}:
        message = "package SHA-256 must be 64 nonzero lowercase hexadecimal characters"
        raise argparse.ArgumentTypeError(message)
    return value


def _positive_run_id(value: str) -> int:
    try:
        run_id = int(value)
    except ValueError as error:
        message = "workflow run ID must be a positive integer"
        raise argparse.ArgumentTypeError(message) from error
    if run_id <= 0:
        message = "workflow run ID must be a positive integer"
        raise argparse.ArgumentTypeError(message)
    return run_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=_repository)
    parser.add_argument("--source-sha", required=True, type=_source_sha)
    parser.add_argument("--workflow-run-id", required=True, type=_positive_run_id)
    parser.add_argument("--foundation-version", required=True)
    parser.add_argument("--application-version", required=True)
    parser.add_argument("--foundation-digest", required=True, type=_digest)
    parser.add_argument("--application-digest", required=True, type=_digest)
    parser.add_argument("--foundation-package-sha256", required=True, type=_package_sha256)
    parser.add_argument("--application-package-sha256", required=True, type=_package_sha256)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    """Validate inputs and atomically emit the release record."""
    args = _parser().parse_args()
    foundation_version = f"0.1.0-{args.source_sha}"
    application_version = f"0.2.0-{args.source_sha}"
    if args.foundation_version != foundation_version or args.application_version != application_version:
        message = "chart versions must be derived from the exact source SHA"
        raise SystemExit(message)
    if args.foundation_digest == args.application_digest:
        message = "chart digests must be distinct"
        raise SystemExit(message)
    if args.foundation_package_sha256 == args.application_package_sha256:
        message = "canonical package SHA-256 values must be distinct"
        raise SystemExit(message)

    registry_root = f"ghcr.io/{args.repository.lower()}/charts"
    record = {
        "charts": [
            {
                "digest": args.foundation_digest,
                "package_sha256": args.foundation_package_sha256,
                "name": "nohiki-foundation",
                "ref": f"{registry_root}/nohiki-foundation:{foundation_version}",
                "version": foundation_version,
            },
            {
                "digest": args.application_digest,
                "package_sha256": args.application_package_sha256,
                "name": "nohiki",
                "ref": f"{registry_root}/nohiki:{application_version}",
                "version": application_version,
            },
        ],
        "source_sha": args.source_sha,
        "workflow_url": f"https://github.com/{args.repository}/actions/runs/{args.workflow_run_id}",
        "verification": {
            "certificate_identity": _CERTIFICATE_IDENTITY,
            "certificate_oidc_issuer": _CERTIFICATE_ISSUER,
        },
    }

    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
