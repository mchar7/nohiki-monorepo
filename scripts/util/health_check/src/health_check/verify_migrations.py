"""Compare canonical Alembic heads through per-service read-only connections."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import psycopg
from psycopg import sql

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")
_SERVICE = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
_HEAD = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True, slots=True)
class Entry:
    """Canonical migration expectation for one service schema."""

    service: str
    schema: str
    head: str

    @property
    def database_env(self) -> str:
        """Return the service-specific database URL environment variable name."""
        return f"MIGRATION_DATABASE_URL_{self.service.upper().replace('-', '_')}"


def _load_inventory(path: Path) -> tuple[Entry, ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        message = "invalid migration inventory"
        raise ValueError(message) from exc
    if not isinstance(payload, dict) or set(payload) != {"entries"}:
        message = "migration inventory must contain only entries"
        raise ValueError(message)
    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        message = "migration inventory has no entries"
        raise ValueError(message)
    entries: list[Entry] = []
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict) or set(raw) != {"service", "schema", "head"}:
            message = f"invalid migration inventory entry {index}"
            raise ValueError(message)
        entry = cast(dict[str, object], raw)
        service, schema, head = entry["service"], entry["schema"], entry["head"]
        if not isinstance(service, str) or not _SERVICE.fullmatch(service):
            message = f"invalid migration service at entry {index}"
            raise ValueError(message)
        if not isinstance(schema, str) or not _IDENTIFIER.fullmatch(schema):
            message = f"invalid migration schema at entry {index}"
            raise ValueError(message)
        if not isinstance(head, str) or not _HEAD.fullmatch(head):
            message = f"invalid migration head at entry {index}"
            raise ValueError(message)
        entries.append(Entry(service, schema, head))
    if entries != sorted(entries, key=lambda entry: entry.service):
        message = "migration inventory entries must be sorted"
        raise ValueError(message)
    if len({entry.service for entry in entries}) != len(entries) or len({entry.schema for entry in entries}) != len(
        entries
    ):
        message = "migration inventory contains duplicates"
        raise ValueError(message)
    return tuple(entries)


def _observed_head(entry: Entry) -> str:
    database_url = os.environ.get(entry.database_env)
    if not database_url:
        return "<configuration-missing>"
    query = sql.SQL("SELECT version_num, count(*) OVER () FROM {}.alembic_version LIMIT 1").format(
        sql.Identifier(entry.schema)
    )
    try:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute("SET default_transaction_read_only = on")
            row = connection.execute(query).fetchone()
    except psycopg.Error:
        return "<query-failed>"
    if row is None:
        return "<missing>"
    version, count = row
    if count != 1:
        return "<multiple>"
    return version if isinstance(version, str) and _HEAD.fullmatch(version) else "<invalid>"


def _write_evidence(path: Path, evidence: dict[str, object]) -> None:
    data = json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        with suppress(FileNotFoundError):
            Path(temporary).unlink()
        raise


def main() -> int:
    """Verify live migration heads and write deterministic evidence.

    Returns:
        Zero when every observed migration head matches its inventory entry.

    Raises:
        SystemExit: If the inventory is invalid or any migration head differs.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        entries = _load_inventory(args.inventory)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    results: list[dict[str, str | bool]] = []
    failures: list[str] = []
    for entry in entries:
        observed = _observed_head(entry)
        matches = observed == entry.head
        results.append(
            {
                "expected": entry.head,
                "matches": matches,
                "observed": observed,
                "schema": entry.schema,
                "service": entry.service,
            }
        )
        if not matches:
            failures.append(f"{entry.service}: expected exactly {entry.head}, observed {observed}")
    _write_evidence(args.evidence, {"entries": results, "passed": not failures})
    if failures:
        raise SystemExit("; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
