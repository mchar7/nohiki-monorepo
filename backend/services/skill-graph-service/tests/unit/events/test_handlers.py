"""Tests for Kafka event handlers."""

from __future__ import annotations

import base64
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.common.v1 import CallbackHeader, ErrorInfo
from nohiki.ml.v1 import (
    BatchEmbeddingCallback,
    BatchEmbeddingResult,
    BatchEmbeddingResultItem,
    DenseData,
    EmbeddingType,
    EmbeddingVector,
    EntityType,
)
from nohiki.skill.v1 import (
    MatchConfidence,
    RawSkillWithLevel,
    SkillGraphSeeded,
    SkillMatchType,
    SkillMentionSource,
    SkillProficiencyLevel,
)
from nohiki_common_exceptions import DataNotAvailableError
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from skill_graph_service.events.handlers import (
    _get_embedded_skill_ids,
    handle_alias_learned,
    handle_batch_embedding_callback,
    handle_normalization_embedding_callback,
    handle_skill_graph_seeded,
    handle_skill_mention_created,
    handle_skill_normalization_requested,
    handle_skill_proposed,
    start_event_consumer,
)
from skill_graph_service.services.embedding_service import EmbeddingVariant, skill_variant_point_id
from skill_graph_service.services.normalization.models import (
    DeterministicMatchResult,
    SkillNormalizationResult,
)


