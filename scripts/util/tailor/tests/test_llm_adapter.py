"""Tests for tailor.adapters.llm_adapter -- TailorLLMAdapter."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_llm_client import ApiKeyRegistry
from tailor.adapters.llm_adapter import LLMGenerationDeps, TailorLLMAdapter, _build_system_prompt, _build_user_prompt
from tailor.core.types import JsonDict
from tailor.exceptions import GenerationError
from tailor.models.outputs import GenerationResult

_DUMMY_API_KEYS = ApiKeyRegistry.model_validate({"openrouter": "sk-or-dummy-test-key"})

_SAMPLE_SCHEMA: JsonDict = {"type": "object", "properties": {"name": {"type": "string"}}}
_SAMPLE_CONTEXT = "I have 5 years of Python experience."
_SAMPLE_JOB = "We are looking for a Python developer."


@pytest.fixture
def mock_tailor_settings() -> MagicMock:
    """Return a plain MagicMock with the llm_model string pre-configured.

    Overrides the conftest fixture so tests here can exercise the adapter's
    internal LLMModelConfig construction without loading real secrets.
    """
    settings = MagicMock()
    settings.llm_model = "openrouter:google/gemini-flash-1.5"
    return settings


@pytest.fixture
def mock_llm_client() -> MagicMock:
    """Return a MagicMock representing the LLMClient used inside the adapter."""
    mock_result = MagicMock()
    mock_result.output = {"name": "John"}
    mock_result.usage.input_tokens = 100
    mock_result.usage.output_tokens = 50
    mock_result.usage.cache_read_tokens = 10
    mock_result.usage.cache_write_tokens = 5
    mock_result.model_used = "gpt-4"
    client = MagicMock()
    client.run = AsyncMock(return_value=mock_result)
    client.create_dynamic_schema_agent = MagicMock(return_value=MagicMock())
    return client


@pytest.fixture
def adapter(mock_tailor_settings: MagicMock, mock_llm_client: MagicMock) -> TailorLLMAdapter:
    """Return a TailorLLMAdapter with a pre-injected mock LLM client."""
    inst = TailorLLMAdapter(mock_tailor_settings)
    inst._client = mock_llm_client
    return inst


class TestLLMGenerationDeps:
    """Tests for the LLMGenerationDeps frozen dataclass."""

    def test_is_frozen_dataclass(self) -> None:
        """LLMGenerationDeps must be immutable (FrozenInstanceError on mutation)."""
        deps = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        # Use setattr with a runtime variable name to satisfy both ruff (no B010)
        # and ty (no invalid-assignment), while still exercising the frozen guard at runtime.
        field_name = "context_content"
        with pytest.raises(AttributeError):
            setattr(deps, field_name, "changed")

    def test_two_instances_with_same_data_are_equal(self) -> None:
        """Two LLMGenerationDeps with identical field values must compare equal."""
        deps_a = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        deps_b = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        assert deps_a == deps_b

    def test_fields_accessible(self) -> None:
        """All three fields are accessible with correct values."""
        deps = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        assert deps.schema_definition == _SAMPLE_SCHEMA
        assert deps.context_content == _SAMPLE_CONTEXT
        assert deps.job_content == _SAMPLE_JOB


class TestBuildSystemPrompt:
    """Tests for the _build_system_prompt module-level function."""

    def test_contains_schema_json(self) -> None:
        """System prompt includes the JSON-serialised schema definition."""
        deps = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        prompt = _build_system_prompt(deps)
        assert json.dumps(_SAMPLE_SCHEMA, indent=2) in prompt

    def test_contains_context_content(self) -> None:
        """System prompt includes the personal context content."""
        deps = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        prompt = _build_system_prompt(deps)
        assert _SAMPLE_CONTEXT in prompt

    def test_is_non_empty_string(self) -> None:
        """System prompt must be a non-empty string."""
        deps = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        prompt = _build_system_prompt(deps)
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestBuildUserPrompt:
    """Tests for the _build_user_prompt module-level function."""

    def test_contains_job_content(self) -> None:
        """User prompt includes the job listing content."""
        deps = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        prompt = _build_user_prompt(deps)
        assert _SAMPLE_JOB in prompt

    def test_is_non_empty_string(self) -> None:
        """User prompt must be a non-empty string."""
        deps = LLMGenerationDeps(
            schema_definition=_SAMPLE_SCHEMA,
            context_content=_SAMPLE_CONTEXT,
            job_content=_SAMPLE_JOB,
        )
        prompt = _build_user_prompt(deps)
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestTailorLLMAdapterClientCreation:
    """Tests for lazy LLM client initialisation."""

    def test_client_created_lazily_on_first_access(self, mock_tailor_settings: MagicMock) -> None:
        """LLMClient is not created until _llm_client is first accessed."""
        with (
            patch("tailor.adapters.llm_adapter.LLMClient") as mock_cls,
            patch("tailor.adapters.llm_adapter.load_api_keys", return_value=_DUMMY_API_KEYS),
        ):
            mock_cls.return_value = MagicMock()
            inst = TailorLLMAdapter(mock_tailor_settings)
            assert inst._client is None
            _ = inst._llm_client
            mock_cls.assert_called_once()

    def test_client_same_instance_on_second_access(self, mock_tailor_settings: MagicMock) -> None:
        """The same LLMClient instance is returned on subsequent accesses."""
        with (
            patch("tailor.adapters.llm_adapter.LLMClient") as mock_cls,
            patch("tailor.adapters.llm_adapter.load_api_keys", return_value=_DUMMY_API_KEYS),
        ):
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            inst = TailorLLMAdapter(mock_tailor_settings)
            first = inst._llm_client
            second = inst._llm_client
            assert first is second
            mock_cls.assert_called_once()

    def test_model_name_property(self, mock_tailor_settings: MagicMock) -> None:
        """model_name derives from the provider:model_name string in settings."""
        inst = TailorLLMAdapter(mock_tailor_settings)
        assert inst.model_name == "google/gemini-flash-1.5"

    def test_provider_name_property(self, mock_tailor_settings: MagicMock) -> None:
        """provider_name derives from the provider:model_name string in settings."""
        inst = TailorLLMAdapter(mock_tailor_settings)
        assert inst.provider_name == "openrouter"


class TestTailorLLMAdapterGenerate:
    """Tests for TailorLLMAdapter.generate success and error paths."""

    async def test_creates_dynamic_agent_config_with_schema_name(
        self, adapter: TailorLLMAdapter, mock_llm_client: MagicMock
    ) -> None:
        """Generate calls create_dynamic_schema_agent with the provided schema_name."""
        from nohiki_llm_client import DynamicAgentConfig

        await adapter.generate(_SAMPLE_SCHEMA, _SAMPLE_CONTEXT, _SAMPLE_JOB, schema_name="resume")
        mock_llm_client.create_dynamic_schema_agent.assert_called_once()
        call_args = mock_llm_client.create_dynamic_schema_agent.call_args
        config: DynamicAgentConfig = call_args[0][0]
        assert config.schema_name == "resume"

    async def test_returns_generation_result_with_correct_content(self, adapter: TailorLLMAdapter) -> None:
        """Generate returns GenerationResult whose content matches result.output."""
        result = await adapter.generate(_SAMPLE_SCHEMA, _SAMPLE_CONTEXT, _SAMPLE_JOB)
        assert isinstance(result, GenerationResult)
        assert result.content == {"name": "John"}

    async def test_returns_correct_token_counts(self, adapter: TailorLLMAdapter) -> None:
        """Generate maps usage tokens to GenerationResult fields correctly."""
        result = await adapter.generate(_SAMPLE_SCHEMA, _SAMPLE_CONTEXT, _SAMPLE_JOB)
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50
        assert result.cache_read_tokens == 10
        assert result.cache_write_tokens == 5

    async def test_duration_seconds_positive(self, adapter: TailorLLMAdapter) -> None:
        """Generate records a positive duration_seconds for the LLM call."""
        result = await adapter.generate(_SAMPLE_SCHEMA, _SAMPLE_CONTEXT, _SAMPLE_JOB)
        assert result.duration_seconds >= 0

    async def test_raises_generation_error_on_llm_exception(
        self, adapter: TailorLLMAdapter, mock_llm_client: MagicMock
    ) -> None:
        """GenerationError is raised when the LLM client raises an exception."""
        mock_llm_client.run = AsyncMock(side_effect=RuntimeError("LLM timeout"))
        with pytest.raises(GenerationError, match="Content generation failed"):
            await adapter.generate(_SAMPLE_SCHEMA, _SAMPLE_CONTEXT, _SAMPLE_JOB)

    async def test_generation_error_model_and_provider_set(
        self, adapter: TailorLLMAdapter, mock_llm_client: MagicMock
    ) -> None:
        """GenerationError carries model and provider derived from the model string."""
        mock_llm_client.run = AsyncMock(side_effect=ValueError("bad output"))
        with pytest.raises(GenerationError) as exc_info:
            await adapter.generate(_SAMPLE_SCHEMA, _SAMPLE_CONTEXT, _SAMPLE_JOB)
        err = exc_info.value
        assert err.model == "google/gemini-flash-1.5"
        assert err.provider == "openrouter"
