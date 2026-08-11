"""LLM provider configuration settings and mixin for Nohiki services.

Uses PydanticAI's ``provider:model`` string format as the canonical model
identifier. Models are configured as a priority-ordered list with a
cross-provider API key registry and optional named per-use-case chains.
"""

import logging
from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from nohiki_llm_client.transport import validate_http_base_url

from .constants import (
    API_KEY_OPTIONAL_PROVIDERS,
    DEFAULT_APP_TITLE,
    DEFAULT_MAX_TOOL_RETRIES,
    DEFAULT_OLLAMA_NUM_CTX,
    DEFAULT_OLLAMA_REPEAT_PENALTY,
    DEFAULT_OLLAMA_TOP_K,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT_SECONDS,
    KEYLESS_PROVIDERS,
    LLM_MODEL_SEPARATOR,
    OLLAMA_MAX_CONTEXT,
    OLLAMA_MIN_CONTEXT,
    PROVIDER_MAX_TOKENS,
    PROVIDER_REQUEST_TIMEOUT_MAX,
    PROVIDER_TOOL_RETRIES_MAX,
    ReasoningEffort,
)

_logger = logging.getLogger(__name__)


def _validate_provider_identifier(value: object) -> str:
    """Require a canonical lowercase provider identifier."""
    if not isinstance(value, str) or not value:
        msg = "provider name must be a nonblank string"
        raise ValueError(msg)
    labels = value.split("-")
    if any(not label or not label.isascii() or not label.isalnum() or label.lower() != label for label in labels):
        msg = "provider name must use canonical lowercase letters, digits, and single hyphens"
        raise ValueError(msg)
    return value


class ApiKeyRegistry(BaseModel):
    """Cross-provider API key registry mapping provider names to secret keys.

    Values are coerced to ``SecretStr`` on construction, preventing accidental
    logging of API keys in repr, str, or serialization output.

    Uses ``extra="allow"`` so any provider name can be stored dynamically.

    Environment variable format::

        LLM__PROVIDER__API_KEYS__OPENROUTER=sk-or-...
        LLM__PROVIDER__API_KEYS__OPENAI=sk-proj-...

    File secret format::

        /run/secrets/llm/provider/api_keys/openrouter
        /run/secrets/llm/provider/api_keys/openai
    """

    model_config = {"extra": "allow", "frozen": True}

    @model_validator(mode="before")
    @classmethod
    def _coerce_values_to_secret(cls, data: object) -> object:
        """Wrap nonblank string values in ``SecretStr`` and omit blank keys."""
        if not isinstance(data, dict):
            return data
        keys: dict[str, object] = {}
        for raw_key, value in data.items():
            key = _validate_provider_identifier(raw_key)
            if isinstance(value, SecretStr):
                if value.get_secret_value().strip():
                    keys[key] = value
            elif isinstance(value, str):
                if value.strip():
                    keys[key] = SecretStr(value)
            else:
                keys[key] = value
        return keys

    def get(self, provider_name: str) -> SecretStr | None:
        """Look up API key by provider name.

        Args:
            provider_name: Provider identifier (e.g., ``"openrouter"``).

        Returns:
            Secret API key or ``None`` if not registered.
        """
        if self.model_extra is None:
            return None
        val = self.model_extra.get(provider_name)
        if isinstance(val, SecretStr) and val.get_secret_value().strip():
            return val
        return None

    def __contains__(self, key: object) -> bool:
        """Check if a provider has a usable registered API key."""
        return isinstance(key, str) and self.get(key) is not None

    def __bool__(self) -> bool:
        """True if any usable API keys are registered."""
        return any(self.get(key) is not None for key in (self.model_extra or {}))

    def __len__(self) -> int:
        """Number of usable registered API keys."""
        return sum(self.get(key) is not None for key in (self.model_extra or {}))


def _parse_ordered_models(v: object) -> list:
    """Convert dict-style model list from env vars to priority-ordered list.

    pydantic-settings v2 parses ``LLM__PROVIDER__MODELS__0__MODEL`` as
    ``{'models': {'0': {'model': ...}}}`` instead of a list.
    This validator converts the dict format to a sorted list.

    Args:
        v: Either a dict with numeric string keys, a list, or None.

    Returns:
        Priority-ordered list of model configs, sorted by numeric key.
    """
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        sorted_items = sorted(
            ((int(k), item) for k, item in v.items() if isinstance(k, str) and k.isdigit()),
            key=lambda x: x[0],
        )
        return [item for _, item in sorted_items]
    return []


