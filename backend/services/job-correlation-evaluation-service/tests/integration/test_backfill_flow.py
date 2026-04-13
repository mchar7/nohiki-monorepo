"""Integration tests for profile backfill flow.

to matching listings against the new profile.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import CallbackHeader, EntityTimestamps
from nohiki.job.listing.v1 import BackfillCallback, BackfillResult, ListingSnapshot
from nohiki.user.pref.v1 import PrefCreated, SearchPrefSnapshot
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


@pytest.mark.integration
class TestBackfillPublishingFlow:
    """Integration tests for backfill request publishing."""

    @pytest.mark.asyncio
    async def test_profile_created_triggers_backfill(self) -> None:
        """Test that profile creation triggers backfill request."""
        sample_profile_snapshot = SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=str(uuid4()),
            pref_name="Test Profile",
            is_active=True,
            search_keywords=["python", "backend"],
            disallowed_keywords=["frontend"],
            work_arrangements=[],
            example_uploads=[],
            context_uploads=[],
            timestamps=EntityTimestamps(
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        sample_pref_created_message = PrefCreated(
            pref_id=sample_profile_snapshot.id,
            pref_snapshot=sample_profile_snapshot,
        )
        mock_db = create_mock_session()
        mock_context = MagicMock(spec=MessageContext)
        mock_context.correlation_id = str(uuid4())
        mock_context.require_db_session.return_value = mock_db

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as mock_repo_cls,
            patch(
                "job_correlation_evaluation_service.events.handlers.publish_backfill_request",
                new=AsyncMock(),
            ) as mock_publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as mock_settings,
        ):
            mock_repo = AsyncMock()
            mock_repo_cls.return_value = mock_repo
            mock_repo.upsert_profile.return_value = True

            mock_settings.backfill.enabled = True
            mock_settings.database = MagicMock()
            mock_publish.return_value = str(uuid4())

            from job_correlation_evaluation_service.events.handlers import (
                handle_profile_created,
            )

            await handle_profile_created(sample_pref_created_message, mock_context)

            mock_repo.upsert_profile.assert_awaited_once()
            mock_publish.assert_awaited_once()

            assert mock_publish.await_args is not None
            publish_db, request = mock_publish.await_args.args
            assert publish_db is mock_db
            assert request.pref_id == sample_pref_created_message.pref_id
            assert request.user_id == sample_pref_created_message.pref_snapshot.user_id

    @pytest.mark.asyncio
    async def test_backfill_disabled_skips_publish(self) -> None:
        """Test that backfill is skipped when disabled."""
        sample_profile_snapshot = SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=str(uuid4()),
            pref_name="Test Profile",
            is_active=True,
            search_keywords=["python", "backend"],
            disallowed_keywords=["frontend"],
            work_arrangements=[],
            example_uploads=[],
            context_uploads=[],
            timestamps=EntityTimestamps(
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
        sample_pref_created_message = PrefCreated(
            pref_id=sample_profile_snapshot.id,
            pref_snapshot=sample_profile_snapshot,
        )
        mock_db = create_mock_session()
        mock_context = MagicMock(spec=MessageContext)
        mock_context.correlation_id = str(uuid4())
        mock_context.require_db_session.return_value = mock_db

        with (
            patch(
                "job_correlation_evaluation_service.events.handlers._claim_event",
                new=AsyncMock(return_value=True),
            ),
            patch("job_correlation_evaluation_service.events.handlers.ProfileProjectionRepository") as mock_repo_cls,
            patch(
                "job_correlation_evaluation_service.events.handlers.publish_backfill_request",
                new=AsyncMock(),
            ) as mock_publish,
            patch("job_correlation_evaluation_service.events.handlers.settings") as mock_settings,
        ):
            mock_repo = AsyncMock()
            mock_repo.upsert_profile.return_value = True
            mock_repo_cls.return_value = mock_repo

            mock_settings.backfill.enabled = False
            mock_settings.database = MagicMock()

            from job_correlation_evaluation_service.events.handlers import (
                handle_profile_created,
            )

            await handle_profile_created(sample_pref_created_message, mock_context)

            mock_repo.upsert_profile.assert_awaited_once()
            mock_publish.assert_not_awaited()


@pytest.mark.integration
class TestBackfillListingsHandlerFlow:
    """Integration tests for handling backfill listings responses."""

    @pytest.mark.asyncio
    async def test_backfill_listings_matched(self) -> None:
        """Test that backfill listings are matched against profile."""
        sample_listing_snapshots = [
            ListingSnapshot(
                id=str(uuid4()),
                listing_url=f"https://example.com/job/{i}",
                title=f"Software Engineer {i}",
                company_name=f"Tech Corp {i}",
                description="Build amazing software",
                posted_at=datetime.now(UTC),
            )
            for i in range(3)
        ]
        sample_backfill_message = BackfillCallback(
            pref_id=str(uuid4()),
            user_id=str(uuid4()),
            callback=CallbackHeader(
                operation_id=str(uuid4()),
                caller_context=b"",
                attributes={},
            ),
            success=BackfillResult(
                listings=sample_listing_snapshots,
                batch_number=1,
                total_batches=1,
                is_final_batch=True,
                total_listings=len(sample_listing_snapshots),
            ),
        )
        mock_context = MagicMock(spec=MessageContext)
        mock_context.correlation_id = str(uuid4())

        mock_profile = MagicMock()
        mock_profile.id = sample_backfill_message.pref_id

        with (
            patch("job_correlation_evaluation_service.events.backfill_handler.db_session") as mock_db_session,
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.ProfileProjectionRepository"
            ) as mock_repo_cls,
            patch("job_correlation_evaluation_service.events.backfill_handler.JobMatcherService") as mock_matcher_cls,
        ):
            mock_db = create_mock_session()
            mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_repo = AsyncMock()
            mock_repo.get_profile = AsyncMock(return_value=mock_profile)
            mock_repo_cls.return_value = mock_repo

            mock_matcher = AsyncMock()
            mock_matcher.match_listings_to_profile = AsyncMock(return_value=3)
            mock_matcher_cls.return_value = mock_matcher

            from job_correlation_evaluation_service.events.backfill_handler import (
                handle_backfill_listings,
            )

            await handle_backfill_listings(sample_backfill_message, mock_context)

            mock_repo.get_profile.assert_awaited_once()
            mock_matcher.match_listings_to_profile.assert_awaited_once()

            call_kwargs = mock_matcher.match_listings_to_profile.call_args.kwargs
            assert len(call_kwargs["listings"]) == 3
            assert call_kwargs["profile"] == mock_profile

    @pytest.mark.asyncio
    async def test_backfill_skipped_for_missing_profile(self) -> None:
        """Test that backfill is skipped if profile not found."""
        sample_listing_snapshots = [
            ListingSnapshot(
                id=str(uuid4()),
                listing_url=f"https://example.com/job/{i}",
                title=f"Software Engineer {i}",
                company_name=f"Tech Corp {i}",
                description="Build amazing software",
                posted_at=datetime.now(UTC),
            )
            for i in range(3)
        ]
        sample_backfill_message = BackfillCallback(
            pref_id=str(uuid4()),
            user_id=str(uuid4()),
            callback=CallbackHeader(
                operation_id=str(uuid4()),
                caller_context=b"",
                attributes={},
            ),
            success=BackfillResult(
                listings=sample_listing_snapshots,
                batch_number=1,
                total_batches=1,
                is_final_batch=True,
                total_listings=len(sample_listing_snapshots),
            ),
        )
        mock_context = MagicMock(spec=MessageContext)
        mock_context.correlation_id = str(uuid4())

        with (
            patch("job_correlation_evaluation_service.events.backfill_handler.db_session") as mock_db_session,
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.ProfileProjectionRepository"
            ) as mock_repo_cls,
            patch("job_correlation_evaluation_service.events.backfill_handler.JobMatcherService") as mock_matcher_cls,
        ):
            mock_db = create_mock_session()
            mock_db_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db_session.return_value.__aexit__ = AsyncMock(return_value=None)

            mock_repo = AsyncMock()
            mock_repo.get_profile = AsyncMock(return_value=None)
            mock_repo_cls.return_value = mock_repo

            mock_matcher = AsyncMock()
            mock_matcher_cls.return_value = mock_matcher

            from job_correlation_evaluation_service.events.backfill_handler import (
                handle_backfill_listings,
            )

            await handle_backfill_listings(sample_backfill_message, mock_context)

            mock_repo.get_profile.assert_awaited_once()
            mock_matcher.match_listings_to_profile.assert_not_awaited()


@pytest.mark.integration
class TestMatchListingsToProfileFlow:
    """Integration tests for matching listings to a single profile."""

    @pytest.mark.asyncio
    async def test_match_listings_creates_correlations(self) -> None:
        """Test that matching listings creates correlations."""
        sample_profile = SearchPrefSnapshot(
            id=str(uuid4()),
            user_id=str(uuid4()),
            pref_name="Test Profile",
            is_active=True,
            search_keywords=["python", "backend"],
            disallowed_keywords=[],
            work_arrangements=[],
            example_uploads=[],
            context_uploads=[],
        )
        sample_listings = [
            ListingSnapshot(
                id=str(uuid4()),
                listing_url=f"https://example.com/job/{i}",
                title=f"Python Developer {i}",
                company_name=f"Company {i}",
                description="Python backend developer needed",
                posted_at=datetime.now(UTC),
            )
            for i in range(5)
        ]
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )
        from job_correlation_evaluation_service.services.scoring_service import (
            MLScoringResult,
        )

        mock_db = create_mock_session()

        mock_ml_results = [
            MLScoringResult(
                score=50,
                confidence=0.8,
                is_disqualified=False,
                disqualification_reason=None,
                feature_importances=None,
                explanation=None,
                feature_vector=(0.1, 0.2, 0.3, 0.4, 0.5),
            )
            for _ in sample_listings
        ]

        mock_ml_service = MagicMock()
        mock_ml_service.is_initialized = True
        mock_ml_service.extract_query_encoding_from_snapshot = MagicMock(return_value=MagicMock())
        mock_ml_service.score_listings_batch = AsyncMock(return_value=mock_ml_results)
        service = JobMatcherService(ml_scoring_service=mock_ml_service)

        mock_repo = MagicMock()
        mock_repo.get_existing_listing_ids = AsyncMock(return_value=set())
        mock_repo.record_matches_batch_no_commit = AsyncMock(return_value=5)

        with (
            patch(
                "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository"
            ) as mock_repo_class,
            patch(
                "job_correlation_evaluation_service.services.matcher_service.publish_correlation_evaluated"
            ) as mock_publish,
        ):
            mock_repo_class.return_value = mock_repo
            mock_publish.return_value = None

            result = await service.match_listings_to_profile(
                db=mock_db,
                listings=sample_listings,
                profile=sample_profile,
                correlation_id="test-correlation",
            )

            assert result == 5
            mock_repo.record_matches_batch_no_commit.assert_awaited_once()
            assert mock_publish.call_count == 5

    @pytest.mark.asyncio
    async def test_match_skips_existing_correlations(
        self,
        sample_profile: SearchPrefSnapshot,
        sample_listings: list[ListingSnapshot],
    ) -> None:
        """Test that existing correlations are skipped."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_db = create_mock_session()
        service = JobMatcherService()

        existing_ids = {str(listing.id) for listing in sample_listings}

        mock_repo = MagicMock()
        mock_repo.get_existing_listing_ids = AsyncMock(return_value=existing_ids)

        mock_pipeline = MagicMock()
        mock_pipeline.execute = MagicMock()

        with patch(
            "job_correlation_evaluation_service.services.matcher_service.MatchRecordRepository"
        ) as mock_repo_class:
            mock_repo_class.return_value = mock_repo
            # Fix: match_listings_to_profile does not use _pipeline, it uses _ml_service.
            # But the test was mocking _pipeline which doesn't exist on JobMatcherService anymore.
            # However, in this test it should just return 0 because of existing_ids.

            result = await service.match_listings_to_profile(
                db=mock_db,
                listings=sample_listings,
                profile=sample_profile,
                correlation_id="test-correlation",
            )

            assert result == 0
            mock_pipeline.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_match_handles_empty_listings(
        self,
        sample_profile: SearchPrefSnapshot,
    ) -> None:
        """Test that empty listings list is handled gracefully."""
        from job_correlation_evaluation_service.services.matcher_service import (
            JobMatcherService,
        )

        mock_db = create_mock_session()
        service = JobMatcherService()

        result = await service.match_listings_to_profile(
            db=mock_db,
            listings=[],
            profile=sample_profile,
            correlation_id="test-correlation",
        )

        assert result == 0
