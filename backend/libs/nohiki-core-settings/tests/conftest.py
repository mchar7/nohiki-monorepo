"""Shared test fixtures for nohiki-core-settings."""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate test environment from system secrets."""
    # Prevent /run/secrets from being used
    monkeypatch.setenv("SECRETS_DIR", "/nonexistent/secrets/path")
    # Clear any Azure Key Vault URL that might be set
    monkeypatch.delenv("AZURE_KEY_VAULT_URL", raising=False)
    yield
    return None
