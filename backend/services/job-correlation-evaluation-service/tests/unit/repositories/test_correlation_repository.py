"""Unit tests for CorrelationRepository."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from job_correlation_evaluation_service.repositories.correlation_repository import (
    CorrelationNotFoundError,
    CorrelationRepository,
    CorrelationUpdate,
)
from nohiki.common.v1 import UserFeedback


class TestCorrelationNotFoundError:
    """Tests for CorrelationNotFoundError exception."""

    def test_error_message(self) -> None:
        """Test error message format."""
        correlation_id = uuid4()
        error = CorrelationNotFoundError(correlation_id)

        assert str(correlation_id) in str(error)
        assert "Correlation not found" in str(error)

    def test_error_stores_correlation_id(self) -> None:
        """Test error stores correlation_id attribute."""
        correlation_id = uuid4()
        error = CorrelationNotFoundError(correlation_id)

        assert error.correlation_id == correlation_id


class TestCorrelationRepository:
    """Tests for CorrelationRepository."""


class TestGetById:
    """Tests for get_by_id method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> CorrelationRepository:
        """Create repository with mock session."""
        return CorrelationRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_by_id_found(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_by_id returns correlation when found."""
        correlation_id = uuid4()
        mock_correlation = MagicMock()
        mock_correlation.id = correlation_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_correlation
        mock_session.execute.return_value = mock_result

        result = await repository.get_by_id(correlation_id)

        assert result is not None
        assert result.id == correlation_id

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_by_id returns None when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_by_id(uuid4())

        assert result is None


class TestUpdate:
    """Tests for update method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> CorrelationRepository:
        """Create repository with mock session."""
        return CorrelationRepository(session=mock_session)

    @pytest.fixture
    def mock_correlation(self) -> MagicMock:
        """Create mock correlation."""
        corr = MagicMock()
        corr.id = uuid4()
        corr.is_viewed = False
        corr.is_applied = False
        corr.is_dismissed = False
        corr.user_feedback = None
        return corr

    @pytest.mark.asyncio
    async def test_update_is_viewed(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
        mock_correlation: MagicMock,
    ) -> None:
        """Test updating is_viewed flag."""
        # Setup get_by_id to return the correlation
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_correlation
        mock_session.execute.return_value = mock_result

        result = await repository.update(mock_correlation.id, CorrelationUpdate(is_viewed=True))

        assert result.is_viewed is True
        mock_session.flush.assert_called_once()
        mock_session.commit.assert_not_called()
        mock_session.refresh.assert_called_once_with(mock_correlation)

    @pytest.mark.asyncio
    async def test_update_is_applied(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
        mock_correlation: MagicMock,
    ) -> None:
        """Test updating is_applied flag."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_correlation
        mock_session.execute.return_value = mock_result

        result = await repository.update(mock_correlation.id, CorrelationUpdate(is_applied=True))

        assert result.is_applied is True

    @pytest.mark.asyncio
    async def test_update_user_feedback(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
        mock_correlation: MagicMock,
    ) -> None:
        """Test updating user_feedback."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_correlation
        mock_session.execute.return_value = mock_result

        result = await repository.update(
            mock_correlation.id,
            CorrelationUpdate(user_feedback=UserFeedback.POSITIVE),
        )

        assert result.user_feedback == UserFeedback.POSITIVE

    @pytest.mark.asyncio
    async def test_update_not_found_raises(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test update raises CorrelationNotFoundError when not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with pytest.raises(CorrelationNotFoundError):
            await repository.update(uuid4(), CorrelationUpdate(is_viewed=True))

    @pytest.mark.asyncio
    async def test_update_multiple_fields(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
        mock_correlation: MagicMock,
    ) -> None:
        """Test updating multiple fields at once."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_correlation
        mock_session.execute.return_value = mock_result

        result = await repository.update(
            mock_correlation.id,
            CorrelationUpdate(is_viewed=True, is_applied=True),
        )

        assert result.is_viewed is True
        assert result.is_applied is True


class TestGetFeedbackStats:
    """Tests for get_feedback_stats method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> CorrelationRepository:
        """Create repository with mock session."""
        return CorrelationRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_feedback_stats_returns_dict(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_feedback_stats returns expected structure."""
        mock_row = MagicMock()
        mock_row.total_feedback = 10
        mock_row.viewed = 5
        mock_row.applied = 3
        mock_row.dismissed = 2
        mock_row.positive = 4
        mock_row.negative = 1
        mock_row.training_samples = 8

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        stats = await repository.get_feedback_stats()

        assert "total_feedback_count" in stats
        assert "feedback_by_type" in stats
        assert "training_samples_available" in stats
        assert stats["total_feedback_count"] == 10
        feedback_by_type = cast(dict[str, int], stats["feedback_by_type"])
        assert feedback_by_type["viewed"] == 5
        assert stats["training_samples_available"] == 8

    @pytest.mark.asyncio
    async def test_get_feedback_stats_handles_none(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_feedback_stats handles None values in result row."""
        mock_row = MagicMock()
        mock_row.total_feedback = None
        mock_row.viewed = None
        mock_row.applied = None
        mock_row.dismissed = None
        mock_row.positive = None
        mock_row.negative = None
        mock_row.training_samples = None

        mock_result = MagicMock()
        mock_result.one.return_value = mock_row
        mock_session.execute.return_value = mock_result

        stats = await repository.get_feedback_stats()

        assert stats["total_feedback_count"] == 0
        assert stats["training_samples_available"] == 0
        feedback_by_type = cast(dict[str, int], stats["feedback_by_type"])
        assert feedback_by_type["viewed"] == 0


class TestGetForTraining:
    """Tests for get_for_training method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> CorrelationRepository:
        """Create repository with mock session."""
        return CorrelationRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_get_for_training_returns_list(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_for_training returns list of correlations."""
        mock_correlations = [MagicMock(), MagicMock()]
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = mock_correlations
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        results = await repository.get_for_training()

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_get_for_training_with_date_range(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_for_training respects date filters."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        min_date = datetime.now(UTC) - timedelta(days=30)
        max_date = datetime.now(UTC)

        results = await repository.get_for_training(
            min_date=min_date,
            max_date=max_date,
        )

        assert isinstance(results, list)
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_for_training_with_limit(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test get_for_training respects limit."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        await repository.get_for_training(limit=100)

        mock_session.execute.assert_called_once()


class TestBulkUpdateViewed:
    """Tests for bulk_update_viewed method."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create mock session."""
        return AsyncMock()

    @pytest.fixture
    def repository(self, mock_session: AsyncMock) -> CorrelationRepository:
        """Create repository with mock session."""
        return CorrelationRepository(session=mock_session)

    @pytest.mark.asyncio
    async def test_bulk_update_empty_list(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test bulk_update_viewed with empty list returns 0."""
        result = await repository.bulk_update_viewed([])

        assert result == 0
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_bulk_update_returns_count(
        self,
        repository: CorrelationRepository,
        mock_session: AsyncMock,
    ) -> None:
        """Test bulk_update_viewed returns row count."""
        mock_result = MagicMock()
        mock_result.rowcount = 5
        mock_session.execute.return_value = mock_result

        correlation_ids = [uuid4() for _ in range(5)]
        result = await repository.bulk_update_viewed(correlation_ids)

        assert result == 5
        mock_session.commit.assert_not_awaited()
