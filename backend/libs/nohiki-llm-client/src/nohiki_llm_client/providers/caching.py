"""Custom OpenRouter model with cache_control support for system prompts.

OpenRouter supports Anthropic-style cache_control breakpoints which enable
prompt caching for providers like Google Gemini. A
custom model class that automatically adds cache_control to system prompts.

Usage:
    from nohiki_llm_client.caching import CachingOpenRouterModel

    model = CachingOpenRouterModel(
        "google/gemini-3-flash-preview",
        provider=OpenRouterProvider(api_key=api_key),
    )

Reference:
    https://openrouter.ai/docs/guides/best-practices/prompt-caching

"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from openai import AsyncOpenAI

from nohiki_llm_client.config.settings import CacheTTL

from .openrouter import RobustOpenRouterModel

if TYPE_CHECKING:
    from openai.types import chat
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.models import ModelRequestParameters
    from pydantic_ai.profiles import ModelProfileSpec
    from pydantic_ai.providers import Provider
    from pydantic_ai.settings import ModelSettings


@dataclass(frozen=True, slots=True)
class CachingConfig:
    """Configuration for prompt caching behavior."""

    enabled: bool = True
    ttl: CacheTTL = "5m"


class CachingOpenRouterModel(RobustOpenRouterModel):
    """OpenRouter model with automatic cache_control for system prompts.

    This model automatically adds cache_control breakpoints to system prompts,
    enabling prompt caching for supported providers (Anthropic, Google Gemini, etc.).

    """

    def __init__(
        self,
        model_name: str,
        *,
        provider: Literal["openrouter"] | Provider[AsyncOpenAI] = "openrouter",
        profile: ModelProfileSpec | None = None,
        settings: ModelSettings | None = None,
        caching: CachingConfig | None = None,
    ) -> None:
        """Initialize a caching OpenRouter model.

        Args:
            model_name: The name of the model to use.
            provider: The OpenRouter provider for authentication.
            profile: Optional model profile specification.
            settings: Optional default model settings.
            caching: Optional caching configuration (defaults to enabled with 5m TTL).

        """
        super().__init__(model_name, provider=provider, profile=profile, settings=settings)
        self._caching = caching or CachingConfig()

    async def _map_messages(
        self,
        messages: Sequence[ModelMessage],
        model_request_parameters: ModelRequestParameters,
        *,
        model_settings: ModelSettings | None = None,
    ) -> list[chat.ChatCompletionMessageParam]:
        """Override to add cache_control to system prompts."""
        openai_messages = await super()._map_messages(
            messages,
            model_request_parameters,
            model_settings=model_settings,
        )

        if not self._caching.enabled:
            return openai_messages

        return self._add_cache_control_to_system_prompts(openai_messages)

    def _add_cache_control_to_system_prompts(
        self,
        messages: list[chat.ChatCompletionMessageParam],
    ) -> list[chat.ChatCompletionMessageParam]:
        """Add cache_control to system prompt messages."""
        result: list[chat.ChatCompletionMessageParam] = []

        for msg in messages:
            msg_dict = cast("dict[str, Any]", msg)
            if msg_dict.get("role") == "system":
                content = msg_dict.get("content")
                if isinstance(content, str) and content:
                    cached_msg = self._convert_to_cached_system_message(content)
                    result.append(cached_msg)
                else:
                    result.append(msg)
            else:
                result.append(msg)

        return result

    def _convert_to_cached_system_message(
        self,
        content: str,
    ) -> chat.ChatCompletionMessageParam:
        """Convert a string system message to multipart format with cache_control on large content.

        Following OpenRouter documentation pattern:
        - First block: context/instructions (no cache)
        - Second block: large content with cache_control
        """
        return cast(
            "chat.ChatCompletionMessageParam",
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral", "ttl": self._caching.ttl},
                    }
                ],
            },
        )
