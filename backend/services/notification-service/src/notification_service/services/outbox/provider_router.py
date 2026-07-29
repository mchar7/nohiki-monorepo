"""Resilient provider dispatch with per-provider circuit breakers.

One :class:`~nohiki_redis_utils.CircuitBreaker` per provider name, so a Resend
outage doesn't take SendGrid down with it.

Breaker state is in-process and per-pod. The tradeoff is intentional:

* Pro: zero hot-path latency, no Redis dependency, self-healing on deploy,
  no atomic-state-machine complexity.
* Con: each pod learns about a provider outage independently. With N pods
  and ``failure_threshold=F``, up to ``N * F`` failed sends are wasted
  before the whole fleet routes to the fallback. Recovery sends N probes
  instead of one.

For this service (small replica count, moderate volume, cheap provider
calls) the waste is bounded and small. If we ever scale to ~20+ replicas,
metered providers, or a sub-second convergence SLO, replace this with a
shared Redis-backed breaker.

``send()`` always returns a :class:`SendOutcome` instead of raising. The
worker pattern-matches on :class:`SendVerdict` to commit, retry, or leave the
row alone until the next poll cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from nohiki_observability import get_logger
from nohiki_redis_utils import CircuitBreaker, CircuitBreakerConfig

from notification_service.core.providers import (
    BaseProvider,
    ProviderNotFoundError,
    ProviderResult,
    get_fallback_providers,
    get_provider,
)

if TYPE_CHECKING:
    from notification_service.db.models import Message

logger = get_logger(__name__)


class SendVerdict(Enum):
    """Outcome category of a dispatch attempt across one or more providers.

    Members:
        DELIVERED: One provider accepted the message; ``SendOutcome.result``
            carries the provider's ``ProviderResult`` with ``success=True``.
        FAILED: A provider responded but rejected the message (validation,
            permanent error, or retryable error where the breaker was still
            CLOSED). ``SendOutcome.result`` carries the rejection.
        ALL_CIRCUITS_OPEN: Every candidate provider's circuit breaker is open.
            No provider was actually contacted. The caller should leave the
            message in its current state and re-poll later, when the breaker
            timeout has elapsed.
        THROTTLED: A limiter refused this send, so no provider was contacted.
            Never produced by the router; the worker raises it ahead of
            dispatch so its match stays exhaustive.
    """

    DELIVERED = "delivered"
    FAILED = "failed"
    ALL_CIRCUITS_OPEN = "all_circuits_open"
    THROTTLED = "throttled"


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """Typed outcome of a :meth:`ProviderRouter.send` call.

    ``provider`` and ``result`` are ``None`` exactly when ``verdict`` is
    :attr:`SendVerdict.ALL_CIRCUITS_OPEN` or :attr:`SendVerdict.THROTTLED`
    (no provider was contacted). ``retry_after`` is set only for
    :attr:`SendVerdict.THROTTLED`, carrying the refusing limiter's own estimate
    of the seconds until capacity returns.
    """

    verdict: SendVerdict
    provider: BaseProvider | None
    result: ProviderResult | None
    retry_after: float | None = None


class _ProviderSendError(Exception):
    """Wraps a provider's ``ProviderResult.error`` string for the breaker.

    Email providers return ``ProviderResult(success=False, retryable=True)``
    on 5xx/429 rather than raising. ``CircuitBreaker.record_failure`` wants an
    ``Exception``, so we wrap the error string here instead of leaking a
    synthetic public exception type.
    """


class ProviderRouter:
    """Routes a message to the primary provider with per-provider breakers.

    Breakers are created on first use, one per provider name. All breakers
    share the same config; if per-provider tuning is ever needed, swap the
    single config for a name-keyed mapping.

    Args:
        cb_config: Circuit-breaker config used for every breaker.

    """

    def __init__(self, cb_config: CircuitBreakerConfig) -> None:
        """Build a router with no breakers yet allocated.

        Args:
            cb_config: Shared circuit-breaker configuration.

        """
        self._cb_config = cb_config
        self._breakers: dict[str, CircuitBreaker] = {}

    async def send(self, message: Message) -> SendOutcome:
        """Try the primary provider, then fall back through registered alternates.

        Resolution order:

        1. ``message.provider_name`` if set, otherwise the channel default.
        2. Other providers registered for the channel, in registration order,
           but only while the primary's breaker is open.

        Args:
            message: Message to deliver. Treated read-only here; DB writes
                are the worker's job.

        Returns:
            A :class:`SendOutcome`. Never raises on routine provider failure.

        """
        try:
            primary = get_provider(message.channel.to_proto(), message.provider_name)
        except ProviderNotFoundError as exc:
            # Hand back a non-retryable FAILED outcome so the worker can mark
            # the row permanently failed without knowing about registry errors.
            logger.exception(
                "Provider lookup failed; cannot dispatch",
                message_id=str(message.id),
                provider_name=message.provider_name,
                error=str(exc),
            )
            return SendOutcome(
                verdict=SendVerdict.FAILED,
                provider=None,
                result=ProviderResult(
                    success=False,
                    error=f"Provider not found: {exc}",
                    retryable=False,
                ),
            )

        primary_outcome = await self._try_provider(primary, message)
        if primary_outcome is not None:
            return primary_outcome

        # Recompute the fallback list every call: which providers are healthy
        # changes over time as breakers flip open and closed.
        fallbacks = get_fallback_providers(message.channel.to_proto(), exclude=primary.name)
        for fallback in fallbacks:
            outcome = await self._try_provider(fallback, message)
            if outcome is not None:
                logger.info(
                    "Delivered via fallback provider",
                    message_id=str(message.id),
                    primary=primary.name,
                    fallback=fallback.name,
                    verdict=outcome.verdict.value,
                )
                return outcome

        logger.warning(
            "All providers' circuits are open; deferring message",
            message_id=str(message.id),
            primary=primary.name,
            fallback_count=len(fallbacks),
        )
        return SendOutcome(verdict=SendVerdict.ALL_CIRCUITS_OPEN, provider=None, result=None)

    async def _try_provider(
        self,
        provider: BaseProvider,
        message: Message,
    ) -> SendOutcome | None:
        """Run one provider through its breaker.

        Args:
            provider: Provider to try.
            message: Message to send.

        Returns:
            ``None`` if the breaker is open (caller should try a fallback).
            Otherwise a :class:`SendOutcome`. A provider that responded with
            rejection is a real result, not a reason to fall through. If the
            provider raises (contract violation), the breaker is updated and
            the exception is converted into a retryable FAILED outcome so
            the worker can dispatch a single uniform handler.

        """
        breaker = self._get_or_create_breaker(provider.name)

        if not await breaker.can_execute():
            logger.debug(
                "Provider circuit open; deferring to fallback",
                provider=provider.name,
                message_id=str(message.id),
            )
            return None

        try:
            result = await provider.send(message)
        except Exception as exc:
            await breaker.record_failure(exc)
            logger.exception(
                "Provider raised unexpectedly; converting to retryable failure",
                provider=provider.name,
                message_id=str(message.id),
            )
            return SendOutcome(
                verdict=SendVerdict.FAILED,
                provider=provider,
                result=ProviderResult(success=False, error=str(exc), retryable=True),
            )

        # A 4xx from the provider is the message's fault, not the provider's.
        # Release the HALF_OPEN probe slot instead of counting the call.
        if result.success:
            await breaker.record_success()
        elif result.retryable:
            await breaker.record_failure(_ProviderSendError(result.error or "send failed"))
        else:
            breaker.release_half_open_slot()

        verdict = SendVerdict.DELIVERED if result.success else SendVerdict.FAILED
        return SendOutcome(verdict=verdict, provider=provider, result=result)

    def _get_or_create_breaker(self, provider_name: str) -> CircuitBreaker:
        """Look up the breaker for ``provider_name``, creating it on first use.

        Args:
            provider_name: Registered provider name.

        Returns:
            The breaker for that provider.

        """
        existing = self._breakers.get(provider_name)
        if existing is not None:
            return existing

        breaker = CircuitBreaker(name=f"provider:{provider_name}", config=self._cb_config)
        self._breakers[provider_name] = breaker
        return breaker
