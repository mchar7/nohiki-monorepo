"""CLI command for listing available test fixtures."""

from __future__ import annotations

from llm_benchmark.display.panels import display_available_fixtures
from llm_benchmark.fixtures import list_fixture_ids


def list_fixtures() -> None:
    """List available test fixtures."""
    display_available_fixtures(list_fixture_ids())
