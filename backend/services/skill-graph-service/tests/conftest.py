"""Pytest configuration and fixtures for skill-graph-service tests."""

from __future__ import annotations

import asyncio
import os
import warnings
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(autouse=True)
def _close_stale_event_loops() -> Generator[None]:
    """Close any event loop left in thread-local state between tests.

    pytest-asyncio sets a new event loop but does not always close it
    before the next test. Prevents ResourceWarning from orphaned loops.
    """
    yield
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            return
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)


# Set environment variables BEFORE any imports that might load settings
# DatabaseSettings expects DSN (not separate host/port/etc) and schema_name
os.environ.setdefault("SKILL_GRAPH_DATABASE__DSN", "postgresql://test:test@localhost:5432/test?sslmode=disable")
os.environ.setdefault("SKILL_GRAPH_DATABASE__SCHEMA_NAME", "skill_graph_schema")
os.environ.setdefault("SKILL_GRAPH_REDIS__CONNECTION_STRING", "redis://localhost:6379/0")
os.environ.setdefault("SKILL_GRAPH_KAFKA__BOOTSTRAP_SERVERS", "localhost:29092")
os.environ.setdefault("SKILL_GRAPH_ENVIRONMENT", "development")
os.environ.setdefault(
    "SKILL_GRAPH_MANIFEST_PATH",
    str(Path(__file__).resolve().parents[4] / "data" / "config" / "semantic_representation_manifest.json"),
)

import pytest


@pytest.fixture(autouse=True)
def _reset_caches() -> Generator[None]:
    """Reset configuration caches before and after each test."""
    from nohiki_ml_manifest import ManifestCache
    from skill_graph_service.core.config import get_settings

    get_settings.cache_clear()
    ManifestCache.reset()
    yield
    get_settings.cache_clear()
    ManifestCache.reset()


@pytest.fixture(autouse=True)
def _set_test_env() -> Generator[None]:
    """Set environment variables for testing."""
    env_vars = {
        "SKILL_GRAPH_DATABASE__DSN": "postgresql://test:test@localhost:5432/test?sslmode=disable",
        "SKILL_GRAPH_DATABASE__SCHEMA_NAME": "skill_graph_schema",
        "SKILL_GRAPH_REDIS__CONNECTION_STRING": "redis://localhost:6379/0",
        "SKILL_GRAPH_KAFKA__BOOTSTRAP_SERVERS": "localhost:29092",
        "SKILL_GRAPH_ENVIRONMENT": "development",
        "SKILL_GRAPH_MANIFEST_PATH": str(
            Path(__file__).resolve().parents[4] / "data" / "config" / "semantic_representation_manifest.json"
        ),
    }
    original = {k: os.environ.get(k) for k in env_vars}
    os.environ.update(env_vars)
    yield
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def mock_db_session() -> MagicMock:
    """Create a mock database session with spec=AsyncSession."""
    return create_mock_session()


@pytest.fixture
def mock_manifest() -> MagicMock:
    """Create a mock SemanticRepresentationManifest."""
    manifest = MagicMock()
    manifest.get_collection_version.return_value = "v1"
    manifest.get_entity_version.return_value = "v1"
    manifest.dense = MagicMock()
    manifest.dense.embedding_dim = 1024
    # Model-dependent normalization thresholds (loaded from manifest)
    manifest.dense.normalization = MagicMock()
    manifest.dense.normalization.auto_match_threshold = 0.83
    manifest.dense.normalization.uncertain_min_threshold = 0.50
    return manifest


@pytest.fixture(autouse=True)
def mock_manifest_globally(mock_manifest: MagicMock) -> Generator[None]:
    """Mock get_manifest globally for all tests."""
    with (
        patch("skill_graph_service.core.config.get_manifest", return_value=mock_manifest),
        patch("skill_graph_service.core.embedding.get_manifest", return_value=mock_manifest),
        patch("skill_graph_service.services.normalization.workflow.get_manifest", return_value=mock_manifest),
        patch("skill_graph_service.services.skill_governance.get_manifest", return_value=mock_manifest),
    ):
        yield
