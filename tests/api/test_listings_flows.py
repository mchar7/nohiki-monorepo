"""API contract tests and user journey tests for job discovery pipeline.

TEST TAXONOMY (per refactor_overview.md):

1. **API Contract Tests** (TestJobListingsAPI, TestJobCorrelationsAPI)
   - Verify BFF endpoints return correct structure
   - Use session-scoped fixtures (no new users per test)
   - Fast, cheap, run on every PR

2. **User Journey Test** (TestJobDiscoveryJourney)
   - Single sequential test verifying FULL pipeline ONCE
   - Uses session profile to avoid redundant scraping/enrichment
   - Shares state across steps (no profile creation per step)
   - Expensive (real scraping, real LLM), run on merge to main

Run with:
    pytest tests/api/test_listings_flows.py -v --tb=short

Prerequisites:
    just compose-up
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import TYPE_CHECKING

import pytest
from requests.exceptions import HTTPError

if TYPE_CHECKING:
    from .client import NohikiClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nohiki-e2e")

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
TEST_PASSWORD = "NohikiE2E2024!"

# Pipeline timeouts (seconds)
# Note: LLM enrichment is the bottleneck - each job takes 10-30 seconds
PROFILE_PROJECTION_TIMEOUT = 15
QUERY_COMPOSITION_TIMEOUT = 30
JOB_DISCOVERY_TIMEOUT = 300
CORRELATION_TIMEOUT = 360


def unique_email() -> str:
    """Generate unique email for test isolation."""
    return f"e2e-{uuid.uuid4().hex[:8]}@test.nohiki.com"


# Realistic keywords that will produce actual job listings
# Tests must clean up properly so each run creates fresh queries
REALISTIC_KEYWORDS = ["python", "software engineer", "backend"]
REALISTIC_KEYWORDS_ALT = ["data engineer", "python", "remote"]


# NOTE: Use session-scoped fixtures from conftest.py (session_client, authenticated_client)
# to avoid creating new users for every test which wastes resources and money.
# Import fixtures from conftest.py - they are automatically available.


# Job Listings Projection Tests (bff-service)


class TestJobListingsSearch:
    """Test job listings FTS search via BFF."""

    def test_search_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Test that searching jobs requires authentication."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.search_job_listings("python")

    def test_search_returns_structure(self, authenticated_client: NohikiClient) -> None:
        """Test search returns proper response structure."""
        result = authenticated_client.search_job_listings("software")

        assert "items" in result
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert isinstance(result["items"], list)
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_search_with_pagination(self, authenticated_client: NohikiClient) -> None:
        """Test search respects pagination parameters."""
        result = authenticated_client.search_job_listings("engineer", page=2, page_size=10)

        assert result["page"] == 2
        assert result["page_size"] == 10

    def test_search_query_too_short_returns_422(self, authenticated_client: NohikiClient) -> None:
        """Test search with query too short returns validation error."""
        with pytest.raises(HTTPError, match="422"):
            authenticated_client.search_job_listings("a")

    def test_search_empty_query_returns_422(self, authenticated_client: NohikiClient) -> None:
        """Test search with empty query returns validation error."""
        with pytest.raises(HTTPError, match="422"):
            authenticated_client.search_job_listings("")


class TestJobListingsProjection:
    """Test job listings read-only projections via BFF."""

    def test_list_job_listings_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Test that listing jobs requires authentication."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.list_job_listings()

    def test_list_job_listings_returns_structure(self, authenticated_client: NohikiClient) -> None:
        """Test listing jobs returns proper structure."""
        result = authenticated_client.list_job_listings()

        assert "items" in result
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert isinstance(result["items"], list)
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_list_job_listings_with_pagination(self, authenticated_client: NohikiClient) -> None:
        """Test listing jobs with custom pagination."""
        result = authenticated_client.list_job_listings(page=2, page_size=10)

        assert result["page"] == 2
        assert result["page_size"] == 10

    def test_list_job_listings_with_source_filter(self, authenticated_client: NohikiClient) -> None:
        """Test listing jobs with source filter."""
        result = authenticated_client.list_job_listings(source="LINKEDIN")

        assert "items" in result
        assert isinstance(result["items"], list)

    def test_list_job_listings_with_company_filter(self, authenticated_client: NohikiClient) -> None:
        """Test listing jobs with company filter."""
        result = authenticated_client.list_job_listings(company="Google")

        assert "items" in result
        assert isinstance(result["items"], list)


# Job Correlations Projection Tests (bff-service)


class TestJobCorrelationsProjection:
    """Test job correlation/match projections via BFF."""

    def test_list_correlations_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Test that listing correlations requires authentication."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.list_my_correlations()

    def test_list_correlations_returns_structure(self, authenticated_client: NohikiClient) -> None:
        """Test listing correlations returns proper structure."""
        result = authenticated_client.list_my_correlations()

        assert "items" in result
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert isinstance(result["items"], list)
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_list_correlations_with_pagination(self, authenticated_client: NohikiClient) -> None:
        """Test listing correlations with custom pagination."""
        result = authenticated_client.list_my_correlations(page=1, page_size=10)

        assert result["page"] == 1
        assert result["page_size"] == 10

    def test_list_correlations_with_min_score(self, authenticated_client: NohikiClient) -> None:
        """Test listing correlations with minimum score filter."""
        result = authenticated_client.list_my_correlations(min_score=75)

        assert "items" in result
        assert isinstance(result["items"], list)


# Job Listing Detail Tests


class TestJobListingDetail:
    """Test individual job listing retrieval."""

    def test_get_nonexistent_listing_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test that getting a non-existent listing returns 404."""
        fake_id = str(uuid.uuid4())

        with pytest.raises(HTTPError, match="404"):
            authenticated_client.get_job_listing(fake_id)

    def test_get_correlation_nonexistent_returns_404(self, authenticated_client: NohikiClient) -> None:
        """Test that getting a non-existent correlation returns 404."""
        fake_id = str(uuid.uuid4())

        with pytest.raises(HTTPError, match="404"):
            authenticated_client.get_correlation(fake_id)


