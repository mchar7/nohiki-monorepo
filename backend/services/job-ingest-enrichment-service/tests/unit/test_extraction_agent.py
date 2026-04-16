"""Unit tests for extraction_agent module."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from job_ingest_enrichment_service.extraction_contract import ExtractionSpecification
from job_ingest_enrichment_service.schemas.extraction import JobExtractionSchema
from job_ingest_enrichment_service.services.extraction_agent import (
    ExtractionContext,
    _get_extraction_agent,
    _get_extraction_spec,
    _get_llm_client,
    close_extraction_llm_client,
    run_extraction_agent,
)
from nohiki.common.v1 import JobBoardSource
from nohiki.job.ingest.v1 import DiscoveredListing


@pytest.fixture(autouse=True)
def _clear_extraction_caches() -> Iterator[None]:
    """Keep production singleton state isolated between tests."""
    _get_extraction_spec.cache_clear()
    _get_llm_client.cache_clear()
    _get_extraction_agent.cache_clear()
    yield
    _get_extraction_spec.cache_clear()
    _get_llm_client.cache_clear()
    _get_extraction_agent.cache_clear()


class TestExtractionContext:
    """Tests for ExtractionContext dataclass."""

    def test_frozen_and_slots(self) -> None:
        """Context is immutable and uses slots."""
        import dataclasses

        ctx = ExtractionContext(listing_url="https://example.com", source="INDEED")
        assert ctx.listing_url == "https://example.com"
        assert ctx.source == "INDEED"

        assert dataclasses.is_dataclass(ExtractionContext)
        params = getattr(ExtractionContext, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


class TestGetLlmClient:
    """Tests for _get_llm_client singleton."""

    def test_creates_client_from_settings(self) -> None:
        """Creates LLMClient using settings.llm config."""
        mock_settings = MagicMock()
        mock_settings.llm = MagicMock()

        with (
            patch(
                "job_ingest_enrichment_service.services.extraction_agent.get_settings",
                return_value=mock_settings,
            ),
            patch("job_ingest_enrichment_service.services.extraction_agent.LLMClient") as mock_cls,
        ):
            result = _get_llm_client()

        mock_cls.assert_called_once_with(mock_settings.llm, chain="extraction")
        assert result is mock_cls.return_value

    @pytest.mark.asyncio
    async def test_close_before_use_is_noop(self) -> None:
        """Shutdown does not construct an extraction client that was never used."""
        with patch("job_ingest_enrichment_service.services.extraction_agent.LLMClient") as client_class:
            await close_extraction_llm_client()

        client_class.assert_not_called()

    @pytest.mark.asyncio
    async def test_close_is_idempotent_and_next_use_reconstructs(self) -> None:
        """One initialized owner closes once, clears, and is recreated on demand."""
        first = MagicMock(close=AsyncMock())
        second = MagicMock(close=AsyncMock())

        with (
            patch("job_ingest_enrichment_service.services.extraction_agent.get_settings") as settings,
            patch(
                "job_ingest_enrichment_service.services.extraction_agent.LLMClient",
                side_effect=[first, second],
            ) as client_class,
        ):
            settings.return_value.llm = MagicMock()
            assert _get_llm_client() is first
            await close_extraction_llm_client()
            await close_extraction_llm_client()
            assert _get_llm_client() is second

        first.close.assert_awaited_once_with()
        second.close.assert_not_awaited()
        assert client_class.call_count == 2

    @pytest.mark.asyncio
    async def test_close_failure_retains_owner_for_retry(self) -> None:
        """A failed close does not discard the only handle that can retry cleanup."""
        client = MagicMock(close=AsyncMock(side_effect=RuntimeError("close failed")))

        with (
            patch("job_ingest_enrichment_service.services.extraction_agent.get_settings") as settings,
            patch(
                "job_ingest_enrichment_service.services.extraction_agent.LLMClient",
                return_value=client,
            ) as client_class,
        ):
            settings.return_value.llm = MagicMock()
            assert _get_llm_client() is client
            with pytest.raises(RuntimeError, match="close failed"):
                await close_extraction_llm_client()
            assert _get_llm_client() is client

        client.close.assert_awaited_once_with()
        client_class.assert_called_once()


class TestGetExtractionAgent:
    """Tests for _get_extraction_agent singleton."""

    def test_configures_agent_from_production_spec(self) -> None:
        """Agent schema, context, and system prompt come from the configured spec."""
        mock_settings = MagicMock()
        mock_settings.processing.max_prompt_field_chars = 37
        mock_settings.processing.max_prompt_description_chars = 113
        mock_client = MagicMock()
        mock_agent = MagicMock()
        mock_client.create_agent.return_value = mock_agent

        with (
            patch(
                "job_ingest_enrichment_service.services.extraction_agent.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "job_ingest_enrichment_service.services.extraction_agent._get_llm_client",
                return_value=mock_client,
            ),
        ):
            specification = _get_extraction_spec()
            result = _get_extraction_agent()

        assert isinstance(specification, ExtractionSpecification)
        assert specification.limits.field_chars == 37
        assert specification.limits.description_chars == 113
        config = mock_client.create_agent.call_args.args[0]
        assert config.deps_type is ExtractionContext
        assert config.output_type is specification.output_type
        assert config.system_prompt == specification.system_prompt
        assert result is mock_agent

    def test_is_singleton(self) -> None:
        """Returns the same Agent instance on repeated calls."""
        mock_client = MagicMock()
        mock_client.create_agent.return_value = MagicMock()

        with patch(
            "job_ingest_enrichment_service.services.extraction_agent._get_llm_client",
            return_value=mock_client,
        ):
            agent_1 = _get_extraction_agent()
            agent_2 = _get_extraction_agent()

        assert agent_1 is agent_2
        mock_client.create_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_failure_retains_cached_client_for_cleanup(self) -> None:
        """Extraction agent construction cannot orphan partially allocated transports."""
        client = MagicMock(close=AsyncMock())
        client.create_agent.side_effect = RuntimeError("agent construction failed")
        specification = MagicMock(output_type=JobExtractionSchema, system_prompt="test")

        with (
            patch(
                "job_ingest_enrichment_service.services.extraction_agent.get_settings",
                return_value=MagicMock(llm=MagicMock()),
            ),
            patch(
                "job_ingest_enrichment_service.services.extraction_agent.LLMClient",
                return_value=client,
            ),
            patch(
                "job_ingest_enrichment_service.services.extraction_agent._get_extraction_spec",
                return_value=specification,
            ),
        ):
            assert _get_llm_client() is client
            with pytest.raises(RuntimeError, match="agent construction failed"):
                _get_extraction_agent()
            assert _get_llm_client() is client
            await close_extraction_llm_client()

        client.close.assert_awaited_once_with()


class TestRunExtractionAgent:
    """Tests for run_extraction_agent async function."""

    @pytest.mark.asyncio
    async def test_runs_agent_with_configured_bounded_prompt_and_context(self) -> None:
        """Production execution applies configured limits and supplies listing context."""
        mock_output = MagicMock()
        mock_output.seniority_level.name = "MID"
        mock_output.skills = ["Python", "Go"]

        mock_result = MagicMock()
        mock_result.output = mock_output
        mock_result.usage.input_tokens = 100
        mock_result.usage.output_tokens = 50

        mock_settings = MagicMock()
        mock_settings.processing.max_prompt_field_chars = 8
        mock_settings.processing.max_prompt_description_chars = 12
        mock_client = MagicMock()
        mock_client.create_agent.return_value = MagicMock()
        mock_client.run = AsyncMock(return_value=mock_result)

        discovered = DiscoveredListing(
            listing_url="https://example.com/job/1",
            source=JobBoardSource.INDEED,
            title="Software Engineer",
            company_name="Acme Corporation",
            description="Build software beyond the configured boundary.",
            location_raw="San Francisco, California",
        )

        with (
            patch(
                "job_ingest_enrichment_service.services.extraction_agent.get_settings",
                return_value=mock_settings,
            ),
            patch(
                "job_ingest_enrichment_service.services.extraction_agent._get_llm_client",
                return_value=mock_client,
            ),
        ):
            result = await run_extraction_agent(discovered)

        assert result is mock_result
        mock_client.create_agent.assert_called_once()
        mock_client.run.assert_awaited_once()
        call_args = mock_client.run.call_args
        prompt = call_args.args[1]
        assert '**Title:** "Software"' in prompt
        assert "Engineer" not in prompt
        assert '"Build softwa"' in prompt
        assert "beyond" not in prompt
        assert call_args.kwargs["deps"] == ExtractionContext(
            listing_url="https://example.com/job/1",
            source="INDEED",
        )