def _make_context(
    *,
    db_session: MagicMock | AsyncMock | None = None,
    session_factory: MagicMock | None = None,
) -> MessageContext:
    """Build a MessageContext for testing with optional injected session."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
        session_factory=session_factory or MagicMock(),
    )


def _dense_embedding(values: list[float] | None = None) -> EmbeddingVector:
    return EmbeddingVector(
        embedding_type=EmbeddingType.DENSE,
        dense=DenseData(values=values or ([0.1] * 8)),
        content_hash="a" * 64,
        collection_version="v1",
    )


class TestHandleBatchEmbeddingCallback:
    """Tests for handle_batch_embedding_callback handler."""

    @pytest.mark.asyncio
    async def test_success_upserts_to_qdrant(self) -> None:
        """On success, converts results to VectorPoints and upserts to Qdrant."""
        skill_id = str(uuid.uuid4())
        result_item = BatchEmbeddingResultItem(
            point_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{skill_id}_label")),
            entity_id=skill_id,
            embeddings=[_dense_embedding()],
            content_hash="a" * 64,
            item_attributes={"variant": "label", "skill_id": skill_id, "name": "Python"},
        )
        message = BatchEmbeddingCallback(
            entity_type=EntityType.SKILL,
            success=BatchEmbeddingResult(results=[result_item]),
        )
        mock_qdrant = AsyncMock()
        mock_qdrant.upsert_vector_points_batch = AsyncMock(return_value=1)
        with (
            patch("skill_graph_service.events.handlers.get_qdrant_client", return_value=mock_qdrant),
            patch("skill_graph_service.events.handlers.get_manifest") as mock_manifest,
        ):
            mock_manifest.return_value.get_collection_name.return_value = "skills_v1"
            await handle_batch_embedding_callback(message, _make_context())
        mock_qdrant.upsert_vector_points_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_error_logs_without_raising(self) -> None:
        """On error, logs the failure and does not raise."""
        message = BatchEmbeddingCallback(
            error=ErrorInfo(error_code="PIPELINE_ERROR", error_message="crashed", retryable=False),
        )
        with patch("skill_graph_service.events.handlers.logger") as mock_logger:
            await handle_batch_embedding_callback(message, _make_context())
        mock_logger.error.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_raises_validation_error(self) -> None:
        """Neither success nor error present raises ValidationError."""
        from nohiki_common_exceptions import ValidationError

        with pytest.raises(ValidationError):
            await handle_batch_embedding_callback(BatchEmbeddingCallback(), _make_context())


class TestHandleSkillMentionCreated:
    """Tests for handle_skill_mention_created handler."""

    @pytest.mark.asyncio
    async def test_skips_when_no_match(self) -> None:
        """Handler skips when message has no match."""
        message = MagicMock()
        message.match = None
        message.mention = MagicMock()

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        await handle_skill_mention_created(message, context)

        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_mention(self) -> None:
        """Handler skips when message has no mention."""
        message = MagicMock()
        message.match = MagicMock()
        message.mention = None

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        await handle_skill_mention_created(message, context)

        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_mention_count_for_job_source(self) -> None:
        """Handler executes UPDATE statement for job source."""
        match = MagicMock()
        match.canonical_id = "skill-123"
        mention = MagicMock()
        mention.source_type = SkillMentionSource.JOB

        message = MagicMock()
        message.match = match
        message.mention = mention

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        await handle_skill_mention_created(message, context)

        mock_db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_mention_count_for_profile_source(self) -> None:
        """Handler executes UPDATE statement for profile source."""
        match = MagicMock()
        match.canonical_id = "skill-123"
        mention = MagicMock()
        mention.source_type = SkillMentionSource.PROFILE

        message = MagicMock()
        message.match = match
        message.mention = mention

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        await handle_skill_mention_created(message, context)

        mock_db.execute.assert_called_once()


class TestHandleSkillNormalizationRequested:
    """Tests for handle_skill_normalization_requested handler."""

    def _msg(self, callback: str = "req.callback.v1") -> MagicMock:
        cmd = MagicMock()
        cmd.operation_id = str(uuid.uuid4())
        cmd.callback_topic = callback
        cmd.caller_context = b""
        cmd.attributes = {}
        m = MagicMock()
        m.raw_skills = ["python", "js"]
        m.canonical_skill_ids = []
        m.job_context = None
        m.metadata.correlation_id = "c-1"
        m.command = cmd
        return m

    @pytest.mark.asyncio
    async def test_all_matched_publishes_callback_directly(self) -> None:
        """All deterministic matches publish SkillNormalizationCallback without embedding."""
        p1 = MagicMock(all_matched=True, skill_results=[])
        br = MagicMock(canonical_skill_ids=["id-1"])
        _ready_gate = MagicMock(is_ready=True)
        with (
            patch(
                "skill_graph_service.events.handlers.run_deterministic_matching",
                new_callable=AsyncMock,
                return_value=p1,
            ) as run_raw,
            patch(
                "skill_graph_service.events.handlers.assemble_batch_normalization_result",
                new_callable=AsyncMock,
                return_value=br,
            ) as assemble_result,
            patch("skill_graph_service.events.handlers.kafka_client") as mk,
            patch("skill_graph_service.events.handlers.get_manifest") as mm,
            patch("skill_graph_service.events.handlers.get_qdrant_client"),
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=_ready_gate),
        ):
            mk.publish = AsyncMock()
            mm.return_value.get_entity_version.return_value = "v1"
            await handle_skill_normalization_requested(self._msg("req.callback.v1"), _make_context())
        mk.publish.assert_awaited_once()
        assert mk.publish.call_args.kwargs["topic"] == "req.callback.v1"
        run_raw.assert_awaited_once()
        assert run_raw.await_args is not None
        assert run_raw.await_args.kwargs["raw_skills"] == ["python", "js"]
        assemble_result.assert_awaited_once()
        assert assemble_result.await_args is not None
        assert assemble_result.await_args.kwargs["raw_skill_metadata"] == [
            ("python", int(SkillProficiencyLevel.UNSPECIFIED), False),
            ("js", int(SkillProficiencyLevel.UNSPECIFIED), False),
        ]

    @pytest.mark.asyncio
    async def test_raw_levels_produce_ordered_canonical_requirements(self) -> None:
        """Raw per-position levels reach callback requirements without raw-name fallback."""
        first, second = uuid.uuid4(), uuid.uuid4()
        msg = self._msg()
        msg.raw_skills = ["python", "sql", "python"]
        msg.raw_skills_with_levels = [
            RawSkillWithLevel(
                raw_skill="python",
                proficiency_level=SkillProficiencyLevel.BEGINNER,
                is_required=True,
            ),
            RawSkillWithLevel(
                raw_skill="sql",
                proficiency_level=SkillProficiencyLevel.EXPERT,
                is_required=False,
            ),
            RawSkillWithLevel(raw_skill="python"),
        ]
        det_result = DeterministicMatchResult(
            skill_results=[
                (
                    0,
                    "python",
                    SkillNormalizationResult(
                        canonical_id=first,
                        canonical_name="Canonical Python",
                        match_type=SkillMatchType.EXACT,
                        confidence=MatchConfidence.CONFIDENT,
                        similarity_score=0.91,
                    ),
                ),
                (
                    1,
                    "sql",
                    SkillNormalizationResult(
                        canonical_id=second,
                        canonical_name="Canonical SQL",
                        match_type=SkillMatchType.ALIAS,
                        confidence=MatchConfidence.AUTO_MATCH,
                        similarity_score=0.82,
                    ),
                ),
                (
                    2,
                    "python",
                    SkillNormalizationResult(
                        canonical_id=first,
                        canonical_name="Canonical Python",
                        match_type=SkillMatchType.EXACT,
                        confidence=MatchConfidence.CONFIDENT,
                        similarity_score=0.73,
                    ),
                ),
            ],
            unmatched=[],
            all_matched=True,
        )
        qdrant = AsyncMock()
        qdrant.retrieve_vectors = AsyncMock(
            return_value={
                skill_variant_point_id(first, EmbeddingVariant.LABEL): [1.0, 0.0],
                skill_variant_point_id(second, EmbeddingVariant.LABEL): [0.0, 1.0],
            }
        )
        gate = MagicMock(is_ready=True)
        with (
            patch(
                "skill_graph_service.events.handlers.run_deterministic_matching",
                new_callable=AsyncMock,
                return_value=det_result,
            ),
            patch("skill_graph_service.events.handlers.kafka_client") as kafka,
            patch("skill_graph_service.events.handlers.get_manifest") as manifest,
            patch("skill_graph_service.events.handlers.get_qdrant_client", return_value=qdrant),
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=gate),
        ):
            kafka.publish = AsyncMock()
            manifest.return_value.get_entity_version.return_value = "v1"
            manifest.return_value.get_collection_name.return_value = "skills_v1"
            await handle_skill_normalization_requested(msg, _make_context())

        assert kafka.publish.await_args is not None
        callback = kafka.publish.await_args.kwargs["message"]
        assert [
            (
                requirement.skill_id,
                requirement.skill_name,
                requirement.proficiency_level,
                requirement.is_required,
                requirement.extraction_confidence,
            )
            for requirement in callback.success.skill_requirements
        ] == [
            (str(first), "Canonical Python", SkillProficiencyLevel.BEGINNER, True, 0.91),
            (str(second), "Canonical SQL", SkillProficiencyLevel.EXPERT, False, 0.82),
            (str(first), "Canonical Python", SkillProficiencyLevel.UNSPECIFIED, False, 0.73),
        ]
        assert list(callback.success.canonical_skill_ids) == [str(first), str(second)]

    @pytest.mark.asyncio
    async def test_canonical_ids_bypass_raw_matching_and_publish_complete_result(self) -> None:
        """Canonical picker IDs resolve directly without label normalization."""
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        msg = self._msg()
        msg.raw_skills = []
        msg.canonical_skill_ids = ids
        batch = MagicMock(
            canonical_skill_ids=ids,
            aggregated_embedding=_dense_embedding([0.6, 0.8]),
            results=[MagicMock(), MagicMock()],
            requires_clarification=False,
            clarifications=[],
            skill_requirements=[MagicMock(), MagicMock()],
        )
        gate = MagicMock(is_ready=True)
        with (
            patch(
                "skill_graph_service.events.handlers.resolve_canonical_skill_ids",
                new_callable=AsyncMock,
                return_value=batch,
            ) as resolve,
            patch(
                "skill_graph_service.events.handlers.run_deterministic_matching", new_callable=AsyncMock
            ) as raw_match,
            patch("skill_graph_service.events.handlers.get_normalization_embedding_publisher") as embed_publisher,
            patch("skill_graph_service.events.handlers.kafka_client") as kafka,
            patch("skill_graph_service.events.handlers.get_manifest") as manifest,
            patch("skill_graph_service.events.handlers.get_qdrant_client") as get_qdrant,
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=gate),
        ):
            kafka.publish = AsyncMock()
            manifest.return_value.get_entity_version.return_value = "v1"
            context = _make_context(session_factory=MagicMock())
            await handle_skill_normalization_requested(msg, context)

        resolve.assert_awaited_once_with(ids, context.require_session_factory(), "v1", get_qdrant.return_value)
        raw_match.assert_not_awaited()
        embed_publisher.assert_not_called()
        assert kafka.publish.await_args is not None
        callback = kafka.publish.await_args.kwargs["message"]
        assert list(callback.success.canonical_skill_ids) == ids
        assert list(callback.success.skills_embedding.dense.values) == pytest.approx([0.6, 0.8])
        assert len(callback.success.results) == 2
        assert not callback.error

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("raw", "canonical"), [(["Python"], ["550e8400-e29b-41d4-a716-446655440000"]), ([], [])])
    async def test_invalid_input_modes_fail_closed(self, raw: list[str], canonical: list[str]) -> None:
        """Mixed and empty modes publish a non-retryable validation callback."""
        msg = self._msg()
        msg.raw_skills = raw
        msg.canonical_skill_ids = canonical
        with (
            patch("skill_graph_service.events.handlers.kafka_client") as kafka,
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=MagicMock(is_ready=True)),
            patch(
                "skill_graph_service.events.handlers.run_deterministic_matching", new_callable=AsyncMock
            ) as raw_match,
        ):
            kafka.publish = AsyncMock()
            await handle_skill_normalization_requested(msg, _make_context())

        raw_match.assert_not_awaited()
        assert kafka.publish.await_args is not None
        callback = kafka.publish.await_args.kwargs["message"]
        assert callback.error
        assert callback.error.retryable is False

    @pytest.mark.asyncio
    async def test_missing_canonical_id_fails_closed(self) -> None:
        """A missing picker ID is reported rather than silently omitted."""
        from nohiki_common_exceptions import ValidationError

        msg = self._msg()
        msg.raw_skills = []
        msg.canonical_skill_ids = [str(uuid.uuid4())]
        with (
            patch(
                "skill_graph_service.events.handlers.resolve_canonical_skill_ids",
                new_callable=AsyncMock,
                side_effect=ValidationError("missing canonical skill"),
            ),
            patch("skill_graph_service.events.handlers.kafka_client") as kafka,
            patch("skill_graph_service.events.handlers.get_manifest") as manifest,
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=MagicMock(is_ready=True)),
        ):
            kafka.publish = AsyncMock()
            manifest.return_value.get_entity_version.return_value = "v1"
            await handle_skill_normalization_requested(msg, _make_context())

        assert kafka.publish.await_args is not None
        callback = kafka.publish.await_args.kwargs["message"]
        assert callback.error
        assert callback.error.retryable is False

    @pytest.mark.asyncio
    async def test_unmatched_defers_to_batch_embedding(self) -> None:
        """Unmatched skills trigger request_batch_embedding; no immediate callback."""
        p1 = MagicMock(all_matched=False, skill_results=[(0, "python", MagicMock())], unmatched=[(1, "rare")])
        pub = AsyncMock()
        pub.request_batch_embedding = AsyncMock(return_value="op-1")
        _ready_gate = MagicMock(is_ready=True)
        with (
            patch(
                "skill_graph_service.events.handlers.run_deterministic_matching",
                new_callable=AsyncMock,
                return_value=p1,
            ),
            patch("skill_graph_service.events.handlers.get_normalization_embedding_publisher", return_value=pub),
            patch("skill_graph_service.events.handlers.serialize_skill_result", return_value={}),
            patch("skill_graph_service.events.handlers.NormalizationEmbeddingState") as ms,
            patch("skill_graph_service.events.handlers.kafka_client") as mk,
            patch("skill_graph_service.events.handlers.get_manifest") as mm,
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=_ready_gate),
        ):
            mk.publish = AsyncMock()
            mm.return_value.get_entity_version.return_value = "v1"
            ms.return_value.to_bytes.return_value = b"s"
            await handle_skill_normalization_requested(self._msg(), _make_context())
        pub.request_batch_embedding.assert_awaited_once()
        mk.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_industry_hint_stripped_and_lowercased(self) -> None:
        """Industry hint from job_context is stripped and lowercased."""
        msg = self._msg()
        msg.job_context = MagicMock(industry="  Software Engineering  ")
        msg.raw_skills = ["python"]
        p1 = MagicMock(all_matched=True, skill_results=[])
        br = MagicMock(canonical_skill_ids=[])
        _ready_gate = MagicMock(is_ready=True)
        with (
            patch(
                "skill_graph_service.events.handlers.run_deterministic_matching",
                new_callable=AsyncMock,
                return_value=p1,
            ) as run,
            patch(
                "skill_graph_service.events.handlers.assemble_batch_normalization_result",
                new_callable=AsyncMock,
                return_value=br,
            ),
            patch("skill_graph_service.events.handlers.kafka_client") as mk,
            patch("skill_graph_service.events.handlers.get_manifest") as mm,
            patch("skill_graph_service.events.handlers.get_qdrant_client"),
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=_ready_gate),
        ):
            mk.publish = AsyncMock()
            mm.return_value.get_entity_version.return_value = "v1"
            await handle_skill_normalization_requested(msg, _make_context())
        assert run.call_args.kwargs["context_hint"] == "software engineering"

    @pytest.mark.asyncio
    async def test_raises_when_readiness_gate_not_ready(self) -> None:
        """Normalization raises DataNotAvailableError when skill graph is not ready."""
        _not_ready_gate = MagicMock(is_ready=False)
        with (
            patch("skill_graph_service.events.handlers.get_readiness_gate", return_value=_not_ready_gate),
            pytest.raises(DataNotAvailableError, match="SkillEmbeddingCollection"),
        ):
            await handle_skill_normalization_requested(self._msg(), _make_context())


class TestHandleNormalizationEmbeddingCallback:
    """Tests for handle_normalization_embedding_callback handler."""

    def _state(self, topic: str = "req.cb.v1") -> MagicMock:
        s = MagicMock()
        s.requester_operation_id = str(uuid.uuid4())
        s.requester_callback_topic = topic
        s.requester_caller_context_b64 = base64.b64encode(b"ctx").decode("ascii")
        s.requester_attributes = {}
        s.raw_skills = ["python"]
        s.collection_version = "v1"
        return s

    def _cb_message(self, *, success: bool = False, error: bool = False) -> BatchEmbeddingCallback:
        cb = CallbackHeader(operation_id=str(uuid.uuid4()), caller_context=b"mock")
        if success:
            return BatchEmbeddingCallback(callback=cb, success=BatchEmbeddingResult(results=[]))
        if error:
            return BatchEmbeddingCallback(
                callback=cb, error=ErrorInfo(error_code="ERR", error_message="fail", retryable=False)
            )
        return BatchEmbeddingCallback(callback=cb)

    @pytest.mark.asyncio
    async def test_success_publishes_to_requester_topic(self) -> None:
        """Success assembles result and publishes SkillNormalizationCallback to requester."""
        state = self._state("req.cb.v1")
        br = MagicMock(
            canonical_skill_ids=["id-1"],
            aggregated_embedding=None,
            results=[],
            requires_clarification=False,
            clarifications=[],
        )
        with (
            patch("skill_graph_service.events.handlers.NormalizationEmbeddingState") as ms,
            patch(
                "skill_graph_service.events.handlers.deserialize_deterministic_match_result",
                return_value=MagicMock(unmatched=[]),
            ),
            patch(
                "skill_graph_service.events.handlers.run_semantic_qdrant_search",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "skill_graph_service.events.handlers.assemble_batch_normalization_result",
                new_callable=AsyncMock,
                return_value=br,
            ),
            patch("skill_graph_service.events.handlers.kafka_client") as mk,
            patch("skill_graph_service.events.handlers.get_qdrant_client"),
        ):
            ms.from_bytes.return_value = state
            mk.publish = AsyncMock()
            await handle_normalization_embedding_callback(self._cb_message(success=True), _make_context())
        mk.publish.assert_awaited_once()
        assert mk.publish.call_args.kwargs["topic"] == "req.cb.v1"

    @pytest.mark.asyncio
    async def test_error_propagates_to_requester(self) -> None:
        """Embedding failure publishes an error callback to the original requester."""
        state = self._state("req.cb.v1")
        with (
            patch("skill_graph_service.events.handlers.NormalizationEmbeddingState") as ms,
            patch("skill_graph_service.events.handlers.kafka_client") as mk,
        ):
            ms.from_bytes.return_value = state
            mk.publish = AsyncMock()
            await handle_normalization_embedding_callback(self._cb_message(error=True), _make_context())
        mk.publish.assert_awaited_once()
        assert mk.publish.call_args.kwargs["topic"] == "req.cb.v1"

    @pytest.mark.asyncio
    async def test_empty_raises_validation_error(self) -> None:
        """No success or error field raises ValidationError."""
        from nohiki_common_exceptions import ValidationError

        state = self._state()
        with patch("skill_graph_service.events.handlers.NormalizationEmbeddingState") as ms:
            ms.from_bytes.return_value = state
            with pytest.raises(ValidationError):
                await handle_normalization_embedding_callback(self._cb_message(), _make_context())


class TestHandleAliasLearned:
    """Tests for handle_alias_learned handler."""

    @pytest.mark.asyncio
    async def test_upserts_alias_to_database(self) -> None:
        """Handler delegates to upsert_alias with injected session."""
        message = MagicMock()
        message.alias_text = "py"
        message.canonical_skill_id = "550e8400-e29b-41d4-a716-446655440000"
        message.source = "USER_FEEDBACK"
        message.context_hint = "programming"
        message.confidence = 0.95
        message.source_job_id = "550e8400-e29b-41d4-a716-446655440001"

        mock_db = create_mock_session()
        context = _make_context(db_session=mock_db)

        with patch(
            "skill_graph_service.events.handlers.upsert_alias",
            new_callable=AsyncMock,
        ) as mock_upsert:
            await handle_alias_learned(message, context)

            mock_upsert.assert_awaited_once()
            call_args = mock_upsert.call_args
            assert call_args[0][0] is mock_db


class TestHandleSkillProposed:
    """Tests for handle_skill_proposed handler."""

    def _proposal_message(self, *, source_job_id: str | None = None, embedding: None = None) -> MagicMock:
        proposal = MagicMock()
        proposal.canonical_name = "rust"
        proposal.display_name = "Rust"
        proposal.suggested_aliases = ["rs"]
        proposal.category = None
        proposal.description = "Systems language"
        m = MagicMock()
        m.proposal = proposal
        m.source = "JOB_ANALYSIS"
        m.source_job_id = source_job_id
        m.embedding = embedding
        return m

    @pytest.mark.asyncio
    async def test_delegates_to_process_proposal(self) -> None:
        """Delegates to process_skill_proposal with session and qdrant client."""
        mock_db = create_mock_session()
        mock_qdrant = MagicMock()
        with (
            patch("skill_graph_service.events.handlers.get_qdrant_client", return_value=mock_qdrant),
            patch(
                "skill_graph_service.events.handlers.process_skill_proposal",
                new_callable=AsyncMock,
                return_value=("pending_review", "created", None),
            ) as mock_process,
        ):
            await handle_skill_proposed(self._proposal_message(), _make_context(db_session=mock_db))
        mock_process.assert_awaited_once()
        assert mock_process.call_args[0][0] is mock_db
        assert mock_process.call_args[0][1] is mock_qdrant

    @pytest.mark.asyncio
    async def test_auto_approved_triggers_batch_embedding(self) -> None:
        """Auto-approved proposal publishes triple embedding via EmbeddingPublisher."""
        skill_id = uuid.uuid4()
        pub = AsyncMock()
        pub.request_batch_embedding = AsyncMock(return_value="op-1")
        with (
            patch("skill_graph_service.events.handlers.get_qdrant_client"),
            patch(
                "skill_graph_service.events.handlers.process_skill_proposal",
                new_callable=AsyncMock,
                return_value=("auto_approved", "created", skill_id),
            ),
            patch("skill_graph_service.events.handlers.get_batch_embedding_publisher", return_value=pub),
            patch("skill_graph_service.events.handlers.get_manifest") as mm,
        ):
            mm.return_value.get_entity_version.return_value = "v1"
            await handle_skill_proposed(self._proposal_message(), _make_context(db_session=create_mock_session()))
        pub.request_batch_embedding.assert_awaited_once()
        assert pub.request_batch_embedding.call_args.kwargs["entity_type"] == EntityType.SKILL

    @pytest.mark.asyncio
    async def test_pending_review_skips_batch_embedding(self) -> None:
        """Pending-review proposal does not publish embedding."""
        pub = AsyncMock()
        pub.request_batch_embedding = AsyncMock()
        with (
            patch("skill_graph_service.events.handlers.get_qdrant_client"),
            patch(
                "skill_graph_service.events.handlers.process_skill_proposal",
                new_callable=AsyncMock,
                return_value=("pending_review", "created", None),
            ),
            patch("skill_graph_service.events.handlers.get_batch_embedding_publisher", return_value=pub),
        ):
            await handle_skill_proposed(self._proposal_message(), _make_context(db_session=create_mock_session()))
        pub.request_batch_embedding.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_replayed_proposal_has_no_side_effects(self) -> None:
        """A previously claimed proposal cannot mutate state or republish embeddings."""
        with (
            patch(
                "skill_graph_service.events.handlers._claim_event_once",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("skill_graph_service.events.handlers.get_qdrant_client") as get_qdrant,
            patch(
                "skill_graph_service.events.handlers.process_skill_proposal",
                new_callable=AsyncMock,
            ) as process_proposal,
        ):
            await handle_skill_proposed(self._proposal_message(), _make_context(db_session=create_mock_session()))

        get_qdrant.assert_not_called()
        process_proposal.assert_not_awaited()


class TestGetEmbeddedSkillIds:
    """Tests for bootstrap embedding completeness detection."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "present_variants",
        [
            (EmbeddingVariant.LABEL,),
            (EmbeddingVariant.LABEL, EmbeddingVariant.DESCRIPTION),
        ],
        ids=["one-variant", "two-variants"],
    )
    async def test_incomplete_skill_is_not_treated_as_embedded(
        self,
        present_variants: tuple[EmbeddingVariant, ...],
    ) -> None:
        """One or two stored variants still require bootstrap embedding."""
        skill_id = uuid.uuid4()
        records = [
            MagicMock(
                id=skill_variant_point_id(skill_id, variant),
                payload={"entity_id": str(skill_id)},
            )
            for variant in present_variants
        ]
        qdrant = MagicMock()
        qdrant.raw_client.scroll = AsyncMock(return_value=(records, None))

        assert await _get_embedded_skill_ids(qdrant, "skills_v1") == set()
        qdrant.raw_client.scroll.assert_awaited_once_with(
            collection_name="skills_v1",
            limit=1000,
            offset=None,
            with_payload=["entity_id"],
            with_vectors=False,
        )

    @pytest.mark.asyncio
    async def test_skill_is_embedded_only_after_all_three_variants_exist(self) -> None:
        """All three stored variants make bootstrap skip the skill."""
        skill_id = uuid.uuid4()
        records = [
            MagicMock(
                id=skill_variant_point_id(skill_id, variant),
                payload={"entity_id": str(skill_id)},
            )
            for variant in EmbeddingVariant
        ]
        qdrant = MagicMock()
        qdrant.raw_client.scroll = AsyncMock(return_value=(records, None))

        assert await _get_embedded_skill_ids(qdrant, "skills_v1") == {skill_id}


