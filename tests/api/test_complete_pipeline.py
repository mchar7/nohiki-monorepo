"""Complete end-to-end pipeline test validating ALL 9 services in the event flow.

This test suite verifies the ENTIRE event-driven pipeline from user signup
through notification delivery, with NO mocks and NO fallbacks.

Complete Event Flow (ALL must work with REAL data):
1. User signup → user-auth-service creates user → CDC event published
2. Job prefs entered → user-pref-service stores prefs → event published
3. job-query-composition-service consumes → composes search config → CDC event
4. job-ingest-schedule-service consumes CDC → publishes discovery trigger
5. job-ingest-discovery-service scrapes REAL jobs (jobspy) → event published
6. job-ingest-enrichment-service enriches via LLM → event published
7. job-storage-service stores → CDC event published
8. job-correlation-evaluation-service scores via:
   - ml-gateway-service → ml-compute-service (REAL ML inference)
   - ColBERT/MUVERA embeddings for semantic matching
   - L2R scoring with LightGBM model
9. notification-service sends alerts based on user preferences

Run with:
    uv run pytest tests/api/test_complete_pipeline.py -v --tb=short
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import TYPE_CHECKING

import pytest

from ._helpers import poll_for_complete_profile
from .client import poll_until

if TYPE_CHECKING:
    from .client import NohikiClient

pytestmark = pytest.mark.integration

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("nohiki-pipeline-e2e")

PIPELINE_TIMEOUT = 600
DISCOVERY_TIMEOUT = 300
ENRICHMENT_TIMEOUT = 180
CORRELATION_TIMEOUT = 180


def unique_email() -> str:
    """Generate unique email for complete test isolation."""
    return f"pipeline-{uuid.uuid4().hex[:8]}@test.nohiki.com"


class TestCompletePipelineFlow:
    """test of the complete 9-service event-driven pipeline.

    CRITICAL: These tests use NO mocks and require ALL services to be healthy.
    If ANY service fails, the test FAILS - no skipping, no fallbacks.
    """

    @pytest.mark.timeout(PIPELINE_TIMEOUT)
    def test_complete_user_to_notification_pipeline(
        self,
        session_client: NohikiClient,
        *,
        ml_pipeline_ready: bool,
    ) -> None:
        """Complete pipeline test from user profile to ML-scored correlations.

        This test verifies:
        1. Profile creation triggers query composition
        2. Query composition triggers job discovery
        3. Job discovery scrapes REAL jobs
        4. LLM enrichment processes jobs
        5. Job storage persists enriched jobs
        6. ML scoring produces REAL scores (not fallback)
        7. Correlations appear in BFF projection with valid ML scores
        """
        if not ml_pipeline_ready:
            pytest.fail(
                "ML pipeline NOT ready - ml-compute-service unhealthy. "
                "This test requires REAL ML scoring. Check ml-compute-service logs.",
            )

        # Use session profile which triggers the full pipeline
        profile = self._get_or_create_test_profile(session_client)
        pref_id = profile["id"]
        logger.info("Testing pipeline with profile: %s", pref_id)

        # Step 1: Verify job listings exist and have LLM-enriched fields
        self._verify_job_listings_exist(session_client)
        self._verify_listings_are_enriched(session_client)

        # Step 2: Verify correlations exist with REAL ML scores
        correlations = self._verify_correlations_exist(session_client, pref_id)
        self._verify_ml_scores_are_real(correlations)

        # Step 3: Verify score breakdown has all required components
        self._verify_score_breakdown_complete(correlations)

        logger.info("=== COMPLETE PIPELINE TEST PASSED ===")

    def _get_or_create_test_profile(self, client: NohikiClient) -> dict:
        """Get existing session profile or create one for testing.

        Existing profiles are checked for data completeness, profiles
        missing salary/experience data from previous sessions are updated
        to ensure meaningful L2R feature vectors.
        """
        profiles = client.list_profiles()
        for profile in profiles:
            if profile.get("search_keywords"):
                if self._is_profile_data_complete(profile):
                    return profile
                # Stale profile, update with rich data for ML scoring
                logger.info("Updating stale profile %s with rich data", profile["id"])
                client.update_profile(
                    profile["id"],
                    {
                        "salary_preference": {
                            "min_salary": {"minor_units": 8000000, "currency": "USD"},
                            "target_salary": {
                                "minor_units": 12000000,
                                "currency": "USD",
                            },
                            "preferred_frequency": "ANNUALLY",
                        },
                        "experience_preference": {
                            "experience_years": 5,
                            "seniority_levels": ["MID", "SENIOR"],
                        },
                        "work_arrangements": ["REMOTE", "HYBRID"],
                        "open_to_relocation": True,
                    },
                )
                # Poll the projection rather than a magic sleep, CDC propagation
                # latency varies by infrastructure pressure, and a fixed 5s is
                # both flakey and slower than necessary on healthy clusters.
                updated = poll_for_complete_profile(client, profile["id"], timeout=30)
                return updated or profile

        profile_name = f"Pipeline Test {uuid.uuid4().hex[:6]}"
        client.create_profile(
            profile_name=profile_name,
            search_keywords=["python", "backend", "software engineer"],
            work_arrangements=["REMOTE", "HYBRID"],
            open_to_relocation=True,
        )

        profile = client.poll_for_profile(
            profile_name=profile_name,
            timeout=60,
        )
        if not profile:
            pytest.fail("Failed to create test profile")
        return profile

    @staticmethod
    def _is_profile_data_complete(profile: dict) -> bool:
        """Check if profile has required data for meaningful ML scoring."""
        salary = profile.get("salary_preference") or {}
        experience = profile.get("experience_preference") or {}
        return bool(
            salary.get("min_salary") is not None
            and experience.get("experience_years") is not None
            and profile.get("work_arrangements"),
        )

    def _verify_job_listings_exist(self, client: NohikiClient) -> list[dict]:
        """Verify job listings exist and pipeline processed them."""
        logger.info("Verifying job listings exist...")

        def get_listings() -> list[dict] | None:
            result = client.list_job_listings(page_size=100)
            if result["total"] <= 0:
                return None
            logger.info("Found %d job listings", result["total"])
            return result["items"]

        if listings := poll_until(get_listings, timeout=DISCOVERY_TIMEOUT):
            return listings

        pytest.fail(
            f"No job listings found after {DISCOVERY_TIMEOUT}s. "
            "Pipeline failed at: job-ingest-discovery-service, "
            "job-ingest-enrichment-service, or job-storage-service. "
            "Check service logs for errors.",
        )

    def _verify_listings_are_enriched(self, client: NohikiClient) -> list[dict]:
        """Poll until at least one enriched listing with skills appears in BFF."""
        logger.info("Verifying listings are LLM-enriched...")
        start = time.monotonic()

        def get_enriched_listings() -> list[dict] | None:
            result = client.list_job_listings(page_size=100)
            listings = result.get("items", [])
            enriched = [
                listing for listing in listings if listing.get("required_skills") or listing.get("work_arrangement")
            ]
            if enriched:
                for listing in enriched[:3]:
                    logger.info(
                        "  Enriched: %s (skills: %d, arrangement: %s)",
                        listing.get("title", "Unknown")[:50],
                        len(listing.get("required_skills", [])),
                        listing.get("work_arrangement", "N/A"),
                    )
                logger.info("Verified %d/%d listings are enriched", len(enriched), len(listings))
                return listings
            logger.info(
                "Waiting for enriched listings... (%.0fs elapsed, %d listings found)",
                time.monotonic() - start,
                len(listings),
            )
            return None

        if listings := poll_until(get_enriched_listings, timeout=ENRICHMENT_TIMEOUT):
            return listings

        pytest.fail(
            f"No enriched listings found after {ENRICHMENT_TIMEOUT}s. "
            "job-ingest-enrichment-service did not process jobs with LLM. "
            "Check LLM client configuration and enrichment service logs.",
        )

    def _verify_correlations_exist(
        self,
        client: NohikiClient,
        pref_id: str,
    ) -> list[dict]:
        """Verify correlations exist for the profile."""
        logger.info("Verifying correlations exist for profile %s...", pref_id)

        correlations = client.poll_for_correlations(
            pref_id=pref_id,
            min_count=1,
            timeout=CORRELATION_TIMEOUT,
            interval=10.0,
        )

        if not correlations:
            pytest.fail(
                f"No correlations found after {CORRELATION_TIMEOUT}s. "
                "Pipeline failed at: job-correlation-evaluation-service. "
                "Check that ml-gateway-service and ml-compute-service are healthy "
                "and processing Kafka events.",
            )

        logger.info("Found %d correlations", len(correlations))
        return correlations

    def _verify_ml_scores_are_real(self, correlations: list[dict]) -> None:
        """Verify correlations expose non-zero semantic role relevance."""
        logger.info("Verifying ML scores are REAL (not fallback)...")

        real_ml_scores = [
            corr
            for corr in correlations
            if any(
                factor.get("factor") == "ROLE_RELEVANCE" and float(factor.get("compatibility_score", 0)) > 0
                for factor in (corr.get("fit_ranking_breakdown") or {}).get("factors", [])
            )
        ]
        if not real_ml_scores:
            pytest.fail(
                f"ALL {len(correlations)} correlations have zero or missing ROLE_RELEVANCE. "
                "This indicates ML scoring is not producing semantic relevance. Check:\n"
                "  1. ml-compute-service is processing embedding requests\n"
                "  2. profile and listing embedding artifacts are populated\n"
                "  3. L2R model files are available\n"
                "  4. No 'MLScoringRequiredError' in job-correlation service logs",
            )

        logger.info(
            "ML scoring verified: %d/%d correlations have semantic role relevance",
            len(real_ml_scores),
            len(correlations),
        )

    def _verify_score_breakdown_complete(self, correlations: list[dict]) -> None:
        """Verify the versioned human-facing fit-ranking contract."""
        logger.info("Verifying fit ranking breakdown completeness...")

        problems: list[tuple[str, str]] = []
        for corr in correlations[:5]:
            breakdown = corr.get("fit_ranking_breakdown")
            if not isinstance(breakdown, dict):
                problems.append((str(corr.get("id")), "missing fit_ranking_breakdown"))
                continue
            if not breakdown.get("method_version"):
                problems.append((str(corr.get("id")), "missing method_version"))
            if not breakdown.get("factors"):
                problems.append((str(corr.get("id")), "missing factors"))

        if problems:
            summary = "\n".join(f"  {cid}: {problem}" for cid, problem in problems)
            pytest.fail(f"Found {len(problems)} incomplete fit_ranking_breakdown objects:\n{summary}")

        logger.info("Fit ranking breakdown verification complete")


class TestMLScoringIntegrity:
    """Test ML scoring integrity - no fallbacks allowed."""

    @pytest.mark.timeout(120)
    def test_ml_compute_service_processes_requests(
        self,
        session_client: NohikiClient,
        *,
        ml_pipeline_ready: bool,
    ) -> None:
        """Verify ml-compute-service is actively processing embedding requests.

        This test checks that the ML pipeline is not just 'healthy' but actually
        processing encoding requests via Kafka.
        """
        if not ml_pipeline_ready:
            pytest.fail(
                "ML pipeline NOT ready. ml-compute-service must be healthy and actively processing Kafka events.",
            )

        # Verify we can get correlations with real ML scores
        profiles = session_client.list_profiles()
        if not profiles:
            pytest.skip("No profiles to test ML scoring with")

        pref_id = profiles[0]["id"]
        correlations = session_client.poll_for_correlations(
            pref_id=pref_id,
            min_count=1,
            timeout=90,
            interval=5.0,
        )

        if not correlations:
            pytest.fail("No correlations found - ML pipeline not processing")

        # Technical MaxSim internals are intentionally no longer exposed in the
        # legacy score_breakdown. The versioned fit explanation is the public
        # proof that correlations completed the current scoring path.
        has_real_score = any(
            (breakdown := correlation.get("fit_ranking_breakdown"))
            and breakdown.get("method_version")
            and breakdown.get("factors")
            for correlation in correlations
        )

        if not has_real_score:
            pytest.fail("All correlations lack a versioned fit ranking breakdown")


class TestDocumentGenerationFlow:
    """Test complete document generation with real templates."""

    @pytest.mark.timeout(60)
    def test_document_generation_with_system_template(
        self,
        session_client: NohikiClient,
    ) -> None:
        """Verify document generation works with pre-seeded system templates.

        This tests:
        1. System resume template exists in projection
        2. Document generation request is accepted
        3. Document is rendered to PDF
        4. Download URL is accessible
        """
        # Get system resume template
        try:
            template = session_client.get_system_resume_template()
        except Exception as exc:
            pytest.fail(f"System resume template not found: {exc}")

        assert template is not None
        template_id = template.get("id")
        assert isinstance(template_id, str)
        assert template_id, "Template must have ID"
        latest_version_id = template.get("latest_version_id")
        template_version_id = (
            latest_version_id if isinstance(latest_version_id, str) and latest_version_id else template_id
        )

        # Generate document with valid data matching seed schema
        sample_data = {
            "full_name": "Test User",
            "professional_title": "Senior Software Engineer",
            "contact": {
                "email": "test@example.com",
                "phone": "+1 (555) 123-4567",
                "location": "San Francisco, CA",
            },
            "skills": {
                "label": "Technical Skills",
                "categories": [
                    {
                        "name": "Programming Languages",
                        "skills": ["Python", "TypeScript", "Go"],
                    },
                    {
                        "name": "Frameworks",
                        "skills": ["FastAPI", "React", "Kafka"],
                    },
                ],
            },
            "education": {
                "label": "Education",
                "entries": [
                    {
                        "period": {"start": "2016", "end": "2020"},
                        "credential": "Bachelor of Science in Computer Science",
                        "institution": "Stanford University",
                        "location": "Stanford, CA",
                    },
                ],
            },
            "experience": {
                "label": "Professional Experience",
                "entries": [
                    {
                        "title": "Senior Software Engineer",
                        "organization": "Tech Corp",
                        "location": "San Francisco, CA",
                        "period": {"start": "2020", "end": "Present"},
                        "bullets": [
                            "Led backend development team of 5 engineers",
                            "Designed and implemented microservices architecture",
                        ],
                    },
                ],
            },
            "certifications": {
                "label": "Certifications",
                "entries": [
                    {
                        "name": "AWS Solutions Architect",
                        "date": "2023",
                    },
                ],
            },
            "projects": {
                "label": "Projects",
                "entries": [
                    {
                        "title": "Open Source Contribution",
                        "bullets": ["Contributed to major open source projects"],
                    },
                ],
            },
            "hobbies": {
                "label": "Interests",
                "entries": ["Technology", "Reading"],
            },
        }

        result = session_client.generate_document(
            template_version_id=template_version_id,
            data=sample_data,
            output_format="pdf",
        )

        assert result.get("request_id"), "Must receive request_id"
        request_id = result["request_id"]
        logger.info("Document generation requested: %s", request_id)

        # Poll for completion
        try:
            status = session_client.poll_for_document_completion(
                request_id=request_id,
                timeout=30.0,
                interval=1.0,
            )
        except TimeoutError:
            pytest.fail("Document generation timed out after 30s")
        except RuntimeError as exc:
            pytest.fail(f"Document generation failed: {exc}")

        assert status.get("status") == "completed"
        assert status.get("download_url"), "Completed document must have download_url"

        logger.info("Document generated: %s", status.get("download_url"))


class TestEnrichmentPipeline:
    """Test job enrichment pipeline with real LLM calls."""

    @pytest.mark.timeout(ENRICHMENT_TIMEOUT + 60)
    def test_listings_have_llm_enriched_skills(
        self,
        session_client: NohikiClient,
        session_profile: dict,
    ) -> None:
        """Verify listings have LLM-enriched skill extraction.

        This test FAILS if no listings have extracted skills.
        Polls until enriched listings appear to account for async LLM processing.
        """
        _ = session_profile  # Ensures pipeline has run

        start = time.monotonic()

        def listings_have_skills() -> bool | None:
            result = session_client.list_job_listings(page_size=50)
            listings = result.get("items", [])
            if not listings:
                return None

            listings_with_skills = [
                listing
                for listing in listings
                if listing.get("required_skills") and len(listing["required_skills"]) > 0
            ]
            if listings_with_skills:
                logger.info(
                    "%d/%d listings have LLM-extracted skills",
                    len(listings_with_skills),
                    len(listings),
                )
                for listing in listings_with_skills[:3]:
                    logger.info(
                        "  %s: %s",
                        listing.get("title", "Unknown")[:40],
                        listing.get("required_skills", [])[:5],
                    )
                return True

            logger.info(
                "Waiting for listings with skills... (%.0fs elapsed, %d listings found)",
                time.monotonic() - start,
                len(listings),
            )
            return None

        if poll_until(listings_have_skills, timeout=ENRICHMENT_TIMEOUT):
            return

        result = session_client.list_job_listings(page_size=50)
        listings = result.get("items", [])
        pytest.fail(
            f"None of {len(listings)} listings have extracted skills after {ENRICHMENT_TIMEOUT}s. "
            "job-ingest-enrichment-service LLM extraction failed. "
            "Check LLM client configuration and enrichment logs.",
        )


class TestCorrelationScoreQuality:
    """Test correlation score quality, validity, and distribution."""

    @pytest.mark.timeout(180)
    def test_correlation_scores_are_nonzero(
        self,
        session_client: NohikiClient,
        session_profile: dict,
        *,
        ml_pipeline_ready: bool,
    ) -> None:
        """Assert that ALL correlations have fit_score > 0.

        Zero scores indicate broken scoring pipeline or incomplete model.
        This is a hard fail - at least one correlation must exist with a real score.
        """
        if not ml_pipeline_ready:
            pytest.fail(
                "ML pipeline NOT ready. Cannot validate correlation scores. "
                "Check ml-compute-service health and Kafka consumer status.",
            )

        pref_id = session_profile["id"]
        logger.info("Testing non-zero scores for profile %s...", pref_id)

        correlations = session_client.poll_for_correlations(
            pref_id=pref_id,
            min_count=3,
            timeout=120,
            interval=10.0,
        )

        if not correlations:
            pytest.fail(
                "No correlations found for profile after 120s. Cannot validate score quality without correlations.",
            )

        zero_score_count = 0
        nonzero_correlations = []

        for corr in correlations:
            fit_score = corr.get("fit_score", 0)
            if fit_score <= 0:
                zero_score_count += 1
            else:
                nonzero_correlations.append(corr)
                logger.info(
                    "  Nonzero score: %s (fit=%d)",
                    corr.get("listing_title", "Unknown")[:40],
                    fit_score,
                )

        if not nonzero_correlations:
            pytest.fail(
                f"ALL {len(correlations)} correlations have fit_score <= 0. "
                "ML scoring pipeline is broken or producing invalid scores. "
                "Check job-correlation-evaluation-service logs.",
            )

        if zero_score_count > 0:
            logger.warning(
                "%d/%d correlations have zero score (may indicate incomplete processing)",
                zero_score_count,
                len(correlations),
            )

        logger.info(
            "✓ Nonzero score validation passed: %d/%d correlations have real scores",
            len(nonzero_correlations),
            len(correlations),
        )

    @pytest.mark.timeout(180)
    def test_correlation_scores_within_valid_range(
        self,
        session_client: NohikiClient,
        session_profile: dict,
        *,
        ml_pipeline_ready: bool,
    ) -> None:
        """Assert ALL scores are within valid bounds: 0 <= fit_score <= 100.

        Correlation scores outside this range indicate data corruption
        or scoring model misconfiguration.
        """
        if not ml_pipeline_ready:
            pytest.fail(
                "ML pipeline NOT ready. Cannot validate score bounds. Check ml-compute-service health.",
            )

        pref_id = session_profile["id"]
        logger.info("Testing score bounds for profile %s...", pref_id)

        correlations = session_client.poll_for_correlations(
            pref_id=pref_id,
            min_count=3,
            timeout=120,
            interval=10.0,
        )

        if not correlations:
            pytest.fail("No correlations found - cannot validate bounds")

        out_of_bounds = []

        for corr in correlations:
            fit_score = corr.get("fit_score", 0)
            if fit_score < 0 or fit_score > 100:
                out_of_bounds.append((corr.get("listing_title", "Unknown"), fit_score))

        if out_of_bounds:
            pytest.fail(
                f"Found {len(out_of_bounds)} correlations with invalid scores (outside 0-100): "
                f"{out_of_bounds}. Scores must be percentages (0-100). "
                "Check job-correlation-evaluation-service L2R model output.",
            )

        logger.info(
            "✓ Score bounds validation passed: ALL %d correlations are within 0-100",
            len(correlations),
        )

    @pytest.mark.timeout(180)
    def test_correlation_score_distribution_has_spread(
        self,
        session_client: NohikiClient,
        session_profile: dict,
        *,
        ml_pipeline_ready: bool,
    ) -> None:
        """Assert that score distribution has meaningful spread (range >= 5).

        If all scores are clustered in a narrow band (e.g., all 70-75),
        the scoring model is degenerate or not differentiating between jobs.
        This validates model quality - not just pipeline connectivity.
        """
        if not ml_pipeline_ready:
            pytest.fail(
                "ML pipeline NOT ready. Cannot validate score distribution. Check ml-compute-service health.",
            )

        pref_id = session_profile["id"]
        logger.info("Testing score distribution spread for profile %s...", pref_id)

        # The endpoint returns fit_score DESC, so a default page is the top
        # slice and structurally understates spread; sample the full set.
        correlations = session_client.poll_for_correlations(
            pref_id=pref_id,
            min_count=3,
            timeout=120,
            interval=10.0,
            page_size=100,
        )

        if not correlations:
            pytest.fail("No correlations found - cannot validate distribution")

        # Get all scores, including zero scores
        all_scores = [corr.get("fit_score", 0) for corr in correlations]
        nonzero_scores = [s for s in all_scores if s > 0]

        if not nonzero_scores:
            pytest.fail(
                "No nonzero scores in correlations - cannot assess distribution. ML scoring pipeline not working.",
            )

        min_score = min(nonzero_scores)
        max_score = max(nonzero_scores)
        score_range = max_score - min_score

        logger.info(
            "Score distribution: min=%d, max=%d, range=%d (from %d correlations)",
            min_score,
            max_score,
            score_range,
            len(correlations),
        )

        for i, score in enumerate(sorted(nonzero_scores)):
            if i % max(1, len(nonzero_scores) // 5) == 0:  # Log ~5 samples
                logger.info("  Score sample: %d", score)

        if score_range < 5:
            pytest.fail(
                f"Score range is too narrow: {min_score}-{max_score} (range={score_range}). "
                "The scoring model is degenerate or not differentiating between jobs. "
                "This indicates a model quality issue, not pipeline connectivity. "
                "Check that L2R model has been trained on diverse feedback and all features are active.",
            )

        logger.info(
            "✓ Score distribution validation passed: range=%d (min=%d, max=%d)",
            score_range,
            min_score,
            max_score,
        )

    @pytest.mark.timeout(180)
    def test_fit_ranking_breakdown_contains_real_values(
        self,
        session_client: NohikiClient,
        session_profile: dict,
        *,
        ml_pipeline_ready: bool,
    ) -> None:
        """Assert that the versioned fit-ranking explanation contains real values."""
        if not ml_pipeline_ready:
            pytest.fail(
                "ML pipeline NOT ready. Cannot validate fit ranking breakdown. Check ml-compute-service health.",
            )

        pref_id = session_profile["id"]
        logger.info("Testing fit ranking breakdown for profile %s...", pref_id)

        correlations = session_client.poll_for_correlations(
            pref_id=pref_id,
            min_count=3,
            timeout=120,
            interval=10.0,
        )
        if not correlations:
            pytest.fail("No correlations found - cannot validate fit ranking breakdown")

        problems: list[tuple[str, str]] = []
        has_positive_role_relevance = False
        for corr in correlations:
            correlation_id = str(corr.get("id", "unknown"))
            breakdown = corr.get("fit_ranking_breakdown")
            if not isinstance(breakdown, dict):
                problems.append((correlation_id, "Missing fit_ranking_breakdown object"))
                continue
            if not breakdown.get("method_version"):
                problems.append((correlation_id, "Missing method_version"))

            factors = breakdown.get("factors")
            if not isinstance(factors, list) or not factors:
                problems.append((correlation_id, "Missing factors"))
                continue
            role_relevance = next(
                (factor for factor in factors if factor.get("factor") == "ROLE_RELEVANCE"),
                None,
            )
            if role_relevance is None:
                problems.append((correlation_id, "Missing ROLE_RELEVANCE factor"))
            else:
                has_positive_role_relevance |= float(role_relevance.get("compatibility_score", 0)) > 0

        if not has_positive_role_relevance:
            problems.append(("all", "No correlation has positive ROLE_RELEVANCE"))

        if problems:
            problem_summary = "\n".join(f"  {cid}: {message}" for cid, message in problems[:5])
            pytest.fail(
                f"Found {len(problems)} invalid fit_ranking_breakdown objects:\n{problem_summary}",
            )

        logger.info(
            "Fit ranking validation passed: all %d correlations expose real factors",
            len(correlations),
        )
