"""Configuration dataclasses for benchmark execution and evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, cast

from nohiki_llm_client import ApiKeyRegistry, LLMModelConfig, ReasoningEffort
from nohiki_llm_client.config.constants import (
    API_KEY_OPTIONAL_PROVIDERS,
    DEFAULT_MAX_TOOL_RETRIES,
    KEYLESS_PROVIDERS,
)
from pydantic import SecretStr

from llm_benchmark.config.constants import (
    DEFAULT_BENCHMARK_CONCURRENCY,
    DEFAULT_EVAL_CONCURRENCY,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_OLLAMA_TIMEOUT_SECONDS,
    JUDGE_APP_TITLE,
    JUDGE_MAX_RETRIES,
    JUDGE_TIMEOUT_SECONDS,
)

_VALID_REASONING_EFFORTS: Final[frozenset[str]] = frozenset(
    {"disabled", "low", "medium", "high"},
)

_LOCAL_JUDGE_PROVIDERS: Final[frozenset[str]] = frozenset({"llamacpp", "ollama"})

if TYPE_CHECKING:
    from llm_benchmark.pricing import PricingSnapshot
    from llm_benchmark.schemas.aggregation import JudgmentUnit
    from llm_benchmark.schemas.judge import PointwiseJudgment


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Configuration for benchmark execution.

    Attributes:
        models: Independent candidate model configurations using standard ``nohiki-llm-client`` semantics.
        fixture_ids: Test fixture IDs to use.
        runs_per_fixture: Number of extraction runs per fixture per model.
        api_keys: Provider API key registry for cloud providers (OpenRouter, OpenAI).
        timeout_seconds: Per-call timeout for cloud providers in seconds.
        temperature: Sampling temperature (0.0 for deterministic).
        max_concurrency: Max simultaneous LLM calls for cloud providers.
        reasoning_effort: Reasoning token effort level.
        ollama_base_url: Base URL for Ollama provider.
        ollama_timeout_seconds: Per-call timeout for Ollama models. Defaults to
            600 seconds to accommodate large local models.
        base_url: Base URL for OpenAI-compatible servers (llama.cpp, vLLM, etc.).
        max_tokens: Maximum output tokens per call. ``None`` (default) imposes no
            limit, allowing the provider to use its full context. Only set when
            you need to cap output length.
        max_retries: PydanticAI agent retries for structured output validation
            failures. Each retry sends the validation error back to the model as
            feedback so it can self-correct.
        pricing_snapshots: Immutable per-treatment pricing evidence, index-aligned
            with ``models``. Resolved once (one preflight per treatment) at CLI
            build time and folded into the experiment fingerprint so a resumed run
            cannot mix pricing policies. Empty means the runner resolves lazily.
    """

    models: tuple[LLMModelConfig, ...]
    fixture_ids: list[str]
    runs_per_fixture: int
    api_keys: ApiKeyRegistry = field(default_factory=ApiKeyRegistry)
    timeout_seconds: float = 120.0
    temperature: float = 0.0
    max_concurrency: int = DEFAULT_BENCHMARK_CONCURRENCY
    reasoning_effort: ReasoningEffort = "high"
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    base_url: str | None = None
    # Per-model API key override. When set, takes precedence over the api_keys
    # registry for every model in this benchmark session. Enables using a
    # custom endpoint without changing the shared credential registry.
    api_key: str | None = None
    max_tokens: int | None = None
    max_retries: int = DEFAULT_MAX_TOOL_RETRIES
    verbose: bool = False
    cost_cap_usd: float = 10.0
    unknown_price_max_usd: float | None = None
    pricing_snapshots: tuple[PricingSnapshot, ...] = ()

    @property
    def model_names(self) -> tuple[str, ...]:
        """Return candidate identifiers in treatment order."""
        return tuple(model.model for model in self.models)


