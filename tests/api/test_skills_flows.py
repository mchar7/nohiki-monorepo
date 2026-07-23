"""API tests for the Skills endpoints via BFF.

Skills are read-only endpoints backed by local PG projections.
Authentication is required (skill endpoints are auth-gated).

Run with:
    pytest tests/api/test_skills_flows.py -v --tb=short
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import pytest
from requests.exceptions import HTTPError

if TYPE_CHECKING:
    from .client import NohikiClient

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nohiki-e2e")


# Skill Search Tests


class TestSkillSearch:
    """Test skill search endpoint (GET /api/v1/skills/search)."""

    def test_search_returns_structure(self, authenticated_client: NohikiClient) -> None:
        """Test skill search returns proper response structure."""
        result = authenticated_client.search_skills("python")

        assert "skills" in result
        assert "total" in result
        assert "query" in result
        assert isinstance(result["skills"], list)
        assert result["query"] == "python"
        assert result["total"] >= 0

    def test_search_short_query_returns_422(self, authenticated_client: NohikiClient) -> None:
        """Test search with single-char query fails validation."""
        with pytest.raises(HTTPError, match="422"):
            authenticated_client.search_skills("p")

    def test_search_with_limit(self, authenticated_client: NohikiClient) -> None:
        """Test search respects limit parameter."""
        result = authenticated_client.search_skills("python", limit=5)

        assert len(result["skills"]) <= 5

    def test_search_with_category_filter(self, authenticated_client: NohikiClient) -> None:
        """Test search with category filter returns structure."""
        result = authenticated_client.search_skills("python", category="programming")

        assert "skills" in result
        assert isinstance(result["skills"], list)

    def test_search_result_item_structure(self, authenticated_client: NohikiClient) -> None:
        """Test each skill search result has the required fields."""
        result = authenticated_client.search_skills("software")

        for skill in result["skills"]:
            assert "id" in skill
            assert "name" in skill

    def test_search_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Skill search requires authentication."""
        with pytest.raises(HTTPError, match="401"):
            fresh_client.search_skills("java")

    def test_search_empty_result_for_nonsense_query(self, authenticated_client: NohikiClient) -> None:
        """Test search with nonsense query returns empty result gracefully."""
        result = authenticated_client.search_skills("xyzzy12345nonsense")

        assert "skills" in result
        assert isinstance(result["skills"], list)


# Skill Batch Lookup Tests


class TestSkillBatch:
    """Test batch skill lookup endpoint (POST /api/v1/skills/batch)."""

    def test_batch_with_empty_list_returns_empty(self, authenticated_client: NohikiClient) -> None:
        """Test batch lookup with empty ID list returns empty skills."""
        result = authenticated_client.get_skills_by_ids([])

        assert "skills" in result
        assert result["skills"] == []

    def test_batch_with_nonexistent_ids_returns_empty(self, authenticated_client: NohikiClient) -> None:
        """Test batch lookup with non-existent UUIDs returns empty."""
        fake_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        result = authenticated_client.get_skills_by_ids(fake_ids)

        assert "skills" in result
        assert isinstance(result["skills"], list)

    def test_batch_returns_structure(self, authenticated_client: NohikiClient) -> None:
        """Test batch response contains proper structure."""
        result = authenticated_client.get_skills_by_ids([str(uuid.uuid4())])

        assert "skills" in result
        assert isinstance(result["skills"], list)

    def test_batch_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Batch skill lookup requires authentication."""
        with pytest.raises(HTTPError, match="401"):
            fresh_client.get_skills_by_ids([])


# Individual Skill Tests


class TestSkillDetail:
    """Test individual skill retrieval (GET /api/v1/skills/{skill_id})."""

    def test_get_nonexistent_skill_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test that fetching a non-existent skill returns 404."""
        with pytest.raises(HTTPError, match="404"):
            authenticated_client.get_skill(str(uuid.uuid4()))

    def test_get_skill_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Individual skill endpoint requires authentication."""
        with pytest.raises(HTTPError, match="401"):
            fresh_client.get_skill(str(uuid.uuid4()))


# Skill Categories Tests


class TestSkillCategories:
    """Test skill categories endpoint (GET /api/v1/skills/categories/list)."""

    def test_list_categories_returns_list(self, authenticated_client: NohikiClient) -> None:
        """Test listing skill categories returns a list."""
        categories = authenticated_client.list_skill_categories()

        assert isinstance(categories, list)

    def test_list_categories_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Skill categories endpoint requires authentication."""
        with pytest.raises(HTTPError, match="401"):
            fresh_client.list_skill_categories()

    def test_categories_contain_strings(self, authenticated_client: NohikiClient) -> None:
        """Test all category values are strings."""
        categories = authenticated_client.list_skill_categories()

        for category in categories:
            assert isinstance(category, str)
            assert len(category) > 0


# Skill Search + Batch Integration


class TestSkillSearchAndBatchIntegration:
    """Test combined search then batch workflow."""

    def test_search_then_batch_roundtrip(self, authenticated_client: NohikiClient) -> None:
        """Test that skills found in search can be batch-fetched by ID."""
        search_result = authenticated_client.search_skills("python", limit=3)
        skill_ids = [s["id"] for s in search_result["skills"]]

        if not skill_ids:
            pytest.fail("Skill graph empty. No skills returned from search. Seed the skill graph")

        batch_result = authenticated_client.get_skills_by_ids(skill_ids)

        assert "skills" in batch_result
        returned_ids = {s["id"] for s in batch_result["skills"]}

        for skill_id in skill_ids:
            assert skill_id in returned_ids

    def test_search_then_get_by_id(self, authenticated_client: NohikiClient) -> None:
        """Test that a skill found in search can be retrieved by ID."""
        search_result = authenticated_client.search_skills("java", limit=1)

        if not search_result["skills"]:
            pytest.fail("Skill graph empty. No skills returned from search. Seed the skill graph")

        skill_id = search_result["skills"][0]["id"]
        skill = authenticated_client.get_skill(skill_id)

        assert skill["id"] == skill_id
        assert "name" in skill
