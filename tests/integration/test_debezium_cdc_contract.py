"""Unit contracts for the Debezium CDC availability fixture."""

# ruff: noqa: SLF001 - these contracts intentionally exercise the fixture's private decision helpers.

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from . import test_debezium_cdc as cdc

pytestmark = pytest.mark.unit


def test_canonical_name_predicate_rejects_stale_prefix() -> None:
    """The Helm contract is <service>-outbox, not nohiki-outbox-*."""
    assert cdc._is_canonical_outbox_connector_name("user-auth-service-outbox")
    assert not cdc._is_canonical_outbox_connector_name("nohiki-outbox-user-auth")


def test_self_provisioned_connector_uses_canonical_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """The isolated connector must use the same name contract as Helm."""
    monkeypatch.setattr(
        cdc,
        "urlopen",
        lambda *_args, **_kwargs: nullcontext(SimpleNamespace(status=201)),
    )

    name = cdc._register_test_connector(
        "http://localhost:8083",
        "postgresql://postgres:postgres@localhost:5432/test",
    )

    assert name == "nohiki-test-outbox"
    assert cdc._is_canonical_outbox_connector_name(name)


def test_running_connector_and_tasks_satisfy_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """The isolated connector is ready only after its tasks are running."""
    monkeypatch.setattr(cdc, "urlopen", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        cdc.json,
        "load",
        lambda _response: {
            "connector": {"state": "RUNNING"},
            "tasks": [{"state": "RUNNING"}],
        },
    )

    assert cdc._connector_is_running("http://localhost:8083", "nohiki-test-outbox")


def test_failed_connector_task_does_not_satisfy_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed connector task must keep the CDC fixture from proceeding."""
    monkeypatch.setattr(cdc, "urlopen", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        cdc.json,
        "load",
        lambda _response: {
            "connector": {"state": "RUNNING"},
            "tasks": [{"state": "FAILED"}],
        },
    )

    assert not cdc._connector_is_running("http://localhost:8083", "nohiki-test-outbox")
