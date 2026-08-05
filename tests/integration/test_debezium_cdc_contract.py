"""Unit contracts for the Debezium CDC availability fixture."""

# ruff: noqa: SLF001 - these contracts intentionally exercise the fixture's private decision helpers.

from __future__ import annotations

import pytest

from . import test_debezium_cdc as cdc

pytestmark = pytest.mark.unit


def test_canonical_name_predicate_rejects_stale_prefix() -> None:
    """The Helm contract is <service>-outbox, not nohiki-outbox-*."""
    assert cdc._is_canonical_outbox_connector_name("user-auth-service-outbox")
    assert not cdc._is_canonical_outbox_connector_name("nohiki-outbox-user-auth")


async def test_running_canonical_connector_satisfies_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """A running Helm-named connector must reach the live CDC test."""
    checked: list[str] = []

    def record_running_connector(name: str) -> bool:
        checked.append(name)
        return True

    monkeypatch.setattr(cdc, "_fetch_connectors", lambda: ["user-auth-service-outbox"])
    monkeypatch.setattr(cdc, "_connector_is_running", record_running_connector)

    assert await cdc._check_connect_connectors() is None
    assert checked == ["user-auth-service-outbox"]


async def test_stale_prefix_alone_does_not_satisfy_connector_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    """A superseded connector name must be treated as canonical connector absence."""
    monkeypatch.setattr(cdc, "_fetch_connectors", lambda: ["nohiki-outbox-user-auth"])
    monkeypatch.setattr(cdc, "_connector_is_running", lambda _name: True)

    reason = await cdc._check_connect_connectors()

    assert reason is not None
    assert reason.startswith("No Debezium outbox connector registered")


async def test_discovered_canonical_connector_must_be_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """A discovered canonical connector is a failed prerequisite, never a skip."""
    monkeypatch.setattr(cdc, "_fetch_connectors", lambda: ["user-auth-service-outbox"])
    monkeypatch.setattr(cdc, "_connector_is_running", lambda _name: False)

    with pytest.raises(AssertionError, match="user-auth-service-outbox"):
        await cdc._check_connect_connectors()
