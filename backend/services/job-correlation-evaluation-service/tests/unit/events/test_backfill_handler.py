"""Unit tests for backfill_handler module."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


def _make_context(*, db_session: AsyncMock | None = None) -> MessageContext:
    """Build a ``MessageContext`` with injected db_session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
    )


@pytest.fixture(autouse=True)
def _successful_callback_claim() -> Iterator[None]:
    """Treat each callback as newly claimed unless a test overrides the seam."""
    with patch(
        "job_correlation_evaluation_service.events.backfill_handler.check_and_mark_processed",
        new=AsyncMock(return_value=True),
    ):
        yield


@pytest.fixture
def mock_backfill_message() -> MagicMock:
    """Create a mock BackfillCallback message with empty listings."""
    message = MagicMock()
    message.pref_id = "550e8400-e29b-41d4-a716-446655440000"
    message.error = None
    message.success = MagicMock()
    message.success.listings = []
    message.success.batch_number = 1
    message.success.total_batches = 3
    message.success.is_final_batch = False
    return message


@pytest.fixture
def mock_backfill_message_with_listings() -> MagicMock:
    """Create a mock BackfillCallback message with listings."""
    message = MagicMock()
    message.pref_id = "550e8400-e29b-41d4-a716-446655440000"
    message.error = None
    message.success = MagicMock()
    message.success.batch_number = 2
    message.success.total_batches = 3
    message.success.is_final_batch = True

    listing = MagicMock()
    listing.listing_id = "job-123"
    message.success.listings = [listing]
    return message


