"""Model factory: the ONE place with provider-specific construction knowledge.

Creates PydanticAI ``Model`` instances from ``LLMModelConfig`` with
provider-specific settings baked in. Each model carries its own API key,
reasoning config, usage tracking settings, and a retrying HTTP transport.

Features:
- Provider-specific model construction (OpenRouter, OpenAI, Ollama,
  Google Vertex AI, Anthropic on Vertex AI)
- HTTP-level retry via ``AsyncTenacityTransport`` (429/5xx + network errors)
- PydanticAI ``model_id`` for identification
- Concurrency limiting support
"""

# Heavy provider dependencies load only when their path is selected.
# ruff: noqa: PLC0415
from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, assert_never

import httpx
from httpx import AsyncClient, HTTPStatusError
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential

if TYPE_CHECKING:
    from google.genai.types import ThinkingConfigDict
    from openai import AsyncOpenAI
    from pydantic_ai.models import Model
    from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
    from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel

    # These dataclass annotations stay strings despite the global runtime-evaluated decorator setting.
    from pydantic_ai.models.openrouter import (
        OpenRouterModelSettings,  # noqa: TC004
        OpenRouterReasoning,
    )
    from pydantic_ai.profiles import ModelProfile  # noqa: TC004
    from pydantic_ai.profiles.openai import OpenAIModelProfile
    from pydantic_ai.providers.openrouter import OpenRouterProvider  # noqa: TC004

    from nohiki_llm_client.providers.caching import CachingOpenRouterModel
    from nohiki_llm_client.providers.openrouter import RobustOpenRouterModel

from nohiki_llm_client.client.concurrency import apply_concurrency_limit
from nohiki_llm_client.config.constants import (
    DEFAULT_APP_TITLE,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_NUM_CTX,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_TIMEOUT_SECONDS,
    HTTP_RETRY_ATTEMPTS,
    HTTP_RETRY_MAX_TOTAL_WAIT_SECONDS,
    HTTP_RETRY_MAX_WAIT_SECONDS,
    HTTP_RETRY_MIN_WAIT_SECONDS,
    HTTP_RETRYABLE_STATUS_CODES,
    PROVIDER_OLLAMA,
    PROVIDER_OPENROUTER,
    ReasoningEffort,
)
from nohiki_llm_client.config.settings import (
    ApiKeyRegistry,
    LLMCachingSettings,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    OllamaSettings,
)
from nohiki_llm_client.transport import (
    LLAMACPP_API_KEY_PLACEHOLDER,
    OLLAMA_API_KEY_PLACEHOLDER,
    OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER,
    create_model_ssl_context,
    resolve_google_vertex_base_url,
    resolve_local_api_key,
    resolve_vertex_anthropic_base_url,
)

_OPENAI_BASE_URL = "https://api.openai.com/v1"
_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_OPENAI_FIXED_REASONING_PREFIXES = (
    "gpt-5.1-chat",
    "gpt-5.2-chat",
    "gpt-5.3-chat",
)


def uses_fixed_openai_reasoning(model_name: str) -> bool:
    """Return whether OpenAI requires its fixed medium reasoning default."""
    return model_name.startswith(_OPENAI_FIXED_REASONING_PREFIXES)


def _provider_base_url(config: LLMModelConfig, *, default: str) -> str:
    """Resolve a model endpoint without consulting provider SDK environment fallbacks."""
    return config.base_url or default


@dataclass(slots=True, frozen=True)
class _OpenRouterContext:
    """Prepared context for OpenRouter model construction."""

    provider: OpenRouterProvider
    settings: OpenRouterModelSettings
    profile: ModelProfile | None


