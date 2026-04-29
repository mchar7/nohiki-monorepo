"""Unit tests for callbacks.py event handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.ml.v1 import EncodingMode, EntityType
from nohiki.skill.v1 import UserSkillEntry
from nohiki_common_exceptions import ValidationError
from nohiki_db_utils.testing import create_mock_session
from nohiki_kafka_client import MessageContext
from user_pref_service.core.config import get_manifest
from user_pref_service.core.embedding import PrefEmbeddingState, profile_embedding_content_hash
from user_pref_service.events.callbacks import (
    handle_embedding_callback,
    handle_skill_normalization_callback,
)


def _make_context(
    *,
    db_session: MagicMock | None = None,
    outbox: MagicMock | None = None,
) -> MessageContext:
    """Build a ``MessageContext`` with injected db_session and outbox."""
    return MessageContext(
        topic="test.topic.v1",
        partition=0,
        offset=0,
        timestamp=0,
        headers={},
        key=None,
        db_session=db_session,
        outbox=outbox,
    )


def _make_normalization_callback(
    pref_id: str,
    action: str = "create",
    skill_names: list[str] | None = None,
    *,
    success: bool = True,
) -> MagicMock:
    """Build a mock SkillNormalizationCallback with PrefEmbeddingState in caller_context."""
    state = PrefEmbeddingState(pref_id=pref_id, action=action)
    callback_header = MagicMock()
    callback_header.caller_context = state.to_bytes()

    reqs = []
    for name in skill_names or []:
        req = MagicMock()
        req.skill_name = name
        reqs.append(req)

    message = MagicMock()
    message.callback = callback_header

    if success:
        success_result = MagicMock()
        success_result.skill_requirements = reqs
        success_result.skills_embedding = MagicMock()
        success_result.skills_embedding.dense = MagicMock(values=[0.1, 0.2])
        success_result.collection_version = "v1"
        message.success = success_result
        message.error = None
    else:
        message.success = None
        message.error = MagicMock(error_code="TIMEOUT", error_message="Timed out")

    return message


def _make_embedding_callback(
    pref_id: str,
    action: str = "create",
    *,
    success: bool = True,
    embedded_text: str = "",
    semantic_generation: int = 0,
    semantic_hash: str = "",
    content_hash: str = "",
) -> MagicMock:
    """Build a mock EmbeddingCallback carrying semantic callback identity."""
    state = PrefEmbeddingState(
        pref_id=pref_id,
        action=action,
        embedded_text=embedded_text,
        semantic_generation=semantic_generation,
        semantic_hash=semantic_hash,
    )
    callback_header = MagicMock()
    callback_header.caller_context = state.to_bytes()

    message = MagicMock()
    message.callback = callback_header

    if success:
        success_result = MagicMock()
        success_result.embeddings = []
        success_result.collection_version = get_manifest().get_entity_version(EntityType.PROFILE)
        success_result.content_hash = content_hash
        message.success = success_result
        message.error = None
    else:
        message.success = None
        message.error = MagicMock(error_code="COMPUTE_FAILED", error_message="GPU OOM")

    return message


class TestHandleSkillNormalizationCallback:
    """Tests for handle_skill_normalization_callback."""

    @pytest.mark.asyncio
    async def test_success_builds_rich_deduplicated_query_text(self) -> None:
        """Embedding text keeps name, keywords, and canonical skills in stable order."""
        pref_id = str(uuid4())
        mock_profile = MagicMock()
        mock_profile.pref_name = "  Platform   Roles "
        mock_profile.search_keywords = ["Python", "distributed systems", "python"]
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_normalization_callback(pref_id, skill_names=["Kubernetes", "PYTHON", "Kubernetes"])

        with (
            patch(
                "user_pref_service.events.callbacks.persist_skill_enrichment",
                new_callable=AsyncMock,
                return_value=mock_profile,
            ),
            patch(
                "user_pref_service.events.callbacks.get_embedding_publisher",
            ) as mock_pub_factory,
            patch(
                "user_pref_service.events.callbacks.publish_profile_created_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_publisher = AsyncMock()
            mock_publisher.request_embedding = AsyncMock(return_value="op-1")
            mock_pub_factory.return_value = mock_publisher

            await handle_skill_normalization_callback(message, context)

            mock_publisher.request_embedding.assert_awaited_once()
            request_call = mock_publisher.request_embedding.await_args
            assert request_call is not None
            request = request_call.kwargs
            assert request["text"] == "Platform Roles Python distributed systems Kubernetes"
            assert request["spec"].encoding_mode == EncodingMode.QUERY
            state = PrefEmbeddingState.from_bytes(request["context"].caller_context)
            assert state.embedded_text == request["text"]
            mock_publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_without_query_text_requests_pref_name_embedding(self) -> None:
        """A profile name supplies mandatory fallback text before lifecycle publication."""
        pref_id = str(uuid4())
        mock_profile = MagicMock()
        mock_profile.search_keywords = []
        mock_profile.user_skills_data = None
        mock_profile.pref_name = "Fallback Profile"
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_normalization_callback(pref_id, action="create", skill_names=[])

        with (
            patch(
                "user_pref_service.events.callbacks.persist_skill_enrichment",
                new_callable=AsyncMock,
                return_value=mock_profile,
            ),
            patch("user_pref_service.events.callbacks.get_embedding_publisher") as mock_pub_factory,
            patch(
                "user_pref_service.events.callbacks.publish_profile_created_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_publisher = AsyncMock()
            mock_publisher.request_embedding = AsyncMock(return_value="op-1")
            mock_pub_factory.return_value = mock_publisher

            await handle_skill_normalization_callback(message, context)

            mock_publisher.request_embedding.assert_awaited_once()
            request_call = mock_publisher.request_embedding.await_args
            assert request_call is not None
            assert request_call.kwargs["text"] == "Fallback Profile"
            mock_publish.assert_not_awaited()
            assert mock_profile.is_enrichment_complete is not True

    @pytest.mark.asyncio
    async def test_success_update_action_requests_pref_name_embedding(self) -> None:
        """Update normalization embeds the profile name before lifecycle publication."""
        pref_id = str(uuid4())
        mock_profile = MagicMock()
        mock_profile.search_keywords = []
        mock_profile.user_skills_data = None
        mock_profile.pref_name = "Fallback Profile"
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_normalization_callback(pref_id, action="update", skill_names=[])

        with (
            patch(
                "user_pref_service.events.callbacks.persist_skill_enrichment",
                new_callable=AsyncMock,
                return_value=mock_profile,
            ),
            patch("user_pref_service.events.callbacks.get_embedding_publisher") as mock_pub_factory,
            patch(
                "user_pref_service.events.callbacks.publish_profile_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            mock_publisher = AsyncMock()
            mock_publisher.request_embedding = AsyncMock(return_value="op-1")
            mock_pub_factory.return_value = mock_publisher

            await handle_skill_normalization_callback(message, context)

            mock_publisher.request_embedding.assert_awaited_once()
            request_call = mock_publisher.request_embedding.await_args
            assert request_call is not None
            assert request_call.kwargs["text"] == "Fallback Profile"
            mock_publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_error_result_logs_and_does_not_raise(self) -> None:
        """On error result, logs without raising."""
        pref_id = str(uuid4())
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_normalization_callback(pref_id, success=False)

        await handle_skill_normalization_callback(message, context)

    @pytest.mark.asyncio
    async def test_stale_normalization_generation_stops_before_embedding_request(self) -> None:
        """A normalization result rejected by the generation guard cannot advance the lifecycle."""
        pref_id = str(uuid4())
        message = _make_normalization_callback(pref_id, skill_names=["Python"])
        message.callback.caller_context = PrefEmbeddingState(
            pref_id=pref_id,
            action="update",
            semantic_generation=7,
        ).to_bytes()
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())

        with (
            patch(
                "user_pref_service.events.callbacks.persist_skill_enrichment",
                new_callable=AsyncMock,
                return_value=None,
            ) as persist,
            patch("user_pref_service.events.callbacks.get_embedding_publisher") as publisher_factory,
        ):
            await handle_skill_normalization_callback(message, context)

        persist.assert_awaited_once()
        assert persist.await_args is not None
        assert persist.await_args.kwargs == {"expected_generation": 7}
        publisher_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_callbacks_without_success_or_error_are_rejected(self) -> None:
        """A terminal callback must carry exactly one result arm rather than being acknowledged silently."""
        pref_id = str(uuid4())
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        normalization = _make_normalization_callback(pref_id, success=False)
        normalization.error = None
        embedding = _make_embedding_callback(pref_id, success=False)
        embedding.error = None

        with pytest.raises(ValidationError, match="Empty skill normalization callback result"):
            await handle_skill_normalization_callback(normalization, context)
        with pytest.raises(ValidationError, match="Empty embedding callback result"):
            await handle_embedding_callback(embedding, context)

    @pytest.mark.asyncio
    async def test_caller_context_is_minimal_state_only(self) -> None:
        """Embedding request caller_context carries only pref_id + action (~80 bytes).

        Skills are persisted to DB by persist_skill_enrichment; PrefEmbeddingState
        does NOT carry them inline (plan Appendix D: ~80 byte constraint).
        """
        pref_id = str(uuid4())
        mock_profile = MagicMock()
        mock_profile.search_keywords = []
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_normalization_callback(pref_id, skill_names=["Python"])

        captured: list[dict[str, object]] = []

        with (
            patch(
                "user_pref_service.events.callbacks.persist_skill_enrichment",
                new_callable=AsyncMock,
                return_value=mock_profile,
            ),
            patch("user_pref_service.events.callbacks.get_embedding_publisher") as mock_pub_factory,
        ):
            mock_publisher = AsyncMock()

            async def capture_request(**kwargs: object) -> str:
                captured.append(dict(kwargs))
                return "op-1"

            mock_publisher.request_embedding = capture_request
            mock_pub_factory.return_value = mock_publisher

            await handle_skill_normalization_callback(message, context)

        assert captured
        ctx_arg = captured[0]["context"]
        assert hasattr(ctx_arg, "caller_context")
        raw_ctx = ctx_arg.caller_context
        assert isinstance(raw_ctx, bytes)
        ctx_bytes = raw_ctx
        recovered = PrefEmbeddingState.from_bytes(ctx_bytes)
        assert recovered.pref_id == pref_id
        assert recovered.action == "create"
        assert len(ctx_bytes) < 100


@pytest.fixture(autouse=True)
def _mock_profile_qdrant_transport() -> object:
    """Mock only the Qdrant transport boundary for callback unit tests."""
    with patch("user_pref_service.events.callbacks.upsert_profile_point", new_callable=AsyncMock) as mock:
        yield mock


class TestHandleEmbeddingCallback:
    """Tests for handle_embedding_callback."""

    @pytest.mark.asyncio
    async def test_success_persists_and_publishes_created(self) -> None:
        """On success with action='create', persists embedding and publishes PrefCreated."""
        pref_id = str(uuid4())
        mock_profile = MagicMock()
        mock_profile.user_skills_data = None
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_embedding_callback(pref_id, action="create")

        with (
            patch(
                "user_pref_service.events.callbacks.persist_query_enrichment",
                new_callable=AsyncMock,
                return_value=mock_profile,
            ),
            patch(
                "user_pref_service.events.callbacks.publish_profile_created_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            await handle_embedding_callback(message, context)

            mock_publish.assert_awaited_once()
            assert mock_profile.is_enrichment_complete is True

    @pytest.mark.asyncio
    async def test_success_publishes_updated_for_update_action(self) -> None:
        """On success with action='update', publishes PrefUpdated."""
        pref_id = str(uuid4())
        mock_profile = MagicMock()
        mock_profile.user_skills_data = None
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_embedding_callback(pref_id, action="update")

        with (
            patch(
                "user_pref_service.events.callbacks.persist_query_enrichment",
                new_callable=AsyncMock,
                return_value=mock_profile,
            ),
            patch(
                "user_pref_service.events.callbacks.publish_profile_updated_event",
                new_callable=AsyncMock,
            ) as mock_publish,
        ):
            await handle_embedding_callback(message, context)

            mock_publish.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_success_loads_user_skills_from_db_profile(self) -> None:
        """User skills come from profile.user_skills_data (DB), NOT from ECST state.

        This verifies the plan design: persist_skill_enrichment stores full skill
        data to the DB; handle_embedding_callback reads it via load_user_skills_from_profile.
        """
        pref_id = str(uuid4())
        python_skill = UserSkillEntry(skill_id="s1", skill_name="Python")
        mock_profile = MagicMock()
        mock_profile.user_skills_data = [python_skill.to_dict()]
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_embedding_callback(pref_id, action="create")

        published_user_skills: list[object] = []

        async def capture_publish(
            _db: object, _outbox: object, _profile: object, *, user_skills: list[object] | None = None
        ) -> None:
            published_user_skills.extend(user_skills or [])

        with (
            patch(
                "user_pref_service.events.callbacks.persist_query_enrichment",
                new_callable=AsyncMock,
                return_value=mock_profile,
            ),
            patch(
                "user_pref_service.events.callbacks.publish_profile_created_event",
                side_effect=capture_publish,
            ),
        ):
            await handle_embedding_callback(message, context)

        assert len(published_user_skills) == 1
        first_skill = published_user_skills[0]
        assert hasattr(first_skill, "skill_name")
        assert first_skill.skill_name == "Python"

    @pytest.mark.asyncio
    async def test_error_result_logs_and_does_not_raise(self) -> None:
        """On error result, logs without raising."""
        pref_id = str(uuid4())
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_embedding_callback(pref_id, success=False)

        await handle_embedding_callback(message, context)

    @pytest.mark.asyncio
    async def test_pref_name_embedding_callback_upserts_qdrant_before_canonical_cdc(self) -> None:
        """The fallback-name vector is acknowledged before lifecycle publication."""
        pref_id = str(uuid4())
        profile = MagicMock(user_skills_data=None)
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_embedding_callback(pref_id, embedded_text="Fallback Profile")
        calls: list[str] = []

        async def upsert(*_args: object, **_kwargs: object) -> None:
            calls.append("qdrant")

        async def publish(*_args: object, **_kwargs: object) -> None:
            calls.append("cdc")

        with (
            patch(
                "user_pref_service.events.callbacks.persist_query_enrichment",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch("user_pref_service.events.callbacks.upsert_profile_point", side_effect=upsert) as mock_upsert,
            patch("user_pref_service.events.callbacks.publish_profile_created_event", side_effect=publish),
        ):
            await handle_embedding_callback(message, context)

        assert calls == ["qdrant", "cdc"]
        upsert_call = mock_upsert.await_args
        assert upsert_call is not None
        assert upsert_call.kwargs["embedded_text"] == "Fallback Profile"

    @pytest.mark.asyncio
    async def test_qdrant_failure_suppresses_canonical_cdc(self) -> None:
        """A failed acknowledged write escapes so the transaction cannot commit or publish."""
        profile = MagicMock(user_skills_data=None)
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_embedding_callback(str(uuid4()))
        with (
            patch(
                "user_pref_service.events.callbacks.persist_query_enrichment",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "user_pref_service.events.callbacks.upsert_profile_point",
                new_callable=AsyncMock,
                side_effect=RuntimeError("qdrant unavailable"),
            ),
            patch(
                "user_pref_service.events.callbacks.publish_profile_created_event", new_callable=AsyncMock
            ) as publish,
            pytest.raises(RuntimeError, match="qdrant unavailable"),
        ):
            await handle_embedding_callback(message, context)

        publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_out_of_order_generation_callbacks_only_newest_reaches_side_effects(self) -> None:
        """An older generation is ignored while the newer callback upserts and publishes."""
        pref_id = str(uuid4())
        newest_text = "Newest Profile"
        newest_hash = profile_embedding_content_hash(newest_text)
        old_hash = profile_embedding_content_hash("Older Profile")
        profile = MagicMock(
            user_skills_data=None,
            pref_name=newest_text,
            search_keywords=[],
            semantic_content_generation=2,
            semantic_content_hash=newest_hash,
        )
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        old_message = _make_embedding_callback(
            pref_id,
            action="update",
            semantic_generation=1,
            semantic_hash=old_hash,
            content_hash=old_hash,
        )
        new_message = _make_embedding_callback(
            pref_id,
            action="update",
            semantic_generation=2,
            semantic_hash=newest_hash,
            content_hash=newest_hash,
        )
        persisted_generations: list[int | None] = []

        async def persist(
            *_args: object, expected_generation: int | None = None, expected_hash: str | None = None
        ) -> MagicMock | None:
            persisted_generations.append(expected_generation)
            assert expected_hash in {old_hash, newest_hash}
            return profile if expected_generation == 2 else None

        with (
            patch("user_pref_service.events.callbacks.persist_query_enrichment", side_effect=persist),
            patch("user_pref_service.events.callbacks.upsert_profile_point", new_callable=AsyncMock) as upsert,
            patch(
                "user_pref_service.events.callbacks.publish_profile_updated_event", new_callable=AsyncMock
            ) as publish,
        ):
            await handle_embedding_callback(old_message, context)
            upsert.assert_not_awaited()
            publish.assert_not_awaited()
            await handle_embedding_callback(new_message, context)

        assert persisted_generations == [1, 2]
        upsert.assert_awaited_once()
        upsert_call = upsert.await_args
        assert upsert_call is not None
        assert upsert_call.kwargs["embedded_text"] == newest_text
        publish.assert_awaited_once()
        assert profile.is_enrichment_complete is True

    @pytest.mark.asyncio
    async def test_legacy_text_hash_mismatch_cannot_upsert_or_publish(self) -> None:
        """Legacy callbacks carrying only text are rejected after persisted text changes."""
        pref_id = str(uuid4())
        profile = MagicMock(
            user_skills_data=None,
            pref_name="Current Profile",
            search_keywords=["Python"],
            semantic_content_generation=0,
            semantic_content_hash=None,
        )
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())
        message = _make_embedding_callback(pref_id, embedded_text="Old Profile Python")

        with (
            patch(
                "user_pref_service.events.callbacks.persist_query_enrichment",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch("user_pref_service.events.callbacks.upsert_profile_point", new_callable=AsyncMock) as upsert,
            patch(
                "user_pref_service.events.callbacks.publish_profile_created_event", new_callable=AsyncMock
            ) as publish,
        ):
            await handle_embedding_callback(message, context)

        upsert.assert_not_awaited()
        publish.assert_not_awaited()
        assert profile.is_enrichment_complete is not True

    @pytest.mark.asyncio
    async def test_stale_collection_version_retries_only_current_semantic_state(self) -> None:
        """An old model result is replaced only while its generation and hash still identify the profile."""
        pref_id = str(uuid4())
        text = "Current Profile Python"
        content_hash = profile_embedding_content_hash(text)
        message = _make_embedding_callback(
            pref_id,
            action="update",
            semantic_generation=3,
            semantic_hash=content_hash,
        )
        message.success.collection_version = "obsolete-version"
        profile = MagicMock(
            semantic_content_generation=3,
            semantic_content_hash=content_hash,
        )
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())

        with (
            patch(
                "user_pref_service.events.callbacks.profile_service.get_profile_by_id",
                new_callable=AsyncMock,
                return_value=profile,
            ),
            patch(
                "user_pref_service.events.callbacks.profile_service.build_profile_embedding_text_from_profile",
                return_value=text,
            ),
            patch("user_pref_service.events.callbacks.get_embedding_publisher") as publisher_factory,
            patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
        ):
            publisher = AsyncMock()
            publisher.request_embedding = AsyncMock(return_value="replacement-op")
            publisher_factory.return_value = publisher
            await handle_embedding_callback(message, context)

        publisher.request_embedding.assert_awaited_once()
        assert publisher.request_embedding.await_args is not None
        request = publisher.request_embedding.await_args.kwargs
        assert request["text"] == text
        retry_state = PrefEmbeddingState.from_bytes(request["context"].caller_context)
        assert retry_state.semantic_generation == 3
        assert retry_state.semantic_hash == content_hash
        persist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_stale_collection_version_is_discarded_after_generation_advances(self) -> None:
        """An old model result cannot schedule replacement work for a superseded profile generation."""
        pref_id = str(uuid4())
        content_hash = profile_embedding_content_hash("Old Profile")
        message = _make_embedding_callback(
            pref_id,
            semantic_generation=2,
            semantic_hash=content_hash,
        )
        message.success.collection_version = "obsolete-version"
        current_profile = MagicMock(
            semantic_content_generation=3,
            semantic_content_hash=profile_embedding_content_hash("Current Profile"),
        )
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())

        with (
            patch(
                "user_pref_service.events.callbacks.profile_service.get_profile_by_id",
                new_callable=AsyncMock,
                return_value=current_profile,
            ),
            patch("user_pref_service.events.callbacks.get_embedding_publisher") as publisher_factory,
            patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
        ):
            await handle_embedding_callback(message, context)

        publisher_factory.assert_not_called()
        persist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_callback_hash_disagreement_stops_before_persistence(self) -> None:
        """A result whose content hash disagrees with its request identity cannot mutate durable state."""
        pref_id = str(uuid4())
        expected_hash = profile_embedding_content_hash("Expected Profile")
        message = _make_embedding_callback(
            pref_id,
            semantic_generation=4,
            semantic_hash=expected_hash,
            content_hash=profile_embedding_content_hash("Different Profile"),
        )
        context = _make_context(db_session=create_mock_session(), outbox=MagicMock())

        with (
            patch("user_pref_service.events.callbacks.persist_query_enrichment", new_callable=AsyncMock) as persist,
            patch(
                "user_pref_service.events.callbacks.publish_profile_created_event", new_callable=AsyncMock
            ) as publish,
        ):
            await handle_embedding_callback(message, context)

        persist.assert_not_awaited()
        publish.assert_not_awaited()
