"""PydanticAI agent for unified job-posting extraction."""

import functools
from typing import TYPE_CHECKING

from nohiki_llm_client import LLMClient, LLMResult, StructuredAgentConfig
from nohiki_observability import get_logger

from job_ingest_enrichment_service.core.config import get_settings
from job_ingest_enrichment_service.extraction_contract import (
    EXTRACTION_SYSTEM_PROMPT,
    ExtractionContext,
    ExtractionPromptLimits,
    ExtractionSpecification,
    build_extraction_prompt,
)
from job_ingest_enrichment_service.schemas.extraction import JobExtractionSchema

if TYPE_CHECKING:
    from nohiki.job.ingest.v1 import DiscoveredListing
    from pydantic_ai import Agent

logger = get_logger(__name__)


@functools.lru_cache(maxsize=1)
def _get_extraction_spec() -> ExtractionSpecification:
    """Build the immutable extraction contract from production input limits."""
    processing = get_settings().processing
    return ExtractionSpecification(
        limits=ExtractionPromptLimits(
            field_chars=processing.max_prompt_field_chars,
            description_chars=processing.max_prompt_description_chars,
        )
    )


@functools.lru_cache(maxsize=1)
def _get_llm_client() -> LLMClient:
    """Get or create the extraction LLM client singleton."""
    return LLMClient(get_settings().llm, chain="extraction")


@functools.lru_cache(maxsize=1)
def _get_extraction_agent() -> Agent[ExtractionContext, JobExtractionSchema]:
    """Get or create the production extraction agent singleton."""
    specification = _get_extraction_spec()
    return _get_llm_client().create_agent(
        StructuredAgentConfig(
            deps_type=ExtractionContext,
            output_type=specification.output_type,
            system_prompt=specification.system_prompt,
        )
    )


async def close_extraction_llm_client() -> None:
    """Close and clear the cached extraction model resources if initialized."""
    if _get_llm_client.cache_info().currsize:
        await _get_llm_client().close()
    _get_extraction_agent.cache_clear()
    _get_llm_client.cache_clear()


async def run_extraction_agent(
    discovered: DiscoveredListing,
) -> LLMResult[JobExtractionSchema]:
    """Extract a discovered listing through the configured production model chain.

    Args:
        discovered: Raw listing data from the discovery service.

    Returns:
        Validated extraction result and provider usage metadata.
    """
    specification = _get_extraction_spec()
    result = await _get_llm_client().run(
        _get_extraction_agent(),
        specification.build_prompt(discovered),
        deps=specification.build_context(discovered),
    )
    logger.info(
        "Extraction completed",
        listing_url=discovered.listing_url,
        seniority=result.output.seniority_level.name,
        language=result.output.language,
        skill_count=len(result.output.skills),
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
    )
    return result


__all__ = (
    "EXTRACTION_SYSTEM_PROMPT",
    "ExtractionContext",
    "build_extraction_prompt",
    "run_extraction_agent",
)
