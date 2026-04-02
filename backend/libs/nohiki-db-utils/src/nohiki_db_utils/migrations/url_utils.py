"""Database URL manipulation and SSL engine creation utilities.

Handles conversion between sync/async drivers and SSL configuration for asyncpg.
"""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import create_async_engine

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

_PG_ASYNCPG_DRIVER = "+asyncpg"
_PG_PSYCOPG_DRIVER = "+psycopg"
_PG_SCHEME = "postgresql://"
_PG_PSYCOPG_SCHEME = "postgresql+psycopg://"
_PG_ASYNCPG_SCHEME = "postgresql+asyncpg://"


def to_sync_url(url: str) -> str:
    """Convert database URL to sync psycopg driver."""
    result = url.replace(_PG_ASYNCPG_DRIVER, _PG_PSYCOPG_DRIVER)
    if _PG_PSYCOPG_DRIVER not in result:
        result = result.replace(_PG_SCHEME, _PG_PSYCOPG_SCHEME)
    return result


def to_async_url(url: str) -> str:
    """Convert database URL to async asyncpg driver."""
    if _PG_ASYNCPG_DRIVER in url:
        return url
    return url.replace(_PG_SCHEME, _PG_ASYNCPG_SCHEME)


def create_async_engine_with_ssl(
    url: str,
    *,
    isolation_level: str | None = None,
) -> AsyncEngine:
    """Create async engine with proper SSL handling for asyncpg.

    asyncpg doesn't accept 'sslmode' parameter - it requires 'ssl' with
    an SSLContext or boolean. This function extracts sslmode from URL
    query params and converts it to proper asyncpg connect_args.
    """
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    sslmode = None
    if "sslmode" in query_params:
        sslmode = query_params.pop("sslmode")[0]

    new_query = urlencode({k: v[0] if len(v) == 1 else v for k, v in query_params.items()}, doseq=True)
    clean_url = urlunparse(parsed._replace(query=new_query))

    async_url = to_async_url(clean_url)

    connect_args: dict[str, ssl.SSLContext] = {}

    if sslmode and sslmode != "disable":
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = sslmode == "verify-full"
        ctx.verify_mode = ssl.CERT_REQUIRED if sslmode == "verify-full" else ssl.CERT_NONE
        connect_args["ssl"] = ctx

    return (
        create_async_engine(async_url, connect_args=connect_args, isolation_level=isolation_level)
        if isolation_level
        else create_async_engine(async_url, connect_args=connect_args)
    )
