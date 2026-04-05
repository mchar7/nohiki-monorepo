"""Unit tests for CachingOpenRouterModel."""

from __future__ import annotations

from collections.abc import Mapping
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki_llm_client.providers.caching import CachingConfig, CachingOpenRouterModel
from openai.types import chat
from pydantic_ai.models.openrouter import OpenRouterModel


def _require_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _require_content_parts(message: object) -> list[Mapping[str, object]]:
    content = _require_mapping(message)["content"]
    assert isinstance(content, list)
    return [_require_mapping(part) for part in content]


class TestCachingOpenRouterModelInit:
    """Tests for CachingOpenRouterModel initialization."""

    def test_init_stores_cache_settings(self) -> None:
        """Model stores cache settings."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel(
                "google/gemini-3-flash-preview",
                caching=CachingConfig(enabled=True, ttl="1h"),
            )
            assert model._caching.enabled is True
            assert model._caching.ttl == "1h"

    def test_init_defaults_to_caching_enabled(self) -> None:
        """Caching is enabled by default."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("google/gemini-3-flash-preview")
            assert model._caching.enabled is True
            assert model._caching.ttl == "5m"


class TestAddCacheControlToSystemPrompts:
    """Tests for _add_cache_control_to_system_prompts method."""

    def test_adds_cache_control_to_string_system_prompt(self) -> None:
        """Converts string system prompt to multipart with cache_control."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=True, ttl="5m")

            messages: list[chat.ChatCompletionMessageParam] = [
                chat.ChatCompletionSystemMessageParam(role="system", content="You are a helpful assistant."),
                chat.ChatCompletionUserMessageParam(role="user", content="Hello"),
            ]

            result = model._add_cache_control_to_system_prompts(messages)

            assert len(result) == 2
            first_msg = _require_mapping(result[0])
            assert first_msg["role"] == "system"
            content = _require_content_parts(first_msg)
            assert content[0]["type"] == "text"
            assert content[0]["text"] == "You are a helpful assistant."
            assert content[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}
            assert result[1] == {"role": "user", "content": "Hello"}

    def test_preserves_non_system_messages(self) -> None:
        """Non-system messages are passed through unchanged."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=True, ttl="5m")

            messages: list[chat.ChatCompletionMessageParam] = [
                chat.ChatCompletionUserMessageParam(role="user", content="Hello"),
                chat.ChatCompletionAssistantMessageParam(role="assistant", content="Hi there!"),
            ]

            result = model._add_cache_control_to_system_prompts(messages)

            assert result == messages

    def test_uses_custom_ttl(self) -> None:
        """Uses custom TTL when specified."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=True, ttl="1h")

            messages: list[chat.ChatCompletionMessageParam] = [
                chat.ChatCompletionSystemMessageParam(role="system", content="You are a helpful assistant."),
                chat.ChatCompletionUserMessageParam(role="user", content="Hello"),
            ]

            result = model._add_cache_control_to_system_prompts(messages)

            assert len(result) == 2
            content = _require_content_parts(result[0])
            assert content[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}

    def test_handles_empty_system_content(self) -> None:
        """Empty system content is not converted."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=True, ttl="5m")

            messages: list[chat.ChatCompletionMessageParam] = [
                chat.ChatCompletionSystemMessageParam(role="system", content=""),
            ]

            result = model._add_cache_control_to_system_prompts(messages)

            assert result[0]["content"] == ""


class TestMapMessages:
    """Tests for _map_messages override."""

    @pytest.mark.asyncio
    async def test_map_messages_disabled_returns_parent_result_unchanged(self) -> None:
        """When caching is disabled, returns parent result without adding cache_control."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=False)

        parent_result: list[chat.ChatCompletionMessageParam] = [
            chat.ChatCompletionUserMessageParam(role="user", content="hi")
        ]
        params = MagicMock()
        with patch.object(OpenRouterModel, "_map_messages", new=AsyncMock(return_value=parent_result)):
            result = await model._map_messages([], params)

        assert result is parent_result

    @pytest.mark.asyncio
    async def test_map_messages_enabled_applies_cache_control(self) -> None:
        """When caching is enabled, applies cache_control to system prompts."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=True, ttl="5m")

        parent_messages: list[chat.ChatCompletionMessageParam] = [
            chat.ChatCompletionSystemMessageParam(role="system", content="You are helpful."),
            chat.ChatCompletionUserMessageParam(role="user", content="Hello"),
        ]
        params = MagicMock()
        with patch.object(OpenRouterModel, "_map_messages", new=AsyncMock(return_value=parent_messages)):
            result = await model._map_messages([], params)

        assert len(result) == 2
        system_content = _require_content_parts(result[0])
        assert system_content[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}


class TestConvertToCachedSystemMessage:
    """Tests for _convert_to_cached_system_message method."""

    def test_converts_string_to_multipart_with_cache_control(self) -> None:
        """Converts string content to multipart format with cache_control."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=True, ttl="5m")

            result = model._convert_to_cached_system_message("You are helpful.")

            assert result["role"] == "system"
            content = _require_content_parts(result)
            assert len(content) == 1
            assert content[0]["type"] == "text"
            assert content[0]["text"] == "You are helpful."
            assert content[0]["cache_control"] == {"type": "ephemeral", "ttl": "5m"}

    def test_uses_1h_ttl_when_configured(self) -> None:
        """Uses 1-hour TTL when configured."""
        with patch("pydantic_ai.models.openrouter.OpenRouterModel.__init__", return_value=None):
            model = CachingOpenRouterModel("test-model")
            model._caching = CachingConfig(enabled=True, ttl="1h")

            result = model._convert_to_cached_system_message("Instructions")

            content = _require_content_parts(result)
            cache_control = _require_mapping(content[0]["cache_control"])
            assert cache_control["ttl"] == "1h"
