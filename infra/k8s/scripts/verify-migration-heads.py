#!/usr/bin/env python3
"""Verify live Alembic heads through read-only kubectl/psql queries."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_SERVICE = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_HEAD = re.compile(r"^[A-Za-z0-9_.-]+$")
_DNS_LABEL_MAX_LENGTH = 63

# _resolve_kubectl validates the executable before arguments cross this subprocess boundary.
_TRUSTED_RUN = subprocess.run


@dataclass(frozen=True, slots=True)
class Entry:
    """Expected migration head for one service schema."""

    service: str
    schema: str
    head: str


class VerificationError(ValueError):
    """A safe validation or runtime failure."""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify live Alembic heads and retain redacted JSON evidence.")
    parser.add_argument(
        "--inventory",
        type=Path,
        required=True,
        help="Canonical inventory JSON from ci-checks",
    )
    parser.add_argument("--namespace", default="nohiki", help="Kubernetes namespace (default: nohiki)")
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("migration-head-evidence.json"),
        help="Redacted evidence output",
    )
    parser.add_argument("--kubectl", default="kubectl", help="kubectl executable or path")
    parser.add_argument("--cluster", default="nohiki-pg", help="CloudNativePG cluster name")
    return parser.parse_args()


def _parse_entry(index: int, raw: object) -> Entry:
    if not isinstance(raw, dict) or set(raw) != {"service", "schema", "head"}:
        msg = f"invalid inventory entry {index}: expected service, schema, and head"
        raise VerificationError(msg)
    entry = cast("dict[str, object]", raw)
    service, schema, head = entry["service"], entry["schema"], entry["head"]
    if not isinstance(service, str) or not _SERVICE.fullmatch(service):
        msg = f"invalid inventory entry {index}: invalid service"
        raise VerificationError(msg)
    if not isinstance(schema, str) or not _IDENTIFIER.fullmatch(schema):
        msg = f"invalid inventory entry {index}: invalid schema"
        raise VerificationError(msg)
    if not isinstance(head, str) or not _HEAD.fullmatch(head):
        msg = f"invalid inventory entry {index}: invalid head"
        raise VerificationError(msg)
    return Entry(service, schema, head)


def _validate_entries(entries: list[Entry]) -> tuple[Entry, ...]:
    if not entries:
        msg = "invalid inventory: entries must not be empty"
        raise VerificationError(msg)
    if entries != sorted(entries, key=lambda entry: entry.service):
        msg = "invalid inventory: entries must be sorted by service"
        raise VerificationError(msg)
    services = {entry.service for entry in entries}
    schemas = {entry.schema for entry in entries}
    if len(services) != len(entries) or len(schemas) != len(entries):
        msg = "invalid inventory: duplicate service or schema"
        raise VerificationError(msg)
    return tuple(entries)


def _load_inventory(path: Path) -> tuple[Entry, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"invalid inventory: {exc}"
        raise VerificationError(msg) from exc
    if not isinstance(payload, dict) or set(payload) != {"entries"} or not isinstance(payload["entries"], list):
        msg = "invalid inventory: expected one entries array"
        raise VerificationError(msg)
    entries = [_parse_entry(index, raw) for index, raw in enumerate(payload["entries"])]
    return _validate_entries(entries)


def _run(kubectl: str, *args: str) -> str:
    try:
        result = _TRUSTED_RUN(
            [kubectl, *args],
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        msg = "kubectl execution failed"
        raise VerificationError(msg) from exc
    if result.returncode != 0:
        msg = "kubectl execution failed"
        raise VerificationError(msg)
    return result.stdout.strip()


def _primary_pod(kubectl: str, namespace: str, cluster: str) -> str:
    output = _run(
        kubectl,
        "get",
        "pods",
        "--namespace",
        namespace,
        "--selector",
        f"cnpg.io/cluster={cluster},role=primary",
        "--output",
        "jsonpath={range .items[*]}{.metadata.name}{'\\n'}{end}",
    )
    pods = sorted(line for line in output.splitlines() if line)
    if len(pods) != 1 or not _SERVICE.fullmatch(pods[0]):
        msg = f"expected exactly one primary pod, found {len(pods)}"
        raise VerificationError(msg)
    return pods[0]


def _database_name(service: str) -> str:
    return service.removesuffix("-service").replace("-", "_") + "_db"


def _alembic_head_query(schema: str) -> str:
    """Build a query from an inventory-validated SQL identifier."""
    if not _IDENTIFIER.fullmatch(schema):
        msg = "invalid schema identifier"
        raise VerificationError(msg)
    return f'SELECT version_num FROM "{schema}".alembic_version ORDER BY version_num;'


def _observed_head(kubectl: str, namespace: str, pod: str, entry: Entry) -> str:
    query = _alembic_head_query(entry.schema)
    output = _run(
        kubectl,
        "exec",
        "--namespace",
        namespace,
        pod,
        "--",
        "psql",
        "--no-psqlrc",
        "--dbname",
        _database_name(entry.service),
        "--tuples-only",
        "--no-align",
        "--set",
        "ON_ERROR_STOP=1",
        "--command",
        query,
    )
    versions = [line.strip() for line in output.splitlines() if line.strip()]
    if len(versions) != 1:
        return "<missing-or-multiple>"
    observed = versions[0]
    return observed if _HEAD.fullmatch(observed) else "<invalid>"


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    data = json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        except BaseException:
            with suppress(FileNotFoundError):
                temporary.unlink()
            raise
    except OSError as exc:
        msg = "failed to retain redacted evidence"
        raise VerificationError(msg) from exc


def _validate_cluster_names(namespace: str, cluster: str) -> None:
    if (
        not 1 <= len(namespace) <= _DNS_LABEL_MAX_LENGTH
        or not 1 <= len(cluster) <= _DNS_LABEL_MAX_LENGTH
        or not _SERVICE.fullmatch(namespace)
        or not _SERVICE.fullmatch(cluster)
    ):
        msg = "invalid namespace or cluster name"
        raise VerificationError(msg)


def _emit(message: str, *, error: bool = False) -> None:
    stream = sys.stderr if error else sys.stdout
    stream.write(f"{message}\n")


def _resolve_kubectl(value: str) -> str:
    """Resolve the requested kubectl executable to an absolute trusted path."""
    if executable := shutil.which(value):
        return executable
    msg = "kubectl executable not found"
    raise VerificationError(msg)


def main() -> int:
    """Verify all migration heads and retain deterministic redacted evidence."""
    args = _parse_args()
    try:
        _validate_cluster_names(args.namespace, args.cluster)
        kubectl = _resolve_kubectl(args.kubectl)
        entries = _load_inventory(args.inventory)
        pod = _primary_pod(kubectl, args.namespace, args.cluster)
        results: list[dict[str, str | bool]] = []
        for entry in entries:
            try:
                observed = _observed_head(kubectl, args.namespace, pod, entry)
            except VerificationError:
                observed = "<query-failed>"
            matches = observed == entry.head
            results.append(
                {
                    "actual": observed,
                    "expected": entry.head,
                    "matches": matches,
                    "schema": entry.schema,
                    "service": entry.service,
                }
            )
        passed = all(bool(result["matches"]) for result in results)
        _write_evidence(args.evidence, {"entries": results, "passed": passed})
    except VerificationError as exc:
        with suppress(VerificationError):
            _write_evidence(
                args.evidence,
                {"entries": [], "error": "verification-failed", "passed": False},
            )
        _emit(f"[FAIL] migration verification: {exc}", error=True)
        return 1
    else:
        for result in results:
            status = "PASS" if result["matches"] else "FAIL"
            _emit(
                f"[{status}] {result['service']} schema={result['schema']} "
                f"expected={result['expected']} actual={result['actual']}"
            )
        return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
