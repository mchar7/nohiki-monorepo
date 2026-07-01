"""Main FastAPI application for bff-service."""

from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from functools import partial
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from nohiki_db_utils import (
    DatabaseHealthProbe,
    close_all_engines,
    get_async_engine,
    get_async_sessionmaker,
    initialize_database,
)
from nohiki_fastapi_utils import (
    CSRFMiddleware,
    JWKSConfig,
    build_root_router,
    init_jwks_verifier,
    setup_error_handlers,
    setup_rate_limiting,
)
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_fastapi_utils.rate_limiter import get_client_id
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe, ensure_kafka_ready
from nohiki_observability import Observability, build_metrics_router
from nohiki_redis_utils import CacheFactory
from sqlalchemy.exc import SQLAlchemyError

from bff_service.api.error_handlers import setup_domain_error_handlers
from bff_service.api.routers.attachments import router as attachments_router
from bff_service.api.routers.auth_listings import router as auth_listings_router
from bff_service.api.routers.correlations import router as correlations_router
from bff_service.api.routers.documents import (
    document_events_router,
)
from bff_service.api.routers.documents import (
    router as documents_router,
)
from bff_service.api.routers.listings import router as listings_router
from bff_service.api.routers.ping import router as ping_router
from bff_service.api.routers.profiles import router as profiles_router
from bff_service.api.routers.schemas import router as schemas_router
from bff_service.api.routers.session import router as session_router
from bff_service.api.routers.skills import router as skills_router
from bff_service.api.routers.templates import router as templates_router
from bff_service.core.config import get_settings
from bff_service.core.kafka import kafka_client
from bff_service.events import start_event_consumer
from bff_service.events.projections._constants import (
    projection_auth_revocation_group_id,
)
from bff_service.services.auth_revocation import delete_expired_revocations
from bff_service.sse import close_sse_bridge, init_sse_bridge

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)


_REVOCATION_CLEANUP_INTERVAL_SECONDS = 3600


async def _cleanup_expired_revocations() -> None:
    """Delete expired revocation rows in a short transaction."""
    async with get_async_sessionmaker(settings.database)() as session:
        deleted = await delete_expired_revocations(session)
        await session.commit()
    logger.debug("Expired revocation ledger cleanup complete", deleted=deleted)


async def _run_revocation_cleanup() -> None:
    """Periodically remove expired revocation ledger rows."""
    while True:
        await asyncio.sleep(_REVOCATION_CLEANUP_INTERVAL_SECONDS)
        try:
            await _cleanup_expired_revocations()
        except SQLAlchemyError:
            logger.exception("Expired revocation ledger cleanup failed")