def model_family(model: str) -> str:
    """Return underlying model lineage, independent of transport provider."""
    _provider, separator, raw_model_id = model.partition(":")
    if not separator:
        message = f"Model must use provider:model format: {model!r}"
        raise ValueError(message)

    model_id = raw_model_id.partition("@")[0].casefold()
    vendor, slash, model_name = model_id.partition("/")
    if slash:
        vendor_aliases = {
            "x-ai": "xai",
            "meta-llama": "meta",
            "moonshotai": "moonshot",
        }
        return vendor_aliases.get(vendor, vendor)

    lineage_markers = (
        ("anthropic", ("claude",)),
        ("openai", ("gpt", "codex", "o1", "o3", "o4")),
        ("google", ("gemini", "gemma")),
        ("qwen", ("qwen",)),
        ("deepseek", ("deepseek",)),
        ("xiaomi", ("mimo",)),
        ("meta", ("llama",)),
        ("mistral", ("mistral", "mixtral", "codestral")),
        ("moonshot", ("kimi", "moonshot")),
        ("xai", ("grok",)),
        ("cohere", ("command-r", "command-a")),
    )
    normalized = model_name or vendor
    for family, markers in lineage_markers:
        if any(normalized.startswith(marker) or f"-{marker}" in normalized for marker in markers):
            return family

    # Unknown lineages only collide when their complete normalized IDs match.
    return f"unknown:{normalized}"


