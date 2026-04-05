"""Provider-level shared concurrency limiting for LLM models.

All ``LLMClient`` instances that target the same provider endpoint share a
single ``ConcurrencyLimiter``. This is the correct architecture for providers
like Ollama whose server process is single-threaded: without sharing, two
independently created clients could both acquire their own per-instance
semaphore(1) and issue concurrent requests, defeating the limit entirely.

The registry is module-level and keyed by a provider identity string. Use
``reset_provider_limiters()`` in tests that spin up fresh event loops.
"""

from __future__ import annotations

from pydantic_ai.models import Model
from pydantic_ai.models.concurrency import ConcurrencyLimiter, limit_model_concurrency

_SHARED_LIMITERS: dict[str, ConcurrencyLimiter] = {}


def get_or_create_provider_limiter(provider_key: str, limit: int) -> ConcurrencyLimiter:
    """Get or create a shared ``ConcurrencyLimiter`` for a provider endpoint.

    Uses ``dict.setdefault`` for safe concurrent access under the GIL. If two
    coroutines race, one limiter is discarded; the same shared instance is
    returned to all subsequent callers for the same key.

    Args:
        provider_key: Unique identifier for the provider endpoint (e.g., the
            Ollama base URL ``http://localhost:11434/v1``).
        limit: Maximum concurrent requests permitted for this endpoint.

    Returns:
        A ``ConcurrencyLimiter`` shared across all callers with the same key.
    """
    return _SHARED_LIMITERS.setdefault(
        provider_key,
        ConcurrencyLimiter(limit, name=provider_key),
    )


def reset_provider_limiters() -> None:
    """Clear the shared limiter registry; not safe to call while requests are in-flight."""
    _SHARED_LIMITERS.clear()


def apply_concurrency_limit(
    model: Model,
    limit: int | None,
    *,
    provider_key: str | None = None,
) -> Model:
    """Wrap a model with concurrency limiting.

    When ``provider_key`` is provided, uses a shared ``ConcurrencyLimiter``
    from the module-level registry so that ALL ``LLMClient`` instances
    targeting the same endpoint share the limit. When ``provider_key`` is
    ``None``, creates a per-instance limiter (appropriate for cloud providers
    where each client is independently rate-limited by the API).

    Args:
        model: The PydanticAI model to optionally wrap.
        limit: Maximum concurrent requests. ``None`` means no limit.
        provider_key: Endpoint identity string for shared-limiter lookup.
            Set this for single-process servers like Ollama.

    Returns:
        The original model if ``limit`` is ``None``, or a
        ``ConcurrencyLimitedModel`` wrapper.
    """
    if limit is None:
        return model
    if provider_key is not None:
        limiter = get_or_create_provider_limiter(provider_key, limit)
        return limit_model_concurrency(model, limiter=limiter)
    return limit_model_concurrency(model, limiter=limit)
