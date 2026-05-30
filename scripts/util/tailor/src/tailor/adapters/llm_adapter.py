"""LLM adapter wrapping nohiki-llm-client."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nohiki_llm_client import (
    DynamicAgentConfig,
    LLMClient,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
)
from nohiki_observability import get_logger
from pydantic_ai import RunContext

from tailor.core.config import load_api_keys
from tailor.core.types import JsonDict
from tailor.exceptions import GenerationError
from tailor.models.outputs import GenerationResult

if TYPE_CHECKING:
    from tailor.core.config import TailorSettings

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LLMGenerationDeps:
    """Dependency context injected into the PydanticAI agent at runtime."""

    schema_definition: JsonDict
    context_content: str
    job_content: str


class TailorLLMAdapter:
    """Adapter for nohiki-llm-client for structured content generation."""

    def __init__(self, settings: TailorSettings) -> None:
        """Initialize with LLM settings for lazy client creation.

        Args:
            settings: Tailor CLI settings containing the LLM model string.
        """
        self._model_config = LLMModelConfig(model=settings.llm_model)
        self._client: LLMClient | None = None

    @property
    def _llm_client(self) -> LLMClient:
        """Lazily create LLM client on first access."""
        if self._client is None:
            self._client = self._create_client()
        return self._client

    def _create_client(self) -> LLMClient:
        """Create LLM client by constructing LLMSettings from config and secrets.

        Follows the same manual-construction pattern used by generate_l2r_data
        -- avoids LLMMixin's required-field validation issue.
        """
        llm_settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[self._model_config],
                api_keys=load_api_keys(),
            ),
        )
        client = LLMClient(llm_settings)

        logger.info(
            "LLM client created",
            provider=self._model_config.provider_name,
            model=self._model_config.model_name,
        )

        return client

    async def close(self) -> None:
        """Close the lazy LLM client if it was created."""
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def generate(
        self,
        schema: JsonDict,
        context_content: str,
        job_content: str,
        *,
        schema_name: str = "document",
    ) -> GenerationResult:
        """Generate structured content matching the schema.

        Args:
            schema: JSON schema dict describing the expected output structure.
            context_content: Personal context (resume, background) as markdown text.
            job_content: Job listing description as markdown text.
            schema_name: Human-readable schema label used in agent config.

        Returns:
            ``GenerationResult`` containing the generated content and token usage.

        Raises:
            GenerationError: If the LLM call fails for any reason.
        """
        deps = LLMGenerationDeps(
            schema_definition=schema,
            context_content=context_content,
            job_content=job_content,
        )

        agent = self._llm_client.create_dynamic_schema_agent(
            DynamicAgentConfig(
                deps_type=LLMGenerationDeps,
                json_schema=schema,
                schema_name=schema_name,
                schema_description=f"Tailored {schema_name} content",
            )
        )

        @agent.system_prompt
        async def build_system_prompt(run_ctx: RunContext[LLMGenerationDeps]) -> str:
            return _build_system_prompt(run_ctx.deps)

        user_prompt = _build_user_prompt(deps)
        start = time.monotonic()

        try:
            result = await self._llm_client.run(agent, user_prompt, deps=deps)
            duration = time.monotonic() - start

            return GenerationResult(
                content=result.output,
                prompt_tokens=result.usage.input_tokens,
                completion_tokens=result.usage.output_tokens,
                model_used=result.model_used,
                duration_seconds=duration,
                cache_read_tokens=result.usage.cache_read_tokens,
                cache_write_tokens=result.usage.cache_write_tokens,
            )

        except Exception as e:
            logger.exception("LLM generation failed")
            msg = f"Content generation failed: {e}"
            raise GenerationError(
                msg,
                model=self.model_name,
                provider=self.provider_name,
            ) from e

    @property
    def model_name(self) -> str:
        """Get the configured model name."""
        return self._model_config.model_name

    @property
    def provider_name(self) -> str:
        """Get the active provider name."""
        return self._model_config.provider_name


def _build_system_prompt(deps: LLMGenerationDeps) -> str:
    """Build the system prompt for content generation."""
    schema_json = json.dumps(deps.schema_definition, indent=2)
    return f"""You are an expert document tailoring assistant.
Your task is to generate content that exactly matches the provided JSON schema.

# Target Schema
```json
{schema_json}
```

# Personal Context
Use the following personal information and examples to tailor the content:

{deps.context_content}

# Instructions
1. Generate content that fills ALL required fields in the schema
2. Tailor the content to highlight relevant experience for the job
3. Use specific examples and metrics where available
4. Maintain a professional tone appropriate for the document type
5. Return ONLY valid JSON matching the schema - no markdown, no explanation"""


def _build_user_prompt(deps: LLMGenerationDeps) -> str:
    """Build the user prompt with job details."""
    return f"""Generate content for the following job listing:

{deps.job_content}

Return ONLY valid JSON matching the schema. No additional text or explanation."""
