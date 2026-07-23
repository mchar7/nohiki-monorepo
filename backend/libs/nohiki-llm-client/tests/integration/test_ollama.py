"""Explicit opt-in integration tests for the Ollama provider.

Setting ``OLLAMA_BASE_URL`` alone never performs network I/O. To run the live
lane explicitly:

    NOHIKI_RUN_OLLAMA_SMOKE=1 OLLAMA_BASE_URL=http://localhost:11434 \
        uv run --package nohiki-llm-client pytest \
        backend/libs/nohiki-llm-client/tests/integration/test_ollama.py -m integration -v

The readiness fixture runs after collection. All live tests execute once;
none claim or depend on a repeated-run stability property.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

import httpx
import pytest
from nohiki_llm_client import (
    LLMClient,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    OllamaSettings,
    StructuredAgentConfig,
)
from pydantic import BaseModel, Field
from pydantic_ai import ThinkingPart
from pydantic_ai.messages import ModelMessage

OLLAMA_BASE_URL_ENV: Final[str] = "OLLAMA_BASE_URL"
OLLAMA_MODEL_ENV: Final[str] = "OLLAMA_MODEL"
OLLAMA_SMOKE_ENV: Final[str] = "NOHIKI_RUN_OLLAMA_SMOKE"
DEFAULT_OLLAMA_MODEL: Final[str] = "glm-4.7-flash:latest"


def _get_ollama_base_url() -> str | None:
    """Get Ollama base URL from environment."""
    return os.environ.get(OLLAMA_BASE_URL_ENV)


def _get_ollama_model() -> str:
    """Get Ollama model from environment or use default."""
    return os.environ.get(OLLAMA_MODEL_ENV, DEFAULT_OLLAMA_MODEL)


@pytest.fixture(scope="module")
def ollama_server() -> None:
    """Require an explicit opt-in and a ready Ollama server after collection."""
    if os.environ.get(OLLAMA_SMOKE_ENV) != "1":
        pytest.skip(f"Set {OLLAMA_SMOKE_ENV}=1 to run live Ollama integration tests.")

    base_url = _get_ollama_base_url()
    if not base_url:
        pytest.skip(f"Set {OLLAMA_BASE_URL_ENV} to run live Ollama integration tests.")

    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0)
    except httpx.HTTPError as error:
        pytest.skip(f"Ollama is not ready: {error}")
    if response.status_code != httpx.codes.OK:
        pytest.skip(f"Ollama readiness returned HTTP {response.status_code}.")


class SimpleOutput(BaseModel):
    """Simple structured output for basic tests."""

    answer: str


class MathOutput(BaseModel):
    """Structured output for math operations."""

    result: int
    explanation: str


class ExtractionOutput(BaseModel):
    """Structured output for extraction tests."""

    name: str
    role: str
    skills: list[str]


@dataclass(frozen=True, slots=True)
class AgentContext:
    """Context for test agents."""

    test_name: str


def _create_ollama_settings(
    model: str | None = None,
    *,
    ollama: OllamaSettings | None = None,
) -> LLMSettings:
    """Create LLMSettings configured for Ollama integration tests.

    Args:
        model: Ollama model name (without provider prefix).
        ollama: Optional OllamaSettings override.

    Returns:
        Configured LLMSettings for Ollama provider.
    """
    base_url = _get_ollama_base_url()
    if not base_url:
        msg = f"{OLLAMA_BASE_URL_ENV} environment variable not set"
        raise RuntimeError(msg)

    model_name = model or _get_ollama_model()
    full_model = f"ollama:{model_name}"

    return LLMSettings(
        provider=LLMProviderSettings(
            models=[
                LLMModelConfig(
                    model=full_model,
                    base_url=f"{base_url.rstrip('/')}/v1",
                )
            ],
            temperature=0.0,
            timeout_seconds=120.0,
            ollama=ollama or OllamaSettings(),
        ),
    )


def _extract_thinking_parts(messages: tuple[ModelMessage, ...]) -> list[ThinkingPart]:
    """Extract ThinkingPart objects from message history.

    Args:
        messages: Message history from LLMResult.messages.

    Returns:
        List of ThinkingPart objects found in response.
    """
    return [part for msg in messages if hasattr(msg, "parts") for part in msg.parts if isinstance(part, ThinkingPart)]


@pytest.mark.integration
@pytest.mark.usefixtures("ollama_server")
class TestOllamaBasicConnectivity:
    """Test basic Ollama connectivity and simple LLM calls."""

    @pytest.mark.asyncio
    async def test_simple_structured_output(self) -> None:
        """Test basic structured output generation with Ollama."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=SimpleOutput,
                system_prompt="You are a helpful assistant. Answer questions concisely.",
            )
        )

        ctx = AgentContext(test_name="simple_structured_output")
        result = await client.run(agent, "What is the capital of France? Answer in one word.", deps=ctx)

        assert result.output is not None
        assert isinstance(result.output, SimpleOutput)
        assert len(result.output.answer) > 0
        assert result.usage.input_tokens > 0
        assert result.usage.output_tokens > 0

    @pytest.mark.asyncio
    async def test_math_structured_output(self) -> None:
        """Test structured output with multiple fields."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=MathOutput,
                system_prompt="You are a math assistant. Solve problems and explain your reasoning.",
            )
        )

        ctx = AgentContext(test_name="math_structured_output")
        result = await client.run(agent, "What is 15 + 27?", deps=ctx)

        assert result.output is not None
        assert isinstance(result.output, MathOutput)
        assert result.output.result == 42
        assert len(result.output.explanation) > 0


@pytest.mark.integration
@pytest.mark.usefixtures("ollama_server")
class TestOllamaExtraction:
    """Test extraction capabilities with Ollama."""

    @pytest.mark.asyncio
    async def test_extract_person_info(self) -> None:
        """Test extracting structured person information."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=ExtractionOutput,
                system_prompt="Extract person information from the text. Be accurate.",
            )
        )

        text = """
        John Smith is a Senior Software Engineer at TechCorp.
        He specializes in Python, Kubernetes, and machine learning.
        """

        ctx = AgentContext(test_name="extract_person_info")
        result = await client.run(agent, text, deps=ctx)

        assert result.output is not None
        assert isinstance(result.output, ExtractionOutput)
        assert "john" in result.output.name.lower()
        assert len(result.output.skills) >= 2

    @pytest.mark.asyncio
    async def test_extract_with_missing_info(self) -> None:
        """Test extraction handles missing information gracefully."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=ExtractionOutput,
                system_prompt=(
                    "Extract person information from the text. "
                    "Use 'Unknown' for missing fields and empty list for missing skills."
                ),
            )
        )

        ctx = AgentContext(test_name="extract_with_missing_info")
        result = await client.run(agent, "Jane works as an analyst.", deps=ctx)

        assert result.output is not None
        assert isinstance(result.output, ExtractionOutput)
        assert "jane" in result.output.name.lower()


@pytest.mark.integration
@pytest.mark.usefixtures("ollama_server")
class TestOllamaHealthCheck:
    """Test Ollama health check functionality."""

    @pytest.mark.asyncio
    async def test_health_probe_succeeds(self) -> None:
        """Test that health probe reports healthy for available Ollama."""
        from nohiki_llm_client.observability.health import LLMHealthProbe

        settings = _create_ollama_settings()
        probe = LLMHealthProbe(settings)

        result = await probe.check()

        assert result.is_healthy()
        assert "ollama" in result.message.lower()


@pytest.mark.integration
@pytest.mark.usefixtures("ollama_server")
class TestOllamaMetrics:
    """Test that metrics are recorded correctly for Ollama calls."""

    @pytest.mark.asyncio
    async def test_usage_metrics_recorded(self) -> None:
        """Test that token usage is tracked."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=SimpleOutput,
                system_prompt="Answer questions briefly.",
            )
        )

        ctx = AgentContext(test_name="usage_metrics")
        result = await client.run(agent, "Say hello.", deps=ctx)

        assert result.usage.input_tokens > 0
        assert result.usage.output_tokens > 0
        assert result.usage.total_tokens == result.usage.input_tokens + result.usage.output_tokens


