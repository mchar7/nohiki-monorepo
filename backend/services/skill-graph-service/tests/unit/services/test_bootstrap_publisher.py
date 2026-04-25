"""Unit tests for bootstrap_publisher service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session
from skill_graph_service.events.publishers import publish_skill_created_batch
from skill_graph_service.services.bootstrap_publisher import (
    BootstrapPublishResult,
    publish_skill_created_events_for_bootstrap,
)
from tests.helpers import MockAsyncIterator


class TestBootstrapPublishResult:
    """Tests for BootstrapPublishResult dataclass."""

    def test_init_with_all_fields(self) -> None:
        """Test BootstrapPublishResult initializes correctly."""
        result = BootstrapPublishResult(total_published=100, batch_count=2)
        assert result.total_published == 100
        assert result.batch_count == 2

    def test_is_frozen(self) -> None:
        """Test BootstrapPublishResult is immutable (frozen dataclass)."""
        assert BootstrapPublishResult.__dataclass_params__.frozen


class TestPublishSkillCreatedEventsForBootstrap:
    """Tests for publish_skill_created_events_for_bootstrap function."""

    @pytest.mark.asyncio
    async def test_writes_one_outbox_batch_per_stream_batch(self) -> None:
        """Bootstrap preserves stream batch boundaries in transactional outbox writes."""

        def skill(label: str) -> MagicMock:
            result = MagicMock()
            result.id = uuid.uuid4()
            result.normalized_text = label
            result.display_name = label.title()
            result.description = None
            result.category = None
            result.subcategory = None
            result.skill_type = "specialized"
            result.reuse_level = None
            result.review_status = "approved"
            result.confidence_score = 1.0
            result.mention_count = 0
            result.job_count = 0
            result.profile_count = 0
            return result

        skill_1 = skill("python")
        skill_2 = skill("rust")
        batches = [[(skill_1, None)], [(skill_2, None)]]
        fallback_publisher = AsyncMock()
        outbox = MagicMock()
        outbox.write_events = AsyncMock(side_effect=[[uuid.uuid4()], [uuid.uuid4()]])
        db = create_mock_session()

        with (
            pytest.MonkeyPatch.context() as mp,
            patch("skill_graph_service.events.publishers.OutboxWriter", return_value=outbox),
        ):
            mp.setattr(
                "skill_graph_service.services.bootstrap_publisher.stream_skills_with_provenance",
                lambda *_args, **_kwargs: MockAsyncIterator(batches),
            )
            result = await publish_skill_created_events_for_bootstrap(
                db,
                skill_created_publisher=fallback_publisher,
                skill_created_batch_publisher=publish_skill_created_batch,
                batch_size=1,
            )

        assert result == BootstrapPublishResult(total_published=2, batch_count=2)
        assert outbox.write_events.await_count == 2
        assert [len(call.kwargs["entries"]) for call in outbox.write_events.await_args_list] == [1, 1]
        assert [call.kwargs["entries"][0][1].skill_id for call in outbox.write_events.await_args_list] == [
            str(skill_1.id),
            str(skill_2.id),
        ]
        assert db.commit.await_count == 2
        fallback_publisher.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_skills_returns_zero_counts(self) -> None:
        """Returns zero counts when no skills exist."""
        mock_publisher = AsyncMock(return_value=uuid.uuid4())
        db = create_mock_session()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "skill_graph_service.services.bootstrap_publisher.stream_skills_with_provenance",
                lambda *_args, **_kwargs: MockAsyncIterator([]),
            )

            result = await publish_skill_created_events_for_bootstrap(
                db,
                skill_created_publisher=mock_publisher,
            )

        assert result.total_published == 0
        assert result.batch_count == 0
        mock_publisher.assert_not_called()
        db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_commits_after_each_batch(self) -> None:
        """Commits DB transaction after each batch for reliability."""
        skills = [(MagicMock(id=uuid.uuid4()), MagicMock()) for _ in range(3)]
        batches = [skills[:2], skills[2:]]

        mock_publisher = AsyncMock(return_value=uuid.uuid4())
        db = create_mock_session()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "skill_graph_service.services.bootstrap_publisher.stream_skills_with_provenance",
                lambda *_args, **_kwargs: MockAsyncIterator(batches),
            )

            result = await publish_skill_created_events_for_bootstrap(
                db,
                skill_created_publisher=mock_publisher,
            )

        assert result.batch_count == 2
        assert db.commit.call_count == 2

    @pytest.mark.asyncio
    async def test_passes_skill_and_provenance_to_publisher(self) -> None:
        """Passes correct skill and provenance to publisher."""
        skill = MagicMock(id=uuid.uuid4())
        provenance = MagicMock()

        mock_publisher = AsyncMock(return_value=uuid.uuid4())
        db = create_mock_session()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "skill_graph_service.services.bootstrap_publisher.stream_skills_with_provenance",
                lambda *_args, **_kwargs: MockAsyncIterator([[(skill, provenance)]]),
            )

            await publish_skill_created_events_for_bootstrap(
                db,
                skill_created_publisher=mock_publisher,
            )

        mock_publisher.assert_called_once_with(db, skill, provenance)
