"""Tests for content_service.py - PydanticAI LLM content generation."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from doc_content_service.services.content_service import (
    ContentGenerationParams,
    _agent_cache,
    _extract_content_schema,
    _extract_storage_keys,
    _fetch_attachments_from_s3,
    _fetch_single_attachment,
    _get_or_create_agent,
    _publish_generation_completed,
    _publish_generation_failed,
    process_content_generation,
)
from doc_content_service.services.context import DocumentContentContext
from doc_content_service.services.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
)
from nohiki.common.v1 import JobBoardSource, RenderOutputFormat
from nohiki.doc.content.v1 import ContentGenerationCompleted, ContentGenerationContext
from nohiki.doc.template.v1 import (
    DocumentRenderRequested,
    DocumentTemplateVersionSnapshot,
)
from nohiki.job.listing.v1 import ListingSnapshot
from nohiki.user.pref.v1 import SearchPrefSnapshot
from nohiki_common_exceptions import ValidationError


def _create_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _create_listing_snapshot(listing_id: str | None = None) -> ListingSnapshot:
    return ListingSnapshot(
        id=listing_id or str(_create_uuid()),
        listing_url="https://example.com/job/123",
        source=JobBoardSource.INDEED,
        title="Senior Software Engineer",
        company_name="Tech Corp",
        description=(
            "We are looking for a senior software engineer to join our platform team. "
            "You will design and build distributed services, mentor junior engineers, and "
            "drive architectural decisions across our backend stack. Strong Python, "
            "FastAPI, and PostgreSQL experience required; familiarity with Kubernetes, "
            "Kafka, and observability tooling is highly valued."
        ),
        required_skills=["Python", "FastAPI", "PostgreSQL"],
    )


def _create_template_version_snapshot(
    version_id: str | None = None,
) -> DocumentTemplateVersionSnapshot:
    return DocumentTemplateVersionSnapshot(
        version_id=version_id or str(_create_uuid()),
        version="1.0.0",
        template_content="<html>{{ content }}</html>",
        content_schema_json=json.dumps(
            {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["summary", "skills"],
            }
        ),
        description="Resume template",
    )


def _create_content_generation_context(
    listing: ListingSnapshot | None = None,
    template_version: DocumentTemplateVersionSnapshot | None = None,
) -> ContentGenerationContext:
    return ContentGenerationContext(
        listing=listing or _create_listing_snapshot(),
        template_version=template_version or _create_template_version_snapshot(),
    )


def _create_params(
    request_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    context: ContentGenerationContext | None = None,
) -> ContentGenerationParams:
    resolved_user_id = user_id or _create_uuid()
    return ContentGenerationParams(
        request_id=request_id or _create_uuid(),
        user_id=resolved_user_id,
        context=context or _create_content_generation_context(),
        pref_snapshot=SearchPrefSnapshot(
            id=str(_create_uuid()),
            user_id=str(resolved_user_id),
            pref_name="Tailored resume",
        ),
        correlation_id=str(_create_uuid()),
        output_format=RenderOutputFormat.PDF,
        template_id=str(_create_uuid()),
        template_name="Tailored resume",
        job_correlation_id=str(_create_uuid()),
    )


class TestExtractContentSchema:
    """Tests for _extract_content_schema function."""

    def test_extracts_valid_json_schema(self) -> None:
        template = _create_template_version_snapshot()
        result = _extract_content_schema(template)
        assert result["type"] == "object"
        assert "properties" in result

    def test_returns_empty_dict_when_no_schema(self) -> None:
        template = DocumentTemplateVersionSnapshot(
            version_id=str(_create_uuid()),
            version="1.0.0",
            template_content="<html></html>",
        )
        result = _extract_content_schema(template)
        assert result == {}

    def test_raises_validation_error_on_invalid_json(self) -> None:
        template = DocumentTemplateVersionSnapshot(
            version_id=str(_create_uuid()),
            version="1.0.0",
            template_content="<html></html>",
            content_schema_json="not valid json{",
        )
        with pytest.raises(ValidationError):
            _extract_content_schema(template)

    def test_raises_validation_error_on_non_object_schema(self) -> None:
        template = DocumentTemplateVersionSnapshot(
            version_id=str(_create_uuid()),
            version="1.0.0",
            template_content="<html></html>",
            content_schema_json='"just a string"',
        )
        with pytest.raises(ValidationError):
            _extract_content_schema(template)


class TestExtractStorageKeys:
    """Tests for _extract_storage_keys function."""

    def test_extracts_empty_keys(self) -> None:
        user_id = _create_uuid()
        context = ContentGenerationContext()
        result = _extract_storage_keys(context, user_id)
        assert result == []


class TestBuildSystemPrompt:
    """Tests for build_system_prompt function."""

    def test_includes_schema_definition(self) -> None:
        ctx = DocumentContentContext(
            job_data={"title": "Engineer"},
            schema_definition={"type": "object"},
            schema_name="resume",
            schema_version="1.0.0",
            attachments=[],
            user_preferences={},
        )
        result = build_system_prompt(ctx)
        assert "Target Schema" in result
        assert '"type": "object"' in result

    def test_includes_attachments(self) -> None:
        ctx = DocumentContentContext(
            job_data={"title": "Engineer"},
            schema_definition={"type": "object"},
            schema_name="resume",
            schema_version="1.0.0",
            attachments=[{"name": "example.txt", "content": "Example content"}],
            user_preferences={},
        )
        result = build_system_prompt(ctx)
        assert "example.txt" in result
        assert "Example content" in result

    def test_includes_user_preferences(self) -> None:
        ctx = DocumentContentContext(
            job_data={"title": "Engineer"},
            schema_definition={"type": "object"},
            schema_name="resume",
            schema_version="1.0.0",
            attachments=[],
            user_preferences={"tone": "professional"},
        )
        result = build_system_prompt(ctx)
        assert "User Preferences" in result
        assert "professional" in result


class TestBuildUserPrompt:
    """Tests for build_user_prompt function."""

    def test_includes_job_data(self) -> None:
        ctx = DocumentContentContext(
            job_data={"title": "Senior Engineer", "company": "TechCorp"},
            schema_definition={"type": "object"},
            schema_name="resume",
            schema_version="1.0.0",
            attachments=[],
            user_preferences={},
        )
        result = build_user_prompt(ctx)
        assert "Senior Engineer" in result
        assert "TechCorp" in result


class TestFetchSingleAttachment:
    """Tests for _fetch_single_attachment function."""

    @pytest.mark.asyncio
    async def test_fetches_and_decodes_attachment(self) -> None:
        mock_s3 = AsyncMock()
        mock_s3.get_object.return_value = b"test content"

        result = await _fetch_single_attachment(mock_s3, "path/to/file.txt")

        assert result["name"] == "file.txt"
        assert result["content"] == "test content"
        mock_s3.get_object.assert_called_once_with("path/to/file.txt", max_bytes=1_000_000)


class TestFetchAttachmentsFromS3:
    """Tests for _fetch_attachments_from_s3 function."""

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_keys(self) -> None:
        mock_s3 = AsyncMock()
        result = await _fetch_attachments_from_s3(mock_s3, [])
        assert result == []

    @pytest.mark.asyncio
    async def test_fetches_single_attachment_directly(self) -> None:
        mock_s3 = AsyncMock()
        mock_s3.get_object.return_value = b"content"

        result = await _fetch_attachments_from_s3(mock_s3, ["file.txt"])

        assert len(result) == 1
        assert result[0]["name"] == "file.txt"

    @pytest.mark.asyncio
    async def test_fetches_multiple_attachments_in_parallel(self) -> None:
        mock_s3 = AsyncMock()
        mock_s3.get_object.side_effect = [b"content1", b"content2"]

        result = await _fetch_attachments_from_s3(mock_s3, ["file1.txt", "file2.txt"])

        assert len(result) == 2


class TestPublishGenerationCompleted:
    """Tests for _publish_generation_completed function."""

    @pytest.mark.asyncio
    async def test_publishes_completed_event(self) -> None:
        params = _create_params()
        generated_content = {"summary": "Test summary", "skills": ["Python"]}

        with patch("doc_content_service.services.content_service.kafka_client") as mock_kafka_client:
            mock_kafka_client.publish = AsyncMock()
            await _publish_generation_completed(params, generated_content)

            assert mock_kafka_client.publish.await_count == 2
            completed_call, render_call = mock_kafka_client.publish.await_args_list
            assert completed_call.kwargs["key"] == str(params.request_id)
            assert completed_call.kwargs["topic"] == "doc-content.fct.generation-completed.v1"
            completed = completed_call.kwargs["message"]
            assert isinstance(completed, ContentGenerationCompleted)
            assert completed.generated_content_json == '{"skills":["Python"],"summary":"Test summary"}'
            assert completed.metadata.correlation_id == params.correlation_id
            assert completed.generation_metadata.to_dict() == {"job_correlation_id": params.job_correlation_id}
            assert completed.listing_snapshot.id == params.context.listing.id
            assert completed.pref_snapshot is params.pref_snapshot

            assert render_call.kwargs["key"] == str(params.request_id)
            assert render_call.kwargs["topic"] == "doc-template.cmd.render-requested.v1"
            render = render_call.kwargs["message"]
            assert isinstance(render, DocumentRenderRequested)
            assert render.metadata.correlation_id == params.correlation_id
            assert render.template_id == params.template_id
            assert render.template_name == params.template_name
            assert render.output_format is RenderOutputFormat.PDF
            assert render.data.to_dict() == generated_content


class TestPublishGenerationFailed:
    """Tests for _publish_generation_failed function."""

    @pytest.mark.asyncio
    async def test_publishes_failed_event(self) -> None:
        params = _create_params()
        error_message = "Test error message"

        with patch("doc_content_service.services.content_service.kafka_client") as mock_kafka_client:
            mock_kafka_client.publish = AsyncMock()
            await _publish_generation_failed(params, error_message)

            mock_kafka_client.publish.assert_called_once()
            call_args = mock_kafka_client.publish.call_args
            assert call_args.kwargs["key"] == str(params.request_id)


class TestProcessContentGeneration:
    """Tests for process_content_generation function."""

    @pytest.mark.asyncio
    async def test_successful_content_generation_flow(self) -> None:
        """Test complete successful flow including LLM call and event publishing."""
        params = _create_params()
        mock_s3 = AsyncMock()
        mock_s3.get_object.return_value = b"attachment content"

        mock_llm_client = MagicMock()
        mock_agent = MagicMock()
        mock_llm_client.create_dynamic_schema_agent.return_value = mock_agent
        mock_result = MagicMock()
        mock_result.output = {"summary": "Generated content"}
        mock_llm_client.run = AsyncMock(return_value=mock_result)

        with patch("doc_content_service.services.content_service.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await process_content_generation(params, mock_s3, mock_llm_client)

            assert mock_kafka.publish.await_count == 2
            assert [call.kwargs["topic"] for call in mock_kafka.publish.await_args_list] == [
                "doc-content.fct.generation-completed.v1",
                "doc-template.cmd.render-requested.v1",
            ]

    @pytest.mark.asyncio
    async def test_rejects_other_users_storage_key_before_read_or_generation(
        self,
    ) -> None:
        """A forged attachment owner must not leak object content into the prompt."""
        from nohiki.common.v1 import UploadReference

        user_id = _create_uuid()
        other_user_id = _create_uuid()
        upload_id = _create_uuid()
        context = _create_content_generation_context()
        context.context_uploads.append(
            UploadReference(storage_key=f"user-uploads/{other_user_id}/{upload_id}/private-resume.txt")
        )
        params = _create_params(user_id=user_id, context=context)
        mock_s3 = AsyncMock()
        mock_llm = MagicMock()
        run_generation = AsyncMock(return_value={"summary": "must not be generated"})

        with (
            patch(
                "doc_content_service.services.content_service._run_content_generation_llm",
                new=run_generation,
            ),
            patch(
                "doc_content_service.services.content_service._publish_generation_failed",
                new=AsyncMock(),
            ) as publish_failed,
        ):
            await process_content_generation(params, mock_s3, mock_llm)

        mock_s3.get_object.assert_not_awaited()
        run_generation.assert_not_awaited()
        mock_llm.create_dynamic_schema_agent.assert_not_called()
        publish_failed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reads_same_users_canonical_storage_key_for_generation(self) -> None:
        """The canonical owner-bound upload key remains a valid generation input."""
        from nohiki.common.v1 import UploadReference

        user_id = _create_uuid()
        upload_id = _create_uuid()
        storage_key = f"user-uploads/{user_id}/{upload_id}/resume.txt"
        context = _create_content_generation_context()
        context.context_uploads.append(UploadReference(storage_key=storage_key))
        params = _create_params(user_id=user_id, context=context)
        mock_s3 = AsyncMock()
        mock_s3.get_object.return_value = b"owner-only resume content"
        run_generation = AsyncMock(return_value={"summary": "Generated content"})

        with (
            patch(
                "doc_content_service.services.content_service._run_content_generation_llm",
                new=run_generation,
            ),
            patch(
                "doc_content_service.services.content_service._publish_generation_completed",
                new=AsyncMock(),
            ),
        ):
            await process_content_generation(params, mock_s3, MagicMock())

        mock_s3.get_object.assert_awaited_once_with(storage_key, max_bytes=1_000_000)
        run_generation.assert_awaited_once()
        llm_context = run_generation.await_args_list[0].args[0]
        assert llm_context.attachments == [{"name": "resume.txt", "content": "owner-only resume content"}]

    @pytest.mark.asyncio
    async def test_generation_exception_publishes_terminal_failure_and_returns(
        self,
    ) -> None:
        """A handled generation failure emits exactly one terminal callback."""
        from nohiki_common_exceptions import DataNotAvailableError

        params = _create_params()
        mock_s3 = AsyncMock()
        mock_s3.get_object.return_value = b"attachment content"
        mock_llm_client = MagicMock()
        failure = DataNotAvailableError(resource_type="LLM", resource_id="test", source="test")
        mock_llm_client.create_dynamic_schema_agent.side_effect = failure

        with patch("doc_content_service.services.content_service.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()

            await process_content_generation(params, mock_s3, mock_llm_client)

            mock_kafka.publish.assert_awaited_once()
            assert mock_kafka.publish.call_args.kwargs["topic"] == "doc-content.fct.generation-failed.v1"

    @pytest.mark.asyncio
    async def test_completed_publish_failure_propagates_without_false_failure(
        self,
    ) -> None:
        """A broker error publishing success must not be converted into a failed event."""
        params = _create_params()
        mock_s3 = AsyncMock()
        mock_llm_client = MagicMock()
        completed_publish = AsyncMock(side_effect=RuntimeError("broker unavailable"))
        failed_publish = AsyncMock()

        with (
            patch(
                "doc_content_service.services.content_service._run_content_generation_llm",
                new=AsyncMock(return_value={"summary": "Generated content"}),
            ),
            patch(
                "doc_content_service.services.content_service._publish_generation_completed",
                new=completed_publish,
            ),
            patch(
                "doc_content_service.services.content_service._publish_generation_failed",
                new=failed_publish,
            ),
            pytest.raises(RuntimeError, match="broker unavailable"),
        ):
            await process_content_generation(params, mock_s3, mock_llm_client)

        completed_publish.assert_awaited_once()
        failed_publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_raises_validation_error_if_missing_listing(self) -> None:
        context = ContentGenerationContext(template_version=_create_template_version_snapshot())
        params = _create_params(context=context)
        mock_s3 = AsyncMock()
        mock_llm = AsyncMock()

        with patch("doc_content_service.services.content_service.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()
            await process_content_generation(params, mock_s3, mock_llm)

        mock_kafka.publish.assert_awaited_once()
        assert mock_kafka.publish.call_args.kwargs["topic"] == "doc-content.fct.generation-failed.v1"

    @pytest.mark.asyncio
    async def test_raises_validation_error_if_missing_template_version(self) -> None:
        """Test validation error raised when template version is missing."""
        context = ContentGenerationContext(listing=_create_listing_snapshot())
        params = _create_params(context=context)
        mock_s3 = AsyncMock()
        mock_llm = AsyncMock()

        with patch("doc_content_service.services.content_service.kafka_client") as mock_kafka:
            mock_kafka.publish = AsyncMock()
            await process_content_generation(params, mock_s3, mock_llm)

        mock_kafka.publish.assert_awaited_once()
        assert mock_kafka.publish.call_args.kwargs["topic"] == "doc-content.fct.generation-failed.v1"


class TestExtractStorageKeysWithData:
    """Tests for _extract_storage_keys with actual data."""

    def test_extracts_example_upload_keys(self) -> None:
        """Test extracting storage keys from example uploads."""
        from nohiki.common.v1 import UploadReference

        user_id = _create_uuid()
        first_key = f"user-uploads/{user_id}/{_create_uuid()}/example1.txt"
        second_key = f"user-uploads/{user_id}/{_create_uuid()}/example2.txt"
        context = ContentGenerationContext(
            example_uploads=[
                UploadReference(storage_key=first_key),
                UploadReference(storage_key=second_key),
            ],
            context_uploads=[],
        )
        result = _extract_storage_keys(context, user_id)
        assert result == [first_key, second_key]

    def test_extracts_context_upload_keys(self) -> None:
        """Test extracting storage keys from context uploads."""
        from nohiki.common.v1 import UploadReference

        user_id = _create_uuid()
        resume_key = f"user-uploads/{user_id}/{_create_uuid()}/resume.txt"
        cover_key = f"user-uploads/{user_id}/{_create_uuid()}/cover.txt"
        context = ContentGenerationContext(
            example_uploads=[],
            context_uploads=[
                UploadReference(storage_key=resume_key),
                UploadReference(storage_key=cover_key),
            ],
        )
        result = _extract_storage_keys(context, user_id)
        assert result == [resume_key, cover_key]

    def test_extracts_combined_keys(self) -> None:
        """Test extracting storage keys from both example and context uploads."""
        from nohiki.common.v1 import UploadReference

        user_id = _create_uuid()
        example_key = f"user-uploads/{user_id}/{_create_uuid()}/example.txt"
        context_key = f"user-uploads/{user_id}/{_create_uuid()}/resume.txt"
        context = ContentGenerationContext(
            example_uploads=[
                UploadReference(storage_key=example_key),
            ],
            context_uploads=[
                UploadReference(storage_key=context_key),
            ],
        )
        result = _extract_storage_keys(context, user_id)
        assert result == [example_key, context_key]


class TestFetchSingleAttachmentErrors:
    """Tests for _fetch_single_attachment error handling."""

    @pytest.mark.asyncio
    async def test_raises_data_not_available_on_not_found(self) -> None:
        """Test DataNotAvailableError raised when S3 object not found."""
        from nohiki_common_exceptions import DataNotAvailableError
        from nohiki_s3_client import S3ObjectNotFoundError

        mock_s3 = AsyncMock()
        mock_s3.get_object.side_effect = S3ObjectNotFoundError("path/to/file.txt")

        with pytest.raises(DataNotAvailableError):
            await _fetch_single_attachment(mock_s3, "path/to/file.txt")

    @pytest.mark.asyncio
    async def test_raises_data_not_available_on_connection_error(self) -> None:
        """Test DataNotAvailableError raised when S3 connection fails."""
        from nohiki_common_exceptions import DataNotAvailableError
        from nohiki_s3_client import S3ConnectionError

        mock_s3 = AsyncMock()
        mock_s3.get_object.side_effect = S3ConnectionError("connection failed")

        with pytest.raises(DataNotAvailableError):
            await _fetch_single_attachment(mock_s3, "path/to/file.txt")


class TestGetOrCreateAgent:
    """Tests for _get_or_create_agent cache behaviour."""

    def setup_method(self) -> None:
        _agent_cache.clear()

    def teardown_method(self) -> None:
        _agent_cache.clear()

    def test_creates_agent_on_first_call(self) -> None:
        """Agent is created and cached on first call for a schema_name."""
        mock_llm = MagicMock()
        mock_agent = MagicMock()
        mock_llm.create_dynamic_schema_agent.return_value = mock_agent

        result = _get_or_create_agent(mock_llm, {"type": "object"}, "schema-v1")

        assert result is mock_agent
        mock_llm.create_dynamic_schema_agent.assert_called_once()

    def test_returns_cached_agent_on_second_call(self) -> None:
        """Same schema_name returns the cached agent without calling create again."""
        mock_llm = MagicMock()
        mock_agent = MagicMock()
        mock_llm.create_dynamic_schema_agent.return_value = mock_agent

        first = _get_or_create_agent(mock_llm, {"type": "object"}, "schema-v1")
        second = _get_or_create_agent(mock_llm, {"type": "object"}, "schema-v1")

        assert first is second
        mock_llm.create_dynamic_schema_agent.assert_called_once()

    def test_different_schema_names_create_separate_agents(self) -> None:
        """Different schema_names produce independent cache entries."""
        mock_llm = MagicMock()
        agent_a, agent_b = MagicMock(), MagicMock()
        mock_llm.create_dynamic_schema_agent.side_effect = [agent_a, agent_b]

        result_a = _get_or_create_agent(mock_llm, {"type": "object"}, "schema-a")
        result_b = _get_or_create_agent(mock_llm, {"type": "object"}, "schema-b")

        assert result_a is agent_a
        assert result_b is agent_b
        assert mock_llm.create_dynamic_schema_agent.call_count == 2


class TestDocumentContentContext:
    """Tests for DocumentContentContext dataclass."""

    def test_creates_context(self) -> None:
        ctx = DocumentContentContext(
            job_data={"title": "Engineer"},
            schema_definition={"type": "object"},
            schema_name="resume",
            schema_version="1.0.0",
            attachments=[{"name": "test.txt", "content": "test"}],
            user_preferences={"tone": "professional"},
        )

        assert ctx.job_data == {"title": "Engineer"}
        assert ctx.schema_definition == {"type": "object"}
        assert ctx.schema_name == "resume"
        assert ctx.schema_version == "1.0.0"
        assert len(ctx.attachments) == 1
        assert ctx.user_preferences == {"tone": "professional"}

    def test_context_is_frozen_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(DocumentContentContext)
        params = getattr(DocumentContentContext, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True