class TestHandleBackfillListings:
    """Tests for handle_backfill_listings handler."""

    @pytest.mark.asyncio
    async def test_handles_empty_listings(self, mock_backfill_message: MagicMock) -> None:
        """Test that handler returns early for empty listings."""
        from job_correlation_evaluation_service.events.backfill_handler import (
            handle_backfill_listings,
        )

        context = _make_context()
        await handle_backfill_listings(mock_backfill_message, context)

    @pytest.mark.asyncio
    async def test_handles_invalid_pref_id(self) -> None:
        """Test that handler handles invalid pref_id format."""
        message = MagicMock()
        message.pref_id = "invalid-uuid"
        message.error = None
        message.success = MagicMock()
        message.success.batch_number = 1
        message.success.total_batches = 1
        message.success.is_final_batch = True
        listing = MagicMock()
        message.success.listings = [listing]

        from job_correlation_evaluation_service.events.backfill_handler import (
            handle_backfill_listings,
        )

        context = _make_context()
        await handle_backfill_listings(message, context)

    @pytest.mark.asyncio
    async def test_handles_profile_not_found(
        self,
        mock_backfill_message_with_listings: MagicMock,
    ) -> None:
        """Test that handler handles profile not found."""
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch(
            "job_correlation_evaluation_service.events.backfill_handler.ProfileProjectionRepository",
        ) as mock_repo_cls:
            mock_repo = AsyncMock()
            mock_repo.get_profile.return_value = None
            mock_repo_cls.return_value = mock_repo

            from job_correlation_evaluation_service.events.backfill_handler import (
                handle_backfill_listings,
            )

            await handle_backfill_listings(mock_backfill_message_with_listings, context)

            mock_repo.get_profile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_processes_listings_successfully(
        self,
        mock_backfill_message_with_listings: MagicMock,
    ) -> None:
        """Test that handler processes listings successfully."""
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.ProfileProjectionRepository",
            ) as mock_repo_cls,
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.JobMatcherService",
            ) as mock_matcher_cls,
            patch(
                "job_correlation_evaluation_service.events.backfill_handler._backfill_services",
            ) as mock_services,
        ):
            mock_profile = MagicMock()
            mock_profile.pref_id = UUID("550e8400-e29b-41d4-a716-446655440000")
            mock_repo = AsyncMock()
            mock_repo.get_profile.return_value = mock_profile
            mock_repo_cls.return_value = mock_repo

            mock_matcher = AsyncMock()
            mock_matcher.match_listings_to_profile.return_value = 5
            mock_matcher_cls.return_value = mock_matcher

            mock_services.ml_scoring_service = None

            from job_correlation_evaluation_service.events.backfill_handler import (
                handle_backfill_listings,
            )

            await handle_backfill_listings(mock_backfill_message_with_listings, context)

            mock_repo.get_profile.assert_awaited_once()
            mock_matcher.match_listings_to_profile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_passes_force_rescore_from_callback_context(
        self,
        mock_backfill_message_with_listings: MagicMock,
    ) -> None:
        """Updated-profile callback context selects the upsert/rescore path."""
        from job_correlation_evaluation_service.events.backfill_handler import (
            BackfillCallerContext,
            handle_backfill_listings,
        )

        mock_backfill_message_with_listings.callback = MagicMock()
        mock_backfill_message_with_listings.callback.operation_id = "op-updated"
        mock_backfill_message_with_listings.callback.caller_context = BackfillCallerContext(
            force_rescore=True
        ).to_bytes()
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.ProfileProjectionRepository",
            ) as mock_repo_cls,
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.JobMatcherService",
            ) as mock_matcher_cls,
        ):
            mock_profile = MagicMock()
            mock_repo = AsyncMock()
            mock_repo.get_profile.return_value = mock_profile
            mock_repo_cls.return_value = mock_repo
            mock_matcher = AsyncMock()
            mock_matcher.match_listings_to_profile.return_value = 1
            mock_matcher_cls.return_value = mock_matcher

            await handle_backfill_listings(mock_backfill_message_with_listings, context)

            assert mock_matcher.match_listings_to_profile.call_args.kwargs["force_rescore"] is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize("caller_context", [b"", b"legacy-context", b"{not-json"])
    async def test_invalid_or_legacy_context_safely_uses_missing_only_path(
        self,
        mock_backfill_message_with_listings: MagicMock,
        caller_context: bytes,
    ) -> None:
        """Old callbacks cannot request a destructive rescore implicitly."""
        from job_correlation_evaluation_service.events.backfill_handler import (
            handle_backfill_listings,
        )

        mock_backfill_message_with_listings.callback = MagicMock()
        mock_backfill_message_with_listings.callback.operation_id = "op-legacy"
        mock_backfill_message_with_listings.callback.caller_context = caller_context
        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with (
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.ProfileProjectionRepository",
            ) as mock_repo_cls,
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.JobMatcherService",
            ) as mock_matcher_cls,
        ):
            mock_profile = MagicMock()
            mock_repo = AsyncMock()
            mock_repo.get_profile.return_value = mock_profile
            mock_repo_cls.return_value = mock_repo
            mock_matcher = AsyncMock()
            mock_matcher.match_listings_to_profile.return_value = 1
            mock_matcher_cls.return_value = mock_matcher

            await handle_backfill_listings(mock_backfill_message_with_listings, context)

            assert mock_matcher.match_listings_to_profile.call_args.kwargs["force_rescore"] is False

    @pytest.mark.asyncio
    async def test_duplicate_force_rescore_batch_matches_once(
        self,
        mock_backfill_message_with_listings: MagicMock,
    ) -> None:
        """Broker redelivery with a new event ID cannot emit matches twice."""
        from job_correlation_evaluation_service.events.backfill_handler import (
            BackfillCallerContext,
            handle_backfill_listings,
        )

        message = mock_backfill_message_with_listings
        message.callback = MagicMock(
            operation_id="force-rescore-operation",
            caller_context=BackfillCallerContext(force_rescore=True).to_bytes(),
        )
        message.metadata = MagicMock(event_id="callback-delivery-one")
        db = create_mock_session()
        context = _make_context(db_session=db)
        seen_claims: set[tuple[str, str]] = set()

        async def claim_once(
            _db: object,
            _schema: str,
            event_id: str,
            consumer: str,
        ) -> bool:
            claim = (event_id, consumer)
            if claim in seen_claims:
                return False
            seen_claims.add(claim)
            return True

        with (
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.check_and_mark_processed",
                new=AsyncMock(side_effect=claim_once),
            ),
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.ProfileProjectionRepository",
            ) as repository_class,
            patch(
                "job_correlation_evaluation_service.events.backfill_handler.JobMatcherService",
            ) as matcher_class,
        ):
            repository = AsyncMock()
            repository.get_profile.return_value = MagicMock()
            repository_class.return_value = repository
            matcher = AsyncMock()
            matcher.match_listings_to_profile.return_value = 1
            matcher_class.return_value = matcher

            await handle_backfill_listings(message, context)
            message.metadata = MagicMock(event_id="callback-delivery-two")
            await handle_backfill_listings(message, context)

        matcher.match_listings_to_profile.assert_awaited_once()
        assert len(seen_claims) == 1


class TestSetBackfillMLScoringService:
    """Tests for set_backfill_ml_scoring_service."""

    def test_sets_service(self) -> None:
        """Test that service is set correctly."""
        from job_correlation_evaluation_service.events.backfill_handler import (
            _backfill_services,
            set_backfill_ml_scoring_service,
        )

        mock_service = MagicMock()
        set_backfill_ml_scoring_service(mock_service)

        assert _backfill_services.ml_scoring_service is mock_service

        # Reset to None for other tests
        set_backfill_ml_scoring_service(None)
