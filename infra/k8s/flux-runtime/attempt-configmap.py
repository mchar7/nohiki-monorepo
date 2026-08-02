#!/usr/bin/env python3
"""Produce the mandatory Flux post-build substitution input."""

from __future__ import annotations

import argparse
import json
import re
import sys

ATTEMPT_SUFFIX = re.compile(r"a[0-9]{8}-[0-9a-f]{8}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def main() -> int:
    """Validate attempt bindings and emit one canonical ConfigMap."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt-suffix", required=True)
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--source-reviewed-sha", required=True)
    parser.add_argument("--source-remote-sha", required=True)
    parser.add_argument("--artifact-lock-sha256", required=True)
    args = parser.parse_args()
    if ATTEMPT_SUFFIX.fullmatch(args.attempt_suffix) is None:
        parser.error("attempt suffix must be aNNNNNNNN-xxxxxxxx")
    revisions = (args.source_head_sha, args.source_reviewed_sha, args.source_remote_sha)
    if any(SHA.fullmatch(value) is None for value in revisions) or len(set(revisions)) != 1:
        parser.error("source revisions must be the same full lowercase Git SHA")
    if DIGEST.fullmatch(args.artifact_lock_sha256) is None:
        parser.error("artifact lock SHA-256 must be 64 lowercase hexadecimal characters")
    document = {
        "apiVersion": "v1",
        "data": {
            "NOHIKI_ARTIFACT_LOCK_SHA256": args.artifact_lock_sha256,
            "NOHIKI_ATTEMPT_SUFFIX": args.attempt_suffix,
            "NOHIKI_SOURCE_HEAD_SHA": args.source_head_sha,
            "NOHIKI_SOURCE_REMOTE_SHA": args.source_remote_sha,
            "NOHIKI_SOURCE_REVIEWED_SHA": args.source_reviewed_sha,
        },
        "kind": "ConfigMap",
        "metadata": {"name": "nohiki-verification-attempt", "namespace": "flux-system"},
    }
    sys.stdout.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
