"""Focused contracts for deployed migration-head verification."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import TracebackType
from typing import Self

import pytest
from health_check import verify_migrations


class _Rows:
    def __init__(self, values: tuple[tuple[str, int] | None, ...]) -> None:
        self._values = iter(values)

    def fetchone(self) -> tuple[str, int] | None:
        return next(self._values)


class _Connection:
    def __init__(self, head: str) -> None:
        self._head = head
        self.statements: list[object] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None

    def execute(self, statement: object) -> _Rows:
        self.statements.append(statement)
        if statement == "SET default_transaction_read_only = on":
            return _Rows((None,))
        return _Rows(((self._head, 1),))


def _inventory(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "service": "bff-service",
                        "schema": "bff_schema",
                        "head": "007",
                    },
                    {
                        "service": "user-pref-service",
                        "schema": "user_pref_schema",
                        "head": "002",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )


def _invoke(monkeypatch: pytest.MonkeyPatch, inventory: Path, evidence: Path) -> int:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify-migrations",
            "--inventory",
            str(inventory),
            "--evidence",
            str(evidence),
        ],
    )
    return verify_migrations.main()


def test_each_service_uses_its_own_database_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = tmp_path / "inventory.json"
    evidence = tmp_path / "evidence.json"
    _inventory(inventory)
    monkeypatch.setenv("MIGRATION_DATABASE_URL_BFF_SERVICE", "postgresql://bff-db")
    monkeypatch.setenv("MIGRATION_DATABASE_URL_USER_PREF_SERVICE", "postgresql://user-pref-db")
    connections: dict[str, _Connection] = {}

    def connect(uri: str, *, autocommit: bool) -> _Connection:
        assert autocommit is True
        head = {"postgresql://bff-db": "007", "postgresql://user-pref-db": "002"}[uri]
        connection = _Connection(head)
        connections[uri] = connection
        return connection

    monkeypatch.setattr(verify_migrations.psycopg, "connect", connect)

    assert _invoke(monkeypatch, inventory, evidence) == 0
    assert set(connections) == {"postgresql://bff-db", "postgresql://user-pref-db"}
    assert all(
        connection.statements[0] == "SET default_transaction_read_only = on" and len(connection.statements) == 2
        for connection in connections.values()
    )
    assert json.loads(evidence.read_text(encoding="utf-8")) == {
        "entries": [
            {
                "expected": "007",
                "matches": True,
                "observed": "007",
                "schema": "bff_schema",
                "service": "bff-service",
            },
            {
                "expected": "002",
                "matches": True,
                "observed": "002",
                "schema": "user_pref_schema",
                "service": "user-pref-service",
            },
        ],
        "passed": True,
    }


def test_evidence_replacement_is_atomic_across_interruption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = tmp_path / "inventory.json"
    evidence = tmp_path / "evidence.json"
    _inventory(inventory)
    previous = '{"entries":[{"release":"previous-complete-proof"}]}\n'
    evidence.write_text(previous, encoding="utf-8")
    monkeypatch.setenv("MIGRATION_DATABASE_URL_BFF_SERVICE", "postgresql://bff-db")
    monkeypatch.setenv("MIGRATION_DATABASE_URL_USER_PREF_SERVICE", "postgresql://user-pref-db")

    def connect(uri: str, *, autocommit: bool) -> _Connection:
        assert autocommit is True
        return _Connection("007" if uri == "postgresql://bff-db" else "002")

    monkeypatch.setattr(verify_migrations.psycopg, "connect", connect)

    def interrupt(_source: str | Path, _destination: str | Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(verify_migrations.os, "replace", interrupt)

    with pytest.raises(KeyboardInterrupt):
        _invoke(monkeypatch, inventory, evidence)

    assert evidence.read_text(encoding="utf-8") == previous
    assert set(tmp_path.iterdir()) == {inventory, evidence}