@dataclass(frozen=True, slots=True)
class JudgeConfig:
    """Configuration for a single judge model.

    Attributes:
        model: Fully qualified model string (e.g., ``openrouter:openai/gpt-5.2``).
        reasoning_effort: Reasoning token effort level.
        weight: Weight for consensus calculation (default 1.0).
        provider_order: OpenRouter provider routing preference (e.g.,
            ``("atlas-cloud/fp8",)``). Empty tuple means no routing preference.
        provider_allow_fallbacks: Whether OpenRouter may route outside
            ``provider_order`` when preferred providers are unavailable. Mirrors
            ``LLMModelConfig``; must survive from the settings chain to dispatch.
        provider_zdr: Require OpenRouter Zero Data Retention routing. Mirrors
            ``LLMModelConfig``; must survive from the settings chain to dispatch.
        concurrency: Max parallel calls for this judge. ``None`` means
            auto-detect based on provider type (1 for local, DEFAULT_EVAL_CONCURRENCY
            for cloud).
        timeout_seconds: Per-request timeout for this judge. ``None`` falls back
            to ``JUDGE_TIMEOUT_SECONDS``.
        max_retries: PydanticAI structured-output validation retries for this
            judge. ``None`` falls back to ``JUDGE_MAX_RETRIES``.
    """

    model: str
    reasoning_effort: ReasoningEffort = "high"
    weight: float = 1.0
    provider_order: tuple[str, ...] = ()
    provider_allow_fallbacks: bool = True
    provider_zdr: bool = False
    concurrency: int | None = None
    # Optional custom API endpoint and key for the judge.
    # Both mirror LLMModelConfig semantics: base_url overrides the provider
    # default, api_key overrides the ApiKeyRegistry lookup.
    base_url: str | None = None
    api_key: str | None = None
    timeout_seconds: float | None = None
    max_retries: int | None = None

    def __post_init__(self) -> None:
        """Reject invalid consensus weights at configuration time."""
        if self.weight <= 0.0:
            message = "Judge weight must be greater than zero"
            raise ValueError(message)

    @property
    def effective_concurrency(self) -> int:
        """Resolve concurrency limit.

        Returns the explicit concurrency if set, otherwise falls back
        to ``DEFAULT_EVAL_CONCURRENCY``. Provider-level rate limiting
        (e.g., Ollama concurrency=1) is handled by ``nohiki-llm-client``
        via ``ConcurrencyLimitedModel``.

        Returns:
            Concrete concurrency limit for this judge's task parallelism.
        """
        return self.concurrency if self.concurrency is not None else DEFAULT_EVAL_CONCURRENCY

    @property
    def effective_timeout_seconds(self) -> float:
        """Resolve per-request timeout, falling back to ``JUDGE_TIMEOUT_SECONDS``."""
        return self.timeout_seconds if self.timeout_seconds is not None else JUDGE_TIMEOUT_SECONDS

    @property
    def effective_max_retries(self) -> int:
        """Resolve validation retry count, falling back to ``JUDGE_MAX_RETRIES``."""
        return self.max_retries if self.max_retries is not None else JUDGE_MAX_RETRIES

    @property
    def is_local(self) -> bool:
        """Whether this judge runs on a local zero-cost provider (llama.cpp/Ollama)."""
        return self.model.partition(":")[0] in _LOCAL_JUDGE_PROVIDERS

    @property
    def requires_registry_key(self) -> bool:
        """Whether dispatch needs a shared secret-registry key for this judge.

        Mirrors ``LLMProviderSettings`` key resolution: an explicit per-model
        ``api_key``, a keyless provider (llama.cpp/Ollama), a key-optional
        provider (Google Vertex), or an OpenAI-compatible endpoint with an
        explicit ``base_url`` all need no registry entry, so those judge sets
        require no secret directory.
        """
        if self.api_key is not None:
            return False
        provider = self.model.partition(":")[0]
        if provider in KEYLESS_PROVIDERS or provider in API_KEY_OPTIONAL_PROVIDERS:
            return False
        return not (provider == "openai" and self.base_url is not None)

    @property
    def identity_key(self) -> str:
        """Dispatch identity: every routing/effort setting that changes the call.

        Weight is deliberately excluded (it is a consensus knob, not a route).
        Two judges sharing this key would dispatch identically and, because
        results are keyed by ``model``, cannot coexist without silent collapse.
        """
        return (
            f"{self.model}|effort={self.reasoning_effort}"
            f"|providers={','.join(self.provider_order)}"
            f"|fallbacks={self.provider_allow_fallbacks}"
            f"|zdr={self.provider_zdr}"
            f"|base_url={self.base_url or ''}"
        )

    def to_model_config(self) -> LLMModelConfig:
        """Canonical single source for both dispatch and route-aware pricing.

        Carries ``provider_order``/``provider_allow_fallbacks``/``provider_zdr``
        so client construction and pricing resolution never diverge.
        """
        return LLMModelConfig(
            model=self.model,
            reasoning_effort=self.reasoning_effort,
            app_title=JUDGE_APP_TITLE,
            provider_order=self.provider_order,
            provider_allow_fallbacks=self.provider_allow_fallbacks,
            provider_zdr=self.provider_zdr,
            base_url=self.base_url,
            api_key=SecretStr(self.api_key) if self.api_key else None,
        )

    @classmethod
    def from_string(
        cls,
        spec: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        concurrency: int | None = None,
        weight: float = 1.0,
    ) -> JudgeConfig:
        """Parse a judge spec string into a ``JudgeConfig``.

        Format: ``model:effort@provider1,provider2`` or just ``model``.
        The ``@`` suffix specifies OpenRouter provider routing.
        The effort suffix is identified by matching against known effort levels.

        Examples:
            - ``openrouter:openai/gpt-5.2:high``
            - ``openrouter:qwen/qwen3.5-35b-a3b@atlas-cloud/fp8``
            - ``openrouter:qwen/qwen3.5-35b-a3b:high@atlas-cloud/fp8``
            - ``ollama:qwen3:30b`` (defaults to high)
            - ``anthropic:claude-sonnet-4-6`` (with --base-url / --api-key)

        Args:
            spec: Judge specification string.
            base_url: Optional API endpoint override.
            api_key: Optional per-model API key override.
            concurrency: Optional maximum parallel calls for this judge.
            weight: Positive consensus weight for this judge.

        Returns:
            Parsed ``JudgeConfig``.
        """
        provider_order: tuple[str, ...] = ()
        if "@" in spec:
            spec, provider_part = spec.rsplit("@", maxsplit=1)
            provider_order = tuple(p.strip() for p in provider_part.split(",") if p.strip())

        parts = spec.rsplit(":", maxsplit=1)

        if len(parts) == 2 and parts[1] in _VALID_REASONING_EFFORTS:
            return cls(
                model=parts[0],
                reasoning_effort=cast("ReasoningEffort", parts[1]),
                weight=weight,
                provider_order=provider_order,
                concurrency=concurrency,
                base_url=base_url,
                api_key=api_key,
            )

        return cls(
            model=spec,
            weight=weight,
            provider_order=provider_order,
            concurrency=concurrency,
            base_url=base_url,
            api_key=api_key,
        )


@dataclass(frozen=True, slots=True)
class EvaluationResumeState:
    """Resume state for a partially-completed single-judge evaluation.

    Attributes:
        skip_task_keys: Set of task keys (model::fixture::run) to skip.
        existing_judgments: Pre-populated judgments from checkpoint.
        existing_units: Exact completed evaluation units from checkpoint.
        existing_cost_usd: Accumulated actual provider cost from checkpoint.
        existing_charged_usd: Accumulated budget-charged cost (actual for
            successes, fail-closed reservation for failures) that seeds the
            resumed scheduler so repeated resume cannot exceed the cap.
        existing_completed_count: Number of already-completed tasks.
    """

    skip_task_keys: frozenset[str] = field(default_factory=frozenset)
    existing_judgments: dict[str, list[PointwiseJudgment]] = field(default_factory=dict)
    existing_units: tuple[JudgmentUnit, ...] = ()
    existing_cost_usd: float = 0.0
    existing_charged_usd: float = 0.0
    existing_completed_count: int = 0
