"""Main FastAPI application for user-auth-service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from nohiki_db_utils import DatabaseHealthProbe, close_all_engines, get_async_engine, initialize_database
from nohiki_fastapi_utils import build_root_router
from nohiki_fastapi_utils.errors import setup_error_handlers
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe, ensure_kafka_ready
from nohiki_observability import Observability, build_metrics_router
from nohiki_redis_utils import CacheFactory

from user_auth_service.api.routers.account import router as account_router
from user_auth_service.api.routers.auth import router as auth_router
from user_auth_service.api.routers.oauth import router as oauth_router
from user_auth_service.core.config import get_settings
from user_auth_service.core.csrf import CSRFMiddleware
from user_auth_service.core.db import get_async_db
from user_auth_service.core.jwt_rs256 import (
    JWTConfig,
    get_jwt_handler,
    init_jwt_handler,
    load_private_key_from_file,
)
from user_auth_service.core.kafka import kafka_client
from user_auth_service.core.refresh_tokens import get_refresh_token_service, init_refresh_token_service

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


def _initialize_jwt_handler() -> None:
    """Initialize the RS256 JWT handler with private key."""
    jwt_config = JWTConfig(
        issuer=settings.jwt.issuer,
        audience=settings.jwt.audience,
        key_id=settings.jwt.key_id,
        access_token_expire_minutes=settings.jwt.access_token_expire_minutes,
        refresh_token_expire_days=settings.jwt.refresh_token_expire_days,
    )

    key_path = Path(settings.jwt.private_key_path)
    logger.info("Loading JWT private key", path=str(key_path))
    private_key_pem = load_private_key_from_file(key_path)

    init_jwt_handler(private_key_pem, jwt_config)
    init_refresh_token_service(settings.jwt.refresh_token_expire_days)
    logger.info(
        "RS256 JWT handler initialized",
        key_id=settings.jwt.key_id,
        issuer=settings.jwt.issuer,
    )


_CLEANUP_INTERVAL_SECONDS = 900  # 15 minutes


async def _cleanup_expired_tokens_task() -> None:
    """Background task that periodically removes expired refresh tokens."""
    while True:
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
        try:
            async for db in get_async_db():
                refresh_service = get_refresh_token_service()
                await refresh_service.cleanup_expired(db)
                await db.commit()
        except Exception:
            logger.exception("Failed to clean up expired refresh tokens")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)

    # Initialize RS256 JWT handler
    _initialize_jwt_handler()

    await initialize_database(settings)

    # Initialize Kafka (producer-only service, no consumers)
    await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)
    await kafka_client.ensure_producer_ready()

    cleanup_task = asyncio.create_task(_cleanup_expired_tokens_task(), name="cleanup-expired-tokens")
    logger.info("Scheduled periodic refresh token cleanup", interval_seconds=_CLEANUP_INTERVAL_SECONDS)

    logger.info("Application startup complete")
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task
        logger.info("Shutting down service", service=settings.service_name)

        # 1. Close Kafka connections (producer-only service, no consumers)
        await kafka_client.close()
        logger.debug("Kafka client closed")

        # 2. Close Redis connections
        await CacheFactory.close_all()
        logger.debug("Redis connections closed")

        # 3. Close database connection pools
        await close_all_engines()
        logger.debug("Database engines disposed")

        # 4. Shutdown observability (flush pending telemetry)
        obs.shutdown()
        logger.debug("Observability shutdown complete")

        logger.info("Service shutdown complete", service=settings.service_name)


app = FastAPI(
    title=settings.service_name_friendly,
    description=settings.service_desc_friendly,
    version=settings.service_version,
    lifespan=lifespan,
)

# Middleware Stack (order matters - last added = first executed)

# CORS middleware - must be before other middleware
# Note: With credentials=True, origins MUST be explicit (not "*")
app.add_middleware(
    partial(
        CORSMiddleware,
        allow_origins=settings.security.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-Id"],
    )
)

# CSRF middleware - validates Origin header for state-changing requests
app.add_middleware(partial(CSRFMiddleware, allowed_origins=settings.security.get_csrf_origins()))

obs.init_fastapi(app)

setup_error_handlers(app)

# JWKS Endpoint (served at root level, not under /api/v1)


@app.get("/.well-known/jwks.json", tags=["auth"])
async def get_jwks(response: Response) -> dict[str, Any]:
    """Public JWKS endpoint for JWT verification.

    Returns the public key(s) needed to verify RS256-signed JWTs.
    Caching is enabled for 1 hour.
    """
    response.headers["Cache-Control"] = "public, max-age=3600"
    jwt_handler = get_jwt_handler()
    return jwt_handler.get_jwks()


# Routers

# Shared routers (health, root)
app.include_router(build_root_router(settings.service_name, settings.service_version))
app.include_router(
    build_probe_health_router(
        settings.service_name,
        lambda: [
            DatabaseHealthProbe(get_async_engine(settings.database)),
            KafkaHealthProbe(
                settings.kafka.bootstrap_servers,
                capabilities={KafkaCapability.BROKER_CONNECTIVITY, KafkaCapability.PRODUCER_READY},
            ),
        ],
    )
)
app.include_router(build_metrics_router())

# API routers
app.include_router(auth_router, prefix=f"{settings.api_prefix}/auth")
app.include_router(oauth_router, prefix=f"{settings.api_prefix}/auth/oauth")
app.include_router(account_router, prefix=f"{settings.api_prefix}/account")

logger.info(
    "Service initialized",
    service=settings.service_name,
    version=settings.service_version,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