# Correlation Feedback Tests


class TestCorrelationFeedback:
    """Test correlation feedback endpoints (POST /api/v1/correlations/{id}/*)."""

    def test_record_feedback_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Test that recording feedback requires authentication."""
        import uuid as _uuid

        fake_id = str(_uuid.uuid4())
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.record_correlation_feedback(fake_id, "viewed")

    def test_record_feedback_viewed_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test recording 'viewed' feedback returns 202 with request_id."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.record_correlation_feedback(fake_id, "viewed")

        assert "request_id" in result
        assert result.get("status") == "accepted"

    def test_record_feedback_saved_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test recording 'saved' feedback returns 202."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.record_correlation_feedback(fake_id, "saved")

        assert "request_id" in result

    def test_record_feedback_applied_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test recording 'applied' feedback (strongest signal) returns 202."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.record_correlation_feedback(fake_id, "applied")

        assert "request_id" in result

    def test_record_feedback_dismissed_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test recording 'dismissed' feedback (negative signal) returns 202."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.record_correlation_feedback(fake_id, "dismissed")

        assert "request_id" in result

    def test_record_feedback_invalid_type_returns_422(self, authenticated_client: NohikiClient) -> None:
        """Test recording feedback with invalid type returns validation error."""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPError, match="422"):
            authenticated_client.record_correlation_feedback(fake_id, "INVALID_TYPE")

    def test_submit_score_feedback_good_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test submitting GOOD score feedback returns 202."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.submit_score_feedback(fake_id, "GOOD")

        assert "request_id" in result
        assert result.get("status") == "accepted"

    def test_submit_score_feedback_too_high_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test submitting TOO_HIGH score feedback returns 202."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.submit_score_feedback(fake_id, "TOO_HIGH")

        assert "request_id" in result

    def test_submit_score_feedback_too_low_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test submitting TOO_LOW score feedback returns 202."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.submit_score_feedback(fake_id, "TOO_LOW")

        assert "request_id" in result

    def test_submit_score_adjustment_returns_accepted(self, authenticated_client: NohikiClient) -> None:
        """Test submitting manual score adjustment with reasoning returns 202."""
        fake_id = str(uuid.uuid4())
        result = authenticated_client.submit_score_adjustment(
            fake_id,
            adjusted_score=0.65,
            reasoning="Skills match but location is suboptimal for commute",
        )

        assert "request_id" in result
        assert result.get("status") == "accepted"

    def test_submit_score_adjustment_invalid_score_returns_422(
        self,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test score adjustment with out-of-range score returns validation error."""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPError, match="422"):
            authenticated_client.submit_score_adjustment(
                fake_id,
                adjusted_score=1.5,
                reasoning="This score is invalid and exceeds the maximum of 1.0",
            )

    def test_submit_score_adjustment_short_reasoning_returns_422(
        self,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test score adjustment with reasoning too short returns validation error."""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPError, match="422"):
            authenticated_client.submit_score_adjustment(
                fake_id,
                adjusted_score=0.5,
                reasoning="short",
            )


# Listing Detail Tests (by ID)


class TestListingAndCorrelationDetail:
    """Test individual listing and correlation retrieval by ID."""

    def test_get_listing_by_id_success(self, authenticated_client: NohikiClient) -> None:
        """Test getting a listing that exists returns full data."""
        page_result = authenticated_client.list_job_listings(page_size=1)
        listings = page_result.get("items", [])

        if not listings:
            pytest.skip("No listings available in projection")

        listing_id = listings[0]["id"]
        listing = authenticated_client.get_job_listing(listing_id)

        assert listing["id"] == listing_id
        assert "title" in listing
        assert "listing_url" in listing
        assert "source" in listing
        assert "required_skills" in listing
        assert isinstance(listing["required_skills"], list)

    def test_get_listing_requires_auth(self, fresh_client: NohikiClient) -> None:
        """Test that getting a listing requires authentication."""
        with pytest.raises(HTTPError, match=r"401|403"):
            fresh_client.get_job_listing(str(uuid.uuid4()))

    def test_get_correlation_by_id_success(
        self,
        session_profile: dict,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test getting a correlation that exists returns full data."""
        result = authenticated_client.list_my_correlations(pref_id=session_profile["id"], page_size=1)
        correlations = result.get("items", [])

        if not correlations:
            pytest.skip("No correlations available for session profile")

        corr_id = correlations[0]["id"]
        corr = authenticated_client.get_correlation(corr_id)

        assert corr["id"] == corr_id
        assert "fit_score" in corr
        assert "listing_title" in corr
        assert "listing_url" in corr
        assert "score_breakdown" in corr

    def test_get_listing_fts_with_results(self, authenticated_client: NohikiClient) -> None:
        """Test FTS search returns results matching discovered jobs."""
        page_result = authenticated_client.list_job_listings(page_size=1)

        if page_result.get("total", 0) == 0:
            pytest.skip("No listings available to test FTS search")

        result = authenticated_client.search_job_listings("engineer", page_size=10)

        assert "items" in result
        assert "total" in result
        assert isinstance(result["items"], list)


# FULL JOB DISCOVERY PIPELINE TESTS
#
# These tests verify the complete event-driven pipeline from user profile
# creation through job discovery, enrichment, storage, and correlation.


class TestJobDiscoveryJourney:
    """Single user journey test for the job discovery pipeline.

    IMPORTANT: This replaces multiple redundant tests that each created new profiles
    and triggered expensive scraping/enrichment. Now we use ONE session-scoped profile
    and verify the pipeline steps sequentially.

    Pipeline Flow:
    1. USER_PREF_CREATED → job-query-composition-service
    2. JOB_QUERY_CREATED → job-ingest-schedule-service
    3. JOB_INGEST_SCRAPE_REQUESTED → job-ingest-discovery-service
    4. JOB_INGEST_LISTING_SCRAPED → job-storage-service (dedup)
    5. JOB_LISTING_RAW_ACCEPTED → job-ingest-enrichment-service
    6. JOB_INGEST_ENRICHMENT_COMPLETED → job-storage-service (bank)
    7. JOB_LISTING_CREATED → job-correlation-evaluation-service
    8. JOB_CORRELATION_EVALUATED → notification-service + bff-service
    """

    @pytest.mark.timeout(CORRELATION_TIMEOUT)
    def test_full_pipeline_user_journey(
        self,
        session_profile: dict,
        authenticated_client: NohikiClient,
    ) -> None:
        """Complete user journey: profile → jobs → correlations.

        Uses session-scoped profile fixture to avoid redundant pipeline triggers.
        If session profile already has correlations, verifies existing state.
        If not, waits for pipeline to complete.

        This is the ONLY expensive test - all others are lightweight API contract tests.
        """
        pref_id = session_profile["id"]
        logger.info("=== USER JOURNEY: Using session profile %s ===", pref_id)

        # Step 1: Wait for job listings to appear (pipeline triggered by session_profile fixture)
        listings = self._wait_for_listings(authenticated_client)
        self._log_sample_listings(listings)

        # Step 2: Wait for ML correlation scoring
        correlations = self._wait_for_correlations(authenticated_client, pref_id)
        self._verify_correlations(correlations)

        logger.info("=== USER JOURNEY COMPLETED ===")

    def _wait_for_listings(self, client: NohikiClient, timeout: int = 180) -> list[dict]:
        """Poll for job listings to appear in BFF projection."""
        logger.info("Waiting for job discovery pipeline...")
        start = time.time()

        while time.time() - start < timeout:
            result = client.list_job_listings(page_size=100)
            if result["total"] > 0:
                logger.info("Jobs found in storage: %d", result["total"])
                return result["items"]
            time.sleep(5)

        pytest.fail(
            "No job listings found - verify:\n"
            "  1. Query composition created query\n"
            "  2. Schedule service triggered scrape\n"
            "  3. Discovery service scraped successfully\n"
            "  4. Storage/enrichment/CDC pipeline completed",
        )

    def _log_sample_listings(self, listings: list[dict]) -> None:
        """Log a sample of enriched listings."""
        for listing in listings[:5]:
            if listing.get("required_skills") or listing.get("work_arrangement"):
                logger.info(
                    "  - Enriched: %s (skills: %s)",
                    listing.get("title", "Unknown"),
                    listing.get("required_skills", [])[:3],
                )

    def _wait_for_correlations(
        self,
        client: NohikiClient,
        pref_id: str,
        timeout: int = 90,
    ) -> list[dict]:
        """Poll for ML correlations to appear."""
        logger.info("Waiting for ML correlation scoring...")
        correlations = client.poll_for_correlations(
            pref_id=pref_id,
            min_count=1,
            timeout=timeout,
            interval=5.0,
        )

        if not correlations:
            pytest.fail(
                "No correlations found - verify:\n"
                "  1. job-correlation-evaluation-service is running\n"
                "  2. ML scoring pipeline initialized\n"
                "  3. Qdrant connection working\n"
                "  4. L2R model files available",
            )

        logger.info("Found %d correlations", len(correlations))
        return correlations

    def _verify_correlations(self, correlations: list[dict]) -> None:
        """Verify and log correlation details."""
        for corr in correlations[:5]:
            logger.info(
                "  - %s at %s (score: %d)",
                corr.get("listing_title", "Unknown"),
                corr.get("listing_company", "Unknown"),
                corr.get("fit_score", 0),
            )

        assert any(corr.get("score_breakdown") for corr in correlations), "Correlations should include score_breakdown"


# Profile Correlation Filtering Tests (uses session profile, no new creation)


class TestCorrelationFiltering:
    """Test correlation filtering with session profile (no new profile creation)."""

    def test_correlations_filtered_by_nonexistent_profile(
        self,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test filtering by non-existent profile returns empty."""
        fake_pref_id = str(uuid.uuid4())
        result = authenticated_client.list_my_correlations(pref_id=fake_pref_id)

        assert "items" in result
        assert result["total"] == 0

    def test_correlations_for_session_profile(
        self,
        session_profile: dict,
        authenticated_client: NohikiClient,
    ) -> None:
        """Test correlations can be retrieved for session profile."""
        result = authenticated_client.list_my_correlations(pref_id=session_profile["id"])

        assert "items" in result
        assert result["total"] >= 0