# Complex Schema Tests


class SkillCategory(BaseModel):
    """Skill category with items - matches resume schema structure."""

    category: str = Field(min_length=1)
    items: list[str] = Field(min_length=1)


class EducationEntry(BaseModel):
    """Education entry with validation constraints."""

    period: tuple[str, str]
    credential: str = Field(min_length=1)
    institution: str = Field(min_length=1)
    location: str | None = None


class ExperienceEntry(BaseModel):
    """Work experience entry with nested validation."""

    title: str = Field(min_length=1)
    organization: str = Field(min_length=1)
    period: tuple[str, str]
    bullets: list[str] = Field(default_factory=list)


class ResumeSection(BaseModel):
    """Complex resume schema matching doc-template-service complexity."""

    full_name: str = Field(min_length=1)
    professional_title: str = Field(min_length=1)
    skills: list[SkillCategory] = Field(min_length=1)
    education: list[EducationEntry] = Field(min_length=1)
    experience: list[ExperienceEntry] = Field(default_factory=list)
    summary: str = Field(min_length=10, max_length=500)


@pytest.mark.integration
@pytest.mark.usefixtures("ollama_server")
class TestOllamaComplexSchema:
    """Test complex nested schema extraction matching resume-level complexity."""

    @pytest.mark.asyncio
    async def test_resume_schema_extraction(self) -> None:
        """Test extraction of complex nested resume structure."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=ResumeSection,
                system_prompt=(
                    "Generate a software developer resume section. Include realistic data with proper structure."
                ),
            )
        )

        prompt = """Generate a brief software developer resume with:
        - Full name and professional title
        - 2 skill categories with 3 skills each
        - 1 education entry
        - 1 experience entry with 2 bullet points
        - A professional summary (50-100 words)"""

        ctx = AgentContext(test_name="resume_schema_extraction")
        result = await client.run(agent, prompt, deps=ctx)

        assert isinstance(result.output, ResumeSection)
        assert len(result.output.full_name) >= 1
        assert len(result.output.professional_title) >= 1
        assert len(result.output.skills) >= 1
        for skill_cat in result.output.skills:
            assert len(skill_cat.category) >= 1
            assert len(skill_cat.items) >= 1
        assert len(result.output.education) >= 1
        assert len(result.output.summary) >= 10
        assert len(result.output.summary) <= 500

    @pytest.mark.asyncio
    async def test_nested_validation_constraints(self) -> None:
        """Test that nested field constraints are enforced."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=SkillCategory,
                system_prompt="Extract skill category from text.",
            )
        )

        ctx = AgentContext(test_name="nested_validation")
        result = await client.run(
            agent,
            "Languages: Python, TypeScript, Go",
            deps=ctx,
        )

        assert isinstance(result.output, SkillCategory)
        assert result.output.category.lower() in ["languages", "programming languages"]
        assert len(result.output.items) >= 3


