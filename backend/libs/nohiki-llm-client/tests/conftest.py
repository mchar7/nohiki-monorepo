"""Shared fixtures for nohiki-llm-client tests."""

from __future__ import annotations

import pytest
from nohiki_llm_client.config.settings import (
    ApiKeyRegistry,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
)


@pytest.fixture
def llm_settings() -> LLMSettings:
    """Create LLMSettings with test API key (OpenRouter via registry)."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:test/model")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        ),
    )


@pytest.fixture
def llm_settings_openai() -> LLMSettings:
    """Create LLMSettings with OpenAI key via registry."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="openai:gpt-4o")],
            api_keys=ApiKeyRegistry.model_validate({"openai": "openai-key"}),
        ),
    )


@pytest.fixture
def llm_settings_ollama() -> LLMSettings:
    """Create LLMSettings with Ollama."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[
                LLMModelConfig(
                    model="ollama:llama3",
                    base_url="http://localhost:11434/v1",
                )
            ],
        ),
    )


@pytest.fixture
def llm_settings_google_vertex() -> LLMSettings:
    """Create LLMSettings with Google Vertex AI via registry key."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="google-vertex:gemini-2.5-flash")],
            api_keys=ApiKeyRegistry.model_validate({"google-vertex": "test-vertex-key"}),
        ),
    )


@pytest.fixture
def llm_settings_anthropic() -> LLMSettings:
    """Create LLMSettings with direct Anthropic provider."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-anthropic-key"}),
        ),
    )
