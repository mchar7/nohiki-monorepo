"""Unit tests for skill governance service."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_db_utils.testing import create_mock_session
from skill_graph_service.db.models import ProposedSkill
from skill_graph_service.services.skill_governance import (
    SkillProposalParams,
    check_near_duplicates,
    process_skill_proposal,
)


class TestCheckNearDuplicates:
    """Tests for check_near_duplicates function."""

    @pytest.mark.asyncio
    async def test_returns_duplicates(self) -> None:
        """Test near duplicate detection."""
        mock_qdrant = MagicMock()
        mock_match = MagicMock()
        mock_match.id = uuid.uuid4()
        mock_match.payload = {"name": "python"}
        mock_match.score = 0.9
        mock_qdrant.search_dense = AsyncMock(return_value=[mock_match])

        with patch("skill_graph_service.services.skill_governance.get_manifest") as mock_manifest:
            mock_manifest.return_value.get_collection_name.return_value = "skills_v1"
            results = await check_near_duplicates([0.1] * 1024, mock_qdrant)

            assert len(results) == 1
            assert results[0][0] == str(mock_match.id)
            assert results[0][1] == "python"
            assert results[0][2] == pytest.approx(0.9)


class TestProcessSkillProposal:
    """Tests for process_skill_proposal function."""

    @pytest.mark.asyncio
    async def test_detects_duplicate_via_embedding(self, mock_db_session: AsyncMock) -> None:
        """Test proposal rejection if embedding is too similar."""
        mock_qdrant = MagicMock()
        mock_publisher = AsyncMock(return_value=uuid.uuid4())
        params = SkillProposalParams(canonical_name="python-new", display_name="Python New", embedding=[0.1] * 1024)

        with patch(
            "skill_graph_service.services.skill_governance.check_near_duplicates", return_value=[("id", "python", 0.95)]
        ):
            status, message, skill_id = await process_skill_proposal(
                mock_db_session,
                mock_qdrant,
                params,
                skill_created_publisher=mock_publisher,
            )

            assert skill_id is None
            assert status == "rejected_duplicate"
            assert "Too similar" in message

    @pytest.mark.asyncio
    async def test_reinforce_existing_proposal(self, mock_db_session: AsyncMock) -> None:
        """Test reinforcing an existing proposal."""
        mock_qdrant = MagicMock()
        params = SkillProposalParams(canonical_name="python", display_name="Python")

        proposal = MagicMock(spec=ProposedSkill)
        proposal.id = uuid.uuid4()
        proposal.canonical_name = "python"
        proposal.proposal_count = 1
        proposal.source_job_ids = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = proposal
        mock_db_session.execute.return_value = mock_result

        mock_publisher = AsyncMock(return_value=uuid.uuid4())

        status, message, skill_id = await process_skill_proposal(
            mock_db_session,
            mock_qdrant,
            params,
            skill_created_publisher=mock_publisher,
        )

        assert skill_id is None
        assert status == "proposal_reinforced"
        assert "Proposal count: 2" in message
        mock_db_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_detects_duplicate_name(self, mock_db_session: AsyncMock) -> None:
        """Test proposal rejection if name already exists."""
        mock_result = MagicMock()
        mock_proposal = MagicMock(spec=ProposedSkill)
        mock_proposal.id = uuid.uuid4()
        mock_proposal.canonical_name = "python"
        mock_proposal.proposal_count = 1
        mock_proposal.source_job_ids = []
        mock_result.scalar_one_or_none.return_value = mock_proposal
        mock_db_session.execute.return_value = mock_result

        mock_qdrant = MagicMock()
        mock_qdrant.search_dense = AsyncMock(return_value=[])

        mock_publisher = AsyncMock(return_value=uuid.uuid4())

        params = SkillProposalParams(canonical_name="python", display_name="Python")
        status, message, skill_id = await process_skill_proposal(
            mock_db_session,
            mock_qdrant,
            params,
            skill_created_publisher=mock_publisher,
        )

        assert skill_id is None
        assert status == "proposal_reinforced"
        assert "Proposal count: 2" in message

    @pytest.mark.asyncio
    async def test_creates_proposal(self, mock_db_session: AsyncMock) -> None:
        """Test creation of a new skill proposal."""
        # Mock no existing skill
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute.return_value = mock_result

        # Mock proposal creation
        mock_proposal = MagicMock(spec=ProposedSkill)
        mock_proposal.id = uuid.uuid4()
        mock_proposal.status = "pending_review"
        mock_db_session.add.return_value = mock_proposal
        mock_db_session.flush.return_value = None

        mock_qdrant = MagicMock()
        mock_qdrant.search_dense = AsyncMock(return_value=[])

        mock_publisher = AsyncMock(return_value=uuid.uuid4())

        params = SkillProposalParams(
            canonical_name="new-skill", display_name="New Skill", suggested_aliases=["alias1"], embedding=[0.1] * 1024
        )

        status, message, skill_id = await process_skill_proposal(
            mock_db_session,
            mock_qdrant,
            params,
            skill_created_publisher=mock_publisher,
        )

        assert skill_id is None
        assert status == "pending_review"
        assert "created" in message
        assert mock_db_session.add.called
        mock_db_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_auto_approves_threshold(self, mock_db_session: AsyncMock) -> None:
        """Test auto-approval when threshold is met."""
        mock_qdrant = MagicMock()
        params = SkillProposalParams(canonical_name="popular-skill", display_name="Popular Skill")

        proposal = MagicMock(spec=ProposedSkill)
        proposal.id = uuid.uuid4()
        proposal.canonical_name = "popular-skill"
        proposal.display_name = "Popular Skill"
        proposal.proposal_count = 4  # Threshold is 5
        proposal.source_job_ids = []
        proposal.suggested_aliases = []
        proposal.category = None
        proposal.description = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.side_effect = [proposal, proposal]  # Once for find, once for _approve
        mock_db_session.execute.return_value = mock_result

        mock_publisher = AsyncMock(return_value=uuid.uuid4())

        with patch("skill_graph_service.services.skill_governance.AUTO_APPROVE_THRESHOLD", 5):
            status, message, skill_id = await process_skill_proposal(
                mock_db_session,
                mock_qdrant,
                params,
                skill_created_publisher=mock_publisher,
            )

            assert skill_id is not None
            assert status == "auto_approved"
            assert "Skill created" in message
            mock_publisher.assert_called_once()

    @pytest.mark.asyncio
    async def test_reinforce_with_source_job_id(self, mock_db_session: AsyncMock) -> None:
        """Test reinforcing adds the source_job_id to the tracked set."""
        mock_qdrant = MagicMock()
        params = SkillProposalParams(
            canonical_name="python",
            display_name="Python",
            source_job_id="job-abc-123",
        )

        proposal = MagicMock(spec=ProposedSkill)
        proposal.id = uuid.uuid4()
        proposal.canonical_name = "python"
        proposal.proposal_count = 1
        proposal.source_job_ids = ["job-xyz-000"]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = proposal
        mock_db_session.execute.return_value = mock_result

        mock_publisher = AsyncMock(return_value=uuid.uuid4())

        status, _, skill_id = await process_skill_proposal(
            mock_db_session,
            mock_qdrant,
            params,
            skill_created_publisher=mock_publisher,
        )

        assert skill_id is None
        assert status == "proposal_reinforced"
        assert mock_db_session.execute.call_count == 2  # initial find + update

    @pytest.mark.asyncio
    async def test_auto_approves_with_aliases(self, mock_db_session: AsyncMock) -> None:
        """Test _approve_proposal creates SkillAlias rows when suggested_aliases provided."""
        mock_qdrant = MagicMock()
        params = SkillProposalParams(canonical_name="golang", display_name="Go Language")

        proposal = MagicMock(spec=ProposedSkill)
        proposal.id = uuid.uuid4()
        proposal.canonical_name = "golang"
        proposal.display_name = "Go Language"
        proposal.proposal_count = 4
        proposal.source_job_ids = []
        proposal.suggested_aliases = ["go", "go lang"]
        proposal.category = None
        proposal.description = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = proposal
        mock_result.scalar_one.return_value = proposal  # for _approve_proposal's inner select
        mock_db_session.execute.return_value = mock_result

        mock_publisher = AsyncMock(return_value=uuid.uuid4())

        with patch("skill_graph_service.services.skill_governance.AUTO_APPROVE_THRESHOLD", 5):
            status, _, skill_id = await process_skill_proposal(
                mock_db_session,
                mock_qdrant,
                params,
                skill_created_publisher=mock_publisher,
            )

        assert skill_id is not None
        assert status == "auto_approved"
        add_calls = mock_db_session.add.call_args_list
        assert len(add_calls) == 3  # SkillNode + 2 aliases


class TestPublishSkillCreatedViaOutbox:
    """Tests for publish_skill_created outbox publishing."""

    @pytest.mark.asyncio
    async def test_publishes_skill_created_to_outbox(self) -> None:
        """Test that publish_skill_created writes to the outbox table."""
        from skill_graph_service.events.publishers import publish_skill_created

        skill = MagicMock()
        skill.id = uuid.uuid4()
        skill.normalized_text = "machine-learning"
        skill.display_name = "Machine Learning"
        skill.description = "ML description"
        skill.category = "Tech"
        skill.subcategory = None
        skill.skill_type = None
        skill.reuse_level = None
        skill.review_status = "approved"
        skill.confidence_score = 0.9
        skill.mention_count = 0
        skill.job_count = 0
        skill.profile_count = 0

        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock(return_value=uuid.uuid4())

        with patch("skill_graph_service.events.publishers.OutboxWriter", return_value=mock_outbox):
            result = await publish_skill_created(mock_db, skill, provenance=None)

        assert result is not None
        mock_outbox.write_event.assert_called_once()
