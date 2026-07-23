#!/usr/bin/env python3
"""Fail closed until Compose Kafka Connect and its CDC resources are ready."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Never
from urllib.parse import unquote, urlsplit

_REGISTRATION_SCRIPT = Path(os.environ.get("CONNECT_REGISTRATION_SCRIPT", "/kafka/scripts/register-connectors.sh"))
_CONFIG_DIR = Path(os.environ.get("CONNECT_CONFIG_DIR", str(_REGISTRATION_SCRIPT.parent.parent / "connectors")))
_CONNECT_URL = os.environ.get("CONNECT_URL", "http://localhost:8083").rstrip("/")
_SECRETS_DIR = Path(os.environ.get("SECRETS_DIR", "/run/secrets"))
_RESOURCE_NAME = re.compile(r"[a-z0-9_]+")
_SERVICE_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_POSTGRES_CONNECTOR = "io.debezium.connector.postgresql.PostgresConnector"
_SLOT_QUERY = "SELECT slot_name FROM pg_replication_slots ORDER BY slot_name;"
_PUBLICATION_QUERY = "SELECT pubname FROM pg_publication ORDER BY pubname;"


@dataclass(frozen=True)
class _Expectation:
    connector_class: str
    slot_name: str | None
    publication_name: str | None


class _ReadinessError(Exception):
    pass


def _fail(message: str) -> Never:
    raise _ReadinessError(message)


def _mapping(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        return None
    return value


def _array_entries(script: str, variable: str) -> tuple[str, ...]:
    lines = script.splitlines()
    definition = re.compile(rf"^\s*{re.escape(variable)}=\(\s*(?:#.*)?$")
    starts = [index for index, line in enumerate(lines) if definition.fullmatch(line)]
    if len(starts) != 1:
        _fail(f"registration script must define {variable} exactly once")

    entries: list[str] = []
    for line_number, line in enumerate(lines[starts[0] + 1 :], start=starts[0] + 2):
        stripped = line.strip()
        if re.fullmatch(r"\)\s*(?:#.*)?", stripped):
            if not entries:
                _fail(f"registration script defines no entries in {variable}")
            return tuple(entries)
        if not stripped or stripped.startswith("#"):
            continue
        entry = re.fullmatch(r'"([^"\\]+)"\s*(?:#.*)?', stripped)
        if entry is None:
            _fail(f"unsupported {variable} entry at line {line_number}")
        entries.append(entry[1])
    _fail(f"registration script does not close {variable}")


def _config_expectation(path: Path, replacements: dict[str, str]) -> _Expectation:
    document = _mapping(json.loads(path.read_text(encoding="utf-8")))
    config = _mapping(document.get("config")) if document is not None else None
    if config is None:
        _fail(f"connector config {path} has no config object")

    def rendered(key: str) -> str | None:
        value = config.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            _fail(f"connector config {path} has non-string {key}")
        for marker, replacement in replacements.items():
            value = value.replace(marker, replacement)
        return value

    connector_class = rendered("connector.class")
    if connector_class is None:
        _fail(f"connector config {path} has no connector.class")
    slot_name = rendered("slot.name")
    publication_name = rendered("publication.name")
    if connector_class == _POSTGRES_CONNECTOR:
        if slot_name is None or _RESOURCE_NAME.fullmatch(slot_name) is None:
            _fail(f"connector config {path} has invalid slot.name")
        if publication_name is None or _RESOURCE_NAME.fullmatch(publication_name) is None:
            _fail(f"connector config {path} has invalid publication.name")
    return _Expectation(connector_class, slot_name, publication_name)


def _add_expected(expected: dict[str, _Expectation], name: str, expectation: _Expectation) -> None:
    if name in expected:
        _fail(f"registration script defines duplicate connector identity {name}")
    expected[name] = expectation


def _required_connectors(path: Path) -> dict[str, _Expectation]:
    script = path.read_text(encoding="utf-8")
    expected: dict[str, _Expectation] = {}

    for entry in _array_entries(script, "OUTBOX_CONNECTORS"):
        match entry.split(":"):
            case [service_name, schema_name] if (
                _SERVICE_NAME.fullmatch(service_name) is not None and _RESOURCE_NAME.fullmatch(schema_name) is not None
            ):
                pass
            case _:
                _fail(f"invalid OUTBOX_CONNECTORS entry {entry!r}")
        db_prefix = service_name.removesuffix("-service").replace("-", "_")
        _add_expected(
            expected,
            f"{service_name}-outbox",
            _config_expectation(
                _CONFIG_DIR / "outbox-connector-template.json",
                {"DB_PREFIX": db_prefix},
            ),
        )

    for entry in _array_entries(script, "WAL_CONNECTORS"):
        match entry.split(":"):
            case [service_name, schema_name, resource_prefix] if (
                _SERVICE_NAME.fullmatch(service_name) is not None
                and _RESOURCE_NAME.fullmatch(schema_name) is not None
                and _RESOURCE_NAME.fullmatch(resource_prefix) is not None
            ):
                pass
            case _:
                _fail(f"invalid WAL_CONNECTORS entry {entry!r}")
        _add_expected(
            expected,
            f"{service_name}-wal",
            _config_expectation(
                _CONFIG_DIR / "wal-connector-template.json",
                {"RESOURCE_PREFIX": resource_prefix},
            ),
        )

    literal_names = re.findall(r'^\s*register_connector\s+"([a-z0-9-]+)"\s+', script, re.MULTILINE)
    for name in literal_names:
        config_path = _CONFIG_DIR / f"{name}.json"
        if not config_path.is_file():
            continue
        document = _mapping(json.loads(config_path.read_text(encoding="utf-8")))
        if document is None or document.get("name") != name:
            _fail(f"optional connector config {config_path} has the wrong name")
        _add_expected(expected, name, _config_expectation(config_path, {}))
    return expected


def _connect_state(
    payload: dict[str, object], expected: dict[str, _Expectation]
) -> tuple[list[str], set[str], set[str]]:
    errors = [f"unexpected connector {name}" for name in sorted(set(payload) - set(expected))]
    slots = {item.slot_name for item in expected.values() if item.slot_name is not None}
    publications = {item.publication_name for item in expected.values() if item.publication_name is not None}

    for name, wanted in expected.items():
        details = _mapping(payload.get(name))
        if details is None:
            errors.append(f"missing connector {name}")
            continue

        status = _mapping(details.get("status"))
        connector = _mapping(status.get("connector")) if status is not None else None
        if connector is None or connector.get("state") != "RUNNING":
            errors.append(f"connector {name} is not RUNNING")

        tasks = status.get("tasks") if status is not None else None
        if not isinstance(tasks, list) or not tasks:
            errors.append(f"connector {name} has no running tasks")
        elif any((task := _mapping(item)) is None or task.get("state") != "RUNNING" for item in tasks):
            errors.append(f"connector {name} has a task that is not RUNNING")

        info = _mapping(details.get("info"))
        config = _mapping(info.get("config")) if info is not None else None
        if config is None:
            errors.append(f"connector {name} has no expanded config")
            continue
        for key, value in (
            ("connector.class", wanted.connector_class),
            ("slot.name", wanted.slot_name),
            ("publication.name", wanted.publication_name),
        ):
            if config.get(key) != value:
                errors.append(f"connector {name} has unexpected {key}")

    return errors, slots, publications


def _database_connection() -> tuple[str, str, str, str, str]:
    dsn = (_SECRETS_DIR / "database" / "dsn").read_text(encoding="utf-8").strip()
    parsed = urlsplit(dsn)
    if parsed.scheme not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        _fail("database DSN must use a PostgreSQL scheme")
    if parsed.username is None or parsed.password is None or parsed.hostname is None:
        _fail("database DSN must include username, password, and host")
    database = unquote(parsed.path.lstrip("/"))
    if not database:
        _fail("database DSN must include a database name")
    return (
        unquote(parsed.username),
        unquote(parsed.password),
        parsed.hostname,
        str(parsed.port or 5432),
        database,
    )


def _postgres_names(query: str) -> set[str]:
    user, password, host, port, database = _database_connection()
    psql = shutil.which("psql")
    if psql is None:
        _fail("psql executable is unavailable")
    result = subprocess.run(  # noqa: S603 - resolved executable and argv are not shell-evaluated
        [
            psql,
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            database,
            "-c",
            query,
        ],
        capture_output=True,
        check=False,
        env=os.environ | {"PGPASSWORD": password},
        text=True,
        timeout=5,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"psql exited {result.returncode}"
        _fail(detail)
    return {line for line in result.stdout.splitlines() if line}


def _connect_document() -> object:
    parsed = urlsplit(_CONNECT_URL)
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        _fail("CONNECT_URL must be an HTTP or HTTPS URL with a host")
    connection_type = HTTPSConnection if parsed.scheme == "https" else HTTPConnection
    connection = connection_type(parsed.hostname, parsed.port, timeout=5)
    path = f"{parsed.path.rstrip('/')}/connectors?expand=status&expand=info"
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != HTTPStatus.OK:
            _fail(f"Kafka Connect returned HTTP {response.status}")
        return json.load(response)
    finally:
        connection.close()


def _main() -> int:
    try:
        expected = _required_connectors(_REGISTRATION_SCRIPT)
        payload = _mapping(_connect_document())
        if payload is None:
            _fail("Kafka Connect returned a non-object response")

        errors, slots, publications = _connect_state(payload, expected)
        if not errors:
            errors.extend(f"missing replication slot {name}" for name in sorted(slots - _postgres_names(_SLOT_QUERY)))
            errors.extend(
                f"missing publication {name}" for name in sorted(publications - _postgres_names(_PUBLICATION_QUERY))
            )
    except (OSError, ValueError, _ReadinessError, subprocess.SubprocessError) as error:
        sys.stderr.write(f"Kafka Connect readiness failed: {error}\n")
        return 1

    if errors:
        sys.stderr.write("Kafka Connect readiness failed: " + "; ".join(errors) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