type ModelsList = Annotated[list[LLMModelConfig], BeforeValidator(_parse_ordered_models)]

type CacheTTL = Literal["5m", "1h"]


class LLMModelConfig(BaseModel):
    """Single model endpoint using PydanticAI's ``provider:model`` format.

    The ``model`` field MUST contain a colon-separated provider prefix:

    - ``"openai:configured-primary"`` for an OpenAI-compatible endpoint
    - ``"openrouter:configured/fallback"`` for an OpenRouter model
    - ``"anthropic:configured-generation"`` for a native Anthropic model
    - ``"ollama:configured-local"`` for local inference

    Attributes:
        model: Fully qualified model string in ``provider:model_name`` format.
        reasoning_effort: Reasoning token effort level for this model.
            Controls thinking depth: ``"disabled"`` turns off reasoning entirely,
            ``"low"`` / ``"medium"`` / ``"high"`` map to provider-specific
            parameters (``anthropic_effort``, ``budget_tokens``,
            ``openai_reasoning_effort``, etc.).
        api_key: Per-model API key override. When set, takes precedence over the
            ``api_keys`` registry in ``LLMProviderSettings``. Optional.
        base_url: Custom API base URL. OpenAI-compatible providers require a
            terminal ``/v1`` path; Anthropic requires a base without ``/v1``.
        health_url: Explicit unauthenticated preliminary health endpoint for cloud
            providers. A successful liveness response is followed by a bounded
            exact-model request. Ollama and llama.cpp require their exact native
            probes and reject this override.
        tls_ca_file: Optional CA file that extends system trust only for this
            model's provider transport and health checks.
        app_title: Application identifier sent to providers (OpenRouter X-Title header).
        app_url: Application URL sent to OpenRouter in the HTTP-Referer header.
        provider_order: OpenRouter provider routing preference.
        provider_allow_fallbacks: Whether OpenRouter may route to providers outside
            ``provider_order`` when preferred providers are unavailable.
        provider_zdr: Require OpenRouter Zero Data Retention. When ``True``, the
            factory sends ``provider.zdr = true`` on every request so OpenRouter
            routes only to endpoints that neither log nor retain prompt/response
            data. Merged alongside ``provider_order`` when both are set. Ignored
            by non-OpenRouter transports. Defaults to ``False``.
        google_project: Explicit GCP project ID for Google Vertex ADC. Must be
            configured together with ``google_location``.
        google_location: Explicit GCP region for Google Vertex endpoint routing.
            Required with ``google_project``. Gemini may instead use an explicit
            per-model or registry API key for Vertex Express Mode.
    """

    model_config = {"frozen": True}

    model: str
    reasoning_effort: ReasoningEffort = DEFAULT_REASONING_EFFORT
    api_key: SecretStr | None = None
    base_url: str | None = None
    health_url: str | None = Field(default=None, min_length=1)
    tls_ca_file: str | None = Field(default=None, min_length=1)
    app_title: str = DEFAULT_APP_TITLE
    app_url: str | None = None
    provider_order: tuple[str, ...] = ()
    provider_allow_fallbacks: bool = True
    provider_zdr: bool = False
    google_project: str | None = None
    google_location: str | None = None

    @field_validator("model")
    @classmethod
    def _validate_model_identifier(cls, value: str) -> str:
        """Require nonblank canonical provider and model ID segments."""
        provider, separator, model_name = value.partition(LLM_MODEL_SEPARATOR)
        if not separator:
            msg = "model must use 'provider:model_name' format"
            raise ValueError(msg)
        _validate_provider_identifier(provider)
        if not model_name or model_name != model_name.strip() or any(character.isspace() for character in model_name):
            msg = "model name must be nonblank and contain no whitespace"
            raise ValueError(msg)
        return value

    @field_validator("api_key")
    @classmethod
    def _validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject explicitly configured blank model credentials."""
        if value is not None and not value.get_secret_value().strip():
            msg = "api_key must be nonblank when configured"
            raise ValueError(msg)
        return value

    @field_validator("google_project", "google_location")
    @classmethod
    def _validate_google_routing_value(cls, value: str | None) -> str | None:
        """Normalize and reject blank explicit Vertex ADC routing values."""
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            msg = "Google Vertex project and location must be nonblank when configured"
            raise ValueError(msg)
        return normalized

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        """Require every explicit provider endpoint to be a safe HTTP(S) base URL."""
        return None if value is None else validate_http_base_url(value)

    @field_validator("health_url")
    @classmethod
    def _validate_health_url(cls, value: str | None) -> str | None:
        """Require an explicit health endpoint to be a safe absolute HTTP(S) URL."""
        return None if value is None else validate_http_base_url(value, field_name="health_url")

    @field_validator("provider_order", mode="before")
    @classmethod
    def _coerce_provider_order(cls, v: object) -> object:
        """Coerce dict from Pydantic settings nested env var parsing into an ordered tuple.

        Contract for dict inputs (produced by env vars like ``PROVIDER_ORDER__0=x``):

        - Keys MUST be numeric strings (``"0"``, ``"1"``, ...). Non-numeric keys
          raise ``ValueError`` because they signal a misconfigured env var name.
        - Indices MUST be contiguous starting at 0. Gaps (``0, 2`` with no ``1``)
          raise ``ValueError`` since silent reordering would mask configuration bugs.
        - Duplicate values are allowed but emit a warning, they're almost always
          a copy-paste mistake and OpenRouter routing only honors the first hit.

        Non-dict inputs (lists, tuples, ``None``) pass through unchanged.
        """
        if not isinstance(v, dict):
            return v
        d = cast("dict[str, str]", v)

        non_numeric = [k for k in d if not (isinstance(k, str) and k.isdigit())]
        if non_numeric:
            msg = (
                f"provider_order keys must be numeric strings from PROVIDER_ORDER__N env vars; "
                f"got non-numeric key(s): {sorted(non_numeric)!r}"
            )
            raise ValueError(msg)

        indices = sorted(int(k) for k in d)
        expected = list(range(len(indices)))
        if indices != expected:
            msg = f"provider_order indices must be contiguous starting at 0; got {indices} (expected {expected})"
            raise ValueError(msg)

        ordered = tuple(d[str(i)] for i in indices)
        if len(set(ordered)) != len(ordered):
            _logger.warning(
                "provider_order contains duplicate provider names %r; OpenRouter only honors the first occurrence",
                ordered,
            )
        return ordered

    @property
    def provider_name(self) -> str:
        """Extract provider prefix from model string.

        Returns:
            Provider name (e.g., ``"openrouter"``, ``"openai"``, ``"ollama"``).

        Raises:
            ValueError: If model string has no colon separator.
        """
        if LLM_MODEL_SEPARATOR not in self.model:
            msg = (
                f"Model '{self.model}' must use 'provider:model_name' format "
                f"(e.g., 'openrouter:google/gemini-3-flash-preview')"
            )
            raise ValueError(msg)
        return self.model.split(LLM_MODEL_SEPARATOR, maxsplit=1)[0]

    @property
    def model_name(self) -> str:
        """Extract model name portion after provider prefix.

        Returns:
            Model name (e.g., ``"google/gemini-3-flash-preview"``, ``"gpt-4o"``).
        """
        return self.model.split(LLM_MODEL_SEPARATOR, maxsplit=1)[1]

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        """Validate provider-specific requirements.

        API key presence for cloud providers is validated at the
        ``LLMProviderSettings`` level where the ``api_keys`` registry
        is available.
        """
        provider = self.provider_name

        if provider in {"llamacpp", "ollama"}:
            if self.base_url is None or not self.base_url.strip():
                msg = f"{provider} provider requires base_url to be nonempty (for example, 'http://localhost:11434/v1')"
                raise ValueError(msg)
            if not self.base_url.rstrip("/").endswith("/v1"):
                msg = f"{provider} base_url must end with the OpenAI-compatible /v1 path"
                raise ValueError(msg)
            if self.health_url is not None:
                msg = f"{provider} provider does not support health_url overrides"
                raise ValueError(msg)

        if (
            provider in {"openai", "openrouter"}
            and self.base_url is not None
            and not self.base_url.rstrip("/").endswith("/v1")
        ):
            msg = f"{provider} base_url must end with the OpenAI-compatible /v1 path"
            raise ValueError(msg)

        if provider == "anthropic" and self.base_url is not None and self.base_url.rstrip("/").endswith("/v1"):
            msg = "anthropic base_url must exclude the SDK-managed terminal /v1 path"
            raise ValueError(msg)

        if (
            provider == "google-vertex"
            and self.model_name.startswith("claude")
            and self.base_url is not None
            and self.base_url.rstrip("/").endswith("/v1")
        ):
            msg = "Google Vertex Claude base_url must exclude the SDK-managed terminal /v1 path"
            raise ValueError(msg)
        return self


class OllamaSettings(BaseModel):
    """Ollama-specific runtime options.

    These settings are only applied when the primary provider is Ollama.
    Runtime options go in ``extra_body.options``, while ``think`` is a
    top-level parameter per Ollama's API specification.

    Attributes:
        num_ctx: Context window size in tokens. Larger values allow more context
            but require more memory.
        top_k: Limits token selection to top K candidates. Lower values are more
            focused, higher values are more diverse.
        repeat_penalty: Penalty for repeating tokens. Values >1.0 discourage
            repetition, <1.0 encourage it.
        think: Enable extended thinking/reasoning mode. When True, the model
            returns reasoning in a separate field that PydanticAI extracts
            as ``ThinkingPart`` objects. This is a TOP-LEVEL request parameter,
            not nested in options.
    """

    model_config = {"frozen": True}

    num_ctx: int = Field(
        default=DEFAULT_OLLAMA_NUM_CTX,
        ge=OLLAMA_MIN_CONTEXT,
        le=OLLAMA_MAX_CONTEXT,
    )
    top_k: int = Field(default=DEFAULT_OLLAMA_TOP_K, ge=1, le=100)
    repeat_penalty: float = Field(default=DEFAULT_OLLAMA_REPEAT_PENALTY, ge=0.0, le=2.0)
    think: bool = True

    def to_options_dict(self) -> dict[str, int | float]:
        """Convert runtime options to Ollama options dict.

        Note: ``think`` is NOT included here as it's a top-level parameter,
        not an option. It's handled separately in factory.py.

        Returns:
            Dict suitable for passing as ``extra_body.options``.
        """
        return {
            "num_ctx": self.num_ctx,
            "top_k": self.top_k,
            "repeat_penalty": self.repeat_penalty,
        }


class LLMProviderSettings(BaseModel):
    """Priority-ordered model chain with cross-provider API key registry.

    Models are tried in list order: ``models[0]`` is used first, with
    subsequent entries as automatic fallbacks on failure.

    API keys are resolved per-model in order:

    1. The model's own ``api_key`` (if set)
    2. The ``api_keys`` registry (keyed by provider name)

    Attributes:
        models: Priority-ordered list of model configs. At least one required.
            First entry is the highest-priority model.
        api_keys: Provider API key registry mapping provider name to key.
            Shared across all models: define once per provider.
        temperature: Sampling temperature for all models.
        max_tokens: Maximum output tokens for all models. ``None`` means no explicit
            limit (provider decides). Only set this when you need to cap output length.
        timeout_seconds: Per-request timeout.
        max_tool_retries: PydanticAI agent-level tool retry count for structured output
            validation failures. HTTP-level retries are handled separately by the transport.
        concurrency_limit: Max concurrent requests. Uses PydanticAI ConcurrencyLimitedModel.
        ollama: Ollama-specific runtime options. Only applied when provider is Ollama.
    """

    models: ModelsList
    api_keys: ApiKeyRegistry = Field(default_factory=ApiKeyRegistry)
    temperature: float = Field(default=DEFAULT_TEMPERATURE, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=PROVIDER_MAX_TOKENS)
    timeout_seconds: float = Field(default=DEFAULT_TIMEOUT_SECONDS, ge=1.0, le=PROVIDER_REQUEST_TIMEOUT_MAX)
    max_tool_retries: int = Field(default=DEFAULT_MAX_TOOL_RETRIES, ge=0, le=PROVIDER_TOOL_RETRIES_MAX)
    concurrency_limit: int | None = Field(
        default=None,
        ge=1,
        le=100,
        description="Max concurrent requests to this model. Uses PydanticAI ConcurrencyLimitedModel.",
    )
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)

    @model_validator(mode="after")
    def _validate_models(self) -> Self:
        """Ensure every configured authenticated model has a resolvable key."""
        if not self.models:
            msg = "At least one model is required in 'models'"
            raise ValueError(msg)
        for model in self.models:
            is_keyless_custom_openai = model.provider_name == "openai" and model.base_url is not None
            if model.provider_name == "google-vertex":
                has_project = model.google_project is not None
                has_location = model.google_location is not None
                has_explicit_key = model.api_key is not None or self.api_keys.get(model.provider_name) is not None
                is_claude = model.model_name.startswith("claude")
                if has_project != has_location:
                    msg = "Google Vertex requires an explicit api_key or both google_project and google_location"
                    raise ValueError(msg)
                if is_claude and not has_project:
                    msg = (
                        "Google Vertex Claude requires both google_project and "
                        "google_location; api_key Express mode is not supported"
                    )
                    raise ValueError(msg)
                if not has_project and not has_explicit_key:
                    msg = "Google Vertex requires an explicit api_key or both google_project and google_location"
                    raise ValueError(msg)
            requires_key = (
                model.provider_name not in KEYLESS_PROVIDERS
                and model.provider_name not in API_KEY_OPTIONAL_PROVIDERS
                and not is_keyless_custom_openai
            )
            if requires_key and model.api_key is None and model.provider_name not in self.api_keys:
                msg = f"Provider '{model.provider_name}' requires an api_key on the model or an entry in api_keys"
                raise ValueError(msg)
        return self


class LLMInstrumentationSettings(BaseModel):
    """LLM observability configuration for Phoenix/OpenInference tracing.

    When enabled, wraps the model chain with PydanticAI's ``InstrumentationSettings``.
    Traces are exported via gRPC OTLP to the Phoenix collector.

    Attributes:
        enabled: Whether to enable instrumentation.
        collector_endpoint: Phoenix collector gRPC endpoint.
        project_name: Phoenix project name for trace grouping.
        service_name: Service identifier in traces.
        batch_export: Use ``BatchSpanProcessor`` (True) or ``SimpleSpanProcessor`` (False).
        export_timeout_seconds: OTLP export timeout.
    """

    model_config = {"frozen": True}

    enabled: bool = False
    collector_endpoint: str = ""
    project_name: str = "nohiki"
    service_name: str = "nohiki-llm"
    batch_export: bool = True
    export_timeout_seconds: float = Field(default=10.0, ge=1.0, le=60.0)


class LLMCachingSettings(BaseModel):
    """Prompt caching configuration for OpenRouter and Anthropic providers.

    Caching strategy varies by provider:

    - **OpenRouter**: ``CachingOpenRouterModel`` injects ``cache_control``
      on system prompt message blocks before dispatching the request.
    - **Anthropic**: Native caching via ``AnthropicModelSettings`` fields
      (``anthropic_cache_instructions``, ``anthropic_cache_tool_definitions``,
      ``anthropic_cache_messages``). Works with both the direct Anthropic API
      and custom Anthropic-compatible endpoints that forward ``cache_control``.

    Only applies to the primary model in the chain.

    Attributes:
        enabled: Whether to enable prompt caching.
        ttl: Cache time-to-live (``"5m"`` or ``"1h"``).
        track_metrics: Whether to emit cache hit/miss metrics.
    """

    enabled: bool = True
    ttl: CacheTTL = "5m"
    track_metrics: bool = True


def _model_config_entries(raw: object) -> list[dict[str, object]]:
    """Return mutable model configuration mappings from list or indexed-dict input."""
    match raw:
        case list():
            values = raw
        case dict():
            values = list(raw.values())
        case _:
            return []
    return [cast("dict[str, object]", value) for value in values if isinstance(value, dict)]


def _inherit_model_base_urls(provider_data: dict[str, object], chains_data: dict[str, dict[str, object]]) -> None:
    """Propagate provider endpoints to same-provider models without endpoint-specific credentials."""
    provider_models = _model_config_entries(provider_data.get("models"))
    base_urls: dict[str, object] = {}
    for model in provider_models:
        if isinstance(model_name := model.get("model"), str) and (base_url := model.get("base_url")):
            base_urls.setdefault(model_name.partition(LLM_MODEL_SEPARATOR)[0], base_url)

    all_models = provider_models + [
        model for chain_data in chains_data.values() for model in _model_config_entries(chain_data.get("models"))
    ]
    for model in all_models:
        if model.get("base_url") or model.get("api_key") or not isinstance(model_name := model.get("model"), str):
            continue
        if base_url := base_urls.get(model_name.partition(LLM_MODEL_SEPARATOR)[0]):
            model["base_url"] = base_url


class LLMSettings(BaseModel):
    """Top-level LLM configuration container.

    Composed into service settings via ``LLMMixin``.

    Environment variables (with service prefix)::

        {PREFIX}__LLM__PROVIDER__MODELS__0__MODEL=openai:configured-primary
        {PREFIX}__LLM__PROVIDER__MODELS__0__REASONING_EFFORT=high
        {PREFIX}__LLM__PROVIDER__MODELS__1__MODEL=openrouter:configured/fallback
        {PREFIX}__LLM__PROVIDER__MODELS__1__REASONING_EFFORT=high
        {PREFIX}__LLM__CHAINS__EXTRACTION__MODELS__0__MODEL=anthropic:configured-extraction
        {PREFIX}__LLM__CHAINS__EXTRACTION__MODELS__0__REASONING_EFFORT=low
        {PREFIX}__LLM__PROVIDER__API_KEYS__OPENAI=...
        {PREFIX}__LLM__CACHING__ENABLED=true
        {PREFIX}__LLM__INSTRUMENTATION__ENABLED=true

    Per-use-case named chains (optional, falls back to ``provider``)::

        {PREFIX}__LLM__CHAINS__SKILL_CLARIFICATION__MODELS__0__MODEL=...

    Chains automatically inherit API keys and same-provider model endpoints from
    the default provider unless they define their own values. This allows a single
    secrets mount to serve every named chain and same-provider fallback.

    Attributes:
        provider: Default model chain. Used when no named chain is requested.
        chains: Named per-use-case model chains. Falls back to ``provider``
            when a requested chain name is not found. Inherits provider credentials and endpoints.
        caching: Prompt caching configuration.
        instrumentation: Phoenix/OpenInference tracing configuration.
    """

    provider: LLMProviderSettings
    chains: dict[str, LLMProviderSettings] = Field(default_factory=dict)
    caching: LLMCachingSettings = Field(default_factory=LLMCachingSettings)
    instrumentation: LLMInstrumentationSettings = Field(
        default_factory=LLMInstrumentationSettings,
    )

    @model_validator(mode="before")
    @classmethod
    def _inherit_provider_defaults_to_chains(cls, data: dict[str, object]) -> dict[str, object]:
        """Propagate provider credentials and endpoints to named chains."""
        provider_raw = data.get("provider")
        chains_raw = data.get("chains")

        if not isinstance(provider_raw, dict):
            return data

        provider_data = cast("dict[str, object]", provider_raw)
        chains_data = cast("dict[str, dict[str, object]]", chains_raw) if isinstance(chains_raw, dict) else {}
        if provider_api_keys := provider_data.get("api_keys"):
            for chain_data in chains_data.values():
                if not chain_data.get("api_keys"):
                    chain_data["api_keys"] = provider_api_keys

        _inherit_model_base_urls(provider_data, chains_data)

        return data


class LLMMixin:
    """Settings mixin providing ``llm`` field to services.

    Combine with ``NohikiBaseSettings`` in service config::

        class Settings(LLMMixin, KafkaMixin, NohikiBaseSettings):
            model_config = SettingsConfigDict(env_prefix="DOC_CONTENT_")

    Validation is handled by ``LLMModelConfig._validate_config()`` at parse time,
    which enforces API keys for cloud providers and base_url for Ollama.
    """

    llm: LLMSettings