# Thinking/Reasoning Validation Tests


@pytest.mark.integration
@pytest.mark.usefixtures("ollama_server")
class TestOllamaThinking:
    """Test thinking/reasoning extraction from Ollama responses."""

    @pytest.mark.asyncio
    async def test_thinking_enabled_extracts_parts(self) -> None:
        """Test that thinking is extracted when enabled."""
        ollama_settings = OllamaSettings(think=True, num_ctx=8192)
        settings = _create_ollama_settings(ollama=ollama_settings)
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=MathOutput,
                system_prompt="Solve math problems. Show your reasoning step by step.",
            )
        )

        ctx = AgentContext(test_name="thinking_enabled")
        result = await client.run(agent, "What is 17 * 23?", deps=ctx)

        assert isinstance(result.output, MathOutput)
        assert result.output.result == 391

        thinking_parts = _extract_thinking_parts(result.messages)

        if thinking_parts:
            total_thinking_chars = sum(len(tp.content) for tp in thinking_parts)
            assert total_thinking_chars > 0, "Thinking content should not be empty"

    @pytest.mark.asyncio
    async def test_thinking_disabled_produces_output(self) -> None:
        """Test that structured output works with thinking disabled.

        Verifies OllamaSettings.think=False is correctly passed and
        the model still produces valid structured output.
        """
        ollama_settings = OllamaSettings(think=False, num_ctx=8192)
        settings = _create_ollama_settings(ollama=ollama_settings)
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=SimpleOutput,
                system_prompt="Answer directly.",
            )
        )

        ctx = AgentContext(test_name="thinking_disabled")
        result = await client.run(agent, "What is 2 + 2?", deps=ctx)

        assert isinstance(result.output, SimpleOutput)
        assert len(result.output.answer) > 0

        assert ollama_settings.think is False
        assert "think" not in ollama_settings.to_options_dict()

    @pytest.mark.asyncio
    async def test_model_response_metadata(self) -> None:
        """Test that response metadata is properly populated."""
        settings = _create_ollama_settings()
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=SimpleOutput,
                system_prompt="Answer briefly.",
            )
        )

        ctx = AgentContext(test_name="metadata")
        result = await client.run(agent, "Hello", deps=ctx)

        assert result.model_used is not None
        assert len(result.model_used) > 0
        assert result.duration_seconds > 0
        assert result.usage.input_tokens > 0
        assert result.usage.output_tokens > 0


