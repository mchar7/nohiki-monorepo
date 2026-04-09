"""Shared test fixtures for nohiki-test-utils tests."""

from __future__ import annotations

import pytest
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_test_utils.factories import (
    ListingSnapshotFactory,
    SearchPrefSnapshotFactory,
)
from nohiki_test_utils.fixtures.clients import async_client, async_client_with_db, fastapi_app, test_client
from nohiki_test_utils.sample_data.listings.software import SENIOR_PYTHON_REMOTE
from nohiki_test_utils.sample_data.prefs.software import BACKEND_ENGINEER_PREF

__all__ = [
    "async_client",
    "async_client_with_db",
    "fastapi_app",
    "test_client",
]


@pytest.fixture
def sample_skill_list() -> list[str]:
    """Return a representative skill list for testing."""
    return ["Python", "FastAPI", "PostgreSQL", "Kafka"]


@pytest.fixture
def listing_snapshot_factory() -> type[ListingSnapshotFactory]:
    """Provide ListingSnapshotFactory for tests."""
    return ListingSnapshotFactory


@pytest.fixture
def search_pref_snapshot_factory() -> type[SearchPrefSnapshotFactory]:
    """Provide SearchPrefSnapshotFactory for tests."""
    return SearchPrefSnapshotFactory


@pytest.fixture
def sample_listing() -> ListingSnapshot:
    """Provide a curated listing persona for tests."""
    return SENIOR_PYTHON_REMOTE


@pytest.fixture
def sample_pref() -> SearchPrefSnapshot:
    """Provide a curated preference persona for tests."""
    return BACKEND_ENGINEER_PREF