def create_settings_from_model(
    model: str,
    api_keys: ApiKeyRegistry | None = None,
    *,
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> LLMSettings:
    """Create LLMSettings for a single model with sensible defaults.

    Convenience factory for the common case of configuring a single model
    with minimal configuration. For advanced options (temperature, max_tokens,
    custom base_url, concurrency limits), construct LLMSettings directly.

    Automatically detects Ollama provider and applies appropriate defaults:
    - Uses DEFAULT_OLLAMA_BASE_URL for Ollama models
    - Sets concurrency_limit=1 for Ollama (local inference)
    - Applies DEFAULT_OLLAMA_NUM_CTX context window

    Args:
        model: Fully qualified model string (e.g., ``"openai:primary-model"``).
        api_keys: Provider API key registry. Required for authenticated cloud or proxy providers.
        reasoning_effort: Reasoning token effort level.
        timeout_seconds: Per-request timeout.

    Returns:
        Configured LLMSettings instance ready for LLMClient.

    Example:
        >>> settings = create_settings_from_model(
        ...     "openai:primary-model",
        ...     ApiKeyRegistry(openai="..."),
        ...     reasoning_effort="low",
        ... )
        >>> client = LLMClient(settings)
    """
    is_ollama = model.startswith(f"{PROVIDER_OLLAMA}:")

    model_config = LLMModelConfig(
        model=model,
        reasoning_effort=reasoning_effort,
        base_url=DEFAULT_OLLAMA_BASE_URL if is_ollama else None,
        app_title=DEFAULT_APP_TITLE,
    )

    provider_settings = LLMProviderSettings(
        models=[model_config],
        api_keys=api_keys or ApiKeyRegistry(),
        timeout_seconds=timeout_seconds,
        concurrency_limit=1 if is_ollama else None,
        ollama=OllamaSettings(num_ctx=DEFAULT_OLLAMA_NUM_CTX) if is_ollama else OllamaSettings(),
    )

    return LLMSettings(provider=provider_settings)


def resolve_chain(chain_name: str | None, settings: LLMSettings) -> LLMProviderSettings:
    """Resolve named model chain, falling back to the default provider.

    Args:
        chain_name: Use-case identifier (e.g., ``"enrichment"``,
            ``"skill_clarification"``). ``None`` returns the default.
        settings: Top-level LLM settings containing default and named chains.

    Returns:
        The named chain's ``LLMProviderSettings`` if found, otherwise
        ``settings.provider``.
    """
    if chain_name is None:
        return settings.provider
    return settings.chains.get(chain_name, settings.provider)


def create_model(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    caching: LLMCachingSettings | None = None,
    *,
    transport_clients: list[AsyncClient],
) -> Model:
    """Create one provider model with its transport registered to the caller."""
    supported = {
        "anthropic",
        "google-vertex",
        "llamacpp",
        "ollama",
        "openai",
        "openrouter",
    }
    if config.provider_name not in supported:
        msg = f"Unsupported LLM provider: '{config.provider_name}'"
        raise ValueError(msg)
    http_client = _create_model_http_client(config, transport_clients)
    match config.provider_name:
        case "openrouter":
            return _create_openrouter(config, provider_settings, http_client)
        case "openai":
            return _create_openai(config, provider_settings, http_client)
        case "ollama":
            return _create_ollama(config, provider_settings, http_client)
        case "llamacpp":
            return _create_llamacpp(config, provider_settings, http_client)
        case "anthropic":
            return _create_anthropic(config, provider_settings, http_client, caching)
        case "google-vertex":
            return _create_google_vertex(config, provider_settings, http_client)
        case unsupported:
            msg = f"Unsupported LLM provider: '{unsupported}'"
            raise ValueError(msg)


def _select_primary_model(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    caching_settings: LLMCachingSettings,
    transport_clients: list[AsyncClient],
) -> Model:
    """Create the primary model, including provider-specific prompt caching."""
    if config.provider_name == PROVIDER_OPENROUTER and caching_settings.enabled:
        return create_caching_openrouter(
            config,
            provider_settings,
            caching_settings,
            transport_clients=transport_clients,
        )
    return create_model(
        config,
        provider_settings,
        caching=caching_settings,
        transport_clients=transport_clients,
    )


def create_full_model_chain(
    provider_settings: LLMProviderSettings,
    caching_settings: LLMCachingSettings,
    *,
    transport_clients: list[AsyncClient],
) -> Model:
    """Create a configured model chain and transactionally register its transports."""
    attempt_start = len(transport_clients)
    try:
        first = provider_settings.models[0]
        primary = _select_primary_model(
            first,
            provider_settings,
            caching_settings,
            transport_clients,
        )

        if len(provider_settings.models) > 1:
            from pydantic_ai.models.fallback import FallbackModel

            rest = [
                create_model(
                    config,
                    provider_settings,
                    transport_clients=transport_clients,
                )
                for config in provider_settings.models[1:]
            ]
            model: Model = FallbackModel(primary, *rest)
        else:
            model = primary

        provider_key = first.base_url if first.provider_name == PROVIDER_OLLAMA else None
        return apply_concurrency_limit(
            model,
            provider_settings.concurrency_limit,
            provider_key=provider_key,
        )
    except BaseException as exc:
        failures = rollback_transport_clients(transport_clients, attempt_start)
        if failures:
            message = "Failed to construct and close LLM model transports"
            raise BaseExceptionGroup(message, [exc, *failures]) from exc
        raise


def rollback_transport_clients(
    transport_clients: list[AsyncClient],
    attempt_start: int,
) -> list[BaseException]:
    """Close one failed construction attempt, retaining only failed closes."""
    attempted = tuple(transport_clients[attempt_start:])
    if not attempted:
        return []

    async def close_attempted() -> list[BaseException | None]:
        raw_outcomes = await asyncio.gather(
            *(client.aclose() for client in attempted),
            return_exceptions=True,
        )
        return [outcome if isinstance(outcome, BaseException) else None for outcome in raw_outcomes]

    outcomes: list[BaseException | None] = []

    def run_cleanup() -> None:
        outcomes.extend(asyncio.run(close_attempted()))

    thread = threading.Thread(target=run_cleanup)
    thread.start()
    thread.join()

    transport_clients[attempt_start:] = [
        client for client, outcome in zip(attempted, outcomes, strict=True) if outcome is not None
    ]
    return [outcome for outcome in outcomes if outcome is not None]


def create_caching_openrouter(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    caching: LLMCachingSettings,
    *,
    transport_clients: list[AsyncClient],
) -> CachingOpenRouterModel:
    """Create an OpenRouter model with prompt caching and owned transport."""
    from nohiki_llm_client.providers.caching import CachingConfig, CachingOpenRouterModel

    ctx = _prepare_openrouter_context(
        config,
        provider_settings,
        _create_model_http_client(config, transport_clients),
    )
    return CachingOpenRouterModel(
        config.model_name,
        provider=ctx.provider,
        settings=ctx.settings,
        profile=ctx.profile,
        caching=CachingConfig(enabled=caching.enabled, ttl=caching.ttl),
    )


def _create_retrying_http_client(tls_ca_file: str | None = None) -> AsyncClient:
    """Create a retrying client using fresh system trust plus a model CA."""
    from pydantic_ai.retries import AsyncTenacityTransport, RetryConfig, wait_retry_after

    def _is_retryable(response: httpx.Response) -> None:
        if response.status_code in HTTP_RETRYABLE_STATUS_CODES:
            response.raise_for_status()

    transport = AsyncTenacityTransport(
        wrapped=httpx.AsyncHTTPTransport(verify=create_model_ssl_context(tls_ca_file)),
        config=RetryConfig(
            retry=retry_if_exception_type(
                (
                    HTTPStatusError,
                    httpx.ConnectError,
                    httpx.TimeoutException,
                    httpx.ReadError,
                )
            ),
            wait=wait_retry_after(
                fallback_strategy=wait_exponential(
                    multiplier=1,
                    min=HTTP_RETRY_MIN_WAIT_SECONDS,
                    max=HTTP_RETRY_MAX_WAIT_SECONDS,
                ),
                max_wait=HTTP_RETRY_MAX_TOTAL_WAIT_SECONDS,
            ),
            stop=stop_after_attempt(HTTP_RETRY_ATTEMPTS),
            reraise=True,
        ),
        validate_response=_is_retryable,
    )
    return AsyncClient(transport=transport)


def _create_model_http_client(
    config: LLMModelConfig,
    transport_clients: list[AsyncClient],
) -> AsyncClient:
    """Create and register a transport before provider construction can fail."""
    client = _create_retrying_http_client(config.tls_ca_file)
    transport_clients.append(client)
    return client


def _resolve_effective_profile(
    provider: OpenRouterProvider,
    model_name: str,
    quirk_profile: OpenAIModelProfile | None,
) -> ModelProfile | None:
    """Merge the provider's resolved profile with per-model quirk overrides.

    When no quirk profile is configured, returns ``None`` so the model
    constructor uses ``provider.model_profile`` as a callable, enabling
    PydanticAI's dynamic per-model profile resolution.

    When a quirk profile is set, pre-merges the provider's fully-resolved
    profile (which includes reasoning-field handling, file-URL support, and
    other provider-level defaults) with the quirk overrides.  This prevents
    the profile bypass that occurs when a non-``None`` profile is passed
    directly: ``OpenAIChatModel.__init__`` evaluates
    ``profile or provider.model_profile`` and short-circuits when ``profile``
    is truthy, silently dropping all provider-level settings.

    Args:
        provider: OpenRouter provider for resolving the base profile.
        model_name: Full model slug, including any routing suffix.
        quirk_profile: Override profile from ``_OPENROUTER_QUIRKS``, or
            ``None`` when the model has no registered quirks.

    Returns:
        Merged ``ModelProfile`` with provider defaults and quirk overrides,
        or ``None`` to use provider's dynamic callable resolution.
    """
    from pydantic_ai.profiles import ModelProfile

    if quirk_profile is None:
        return None
    base = provider.model_profile(model_name)
    if base is None:
        return quirk_profile
    return ModelProfile(**(base | quirk_profile))


def _openrouter_attribution_headers(config: LLMModelConfig) -> dict[str, str]:
    """Build attribution headers for a custom OpenRouter gateway client."""
    headers = {"X-Title": config.app_title}
    if config.app_url is not None:
        headers["HTTP-Referer"] = config.app_url
    return headers


def _prepare_openrouter_context(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
) -> _OpenRouterContext:
    """Prepare shared context for OpenRouter model construction.

    Args:
        config: Model endpoint configuration.
        provider_settings: Shared provider settings.
        http_client: Model-owned retrying HTTP client.

    Returns:
        Prepared context ready for model instantiation.
    """
    from openai import AsyncOpenAI
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    from nohiki_llm_client.providers.profiles import select_openrouter_quirks

    api_key = _resolve_api_key(config, provider_settings)
    attribution_headers = _openrouter_attribution_headers(config)
    openai_client = AsyncOpenAI(
        base_url=_provider_base_url(config, default=_OPENROUTER_BASE_URL),
        api_key=api_key,
        http_client=http_client,
        default_headers=attribution_headers,
        organization="",
        project="",
    )
    _seal_openai_routing_headers(openai_client)
    provider = OpenRouterProvider(openai_client=openai_client)

    quirks = select_openrouter_quirks(config.model_name)
    settings = _build_openrouter_settings(
        provider_settings,
        reasoning_effort=config.reasoning_effort,
        suppress_reasoning=not quirks.supports_openrouter_reasoning,
    )
    profile = _resolve_effective_profile(provider, config.model_name, quirks.profile)

    _apply_openrouter_provider_routing(settings, config)

    return _OpenRouterContext(provider=provider, settings=settings, profile=profile)


def _apply_openrouter_provider_routing(
    settings: OpenRouterModelSettings,
    config: LLMModelConfig,
) -> None:
    """Merge OpenRouter provider routing into ``extra_body.provider``.

    Adds ``order`` + ``allow_fallbacks`` when an explicit ``provider_order`` is
    set, and ``zdr: true`` when Zero Data Retention is required. Existing
    ``extra_body`` keys and unrelated ``provider`` routing fields are preserved
    through shallow merges. ``zdr`` is never emitted as ``false``: its absence
    is OpenRouter's default behavior, so a disabled flag adds nothing.
    """
    provider_fields: dict[str, object] = {}
    if config.provider_order:
        provider_fields["order"] = list(config.provider_order)
        provider_fields["allow_fallbacks"] = config.provider_allow_fallbacks
    if config.provider_zdr:
        provider_fields["zdr"] = True

    if not provider_fields:
        return

    extra_body: dict[str, object] = {}
    prev_body = settings.get("extra_body")
    if isinstance(prev_body, dict):
        extra_body = {key: value for key, value in prev_body.items() if isinstance(key, str)}

    provider_obj: dict[str, object] = {}
    prev_provider = extra_body.get("provider")
    if isinstance(prev_provider, dict):
        provider_obj = {key: value for key, value in prev_provider.items() if isinstance(key, str)}

    provider_obj.update(provider_fields)
    extra_body["provider"] = provider_obj
    settings["extra_body"] = extra_body


def _create_openrouter(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
) -> RobustOpenRouterModel:
    """Create OpenRouter model with reasoning, usage tracking, and HTTP retry."""
    from nohiki_llm_client.providers.openrouter import RobustOpenRouterModel

    ctx = _prepare_openrouter_context(config, provider_settings, http_client)
    return RobustOpenRouterModel(
        config.model_name,
        provider=ctx.provider,
        settings=ctx.settings,
        profile=ctx.profile,
    )


def _build_openrouter_settings(
    provider_settings: LLMProviderSettings,
    *,
    reasoning_effort: ReasoningEffort,
    suppress_reasoning: bool = False,
) -> OpenRouterModelSettings:
    """Build OpenRouter-specific model settings with reasoning and usage baked in.

    Args:
        provider_settings: Shared provider settings (temperature, timeouts, etc.).
        reasoning_effort: Reasoning effort level for this specific model.
        suppress_reasoning: When ``True``, the ``openrouter_reasoning`` field is
            omitted regardless of ``reasoning_effort``. Set for providers that
            reject the ``reasoning`` request parameter with HTTP 400.

    Returns:
        Fully configured ``OpenRouterModelSettings``.
    """
    from pydantic_ai.models.openrouter import (
        OpenRouterModelSettings,
        OpenRouterUsageConfig,
    )

    settings = OpenRouterModelSettings(
        temperature=provider_settings.temperature,
        timeout=provider_settings.timeout_seconds,
        openrouter_usage=OpenRouterUsageConfig(include=True),
    )
    if provider_settings.max_tokens is not None:
        settings["max_tokens"] = provider_settings.max_tokens

    if not suppress_reasoning and (reasoning := _build_openrouter_reasoning(reasoning_effort)) is not None:
        settings["openrouter_reasoning"] = reasoning

    return settings


def _build_openrouter_reasoning(
    effort: ReasoningEffort,
) -> OpenRouterReasoning | None:
    """Convert ``ReasoningEffort`` to OpenRouter-specific reasoning config.

    Args:
        effort: Generic reasoning effort level.

    Returns:
        ``OpenRouterReasoning`` dict for non-disabled efforts, ``None`` otherwise.
    """
    from pydantic_ai.models.openrouter import OpenRouterReasoning

    match effort:
        case "disabled":
            return None
        case "low" | "medium" | "high":
            return OpenRouterReasoning(effort=effort)
        case _ as unreachable:
            assert_never(unreachable)


def _seal_openai_routing_headers(client: AsyncOpenAI) -> None:
    """Remove ambient OpenAI organization and project routing."""
    client.organization = None
    client.project = None


def _create_openai(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
) -> OpenAIResponsesModel:
    """Create OpenAI Responses model with reasoning settings and HTTP retry.

    Supports custom ``base_url`` for OpenAI-compatible APIs (llama.cpp, vLLM, etc.).
    """
    from openai import AsyncOpenAI
    from pydantic_ai.models.openai import (
        OpenAIChatModelSettings,
        OpenAIResponsesModel,
    )
    from pydantic_ai.profiles.openai import openai_model_profile
    from pydantic_ai.providers.openai import OpenAIProvider

    fixed_reasoning = uses_fixed_openai_reasoning(config.model_name)
    profile = openai_model_profile(config.model_name)
    reasoning_enabled = fixed_reasoning or (
        profile.get("openai_reasoning_enabled_by_default", False)
        and not (config.reasoning_effort == "disabled" and profile.get("openai_supports_reasoning_effort_none", False))
    )
    if fixed_reasoning and config.reasoning_effort != "medium":
        message = f"OpenAI model '{config.model_name}' requires reasoning effort 'medium'"
        raise ValueError(message)

    api_key = _resolve_api_key(config, provider_settings)
    openai_client = AsyncOpenAI(
        api_key=api_key,
        base_url=_provider_base_url(config, default=_OPENAI_BASE_URL),
        http_client=http_client,
        organization="",
        project="",
    )
    _seal_openai_routing_headers(openai_client)
    provider = OpenAIProvider(openai_client=openai_client)

    settings = OpenAIChatModelSettings(timeout=provider_settings.timeout_seconds)
    if not reasoning_enabled:
        settings["temperature"] = provider_settings.temperature
    if provider_settings.max_tokens is not None:
        settings["max_tokens"] = provider_settings.max_tokens

    if not fixed_reasoning:
        if config.reasoning_effort == "disabled":
            if profile.get("openai_supports_reasoning_effort_none", False):
                settings["openai_reasoning_effort"] = "none"
            elif profile.get("openai_reasoning_enabled_by_default", False):
                message = f"OpenAI model '{config.model_name}' cannot disable reasoning"
                raise ValueError(message)
        else:
            settings["openai_reasoning_effort"] = config.reasoning_effort

    return OpenAIResponsesModel(config.model_name, provider=provider, settings=settings)


def _create_ollama(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
) -> OpenAIChatModel:
    """Create Ollama model via ``OllamaProvider`` (OpenAI-compatible chat API).

    Ollama-specific options (num_ctx, top_k, repeat_penalty) are passed via
    ``extra_body.options``. The ``think`` parameter is a TOP-LEVEL request
    parameter per Ollama's API specification.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.ollama import OllamaProvider
    from pydantic_ai.settings import ModelSettings

    from nohiki_llm_client.providers.profiles import OLLAMA_PROFILE

    provider = OllamaProvider(
        base_url=config.base_url,
        api_key=resolve_local_api_key(
            config.api_key.get_secret_value() if config.api_key else None,
            placeholder=OLLAMA_API_KEY_PLACEHOLDER,
        ),
        http_client=http_client,
    )

    extra_body: dict[str, object] = {"options": provider_settings.ollama.to_options_dict()}
    extra_body["think"] = provider_settings.ollama.think

    settings = ModelSettings(
        temperature=provider_settings.temperature,
        timeout=provider_settings.timeout_seconds,
        extra_body=extra_body,
    )
    if provider_settings.max_tokens is not None:
        settings["max_tokens"] = provider_settings.max_tokens

    return OpenAIChatModel(
        config.model_name,
        provider=provider,
        settings=settings,
        profile=OLLAMA_PROFILE,
    )


def _create_llamacpp(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
) -> OpenAIChatModel:
    """Create llama.cpp model via ``LlamaCppProvider`` (OpenAI-compatible chat API).

    llama.cpp server exposes an OpenAI-compatible Chat Completions API that
    returns reasoning in the ``reasoning_content`` message field. The provider
    profile configures PydanticAI to parse this into ``ThinkingPart`` objects.
    """
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.settings import ModelSettings

    from nohiki_llm_client.providers.llamacpp import LlamaCppProvider

    base_url = config.base_url
    if base_url is None or not base_url.strip():
        msg = "llamacpp provider requires base_url to be nonempty"
        raise ValueError(msg)

    provider = LlamaCppProvider(
        base_url=base_url,
        api_key=resolve_local_api_key(
            config.api_key.get_secret_value() if config.api_key else None,
            placeholder=LLAMACPP_API_KEY_PLACEHOLDER,
        ),
        http_client=http_client,
    )

    settings = ModelSettings(
        temperature=provider_settings.temperature,
        timeout=provider_settings.timeout_seconds,
    )
    if provider_settings.max_tokens is not None:
        settings["max_tokens"] = provider_settings.max_tokens

    # Profile is provided by LlamaCppProvider.model_profile()
    return OpenAIChatModel(
        config.model_name,
        provider=provider,
        settings=settings,
    )


_ANTHROPIC_BUDGET_THINKING_PREFIXES = frozenset(
    {
        "claude-3-7-sonnet",
        "claude-haiku-4-5",
        "claude-opus-4",
        "claude-sonnet-4",
    }
)


def _apply_anthropic_reasoning(
    settings: AnthropicModelSettings,
    model_name: str,
    effort: ReasoningEffort,
) -> bool:
    """Apply source-profiled Anthropic thinking and return whether it is active."""
    from anthropic.types.beta import (
        BetaThinkingConfigAdaptiveParam,
        BetaThinkingConfigEnabledParam,
    )
    from pydantic_ai.profiles.anthropic import (
        ANTHROPIC_THINKING_BUDGET_MAP,
        anthropic_model_profile,
    )

    if effort == "disabled":
        return False
    profile = anthropic_model_profile(model_name)
    if profile is None:
        return False

    if profile.get("anthropic_supports_adaptive_thinking", False):
        settings["anthropic_thinking"] = BetaThinkingConfigAdaptiveParam(type="adaptive")
    elif any(model_name.startswith(prefix) for prefix in _ANTHROPIC_BUDGET_THINKING_PREFIXES):
        budget = ANTHROPIC_THINKING_BUDGET_MAP[effort]
        settings["anthropic_thinking"] = BetaThinkingConfigEnabledParam(
            type="enabled",
            budget_tokens=budget,
        )
    else:
        return False
    if profile.get("anthropic_supports_effort", False):
        settings["anthropic_effort"] = effort
    settings["temperature"] = 1.0
    return True


def seal_anthropic_custom_headers(
    http_client: AsyncClient,
    *,
    api_key: str | None = None,
) -> None:
    """Strip ambient Anthropic custom-header values at the owned HTTP boundary."""
    raw_headers = os.environ.get("ANTHROPIC_CUSTOM_HEADERS")
    if raw_headers is None:
        return
    ambient_header_names: set[str] = set()
    for line in raw_headers.splitlines():
        name, separator, _value = line.partition(":")
        if separator and (normalized_name := name.strip().lower()):
            ambient_header_names.add(normalized_name)

    async def remove_ambient_headers(request: httpx.Request) -> None:
        for name in ambient_header_names:
            request.headers.pop(name, None)
        if api_key is not None:
            request.headers["x-api-key"] = api_key
            request.headers.pop("authorization", None)

    http_client.event_hooks["request"].append(remove_ambient_headers)


def _create_anthropic(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
    caching: LLMCachingSettings | None = None,
) -> AnthropicModel:
    """Create a direct Anthropic model with optional custom base_url.

    Supports both the direct Anthropic API (``base_url=None``) and compatible
    proxy endpoints that expose the native ``/v1/messages`` API (``base_url``
    set to the proxy address, without ``/v1`` suffix: the
    Anthropic SDK appends it internally).

    Reasoning effort is translated to adaptive thinking + effort for models
    that support it. Unsupported models (e.g. ``claude-haiku-4-5``) silently
    skip both fields. When caching is enabled, native ``AnthropicModelSettings``
    cache fields are baked in for system prompts, tool definitions, and messages.

    Args:
        config: Model endpoint configuration.
        provider_settings: Shared provider settings.
        http_client: Model-owned retrying HTTP client.
        caching: Prompt caching configuration.

    Returns:
        Configured ``AnthropicModel`` with retrying HTTP transport.
    """
    from anthropic import AsyncAnthropic
    from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
    from pydantic_ai.profiles import ModelProfile
    from pydantic_ai.providers.anthropic import AnthropicProvider

    api_key = _resolve_api_key(config, provider_settings)
    anthropic_client = AsyncAnthropic(
        api_key=api_key,
        base_url=_provider_base_url(config, default=_ANTHROPIC_BASE_URL),
        http_client=http_client,
        default_headers={},
    )
    seal_anthropic_custom_headers(http_client, api_key=api_key)
    provider = AnthropicProvider(anthropic_client=anthropic_client)

    settings = AnthropicModelSettings(
        temperature=provider_settings.temperature,
        timeout=provider_settings.timeout_seconds,
    )
    if provider_settings.max_tokens is not None:
        settings["max_tokens"] = provider_settings.max_tokens

    thinking_active = _apply_anthropic_reasoning(
        settings,
        config.model_name,
        config.reasoning_effort,
    )

    if caching is not None and caching.enabled:
        settings["anthropic_cache_instructions"] = caching.ttl
        settings["anthropic_cache_tool_definitions"] = caching.ttl
        settings["anthropic_cache_messages"] = caching.ttl

    # When thinking is active, PydanticAI's prepare_request hook resolves
    # output_mode='auto' to 'native' for models where supports_json_schema_output=True.
    # Native mode sends the full JSON schema to Anthropic's grammar compiler, which
    # times out on complex schemas with deep nesting, validators, and unbounded arrays.
    # Overriding the profile to disable native output forces 'auto' → 'prompted' instead:
    # the schema is injected as a prompt instruction and Claude validates client-side,
    # which is equally reliable for capable reasoning models and avoids the compiler.
    profile = ModelProfile(supports_json_schema_output=False) if thinking_active else None

    return AnthropicModel(config.model_name, provider=provider, settings=settings, profile=profile)


def _build_google_thinking_config(
    model_name: str,
    effort: ReasoningEffort,
) -> ThinkingConfigDict | None:
    """Translate configured effort using the installed Google model profile."""
    from google.genai.types import ThinkingConfigDict, ThinkingLevel
    from pydantic_ai.profiles.google import google_model_profile

    profile = google_model_profile(model_name)
    if profile is None or not profile.get("supports_thinking", False):
        return None
    if effort == "disabled" and profile.get("thinking_always_enabled", False):
        return None
    if profile.get("google_supports_thinking_level", False):
        levels = {
            "disabled": ThinkingLevel.MINIMAL,
            "low": ThinkingLevel.LOW,
            "medium": ThinkingLevel.MEDIUM,
            "high": ThinkingLevel.HIGH,
        }
        config = ThinkingConfigDict(thinking_level=levels[effort])
    else:
        budgets = {"disabled": 0, "low": 2048, "medium": 8192, "high": 24576}
        config = ThinkingConfigDict(thinking_budget=budgets[effort])
    if effort != "disabled":
        config["include_thoughts"] = True
    return config


def _create_google_vertex(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
) -> Model:
    """Create a Vertex AI model: Google (Gemini) or Anthropic (Claude).

    Claude models are detected by name prefix and routed through Anthropic's
    Vertex SDK (``AsyncAnthropicVertex``).  All other models use Google's
    GenAI SDK via ``GoogleProvider``.

    Authentication resolves in order:

    1. Per-model ``api_key`` on the config
    2. ``api_keys`` registry entry for ``google-vertex``
    3. Application Default Credentials (ADC) when no key is provided

    Args:
        config: Model endpoint configuration.
        provider_settings: Shared provider settings.
        http_client: Model-owned retrying HTTP client.

    Returns:
        Configured ``GoogleModel`` or ``AnthropicModel`` targeting Vertex AI.
    """
    from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
    from pydantic_ai.providers.google_cloud import GoogleCloudProvider

    if config.model_name.startswith("claude"):
        return _create_vertex_anthropic(config, provider_settings, http_client)

    api_key: str | None = None
    if config.api_key is not None:
        api_key = config.api_key.get_secret_value()
    elif (registry_key := provider_settings.api_keys.get(config.provider_name)) is not None:
        api_key = registry_key.get_secret_value()
    # Google Cloud supports Vertex Express Mode via API key and ADC via
    # project/location. ADC parameters deliberately take precedence.
    provider: GoogleCloudProvider
    uses_adc = config.google_project is not None or config.google_location is not None or api_key is None
    if uses_adc:
        project = config.google_project
        location = config.google_location
        if project is None or location is None:
            msg = "Google Vertex ADC requires both google_project and google_location"
            raise ValueError(msg)
        base_url = resolve_google_vertex_base_url(
            config.base_url,
            location=location,
            has_api_key=False,
        )
        provider = GoogleCloudProvider(
            project=project,
            location=location,
            http_client=http_client,
            base_url=base_url,
        )
    else:
        base_url = resolve_google_vertex_base_url(
            config.base_url,
            location=None,
            has_api_key=True,
        )
        provider = GoogleCloudProvider(api_key=api_key, http_client=http_client, base_url=base_url)
    settings = GoogleModelSettings(
        temperature=provider_settings.temperature,
        timeout=provider_settings.timeout_seconds,
    )
    if provider_settings.max_tokens is not None:
        settings["max_tokens"] = provider_settings.max_tokens

    thinking_config = _build_google_thinking_config(
        config.model_name,
        config.reasoning_effort,
    )
    if thinking_config is not None:
        settings["google_thinking_config"] = thinking_config
    return GoogleModel(config.model_name, provider=provider, settings=settings)


def _create_vertex_anthropic(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
    http_client: AsyncClient,
) -> AnthropicModel:
    """Create an Anthropic model running on Google Vertex AI.

    Uses ``AsyncAnthropicVertex`` from the Anthropic SDK which authenticates
    via Application Default Credentials.  API keys are NOT used: Vertex AI
    routes the request through GCP billing.

    Args:
        config: Model endpoint configuration with ``google_project`` and
            optional ``google_location``.
        provider_settings: Shared provider settings.
        http_client: Model-owned retrying HTTP client.

    Returns:
        Configured ``AnthropicModel`` backed by ``AsyncAnthropicVertex``.
    """
    from anthropic import AsyncAnthropicVertex
    from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
    from pydantic_ai.providers.anthropic import AnthropicProvider

    project = config.google_project
    region = config.google_location
    if project is None or region is None:
        msg = "Google Vertex Claude requires both google_project and google_location"
        raise ValueError(msg)
    vertex_client = AsyncAnthropicVertex(
        project_id=project,
        region=region,
        base_url=resolve_vertex_anthropic_base_url(config.base_url, region=region),
        http_client=http_client,
    )
    provider = AnthropicProvider(anthropic_client=vertex_client)

    settings = AnthropicModelSettings(
        temperature=provider_settings.temperature,
        timeout=provider_settings.timeout_seconds,
    )
    if provider_settings.max_tokens is not None:
        settings["max_tokens"] = provider_settings.max_tokens

    _apply_anthropic_reasoning(settings, config.model_name, config.reasoning_effort)
    return AnthropicModel(config.model_name, provider=provider, settings=settings)


def _resolve_api_key(
    config: LLMModelConfig,
    provider_settings: LLMProviderSettings,
) -> str:
    """Resolve a nonblank API key for an authenticated provider transport.

    Resolution order:

    1. Config's own nonblank ``api_key``
    2. Nonblank owning-chain ``api_keys`` registry entry
    3. Explicit placeholder for a keyless custom OpenAI-compatible endpoint
    4. Raise ``ValueError``

    Args:
        config: The model config that needs an API key.
        provider_settings: Full provider settings containing the ``api_keys`` registry.

    Returns:
        Resolved API key or an explicit custom-endpoint placeholder.

    Raises:
        ValueError: If no API key can be resolved for a non-keyless provider.
    """
    if config.api_key is not None:
        model_key = config.api_key.get_secret_value()
        if model_key.strip():
            return model_key

    registry_key = provider_settings.api_keys.get(config.provider_name)
    if registry_key is not None:
        resolved = registry_key.get_secret_value()
        if resolved.strip():
            return resolved

    if config.provider_name == "openai" and config.base_url is not None:
        return OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER

    provider_name = config.provider_name
    msg = f"No API key for model '{config.model}'. Add '{provider_name}' to api_keys or set api_key on the model."
    raise ValueError(msg)
