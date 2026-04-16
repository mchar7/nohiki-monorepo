"""Unit tests for DB saga callback handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from job_ingest_enrichment_service.db.models import EnrichmentEmbeddingSaga
from job_ingest_enrichment_service.events.publishers import EnrichmentPublishContext
from job_ingest_enrichment_service.services.enrichment_context import EnrichmentContext
from nohiki.common.v1 import ErrorInfo
from nohiki.skill.v1 import (
    JobSkillRequirement,
    SkillNormalizationResult,
    SkillNormalizationResultDetail,
    SkillProficiencyLevel,
)
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext


def _make_context(*, db_session: AsyncMock | None = None) -> MessageContext:
    """Build a MessageContext with optional injected db_session."""
    return MessageContext(
        topic="test-topic",
        partition=0,
        offset=0,
        key="test-key",
        timestamp=0,
        headers={},
        db_session=db_session,
    )


@pytest.fixture
def enrichment_context() -> EnrichmentContext:
    """Create a valid EnrichmentContext for testing."""
    from nohiki.common.v1 import JobBoardSource
    from nohiki.job.ingest.v1 import DiscoveredListing

    discovered = DiscoveredListing(
        listing_url="https://example.com/job/123",
        source=JobBoardSource.LINKEDIN,
        external_id="ext-123",
        title="Software Engineer",
        company_name="Test Corp",
        description="Build amazing software",
        raw_skills=["Python", "Go"],
    )
    return EnrichmentContext(
        listing_id=str(uuid4()),
        listing_url="https://example.com/job/123",
        correlation_id=str(uuid4()),
        discovered_json=discovered.to_json(),
        cleaned_title="Software Engineer",
        cleaned_company="Test Corp",
        work_arrangement="HYBRID",
        employment_term="FULL_TIME",
        seniority_level="MID",
        language="en",
        min_experience_years=3,
        min_experience_source="inferred",
        min_experience_confidence=70,
        max_experience_years=5,
        max_experience_source="inferred",
        max_experience_confidence=70,
        compensation_min_amount=80_000,
        compensation_min_source="llm_inferred",
        compensation_min_confidence=70,
        compensation_max_amount=120_000,
        compensation_max_source="llm_inferred",
        compensation_max_confidence=70,
        compensation_currency="USD",
        compensation_period="ANNUALLY",
        compensation_reasoning="Based on market data",
        location_city="San Francisco",
        location_state="CA",
        location_country_code="USA",
    )


def _make_saga_json(enrichment_ctx: EnrichmentContext) -> str:
    """Build the JSON blob stored inside an EnrichmentEmbeddingSaga."""
    import dataclasses

    return json.dumps(
        {
            "enrichment_ctx": dataclasses.asdict(enrichment_ctx),
            "skill_requirements": [],
        }
    )


class TestHandleSkillNormalizationCallback:
    """Tests for handle_skill_normalization_callback."""

    @pytest.mark.asyncio
    async def test_logs_and_returns_on_error(self) -> None:
        """Returns early when callback carries an error."""
        from job_ingest_enrichment_service.events.callbacks import handle_skill_normalization_callback

        message = MagicMock()
        message.error = ErrorInfo(error_code="TIMEOUT", error_message="normalization failed")
        message.callback.operation_id = "op-1"
        await handle_skill_normalization_callback(message, _make_context())

    @pytest.mark.asyncio
    async def test_raises_validation_error_on_missing_success(self) -> None:
        """Raises ValidationError when success is None."""
        from job_ingest_enrichment_service.events.callbacks import handle_skill_normalization_callback
        from nohiki_common_exceptions import ValidationError

        message = MagicMock()
        message.error = None
        message.success = None
        message.callback.operation_id = "op-1"
        message.callback.caller_context = b"{}"

        with pytest.raises(ValidationError):
            await handle_skill_normalization_callback(message, _make_context())

    @pytest.mark.asyncio
    async def test_routes_to_clarification_branch(self, enrichment_context: EnrichmentContext) -> None:
        """Delegates to _handle_skill_clarification when clarification is needed."""
        from job_ingest_enrichment_service.events.callbacks import handle_skill_normalization_callback

        message = MagicMock()
        message.error = None
        message.success.requires_clarification = True
        message.success.clarifications = [MagicMock()]
        message.success.skill_requirements = []
        message.callback.operation_id = "op-1"
        message.callback.caller_context = enrichment_context.to_bytes()

        with patch(
            "job_ingest_enrichment_service.events.callbacks._handle_skill_clarification",
            new_callable=AsyncMock,
        ) as mock_clarify:
            await handle_skill_normalization_callback(message, _make_context())

        mock_clarify.assert_called_once()

    @pytest.mark.asyncio
    async def test_publishes_immediately_when_no_embeddable_text(self) -> None:
        """Publishes enrichment immediately when cleaned text is empty."""
        from job_ingest_enrichment_service.events.callbacks import handle_skill_normalization_callback
        from nohiki.common.v1 import JobBoardSource
        from nohiki.job.ingest.v1 import DiscoveredListing

        discovered = DiscoveredListing(
            listing_url="https://example.com/j/1",
            source=JobBoardSource.LINKEDIN,
            title="T",
            company_name="C",
            description="",
        )
        empty_ctx = EnrichmentContext(
            listing_id=str(uuid4()),
            listing_url="https://example.com/j/1",
            correlation_id=str(uuid4()),
            discovered_json=discovered.to_json(),
            cleaned_title="",
            cleaned_company="",
            work_arrangement="HYBRID",
            employment_term="FULL_TIME",
            seniority_level="MID",
            language="en",
            min_experience_years=None,
            min_experience_source=None,
            min_experience_confidence=None,
            max_experience_years=None,
            max_experience_source=None,
            max_experience_confidence=None,
            compensation_min_amount=0,
            compensation_min_source="llm_inferred",
            compensation_min_confidence=None,
            compensation_max_amount=0,
            compensation_max_source="llm_inferred",
            compensation_max_confidence=None,
            compensation_currency="USD",
            compensation_period="ANNUALLY",
            compensation_reasoning="",
            location_city=None,
            location_state=None,
            location_country_code="USA",
        )
        message = MagicMock()
        message.error = None
        message.success.requires_clarification = False
        message.success.clarifications = []
        message.success.skill_requirements = []
        message.success.results = []
        message.success.skills_embedding = None
        message.callback.caller_context = empty_ctx.to_bytes()

        with patch(
            "job_ingest_enrichment_service.events.callbacks._publish_enrichment_completed",
            new_callable=AsyncMock,
        ) as mock_pub:
            await handle_skill_normalization_callback(message, _make_context())

        mock_pub.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_saga_and_requests_three_embeddings(self, enrichment_context: EnrichmentContext) -> None:
        """Creates saga and fires retrieval, title, and skills embedding requests."""
        from job_ingest_enrichment_service.events.callbacks import handle_skill_normalization_callback

        skill_req = JobSkillRequirement(skill_name="Python", is_required=True)
        mock_saga = MagicMock()
        mock_saga.id = uuid4()
        mock_db = create_mock_session()
        mock_publisher = AsyncMock()

        message = MagicMock()
        message.error = None
        message.success.requires_clarification = False
        message.success.clarifications = []
        message.success.skill_requirements = [skill_req]
        message.success.results = []
        message.callback.caller_context = enrichment_context.to_bytes()

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks.get_embedding_publisher",
                return_value=mock_publisher,
            ),
        ):
            mock_repo.create = AsyncMock(return_value=mock_saga)
            await handle_skill_normalization_callback(message, _make_context(db_session=mock_db))

        mock_repo.create.assert_awaited_once()
        assert mock_publisher.request_embedding.await_count == 3
        # Verify each embedding type is requested exactly once via the
        # ``embedding_type`` discriminator carried in CommandContext.attributes.
        types_seen = [
            call.kwargs["context"].attributes["embedding_type"]
            for call in mock_publisher.request_embedding.call_args_list
        ]
        assert sorted(types_seen) == ["retrieval", "skills", "title"]

    @pytest.mark.asyncio
    async def test_saga_marked_failed_when_embedding_request_raises(
        self, enrichment_context: EnrichmentContext
    ) -> None:
        """If a request_embedding call inside the TaskGroup raises, the saga must be FAILED, not PENDING."""
        from job_ingest_enrichment_service.events.callbacks import _create_embedding_saga_and_request

        mock_saga = MagicMock()
        mock_saga.id = uuid4()
        mock_db = create_mock_session()
        mock_db.commit = AsyncMock()

        mock_publisher = MagicMock()
        # The first call to request_embedding raises; TaskGroup wraps it in an ExceptionGroup.
        mock_publisher.request_embedding = AsyncMock(side_effect=RuntimeError("ml-gateway down"))

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks.get_embedding_publisher",
                return_value=mock_publisher,
            ),
        ):
            mock_repo.create = AsyncMock(return_value=mock_saga)
            mock_repo.fail = AsyncMock()
            with pytest.raises(BaseExceptionGroup):
                await _create_embedding_saga_and_request(
                    context=_make_context(db_session=mock_db),
                    enrichment_ctx=enrichment_context,
                    skill_requirements=[JobSkillRequirement(skill_name="Python", is_required=True)],
                )

        mock_repo.fail.assert_awaited_once()
        # The fail call must reference the saga id so the row transitions out of PENDING.
        fail_call = mock_repo.fail.await_args
        assert fail_call is not None
        assert fail_call.args[1] == mock_saga.id


class TestGetSkillRequirements:
    """Tests for _get_skill_requirements helper."""

    def test_returns_skill_requirements_when_present(self) -> None:
        """Returns skill_requirements list when non-empty."""
        from job_ingest_enrichment_service.events.callbacks import _get_skill_requirements

        skill_req = JobSkillRequirement(skill_name="Python", is_required=True)
        result_obj = SkillNormalizationResult(skill_requirements=[skill_req], results=[])
        out = _get_skill_requirements(result_obj)
        assert len(out) == 1
        assert out[0].skill_name == "Python"

    def test_falls_back_to_results_when_no_requirements(self) -> None:
        """Falls back to raw results when skill_requirements is empty."""
        from job_ingest_enrichment_service.events.callbacks import _get_skill_requirements

        result_obj = SkillNormalizationResult(
            skill_requirements=[],
            results=[
                SkillNormalizationResultDetail(raw_skill="Python"),
                SkillNormalizationResultDetail(raw_skill="Go"),
            ],
        )
        out = _get_skill_requirements(result_obj)
        assert len(out) == 2
        assert out[0].skill_name == "Python"
        assert out[1].skill_name == "Go"

    def test_returns_empty_when_neither_present(self) -> None:
        """Returns empty list when both skill_requirements and results are empty."""
        from job_ingest_enrichment_service.events.callbacks import _get_skill_requirements

        result_obj = SkillNormalizationResult(skill_requirements=[], results=[])
        assert _get_skill_requirements(result_obj) == []


class TestSkillReqSerialization:
    """Tests for JobSkillRequirement native to_dict / from_dict roundtrip."""

    def test_roundtrip(self) -> None:
        """Native serialization roundtrip preserves all fields."""
        original = JobSkillRequirement(
            skill_id="skill-42",
            skill_name="Python",
            proficiency_level=SkillProficiencyLevel.INTERMEDIATE,
            is_required=True,
        )
        d = original.to_dict()
        recovered = JobSkillRequirement.from_dict(d)
        assert recovered.skill_id == original.skill_id
        assert recovered.skill_name == original.skill_name
        assert recovered.proficiency_level == original.proficiency_level
        assert recovered.is_required == original.is_required

    def test_from_dict_handles_missing_fields(self) -> None:
        """from_dict defaults gracefully when optional fields absent."""
        result = JobSkillRequirement.from_dict({"skill_name": "Go", "is_required": True})
        assert result.skill_name == "Go"
        assert result.is_required is True


class TestHandleEmbeddingCallback:
    """Tests for handle_embedding_callback."""

    def _make_callback_message(
        self,
        *,
        saga_id: str | None = None,
        embedding_type: str = "retrieval",
        has_error: bool = False,
        has_success: bool = True,
    ) -> MagicMock:
        """Build a mock EmbeddingCallback message."""
        msg = MagicMock()
        sid = saga_id or str(uuid4())
        msg.callback.operation_id = "op-emb-1"
        msg.callback.caller_context = json.dumps({"saga_id": sid}).encode("utf-8")
        msg.callback.attributes = {"embedding_type": embedding_type}
        msg.error = ErrorInfo(error_code="FAIL", error_message="err") if has_error else None
        msg.success = b"\x00\x01\x02" if has_success and not has_error else None
        return msg

    @pytest.mark.asyncio
    async def test_fails_saga_on_error(self) -> None:
        """Calls _saga_repo.fail and returns when error is present."""
        from job_ingest_enrichment_service.events.callbacks import handle_embedding_callback

        mock_db = create_mock_session()
        message = self._make_callback_message(has_error=True)

        with patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo:
            mock_repo.fail = AsyncMock()
            await handle_embedding_callback(message, _make_context(db_session=mock_db))

        mock_repo.fail.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_early_on_empty_success(self) -> None:
        """Returns early when success payload is None."""
        from job_ingest_enrichment_service.events.callbacks import handle_embedding_callback

        mock_db = create_mock_session()
        message = self._make_callback_message(has_success=False)

        with patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo:
            mock_repo.record_callback = AsyncMock(return_value=(MagicMock(), False))
            await handle_embedding_callback(message, _make_context(db_session=mock_db))

    @pytest.mark.asyncio
    async def test_commits_without_converging_when_incomplete(self) -> None:
        """Commits saga state without converging when not all callbacks received."""
        from job_ingest_enrichment_service.events.callbacks import handle_embedding_callback

        mock_db = create_mock_session()
        message = self._make_callback_message(embedding_type="retrieval")

        mock_saga = MagicMock()
        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks._converge_and_publish",
                new_callable=AsyncMock,
            ) as mock_converge,
        ):
            mock_repo.record_callback = AsyncMock(return_value=(mock_saga, False))
            await handle_embedding_callback(message, _make_context(db_session=mock_db))

        mock_converge.assert_not_called()
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_converges_when_all_callbacks_received(self, enrichment_context: EnrichmentContext) -> None:
        """Calls _converge_and_publish when saga is complete."""
        from job_ingest_enrichment_service.events.callbacks import handle_embedding_callback

        mock_db = create_mock_session()
        message = self._make_callback_message(embedding_type="title")
        mock_saga = MagicMock()
        mock_saga.enrichment_data_json = _make_saga_json(enrichment_context)

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks._converge_and_publish",
                new_callable=AsyncMock,
            ) as mock_converge,
        ):
            mock_repo.record_callback = AsyncMock(return_value=(mock_saga, True))
            await handle_embedding_callback(message, _make_context(db_session=mock_db))

        mock_converge.assert_awaited_once()


class TestPublishEnrichmentFailed:
    """Tests for the terminal failed enrichment event."""

    @pytest.mark.asyncio
    async def test_includes_manifest_job_collection_version(
        self,
        enrichment_context: EnrichmentContext,
    ) -> None:
        from job_ingest_enrichment_service.events.callbacks import _publish_enrichment_failed
        from nohiki.ml.v1 import EntityType

        ctx = enrichment_context
        manifest = MagicMock()
        manifest.get_entity_version.return_value = "job-v7"

        with (
            patch("job_ingest_enrichment_service.events.callbacks.kafka_client") as mock_kafka,
            patch(
                "job_ingest_enrichment_service.events.callbacks.get_manifest",
                return_value=manifest,
            ),
        ):
            mock_kafka.publish = AsyncMock()
            await _publish_enrichment_failed(
                ctx,
                ErrorInfo(error_code="ENRICHMENT_FAILED", error_message="failed"),
            )

        manifest.get_entity_version.assert_called_once_with(EntityType.JOB)
        event = mock_kafka.publish.call_args.args[1]
        assert event.collection_version == "job-v7"


class TestPublishEnrichmentCompleted:
    """Tests for _publish_enrichment_completed."""

    @pytest.mark.asyncio
    async def test_publishes_with_geocoded_coords(self) -> None:
        """Publishes with GeoCoordinates when geocoded_lat/lon are set."""
        from job_ingest_enrichment_service.events.callbacks import _publish_enrichment_completed

        ctx = MagicMock()
        ctx.listing_id = str(uuid4())
        ctx.listing_url = "https://example.com/j/1"
        ctx.correlation_id = str(uuid4())
        ctx.geocoded_lat = 37.7749
        ctx.geocoded_lon = -122.4194

        with (
            patch("job_ingest_enrichment_service.events.callbacks.kafka_client") as mock_kafka,
            patch("job_ingest_enrichment_service.events.callbacks.build_stored_listing_from_context"),
            patch("job_ingest_enrichment_service.events.callbacks.get_manifest") as mock_manifest,
        ):
            mock_kafka.publish = AsyncMock()
            mock_manifest.return_value.get_entity_version.return_value = "v1"

            discovered = MagicMock()
            discovered.source = MagicMock()
            discovered.external_id = "ext-1"
            await _publish_enrichment_completed(ctx, discovered, [], (None, None, None))

        mock_kafka.publish.assert_awaited_once()
        event = mock_kafka.publish.call_args.args[1]
        assert event.geocoded_coordinates is not None

    @pytest.mark.asyncio
    async def test_publishes_without_geocoded_coords(self) -> None:
        """Omits GeoCoordinates when lat/lon are None."""
        from job_ingest_enrichment_service.events.callbacks import _publish_enrichment_completed

        ctx = MagicMock()
        ctx.listing_id = str(uuid4())
        ctx.listing_url = "https://example.com/j/2"
        ctx.correlation_id = str(uuid4())
        ctx.geocoded_lat = None
        ctx.geocoded_lon = None

        with (
            patch("job_ingest_enrichment_service.events.callbacks.kafka_client") as mock_kafka,
            patch("job_ingest_enrichment_service.events.callbacks.build_stored_listing_from_context"),
            patch("job_ingest_enrichment_service.events.callbacks.get_manifest") as mock_manifest,
        ):
            mock_kafka.publish = AsyncMock()
            mock_manifest.return_value.get_entity_version.return_value = "v1"

            discovered = MagicMock()
            discovered.source = MagicMock()
            discovered.external_id = None
            await _publish_enrichment_completed(ctx, discovered, [], (None, None, None))

        event = mock_kafka.publish.call_args.args[1]
        assert event.geocoded_coordinates is None


class TestHandleSkillClarification:
    """Tests for _handle_skill_clarification."""

    @pytest.mark.asyncio
    async def test_clarifies_and_republishes(self, enrichment_context: EnrichmentContext) -> None:
        """Calls clarification service and republishes SkillNormalizationRequested."""
        from job_ingest_enrichment_service.events.callbacks import _handle_skill_clarification

        mock_decision = MagicMock()
        mock_decision.raw_skill = "Python"
        mock_service = MagicMock()
        mock_service.clarify_skills = AsyncMock(return_value=[mock_decision])
        mock_service.publish_outcomes = AsyncMock()

        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_context = _make_context(db_session=mock_db)

        mock_publisher = MagicMock()
        mock_publisher.request_embedding = AsyncMock()

        with (
            patch(
                "job_ingest_enrichment_service.events.callbacks.get_skill_clarification_service",
                return_value=mock_service,
            ),
            patch(
                "job_ingest_enrichment_service.events.callbacks.get_embedding_publisher",
                return_value=mock_publisher,
            ),
            patch("job_ingest_enrichment_service.events.callbacks.kafka_client") as mock_kafka,
        ):
            mock_kafka.publish = AsyncMock()
            await _handle_skill_clarification(
                context=mock_context,
                clarifications=[MagicMock()],
                enrichment_ctx=enrichment_context,
                confirmed_requirements=[],
            )

        mock_service.clarify_skills.assert_awaited_once()
        mock_service.publish_outcomes.assert_awaited_once()
        mock_publisher.request_embedding.assert_called()


class TestConvergeAndPublish:
    """Tests for _converge_and_publish."""

    @pytest.mark.asyncio
    async def test_publishes_and_transitions_saga(self, enrichment_context: EnrichmentContext) -> None:
        """Reconstructs context from saga JSON, writes to outbox, and transitions to COMPLETED."""
        from job_ingest_enrichment_service.events.callbacks import _converge_and_publish

        mock_saga = MagicMock()
        mock_saga.enrichment_data_json = _make_saga_json(enrichment_context)
        mock_saga.retrieval_embedding_b64 = None
        mock_saga.title_embedding_b64 = None
        mock_saga.skills_embedding_b64 = None
        mock_db = create_mock_session()

        with patch(
            "job_ingest_enrichment_service.events.callbacks.publish_enrichment_completed_outbox",
            new_callable=AsyncMock,
        ) as mock_pub:
            await _converge_and_publish(mock_db, mock_saga)

        mock_pub.assert_awaited_once()
        mock_saga.transition_to.assert_called_once_with("COMPLETED")
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skill_requirements_roundtrip_via_saga_json(self, enrichment_context: EnrichmentContext) -> None:
        """Verify _create_embedding_saga_and_request → _converge_and_publish preserves skill requirements."""
        from job_ingest_enrichment_service.events.callbacks import (
            _converge_and_publish,
            _create_embedding_saga_and_request,
        )

        original_reqs = [
            JobSkillRequirement(
                skill_id="s-1",
                skill_name="Python",
                proficiency_level=SkillProficiencyLevel.EXPERT,
                is_required=True,
            ),
            JobSkillRequirement(
                skill_id="s-2",
                skill_name="Go",
                proficiency_level=SkillProficiencyLevel.INTERMEDIATE,
                is_required=False,
            ),
        ]

        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()
        mock_context = _make_context(db_session=mock_db)

        mock_publisher = AsyncMock()
        captured_saga: EnrichmentEmbeddingSaga | None = None

        async def fake_create(
            _db: object,
            saga: EnrichmentEmbeddingSaga,
        ) -> EnrichmentEmbeddingSaga:
            nonlocal captured_saga
            captured_saga = saga
            return saga

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks.get_embedding_publisher",
                return_value=mock_publisher,
            ),
        ):
            mock_repo.create = fake_create
            await _create_embedding_saga_and_request(
                context=mock_context,
                enrichment_ctx=enrichment_context,
                skill_requirements=original_reqs,
            )

        assert captured_saga is not None

        mock_saga = MagicMock()
        mock_saga.enrichment_data_json = captured_saga.enrichment_data_json
        mock_saga.retrieval_embedding_b64 = None
        mock_saga.title_embedding_b64 = None
        mock_saga.skills_embedding_b64 = None

        captured_publish_ctx: EnrichmentPublishContext | None = None

        async def capture_publish(_db: object, ctx: EnrichmentPublishContext) -> None:
            nonlocal captured_publish_ctx
            captured_publish_ctx = ctx

        with patch(
            "job_ingest_enrichment_service.events.callbacks.publish_enrichment_completed_outbox",
            side_effect=capture_publish,
        ):
            await _converge_and_publish(mock_db, mock_saga)

        assert captured_publish_ctx is not None
        recovered_reqs = list(captured_publish_ctx.stored_data.skill_requirements)

        assert len(recovered_reqs) == len(original_reqs)
        for orig, rec in zip(original_reqs, recovered_reqs, strict=True):
            assert rec.skill_id == orig.skill_id
            assert rec.skill_name == orig.skill_name
            assert rec.proficiency_level == orig.proficiency_level
            assert rec.is_required == orig.is_required


class TestEmbeddingSagaTerminalOutcomes:
    """Regression tests for failed and expired saga terminal outcomes."""

    @staticmethod
    def _saga(enrichment_context: EnrichmentContext) -> MagicMock:
        saga = MagicMock()
        saga.id = uuid4()
        saga.enrichment_data_json = _make_saga_json(enrichment_context)
        saga.llm_model_id = "embedding-model"
        saga.collection_version = "version-at-start"
        return saga

    @pytest.mark.asyncio
    async def test_embedding_error_fails_saga_once_with_persisted_context_and_current_version(
        self,
        enrichment_context: EnrichmentContext,
    ) -> None:
        """An embedding error fails the saga and queues one failed outcome from persisted state."""
        from uuid import UUID

        from job_ingest_enrichment_service.events.callbacks import handle_embedding_callback
        from nohiki.ml.v1 import EntityType

        message = TestHandleEmbeddingCallback()._make_callback_message(has_error=True)
        saga = self._saga(enrichment_context)
        mock_db = create_mock_session()
        manifest = MagicMock()
        manifest.get_entity_version.return_value = "job-current-v9"

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks.publish_enrichment_failed_outbox",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch("job_ingest_enrichment_service.events.callbacks.get_manifest", return_value=manifest),
        ):
            mock_repo.fail = AsyncMock()
            mock_repo.load = AsyncMock(return_value=saga)
            await handle_embedding_callback(message, _make_context(db_session=mock_db))

        saga_id = UUID(json.loads(message.callback.caller_context.decode("utf-8"))["saga_id"])
        mock_repo.fail.assert_awaited_once_with(mock_db, saga_id, reason="err")
        mock_publish.assert_awaited_once()
        publish_call = mock_publish.await_args
        assert publish_call is not None
        publish_ctx, error = publish_call.args[1:]
        assert publish_ctx.listing_id == enrichment_context.listing_id
        assert publish_ctx.correlation_id == enrichment_context.correlation_id
        assert publish_ctx.llm_model_id == "embedding-model"
        assert publish_ctx.collection_version == "job-current-v9"
        assert error.error_code == "FAIL"
        manifest.get_entity_version.assert_called_once_with(EntityType.JOB)

    @pytest.mark.asyncio
    async def test_duplicate_terminal_embedding_error_is_a_noop(
        self,
    ) -> None:
        """A redelivered failure for a terminal saga does not emit another outcome."""
        from job_ingest_enrichment_service.events.callbacks import handle_embedding_callback
        from nohiki_db_utils import InvalidTransitionError

        message = TestHandleEmbeddingCallback()._make_callback_message(has_error=True)
        mock_db = create_mock_session()
        duplicate = InvalidTransitionError(
            entity_type="EnrichmentEmbeddingSaga",
            current_state="FAILED",
            target_state="FAILED",
            allowed_targets=frozenset(),
        )

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks.publish_enrichment_failed_outbox",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_repo.fail = AsyncMock(side_effect=duplicate)
            await handle_embedding_callback(message, _make_context(db_session=mock_db))
            await handle_embedding_callback(message, _make_context(db_session=mock_db))

        assert mock_repo.fail.await_count == 2
        mock_publish.assert_not_awaited()
        assert mock_db.commit.await_count == 2

    @pytest.mark.asyncio
    async def test_failed_outbox_write_rolls_back_embedding_failure(
        self,
        enrichment_context: EnrichmentContext,
    ) -> None:
        from job_ingest_enrichment_service.events.callbacks import handle_embedding_callback
        from nohiki_kafka_client.handlers import DbSessionConfig
        from nohiki_kafka_client.middleware.db_session import execute_with_db_session

        message = TestHandleEmbeddingCallback()._make_callback_message(has_error=True)
        saga = self._saga(enrichment_context)
        mock_db = create_mock_session()
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=mock_db)
        session.__aexit__ = AsyncMock(return_value=None)
        session_factory = MagicMock(return_value=session)

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks.publish_enrichment_failed_outbox",
                new_callable=AsyncMock,
                side_effect=RuntimeError("outbox unavailable"),
            ),
        ):
            mock_repo.fail = AsyncMock()
            mock_repo.load = AsyncMock(return_value=saga)
            with pytest.raises(RuntimeError, match="outbox unavailable"):
                await execute_with_db_session(
                    handle_embedding_callback,
                    message,
                    _make_context(),
                    DbSessionConfig(auto_commit=False),
                    session_factory,
                )

        mock_db.commit.assert_not_awaited()
        mock_db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stale_saga_expires_and_queues_one_failed_outcome_from_persisted_context(
        self,
        enrichment_context: EnrichmentContext,
    ) -> None:
        """The stale sweep expires each saga and queues a typed failure once."""
        from job_ingest_enrichment_service.events.callbacks import expire_stale_embedding_sagas
        from nohiki_db_utils import SagaStatus

        saga = self._saga(enrichment_context)
        mock_db = create_mock_session()
        manifest = MagicMock()
        manifest.get_entity_version.return_value = "job-current-v10"

        with (
            patch("job_ingest_enrichment_service.events.callbacks._saga_repo") as mock_repo,
            patch(
                "job_ingest_enrichment_service.events.callbacks.publish_enrichment_failed_outbox",
                new_callable=AsyncMock,
            ) as mock_publish,
            patch("job_ingest_enrichment_service.events.callbacks.get_manifest", return_value=manifest),
        ):
            mock_repo.find_stale = AsyncMock(return_value=[saga])
            assert await expire_stale_embedding_sagas(mock_db) == 1

        saga.transition_to.assert_called_once_with(SagaStatus.EXPIRED)
        mock_publish.assert_awaited_once()
        publish_call = mock_publish.await_args
        assert publish_call is not None
        publish_ctx, error = publish_call.args[1:]
        assert publish_ctx.listing_id == enrichment_context.listing_id
        assert publish_ctx.correlation_id == enrichment_context.correlation_id
        assert publish_ctx.collection_version == "job-current-v10"
        assert error.error_code == "EMBEDDING_SAGA_EXPIRED"
        assert error.retryable is False
        mock_db.flush.assert_awaited_once()
