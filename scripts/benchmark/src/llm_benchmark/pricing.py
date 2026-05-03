"""Cost calculation for LLM benchmark runs.

Route-aware pricing for explicitly routed OpenRouter treatments: when a config
sets ``provider_order`` with ``provider_allow_fallbacks`` disabled, pricing is
resolved from the selected named endpoints via the OpenRouter endpoints API,
taking the conservative maximum input/output rate across the permitted
providers. Every other cloud treatment falls back to the generic
``genai_prices`` model-level snapshot; local llama.cpp/Ollama are zero cost.

A :class:`PricingSnapshot` is resolved once per treatment (one network fetch
for routed treatments) and threaded, immutable, through the estimate display,
pre-dispatch budget reservation, and recorded actual cost so a resumed run can
never mix pricing policies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

import genai_prices
import httpx
from pydantic_ai.usage import RequestUsage

if TYPE_CHECKING:
    from nohiki_llm_client import LLMModelConfig
    from pydantic_ai.usage import RunUsage

_PROVIDER_API_URLS: Final[dict[str, str]] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com",
}

_OPENROUTER_PROVIDER: Final[str] = "openrouter"
_LOCAL_PROVIDERS: Final[frozenset[str]] = frozenset({"llamacpp", "ollama"})
_OPENROUTER_API_BASE: Final[str] = "https://openrouter.ai/api/v1"
_ONE_MILLION: Final[int] = 1_000_000
_ENDPOINTS_TIMEOUT_SECONDS: Final[float] = 30.0

_SOURCE_LOCAL: Final[str] = "local"
_SOURCE_OPENROUTER_ENDPOINT: Final[str] = "openrouter_endpoint"
_SOURCE_GENAI: Final[str] = "genai_prices"
_SOURCE_UNKNOWN: Final[str] = "unknown"


class PricingRouteError(ValueError):
    """Raised when an explicit OpenRouter route has no matching endpoint."""


@dataclass(frozen=True, slots=True)
class EndpointRate:
    """Per-million input/output pricing for one named OpenRouter endpoint."""

    provider_name: str
    input_per_million_usd: float
    output_per_million_usd: float


@dataclass(frozen=True, slots=True)
class PricingSnapshot:
    """Immutable pricing evidence for one treatment, fixed for the whole run.

    ``input_per_million_usd``/``output_per_million_usd`` are ``None`` only when
    pricing is genuinely unknown (``source == "unknown"``); local treatments
    carry ``0.0``.
    """

    input_per_million_usd: float | None
    output_per_million_usd: float | None
    source: str
    endpoints: tuple[EndpointRate, ...] = ()

    @property
    def is_known(self) -> bool:
        """Whether both per-million rates are resolved."""
        return self.input_per_million_usd is not None and self.output_per_million_usd is not None

    def per_million(self) -> tuple[float | None, float | None]:
        """Return ``(input_per_million_usd, output_per_million_usd)`` for display."""
        return (self.input_per_million_usd, self.output_per_million_usd)

    def calc_cost(self, input_tokens: int, output_tokens: int) -> float | None:
        """Return linear USD cost for the given tokens, or ``None`` when unknown."""
        if input_tokens < 0 or output_tokens < 0:
            msg = "Token counts must be non-negative"
            raise ValueError(msg)
        if self.input_per_million_usd is None or self.output_per_million_usd is None:
            return None
        return (input_tokens * self.input_per_million_usd + output_tokens * self.output_per_million_usd) / _ONE_MILLION

    def maximum_call_cost(
        self,
        *,
        max_input_tokens: int,
        max_output_tokens: int,
        unknown_price_max_usd: float | None = None,
    ) -> float:
        """Resolve the worst-case USD to reserve before one call.

        Known pricing uses the snapshot rates at the supplied hard token bounds.
        Unknown pricing requires an owner-supplied positive per-call maximum.
        """
        if max_input_tokens < 0 or max_output_tokens < 0:
            msg = "Token bounds must be non-negative"
            raise ValueError(msg)
        maximum = self.calc_cost(max_input_tokens, max_output_tokens)
        if maximum is not None:
            return maximum
        if unknown_price_max_usd is None:
            msg = "Pricing is unavailable for this treatment; provide an explicit per-call maximum"
            raise ValueError(msg)
        if unknown_price_max_usd <= 0:
            msg = "Explicit per-call maximum must be greater than zero"
            raise ValueError(msg)
        return unknown_price_max_usd

    def recorded_cost(
        self,
        *,
        client_cost: float | None,
        input_tokens: int,
        output_tokens: int,
    ) -> float | None:
        """Recorded actual cost, threaded through this immutable snapshot.

        Routed OpenRouter treatments bill at the snapshot's conservative route
        rate applied to observed tokens; local llama.cpp/Ollama is always zero;
        unrouted cloud / unknown treatments keep the client-reported cost.
        """
        if self.source == _SOURCE_OPENROUTER_ENDPOINT:
            return self.calc_cost(input_tokens, output_tokens)
        if self.source == _SOURCE_LOCAL:
            return 0.0
        return client_cost

    def fingerprint_material(self) -> dict[str, object]:
        """Return JSON-serialisable identity for experiment/treatment fingerprints."""
        return {
            "source": self.source,
            "input_per_million_usd": self.input_per_million_usd,
            "output_per_million_usd": self.output_per_million_usd,
            "endpoints": [
                [rate.provider_name, rate.input_per_million_usd, rate.output_per_million_usd] for rate in self.endpoints
            ],
        }


def fetch_openrouter_endpoints(
    model_slug: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
) -> tuple[EndpointRate, ...]:
    """Fetch per-endpoint pricing for an OpenRouter model.

    Queries ``GET {base}/models/{model_slug}/endpoints``. ``model_slug`` keeps
    its ``author/model`` slash as unescaped path segments. Returns one
    :class:`EndpointRate` per endpoint that publishes prompt/completion pricing;
    per-token rates are scaled to per-million USD.
    """
    api_base = (base_url or _OPENROUTER_API_BASE).rstrip("/")
    url = f"{api_base}/models/{model_slug}/endpoints"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    response = httpx.get(url, headers=headers, timeout=_ENDPOINTS_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    endpoints = data.get("endpoints") if isinstance(data, dict) else None
    if not isinstance(endpoints, list):
        return ()
    rates: list[EndpointRate] = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        provider_name = endpoint.get("provider_name")
        pricing = endpoint.get("pricing")
        if not isinstance(provider_name, str) or not isinstance(pricing, dict):
            continue
        prompt = pricing.get("prompt")
        completion = pricing.get("completion")
        if prompt is None or completion is None:
            continue
        rates.append(
            EndpointRate(
                provider_name=provider_name,
                input_per_million_usd=float(prompt) * _ONE_MILLION,
                output_per_million_usd=float(completion) * _ONE_MILLION,
            )
        )
    return tuple(rates)


def resolve_pricing_snapshot(model: LLMModelConfig) -> PricingSnapshot:
    """Resolve one immutable pricing snapshot for a treatment (one preflight).

    - Local llama.cpp/Ollama: zero cost.
    - OpenRouter with a non-empty ``provider_order`` and ``provider_allow_fallbacks``
      disabled: prices come from the selected named endpoints, taking the
      conservative maximum input/output rate across the permitted providers. A
      missing route raises :class:`PricingRouteError`.
    - Every other cloud treatment: generic ``genai_prices`` model-level pricing.
    """
    provider = model.provider_name
    if provider in _LOCAL_PROVIDERS:
        return PricingSnapshot(0.0, 0.0, _SOURCE_LOCAL)

    model_slug = model.model.partition(":")[2]
    if provider == _OPENROUTER_PROVIDER and model.provider_order and not model.provider_allow_fallbacks:
        return _resolve_routed_snapshot(model, model_slug)

    input_per_m, output_per_m = _genai_per_million(provider, model_slug)
    source = _SOURCE_GENAI if input_per_m is not None else _SOURCE_UNKNOWN
    return PricingSnapshot(input_per_m, output_per_m, source)


def _resolve_routed_snapshot(model: LLMModelConfig, model_slug: str) -> PricingSnapshot:
    """Resolve pricing from the explicitly named OpenRouter endpoints."""
    api_key = model.api_key.get_secret_value() if model.api_key is not None else None
    endpoints = fetch_openrouter_endpoints(model_slug, api_key=api_key, base_url=model.base_url)
    by_provider: dict[str, EndpointRate] = {}
    for rate in endpoints:
        by_provider.setdefault(rate.provider_name, rate)

    matched: list[EndpointRate] = []
    missing: list[str] = []
    for wanted in model.provider_order:
        rate = by_provider.get(wanted)
        if rate is None:
            missing.append(wanted)
        else:
            matched.append(rate)
    if missing:
        available = sorted(by_provider)
        msg = (
            f"OpenRouter model {model_slug!r} has no endpoint for pinned provider(s) "
            f"{missing!r}; available endpoints: {available!r}"
        )
        raise PricingRouteError(msg)

    max_input = max(rate.input_per_million_usd for rate in matched)
    max_output = max(rate.output_per_million_usd for rate in matched)
    return PricingSnapshot(max_input, max_output, _SOURCE_OPENROUTER_ENDPOINT, tuple(matched))


def _genai_per_million(provider: str, model_slug: str) -> tuple[float | None, float | None]:
    """Return generic genai-prices per-million rates, or ``(None, None)`` when unknown."""
    provider_url = _PROVIDER_API_URLS.get(provider)
    if provider_url is None:
        return (None, None)
    try:
        price_calc = genai_prices.calc_price(
            RequestUsage(input_tokens=_ONE_MILLION, output_tokens=_ONE_MILLION),
            model_slug,
            provider_api_url=provider_url,
        )
    except LookupError:
        return (None, None)
    return (float(price_calc.input_price), float(price_calc.output_price))


def _parse_provider_model(model: str) -> tuple[str, str]:
    """Parse ``provider:model_name`` string into ``(provider, model_name)``.

    Args:
        model: Fully-qualified model string.

    Returns:
        Tuple of ``(provider, model_name)``.

    Raises:
        ValueError: If model string has no provider prefix.
    """
    if ":" not in model:
        msg = f"Model must use 'provider:model_name' format, got: {model!r}"
        raise ValueError(msg)
    provider, _, model_name = model.partition(":")
    return (provider, model_name)


def calc_cost(usage: RunUsage | RequestUsage, model: str) -> float | None:
    """Calculate cost for a usage instance using genai_prices.

    Args:
        usage: Token usage from the LLM call.
        model: Fully-qualified model string (e.g., ``openrouter:google/gemini-3-flash-preview``).

    Returns:
        Total cost in USD, ``0.0`` for local (llama.cpp/Ollama) models, ``None``
        if model or provider is not found in the genai_prices snapshot.
    """
    provider, model_name = _parse_provider_model(model)

    if provider in _LOCAL_PROVIDERS:
        return 0.0

    provider_url = _PROVIDER_API_URLS.get(provider)
    if provider_url is None:
        return None

    try:
        price_calc = genai_prices.calc_price(usage, model_name, provider_api_url=provider_url)
        return float(price_calc.total_price)
    except LookupError:
        return None


def get_per_million_prices(model: str) -> tuple[float | None, float | None]:
    """Get input/output price per million tokens for display.

    Queries genai_prices with exactly 1M input and 1M output tokens so
    ``input_price`` and ``output_price`` directly equal the per-million rates.

    Args:
        model: Fully-qualified model string.

    Returns:
        Tuple of ``(input_per_million_usd, output_per_million_usd)``.
        Values are ``0.0`` for local (llama.cpp/Ollama), ``None`` if unknown.
    """
    provider, model_name = _parse_provider_model(model)

    if provider in _LOCAL_PROVIDERS:
        return (0.0, 0.0)

    provider_url = _PROVIDER_API_URLS.get(provider)
    if provider_url is None:
        return (None, None)

    try:
        price_calc = genai_prices.calc_price(
            RequestUsage(input_tokens=_ONE_MILLION, output_tokens=_ONE_MILLION),
            model_name,
            provider_api_url=provider_url,
        )
        return (float(price_calc.input_price), float(price_calc.output_price))
    except LookupError:
        return (None, None)


def resolve_maximum_call_cost(
    model: str,
    *,
    max_input_tokens: int,
    max_output_tokens: int,
    unknown_price_max_usd: float | None = None,
) -> float:
    """Resolve the amount that must be reserved before one model call.

    Known models use provider pricing at the supplied hard token bounds.
    Unknown-price treatments require an owner-supplied per-call maximum.
    """
    if max_input_tokens < 0 or max_output_tokens < 0:
        msg = "Token bounds must be non-negative"
        raise ValueError(msg)
    maximum = calc_cost(
        RequestUsage(input_tokens=max_input_tokens, output_tokens=max_output_tokens),
        model,
    )
    if maximum is not None:
        return maximum
    if unknown_price_max_usd is None:
        msg = f"Pricing is unavailable for {model!r}; provide an explicit per-call maximum"
        raise ValueError(msg)
    if unknown_price_max_usd <= 0:
        msg = "Explicit per-call maximum must be greater than zero"
        raise ValueError(msg)
    return unknown_price_max_usd


def estimate_benchmark_cost(
    models: list[str],
    fixtures_count: int,
    runs_per_fixture: int,
    *,
    avg_input_tokens: int = 4000,
    avg_output_tokens: int = 500,
) -> dict[str, float | None]:
    """Estimate total cost per model for the full benchmark run.

    Args:
        models: Fully-qualified model identifiers.
        fixtures_count: Number of test fixtures.
        runs_per_fixture: Number of runs per fixture per model.
        avg_input_tokens: Estimated average input tokens per call.
        avg_output_tokens: Estimated average output tokens per call.

    Returns:
        Dict mapping model to estimated total cost in USD.
        Values are ``0.0`` for local (llama.cpp/Ollama), ``None`` if unknown.
    """
    total_runs = fixtures_count * runs_per_fixture
    usage = RequestUsage(
        input_tokens=avg_input_tokens * total_runs,
        output_tokens=avg_output_tokens * total_runs,
    )
    return {model: calc_cost(usage, model) for model in models}
