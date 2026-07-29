"""Pooled httpx client construction shared by the HTTP-backed email providers.

A client per send pays a TCP and TLS handshake every time and burns an
ephemeral port; one client per provider keeps the pool warm for the life of the
service. The timeout budget is per phase so a slow connect cannot eat the whole
allowance and leave the response with none.
"""

from __future__ import annotations

import httpx

from notification_service.core.config import get_settings


def build_pooled_client(*, base_url: str, headers: dict[str, str]) -> httpx.AsyncClient:
    """Create a long-lived client carrying the configured timeout budget.

    Args:
        base_url: Provider API root.
        headers: Headers applied to every request.

    Returns:
        Client whose connection pool is reused until ``aclose`` is awaited.

    """
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=get_settings().email.timeout.to_httpx_timeout(),
    )