class TestHandleSkillGraphSeeded:
    """Tests for handle_skill_graph_seeded handler."""

    def _skill(self, label: str) -> MagicMock:
        r = MagicMock()
        r.id = uuid.uuid4()
        r.preferred_label = label
        r.description = None
        r.alt_labels = []
        return r

    @pytest.mark.asyncio
    async def test_skips_already_embedded_skills(self) -> None:
        """Replay bootstrap embeds only skills absent from Qdrant."""
        skills = [self._skill(f"s{i}") for i in range(4)]
        msg = MagicMock(spec=SkillGraphSeeded, source_version="1.0", skills_seeded=4)
        pub = AsyncMock()
        pub.request_batch_embedding = AsyncMock(return_value="op-1")
        bootstrap_result = MagicMock(total_published=4, batch_count=1)
        with (
            patch(
                "skill_graph_service.events.handlers.publish_skill_created_events_for_bootstrap",
                new_callable=AsyncMock,
                return_value=bootstrap_result,
            ),
            patch(
                "skill_graph_service.events.handlers.fetch_all_skills_for_embedding",
                new_callable=AsyncMock,
                return_value=skills,
            ),
            patch(
                "skill_graph_service.events.handlers._get_embedded_skill_ids",
                new_callable=AsyncMock,
                return_value={skills[0].id},
            ),
            patch("skill_graph_service.events.handlers.get_batch_embedding_publisher", return_value=pub),
            patch("skill_graph_service.events.handlers.get_manifest") as mm,
        ):
            mm.return_value.get_entity_version.return_value = "v1"
            await handle_skill_graph_seeded(msg, _make_context(db_session=create_mock_session()))

        pub.request_batch_embedding.assert_awaited_once()
        items = pub.request_batch_embedding.await_args_list[0].kwargs["items"]
        assert len(items) == 9
        assert {item.entity_id for item in items} == {str(skill.id) for skill in skills[1:]}

    @pytest.mark.asyncio
    async def test_thirty_four_skills_pack_into_two_requests_without_variant_loss(self) -> None:
        """Bootstrap packs whole skills under the 100-item admission ceiling."""
        skills = [self._skill(f"s{i}") for i in range(34)]
        msg = MagicMock(spec=SkillGraphSeeded, source_version="1.0", skills_seeded=34)
        pub = AsyncMock()
        pub.request_batch_embedding = AsyncMock(side_effect=["op-1", "op-2"])
        bootstrap_result = MagicMock(total_published=34, batch_count=1)
        with (
            patch(
                "skill_graph_service.events.handlers.publish_skill_created_events_for_bootstrap",
                new_callable=AsyncMock,
                return_value=bootstrap_result,
            ),
            patch(
                "skill_graph_service.events.handlers.fetch_all_skills_for_embedding",
                new_callable=AsyncMock,
                return_value=skills,
            ),
            patch(
                "skill_graph_service.events.handlers._get_embedded_skill_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("skill_graph_service.events.handlers.get_batch_embedding_publisher", return_value=pub),
            patch("skill_graph_service.events.handlers.get_manifest") as mm,
        ):
            mm.return_value.get_entity_version.return_value = "v1"
            await handle_skill_graph_seeded(msg, _make_context(db_session=create_mock_session()))

        item_lists = [call.kwargs["items"] for call in pub.request_batch_embedding.await_args_list]
        assert [len(items) for items in item_lists] == [99, 3]
        assert all(len(items) <= 100 for items in item_lists)

        actual_variants = [(item.entity_id, item.item_attributes["variant"]) for items in item_lists for item in items]
        expected_variants = [(str(skill.id), variant.value) for skill in skills for variant in EmbeddingVariant]
        assert sorted(actual_variants) == sorted(expected_variants)
        assert len(actual_variants) == len(set(actual_variants)) == 102

    @pytest.mark.asyncio
    async def test_empty_skill_list_makes_no_publish_calls(self) -> None:
        """No skills means no batch embedding published."""
        msg = MagicMock(spec=SkillGraphSeeded, source_version="1.0", skills_seeded=0)
        pub = AsyncMock()
        pub.request_batch_embedding = AsyncMock()
        bootstrap_result = MagicMock(total_published=0, batch_count=0)
        with (
            patch(
                "skill_graph_service.events.handlers.publish_skill_created_events_for_bootstrap",
                new_callable=AsyncMock,
                return_value=bootstrap_result,
            ),
            patch(
                "skill_graph_service.events.handlers.fetch_all_skills_for_embedding",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "skill_graph_service.events.handlers._get_embedded_skill_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ),
            patch("skill_graph_service.events.handlers.get_batch_embedding_publisher", return_value=pub),
            patch("skill_graph_service.events.handlers.get_manifest") as mm,
        ):
            mm.return_value.get_entity_version.return_value = "v1"
            await handle_skill_graph_seeded(msg, _make_context(db_session=create_mock_session()))
        pub.request_batch_embedding.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_duplicate_event_returns_before_qdrant_scan_or_publication(self) -> None:
        """A redelivered seed event cannot publish a second bootstrap batch."""
        skill = self._skill("python")
        msg = MagicMock(source_version="1.0", skills_seeded=1)
        msg.metadata.event_id = "seed-event-1"
        publisher = AsyncMock()
        publisher.request_batch_embedding = AsyncMock(return_value="op-1")

        with (
            patch(
                "skill_graph_service.events.handlers.check_and_mark_processed",
                new_callable=AsyncMock,
                side_effect=[True, False],
            ),
            patch(
                "skill_graph_service.events.handlers.publish_skill_created_events_for_bootstrap",
                new_callable=AsyncMock,
                return_value=MagicMock(total_published=1, batch_count=1),
            ),
            patch(
                "skill_graph_service.events.handlers.fetch_all_skills_for_embedding",
                new_callable=AsyncMock,
                return_value=[skill],
            ),
            patch(
                "skill_graph_service.events.handlers._get_embedded_skill_ids",
                new_callable=AsyncMock,
                return_value=set(),
            ) as scan,
            patch("skill_graph_service.events.handlers.get_batch_embedding_publisher", return_value=publisher),
            patch("skill_graph_service.events.handlers.get_manifest") as manifest,
        ):
            manifest.return_value.get_collection_name.return_value = "skills_v1"
            context = _make_context(db_session=create_mock_session())
            await handle_skill_graph_seeded(msg, context)
            await handle_skill_graph_seeded(msg, context)

        scan.assert_awaited_once()
        publisher.request_batch_embedding.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_distinct_event_ids_remain_processable(self) -> None:
        """A later seed event can rescan Qdrant and repair missing variants."""
        skill = self._skill("python")
        first = MagicMock(source_version="1.0", skills_seeded=1)
        first.metadata.event_id = "seed-event-1"
        second = MagicMock(source_version="1.1", skills_seeded=1)
        second.metadata.event_id = "seed-event-2"
        publisher = AsyncMock()
        publisher.request_batch_embedding = AsyncMock(side_effect=["op-1", "op-2"])

        with (
            patch(
                "skill_graph_service.events.handlers.check_and_mark_processed",
                new_callable=AsyncMock,
                side_effect=[True, True],
            ),
            patch(
                "skill_graph_service.events.handlers.publish_skill_created_events_for_bootstrap",
                new_callable=AsyncMock,
                return_value=MagicMock(total_published=1, batch_count=1),
            ),
            patch(
                "skill_graph_service.events.handlers.fetch_all_skills_for_embedding",
                new_callable=AsyncMock,
                return_value=[skill],
            ),
            patch(
                "skill_graph_service.events.handlers._get_embedded_skill_ids",
                new_callable=AsyncMock,
                side_effect=[set(), set()],
            ) as scan,
            patch("skill_graph_service.events.handlers.get_batch_embedding_publisher", return_value=publisher),
            patch("skill_graph_service.events.handlers.get_manifest") as manifest,
        ):
            manifest.return_value.get_collection_name.return_value = "skills_v1"
            context = _make_context(db_session=create_mock_session())
            await handle_skill_graph_seeded(first, context)
            await handle_skill_graph_seeded(second, context)

        assert scan.await_count == 2
        assert publisher.request_batch_embedding.await_count == 2


class TestStartEventConsumer:
    """Tests for start_event_consumer function."""

    def test_starts_kafka_consumers(self) -> None:
        """start_event_consumer delegates to kafka_client.start_consumers."""
        with (
            patch("skill_graph_service.events.handlers.kafka_client") as mock_kafka,
            patch("skill_graph_service.events.handlers.logger") as mock_logger,
            patch("skill_graph_service.events.handlers.settings") as mock_settings,
        ):
            mock_kafka.start_consumers = MagicMock()
            mock_settings.service_name = "skill-graph-service"

            start_event_consumer()

            mock_kafka.start_consumers.assert_called_once()
            mock_logger.info.assert_called_once()