# OllamaSettings Configuration Tests


@pytest.mark.integration
@pytest.mark.usefixtures("ollama_server")
class TestOllamaSettingsConfiguration:
    """Test OllamaSettings are properly applied."""

    @pytest.mark.asyncio
    async def test_custom_context_length(self) -> None:
        """Test that num_ctx parameter is passed and accepted."""
        ollama_settings = OllamaSettings(num_ctx=4096, top_k=40)
        settings = _create_ollama_settings(ollama=ollama_settings)
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=SimpleOutput,
                system_prompt="Answer briefly.",
            )
        )

        ctx = AgentContext(test_name="custom_context")
        result = await client.run(agent, "Say hello.", deps=ctx)

        assert isinstance(result.output, SimpleOutput)
        assert len(result.output.answer) > 0

    @pytest.mark.asyncio
    async def test_custom_sampling_parameters(self) -> None:
        """Test that sampling parameters (top_k, repeat_penalty) are accepted."""
        ollama_settings = OllamaSettings(
            num_ctx=8192,
            top_k=50,
            repeat_penalty=1.2,
        )
        settings = _create_ollama_settings(ollama=ollama_settings)
        client = LLMClient(settings)

        agent = client.create_agent(
            StructuredAgentConfig(
                deps_type=AgentContext,
                output_type=SimpleOutput,
                system_prompt="Generate creative response.",
            )
        )

        ctx = AgentContext(test_name="custom_sampling")
        result = await client.run(
            agent,
            "Describe a sunset in one sentence.",
            deps=ctx,
        )

        assert isinstance(result.output, SimpleOutput)
        assert len(result.output.answer) > 10

    def test_ollama_settings_to_options_dict(self) -> None:
        """Test OllamaSettings.to_options_dict() method.

        Note: think is NOT in options - it's a top-level Ollama API parameter.
        """
        settings = OllamaSettings(
            num_ctx=16384,
            top_k=60,
            repeat_penalty=1.15,
            think=True,
        )

        options = settings.to_options_dict()

        assert options["num_ctx"] == 16384
        assert options["top_k"] == 60
        assert abs(options["repeat_penalty"] - 1.15) < 1e-9
        assert "think" not in options
        assert settings.think is True