def _initialize_jwks_verifier() -> None:
    """Initialize the JWKS verifier for JWT validation."""
    jwks_config = JWKSConfig(
        jwks_url=settings.jwt.jwks_url,
        issuer=settings.jwt.issuer,
        audience=settings.jwt.audience,
        cookie_name=settings.cookie.access_token_name,
    )
    init_jwks_verifier(jwks_config)
    logger.info(
        "JWKS verifier initialized",
        jwks_url=settings.jwt.jwks_url,
        issuer=settings.jwt.issuer,
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    """Manage application lifespan events."""
    logger.info("Starting service", service=settings.service_name)

    _initialize_jwks_verifier()

    await initialize_database(settings)
    await _cleanup_expired_revocations()
    revocation_cleanup_task = asyncio.create_task(
        _run_revocation_cleanup(),
        name="revocation-ledger-cleanup",
    )

    try:
        await ensure_kafka_ready(bootstrap_servers=settings.kafka.bootstrap_servers)

        # Initialize producer before consumers (needed for profile commands that publish)
        await kafka_client.ensure_producer_ready()
        logger.debug("Kafka producer ready")

        # Configure decorator-based session management for Kafka handlers
        kafka_client.set_db_session_factory(get_async_sessionmaker(settings.database))

        # Initialize SSE bridge before consumers (handlers need bridge access)
        await init_sse_bridge(settings.redis.connection_string)
        # Start Kafka event consumers for projections
        start_event_consumer()
        async with kafka_client.supervise_consumer_failures():
            await kafka_client.wait_for_consumer_catchup(
                projection_auth_revocation_group_id,
                timeout_seconds=settings.kafka.consumer.session_timeout_ms / 1000,
            )

            logger.info("Application startup complete")
            yield
    finally:
        logger.info("Shutting down service", service=settings.service_name)

        # 1. Stop Kafka consumers first (stop accepting new work)
        await kafka_client.stop_consumers()
        logger.debug("Kafka consumers stopped")

        # 1.5. Close SSE bridge (consumers stopped, safe to close)
        await close_sse_bridge()
        logger.debug("SSE bridge closed")

        # 2. Close Kafka connections
        await kafka_client.close()
        logger.debug("Kafka client closed")

        # 3. Close Redis connections
        await CacheFactory.close_all()
        logger.debug("Redis connections closed")

        # 3.5. Stop cleanup before closing its database pool
        revocation_cleanup_task.cancel()
        await asyncio.gather(revocation_cleanup_task, return_exceptions=True)
        logger.debug("Revocation ledger cleanup stopped")

        # 4. Close database connection pools
        await close_all_engines()
        logger.debug("Database engines disposed")

        # 5. Shutdown observability (flush pending telemetry)
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

# Rate limiting - uses BFF rate limit config with JWT-aware user identification
rl = settings.caching.bff_rate_limit


def _bff_rate_limit_key(request: Request) -> str:
    """Route authenticated auth-listings Worker requests to a dedicated service-tier bucket."""
    supplied_secret = request.headers.get("X-Auth-Listings-Secret", "")
    configured_secret = settings.auth_listings.secret
    if (
        request.url.path.startswith(f"{settings.api_prefix}/auth-listings")
        and configured_secret
        and hmac.compare_digest(supplied_secret, configured_secret)
    ):
        return "service:auth-listings-worker"
    return get_client_id(request)


setup_rate_limiting(
    app,
    service_name=settings.service_name,
    redis_url=settings.redis.connection_string,
    key_func=_bff_rate_limit_key,
    default_limits=[
        f"{rl.auth_requests_per_minute}/minute",
        f"{rl.auth_requests_per_hour}/hour",
    ],
)

# CSRF protection
app.add_middleware(partial(CSRFMiddleware, allowed_origins=settings.origins.get_csrf_origins()))

# CORS (executes first, outermost) - must be before other middleware
app.add_middleware(
    partial(
        CORSMiddleware,
        allow_origins=settings.origins.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-Id"],
    )
)

obs.init_fastapi(app)

setup_error_handlers(app)
setup_domain_error_handlers(app)

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
                capabilities={
                    KafkaCapability.BROKER_CONNECTIVITY,
                    KafkaCapability.CONSUMER_READY,
                    KafkaCapability.PRODUCER_READY,
                },
            ),
        ],
    )
)
app.include_router(build_metrics_router())
app.include_router(ping_router)

# API routers
app.include_router(session_router, prefix=f"{settings.api_prefix}/session", tags=["session"])
app.include_router(profiles_router, prefix=f"{settings.api_prefix}/profiles", tags=["profiles"])
app.include_router(
    attachments_router,
    prefix=f"{settings.api_prefix}/attachments",
    tags=["attachments"],
)
app.include_router(schemas_router, prefix=f"{settings.api_prefix}/schema-families", tags=["schemas"])
app.include_router(
    templates_router,
    prefix=f"{settings.api_prefix}/template-families",
    tags=["templates"],
)
app.include_router(document_events_router, prefix="/api/documents", tags=["documents"])
app.include_router(documents_router, prefix=f"{settings.api_prefix}/documents", tags=["documents"])
app.include_router(
    correlations_router,
    prefix=f"{settings.api_prefix}/correlations",
    tags=["correlations"],
)
app.include_router(listings_router, prefix=f"{settings.api_prefix}/listings", tags=["listings"])
app.include_router(skills_router, prefix=f"{settings.api_prefix}/skills", tags=["skills"])
app.include_router(
    auth_listings_router,
    prefix=f"{settings.api_prefix}/auth-listings",
    tags=["auth-listings"],
)

logger.info(
    "Service initialized",
    service=settings.service_name,
    version=settings.service_version,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
