"""LLM cost calculation via genai-prices bundled pricing snapshot.

Uses the bundled pricing data from genai-prices, which is accurate for
known providers at release time. Actual costs returned by provider API
metadata are more authoritative; use this for estimating/logging only.
"""

from __future__ import annotations

from genai_prices import calc_price
from genai_prices.types import AbstractUsage


def calc_llm_cost(
    usage: AbstractUsage,
    model_name: str,
    *,
    provider_api_url: str | None = None,
) -> float | None:
    """Calculate cost for an LLM API call using the current pricing snapshot.

    Delegates to :func:`genai_prices.calc_price`. Returns ``None`` for unknown
    models or providers rather than raising, so callers can gracefully display
    an unknown cost without crashing.

    Args:
        usage: Token usage from the LLM call. Must satisfy
            :class:`genai_prices.types.AbstractUsage` (PydanticAI's
            ``RunUsage`` and ``RequestUsage`` both qualify).
        model_name: Model identifier as recognised by the provider (e.g.
            ``qwen/qwen3-vl-30b-a3b-instruct``). Must NOT include the
            ``provider:`` prefix used in Nohiki's model config strings.
        provider_api_url: Base URL of the provider API. Used by genai-prices to
            identify the correct provider and its pricing table. Supply this
            whenever possible for accurate lookup.

    Returns:
        Total cost in USD, or ``None`` if the model or provider is not in the
        current pricing snapshot.
    """
    try:
        result = calc_price(usage, model_name, provider_api_url=provider_api_url)
        return float(result.total_price)
    except LookupError:
        return None
