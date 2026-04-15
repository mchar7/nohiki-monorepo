"""Installed-package dependency closure for the discovery service."""

from __future__ import annotations

from importlib.metadata import requires


def test_jsearch_http_client_is_a_direct_runtime_dependency() -> None:
    """A production-only install includes the HTTP client imported by the JSearch provider."""
    declared = requires("job-ingest-discovery-service") or []

    assert any(requirement.startswith("httpx") for requirement in declared)
