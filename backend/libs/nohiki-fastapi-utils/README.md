# Nohiki FastAPI Utils

Provides the FastAPI setup primitives consumed by all 18 Nohiki backend services: standardized
health and readiness probes, global error handlers with a typed error response envelope, CSRF
protection via Origin header validation, JWKS-based RS256 JWT verification for cookie-authenticated
endpoints, Redis-backed rate limiting, and pagination helpers for list APIs.

All 18 services install the base `[server]` extra. `bff-service` additionally installs `[jwt]`
and `[otel]` because it is the only service that verifies incoming JWTs directly. All other
services are Kafka-only and have no authentication surface.

## Quick Start

The canonical lifespan pattern used by every Nohiki service:

```python
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from nohiki_db_utils import DatabaseHealthProbe, close_all_engines, get_async_engine, initialize_database
from nohiki_fastapi_utils import build_root_router, setup_error_handlers
from nohiki_fastapi_utils.health_router import build_probe_health_router
from nohiki_kafka_client import KafkaCapability, KafkaHealthProbe

from my_service.core.config import get_settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    await initialize_database(settings)
    yield
    await close_all_engines()


app = FastAPI(lifespan=lifespan)

setup_error_handlers(app)

app.include_router(build_root_router(settings.service_name, settings.service_version))
app.include_router(
    build_probe_health_router(
        settings.service_name,
        lambda: [
            DatabaseHealthProbe(get_async_engine(settings.database)),
            KafkaHealthProbe(
                settings.kafka.bootstrap_servers,
                capabilities={KafkaCapability.BROKER_CONNECTIVITY, KafkaCapability.CONSUMER_READY},
            ),
        ],
    )
)
```

For HTTP-exposed services (`bff-service`) that need JWT verification, CSRF protection, and rate
limiting, see the [BFF lifespan pattern](#bff-service-lifespan-pattern) in Core Concepts.

## Core Concepts

### Health and Readiness Probes

Each service registers `HealthProbe` instances from `nohiki-db-utils` and `nohiki-kafka-client`.
`build_probe_health_router` aggregates their results and exposes two Kubernetes-compliant endpoints:

- **`GET /healthz`** -- Liveness probe. Returns `{"status": "ok"}` as long as the process is
  alive. Kubernetes restarts the container if this fails.
- **`GET /readyz`** -- Readiness probe. Runs all registered probes concurrently. Returns
  `{"status": "healthy"}` with HTTP 200 when all pass. Returns HTTP 503 with
  `{"status": "unhealthy"}` if any probe fails, removing the pod from the load balancer.
  A `"degraded"` status (e.g., slow Redis) returns HTTP 200 -- traffic continues.

The `get_probes` argument is a callable, not a list. It is invoked on every `/readyz` request so
that probe instances can reference freshly resolved dependencies (e.g., the current async engine).

For stateless services with no external dependencies, use `build_stateless_health_router` instead.
Both liveness and readiness return `{"status": "ok"}` immediately.

The optional `readiness_gate` parameter (`ReadinessGateProtocol`) handles services with async
startup (such as ML model downloads). While `gate.is_ready` is `False`, `/readyz` returns HTTP
503 with `{"reason": "models_loading"}`, preventing premature traffic. Once the gate is ready,
normal probe execution resumes.

### Startup Validation

`validate_startup_dependencies` runs the same `HealthProbe` instances used for Kubernetes probes
during service startup, with retry logic. Services call it in their lifespan to fail fast rather
than starting in a broken state:

```python
from nohiki_fastapi_utils.startup_validation import validate_startup_dependencies

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    await validate_startup_dependencies(
        probes=[DatabaseHealthProbe(engine), KafkaHealthProbe(...)],
        timeout_seconds=60.0,
        retry_interval_seconds=2.0,
        fail_fast=True,  # raises RuntimeError if probes don't pass within timeout
    )
    yield
```

With `fail_fast=True` (the default), `validate_startup_dependencies` raises `RuntimeError` if
any probe does not pass within `timeout_seconds`. This prevents the service from registering
with Kubernetes while its dependencies are unavailable.

### Error Handlers

`setup_error_handlers(app)` registers four global exception handlers that map Python exceptions
to a consistent JSON error envelope:

```json
{
  "timestamp": "2025-01-01T00:00:00Z",
  "status": 404,
  "error": "NOT_FOUND",
  "message": "Job not found: abc123",
  "path": "/api/v1/listings/abc123",
  "details": null
}
```

| Exception type | HTTP status | `error` field |
|---|---|---|
| `NohikiError` subclass | From `ErrorCode` on exception | From `ErrorCode` on exception |
| `pydantic.ValidationError` | 422 | `VALIDATION_ERROR` |
| `fastapi.HTTPException` | From exception | Mapped via `ErrorCode` |
| Any other `Exception` | 500 | `INTERNAL_ERROR` |

The library defines its own `NohikiError` hierarchy (`ValidationError`, `NotFoundError`,
`ConflictError`, `PermissionDeniedError`, `RateLimitError`, `InternalError`, `DatabaseError`,
`ExternalServiceError`) for raising typed HTTP errors from service business logic. Each subclass
carries an `ErrorCode` that determines the HTTP status code. The `details` field carries
field-level validation errors when applicable.

Note that `nohiki-common-exceptions` defines a separate, Kafka-oriented exception hierarchy for
retry classification (`DataNotFoundError`, `ExternalServiceError`, etc.). The exceptions in this
library are for HTTP surfaces only.

### CSRF Protection

`CSRFMiddleware` protects state-mutating endpoints against cross-site request forgery without
double-submit tokens. This works correctly because the JWTs are stored in `HttpOnly` cookies,
so JavaScript on a malicious page cannot read them, but a cross-site form could still send a
request that includes the cookie. The middleware defends against this by validating request
origin on `POST`, `PUT`, `PATCH`, and `DELETE` requests that arrive with cookies:

1. If the `Origin` header is present, it must appear in the `allowed_origins` list.
2. If the `Sec-Fetch-Site` header is present, it must be `same-origin` or `same-site`.

Requests with no cookies (e.g., public endpoints, Kafka-only services) pass through without
validation. `GET`, `HEAD`, and `OPTIONS` requests are never validated.

Use `create_csrf_middleware` to produce a class with `allowed_origins` pre-bound, which avoids
a `ParamSpec` issue in Starlette's middleware registration API:

```python
from functools import partial
from nohiki_fastapi_utils import CSRFMiddleware, create_csrf_middleware

# Either approach works:
app.add_middleware(partial(CSRFMiddleware, allowed_origins=settings.origins.get_csrf_origins()))
# or:
app.add_middleware(create_csrf_middleware(settings.origins.get_csrf_origins()))
```

### JWKS Verifier (JWT Extra)

`JWKSVerifier` verifies RS256-signed JWTs issued by `user-auth-service`. It is a singleton
initialized once at startup. The `bff-service` initializes it in its lifespan, and all
authenticated route dependencies call `get_jwks_verifier()` to retrieve the shared instance.

The verifier uses `PyJWKClient` internally, which fetches the JWKS document from
`user-auth-service`'s `/.well-known/jwks.json` endpoint and caches the signing keys for
`cache_ttl_seconds` (default: 3600 seconds). On cache expiry, the next request triggers a
fresh JWKS fetch. This is also how key rotation is handled. The client will pick up a new
key ID on its next cache refresh without any service restart.

Every verification enforces: expiry, issued-at, issuer, audience, and the required claims
`exp`, `iat`, `sub`, `iss`, `aud`, `jti`. Any failure raises `JWKSVerificationError`, which
the FastAPI dependencies translate to HTTP 401.

Tokens are read from the `nohiki_at` HttpOnly cookie by default.

#### BFF Service Lifespan Pattern

```python
from nohiki_fastapi_utils import (
    CSRFMiddleware,
    JWKSConfig,
    build_root_router,
    init_jwks_verifier,
    setup_error_handlers,
    setup_rate_limiting,
)
from nohiki_fastapi_utils.health_router import build_probe_health_router

@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    init_jwks_verifier(JWKSConfig(
        jwks_url=settings.jwt.jwks_url,
        issuer=settings.jwt.issuer,
        audience=settings.jwt.audience,
        cookie_name=settings.cookie.access_token_name,
    ))
    await initialize_database(settings)
    yield
    await close_all_engines()

app = FastAPI(lifespan=lifespan)

setup_rate_limiting(
    app,
    service_name=settings.service_name,
    redis_url=settings.redis.connection_string,
    default_limits=["1000/minute", "10000/hour"],
)
app.add_middleware(partial(CSRFMiddleware, allowed_origins=settings.origins.get_csrf_origins()))
setup_error_handlers(app)

app.include_router(build_root_router(settings.service_name, settings.service_version))
app.include_router(build_probe_health_router(settings.service_name, get_probes))
```

### Rate Limiting

`setup_rate_limiting` adds `RateLimitMiddleware` to the application and registers an exception
handler for `RateLimitExceededHTTP`. Rate counters are stored in Redis via `nohiki-redis-utils`
with TTLs matching the limit window.

Client identification uses this priority order:

1. Verified JWT user ID (extracted by `JWKSVerifier`, if the `jwt` extra is installed and the
   verifier is initialized)
2. `X-Account-ID` header (internal/legacy)
3. `X-Forwarded-For` header, first IP in the list
4. `X-Real-IP` header
5. Direct client IP

Identified users are keyed as `user:<id>`; anonymous clients as `ip:<ip>`. This means
authenticated users share a rate limit bucket regardless of IP, while unauthenticated requests
are limited per IP.

Per-route limits override the default:

```python
from nohiki_fastapi_utils import rate_limit

@router.post("/generate")
@rate_limit("5/minute", "50/hour")
async def generate_document(...):
    ...
```

The default limits applied when no per-route decorator is present are `["100/minute", "1000/hour"]`
unless overridden in the `setup_rate_limiting` call.

### Pagination

`PaginationParams` and `SortParams` are Pydantic models injected as FastAPI query dependencies.
`PaginatedResponse[T]` is the generic envelope for all list endpoints. The BFF uses these on
every listing endpoint (`/listings`, `/correlations`, `/profiles`, `/attachments`, etc.):

```python
from typing import Annotated
from fastapi import Query
from nohiki_fastapi_utils import PaginatedResponse, PaginationParams, SortParams

@router.get("/listings")
async def list_listings(
    pagination: Annotated[PaginationParams, Query()],
    sort: Annotated[SortParams, Query()],
) -> PaginatedResponse[ListingResponse]:
    items, total = await listing_repo.list(
        offset=pagination.offset,
        limit=pagination.page_size,
        sort_by=sort.sort_by,
        ascending=sort.is_ascending,
    )
    return PaginatedResponse.create(items=items, total=total, params=pagination)
```

`PaginationParams` accepts `page` (1-indexed, max 10,000) and `page_size` (1-100, default 20).
The `offset` property computes the SQL `OFFSET` value. `PaginatedResponse.create` computes
`total_pages`, `has_next`, and `has_prev` automatically.

### Authentication Dependencies

Two FastAPI dependencies extract the authenticated user from the JWT cookie:

- **`get_current_user_id_from_cookie`** -- Returns `UUID` from `claims.sub`. Raises HTTP 401
  if the token is missing, expired, has an invalid issuer/audience, or if `sub` is not a
  valid UUID.
- **`get_current_user_claims`** -- Returns the full `JWTClaims` dataclass, giving access to
  `roles`, `permissions`, and `tenant_id`.

For Kafka-only services that proxy user identity through an internal header (e.g., after the
BFF has already verified the JWT), `get_current_user_id_from_header` reads the `X-Account-Id`
header instead.

### Correlation IDs

`CorrelationIdMiddleware` (re-exported from `nohiki-observability`) propagates the
`X-Correlation-Id` header across service boundaries. The `get_correlation_id()` and
`set_correlation_id()` helpers read and write the context-var-backed correlation ID for use
in structured logs.

## API Reference

### Health Probes

- **`build_probe_health_router(service_name, get_probes, *, readiness_gate=None, include_debug_endpoint=False)`** --
  Returns an `APIRouter` with `/healthz` (liveness) and `/readyz` (readiness) endpoints.
  `get_probes` is a `Callable[[], list[HealthProbe]]` invoked on each request.
  Pass `include_debug_endpoint=True` to also mount `/health` with full probe details for
  local debugging.
- **`build_stateless_health_router(service_name)`** -- Returns a minimal `APIRouter` for services
  with no external dependencies. Both `/healthz` and `/readyz` return `{"status": "ok"}`.
- **`ReadinessGateProtocol`** -- Protocol with `is_ready: bool` and `is_failed: bool` properties.
  Implement this to gate readiness on async initialization work.

### Startup Validation

- **`validate_startup_dependencies(probes, *, timeout_seconds=60.0, retry_interval_seconds=2.0, fail_fast=True)`** --
  Retries all probes until they pass or `timeout_seconds` elapses. With `fail_fast=True`
  raises `RuntimeError` on timeout.
- **`run_health_probes(probes)`** -- Runs all probes once and returns results. Used internally
  by the health router; call directly if you need probe results outside of HTTP context.
- **`StartupValidationResult`** -- Dataclass with `success: bool`, `results: list[HealthProbeResult]`,
  and `failed_probes: list[str]`. Call `.raise_if_failed()` to conditionally raise.

### Error Handling

- **`setup_error_handlers(app)`** -- Registers global handlers for `NohikiError`,
  `pydantic.ValidationError`, `HTTPException`, and `Exception`.
- **`NohikiError`** -- Base class for typed HTTP errors. Subclasses: `ValidationError`,
  `NotFoundError`, `ConflictError`, `PermissionDeniedError`, `RateLimitError`, `InternalError`,
  `DatabaseError`, `ExternalServiceError`.
- **`ErrorCode`** -- `StrEnum` pairing error code strings with HTTP status codes. Values:
  `VALIDATION_ERROR` (422), `INVALID_REQUEST` (400), `UNAUTHORIZED` (401), `FORBIDDEN` (403),
  `NOT_FOUND` (404), `CONFLICT` (409), `TOO_MANY_REQUESTS` (429), `INTERNAL_ERROR` (500),
  `DATABASE_ERROR` (500), `SERVICE_UNAVAILABLE` (503), `GATEWAY_TIMEOUT` (504).
- **`ErrorResponse`** -- Pydantic model for the standard error envelope (`timestamp`, `status`,
  `error`, `message`, `path`, `details`).
- **`require_field(value, field_name)`** -- Raises `ValidationError` if `value` is `None` or
  blank. Returns the value unchanged otherwise.
- **`validate_string_length(value, field_name, min_length, max_length)`** -- Raises
  `ValidationError` with field detail if the string falls outside the specified range.

### CSRF

- **`CSRFMiddleware`** -- Starlette `BaseHTTPMiddleware` subclass. Pass `allowed_origins` as a
  constructor argument or use `create_csrf_middleware`.
- **`create_csrf_middleware(allowed_origins)`** -- Factory that returns a `CSRFMiddleware`
  subclass with `allowed_origins` pre-bound. Avoids Starlette `ParamSpec` issues.
- **`validate_csrf(request, allowed_origins)`** -- Standalone function for per-route CSRF
  validation instead of middleware. Raises `HTTPException` 403 on failure.

### JWKS / JWT (`[jwt]` extra required)

- **`init_jwks_verifier(config)`** -- Initializes the global `JWKSVerifier` singleton. Call
  once during service startup.
- **`get_jwks_verifier()`** -- Returns the initialized singleton. Raises `RuntimeError` if
  `init_jwks_verifier` has not been called.
- **`JWKSVerifier`** -- Singleton that fetches and caches JWKS keys, verifies tokens, and
  extracts cookies. Methods: `verify_token(token)`, `verify_request(request)`,
  `get_token_from_cookie(request)`.
- **`JWKSConfig`** -- Pydantic model with fields: `jwks_url`, `issuer`, `audience`,
  `cookie_name` (default `"nohiki_at"`), `cache_ttl_seconds` (default `3600`),
  `algorithm` (default `"RS256"`).
- **`JWTClaims`** -- Dataclass with `sub`, `iss`, `aud`, `exp`, `iat`, `jti`, `roles`,
  `permissions`, `tenant_id`.
- **`JWKSVerificationError`** -- Raised by `JWKSVerifier` on any verification failure
  (missing cookie, expired token, invalid issuer, invalid audience, JWKS fetch error).
- **`get_current_user_id_from_cookie`** -- FastAPI dependency returning `UUID` from JWT cookie.
  Raises HTTP 401 on failure.
- **`get_current_user_claims`** -- FastAPI dependency returning full `JWTClaims`. Raises HTTP
  401 on failure.
- **`get_current_user_id_from_header`** -- FastAPI dependency reading `X-Account-Id` header.
  Raises HTTP 401 if missing or not a valid UUID.

### Rate Limiting (`[cache]` extra required)

- **`setup_rate_limiting(app, service_name, *, redis_url, key_func=None, default_limits=None)`** --
  Adds `RateLimitMiddleware` and registers the exception handler. Default limits are
  `["100/minute", "1000/hour"]`. Returns the configured `Storage` instance.
- **`rate_limit(*limits)`** -- Decorator applying per-route rate limits, e.g.
  `@rate_limit("5/minute", "50/hour")`. Overrides the middleware defaults for that route.
- **`get_client_id(request)`** -- Extracts the rate limit key from the request. Returns
  `"user:<id>"` for authenticated requests or `"ip:<addr>"` for anonymous ones.

### Pagination

- **`PaginationParams`** -- Pydantic model with `page` (default 1) and `page_size` (default 20).
  `.offset` property computes `(page - 1) * page_size`.
- **`SortParams`** -- Pydantic model with `sort_by: str | None` and `sort_dir` (`"asc"` or
  `"desc"`, default `"desc"`). `.is_ascending` property returns `sort_dir == "asc"`.
- **`PaginatedResponse[T]`** -- Generic response model with `items`, `total`, `page`,
  `page_size`, `total_pages`, `has_next`, `has_prev`. Construct with `.create(items, total, params)`
  or `.empty(params)`.

### Routing Utilities

- **`build_root_router(service_name, version)`** -- Returns an `APIRouter` with a single `GET /`
  endpoint returning `{"service": ..., "version": ..., "status": "running"}`.

### Observability Re-exports

- **`CorrelationIdMiddleware`** -- Re-exported from `nohiki-observability`. Propagates
  `X-Correlation-Id` across requests.
- **`CORRELATION_ID_HEADER`**, **`get_correlation_id()`**, **`set_correlation_id()`** --
  Re-exported from `nohiki-observability` for correlation ID access in handlers.

## Configuration

This library has no Pydantic settings mixin of its own. All configuration is passed directly
to the component constructors. Services compose their own settings from `nohiki-core-settings`
base classes and pass the relevant values when calling `init_jwks_verifier`, `setup_rate_limiting`,
and `build_probe_health_router`.

### Optional Extras

| Extra | Adds | Used by |
|---|---|---|
| `server` | `uvicorn` | All 18 services |
| `jwt` | `PyJWT`, `cryptography` | `bff-service` only |
| `otel` | `nohiki-observability[fastapi,httpx]` | `bff-service`, `user-auth-service`, others |
| `cache` | `nohiki-redis-utils` | Services with rate limiting |

Declare the extras in `pyproject.toml`:

```toml
dependencies = [
    "nohiki-fastapi-utils[server,otel,jwt]==0.1.0",
]
```

The `jwt` module imports fail gracefully when `PyJWT` is not installed. The JWKS symbols are
excluded from `__all__` and fall back to `None`. This allows all services to install the base
package without pulling in cryptography dependencies they do not need.

## Testing

### Error Handlers

Use `fastapi.testclient.TestClient` to test the error response shape without mocking:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nohiki_fastapi_utils import setup_error_handlers
from nohiki_fastapi_utils.errors import NotFoundError

app = FastAPI()
setup_error_handlers(app)

@app.get("/items/{item_id}")
async def get_item(item_id: str) -> dict[str, str]:
    raise NotFoundError("Item", item_id)

client = TestClient(app, raise_server_exceptions=False)
response = client.get("/items/missing")
assert response.status_code == 404
assert response.json()["error"] == "NOT_FOUND"
```

### JWKS Verifier

Patch `PyJWKClient` and `jwt.decode` to unit test code that depends on `JWKSVerifier` without
a live `user-auth-service`:

```python
from unittest.mock import MagicMock, patch
from nohiki_fastapi_utils.jwks import JWKSConfig, JWKSVerifier

config = JWKSConfig(
    jwks_url="https://auth.example.com/.well-known/jwks.json",
    issuer="https://auth.example.com",
    audience="my-app",
)

mock_payload = {"sub": "uuid-here", "iss": "...", "aud": "...", "exp": 9999, "iat": 0, "jti": "x"}

with (
    patch("nohiki_fastapi_utils.jwks.PyJWKClient") as mock_client_class,
    patch("nohiki_fastapi_utils.jwks.jwt.decode", return_value=mock_payload),
):
    mock_client_class.return_value.get_signing_key_from_jwt.return_value = MagicMock(key="k")
    verifier = JWKSVerifier(config)
    claims = verifier.verify_token("fake-token")
```

Reset the singleton between test classes by setting `JWKSVerifier._instance = None`.

### Health Router

Pass inline probe classes to `build_probe_health_router` to simulate healthy and unhealthy
probe results without infrastructure:

```python
from nohiki_common_exceptions import HealthProbeResult, HealthStatus
from nohiki_fastapi_utils.health_router import build_probe_health_router

class FailingProbe:
    name = "kafka"

    async def check(self) -> HealthProbeResult:
        return HealthProbeResult(name="kafka", status=HealthStatus.UNHEALTHY, message="down", latency_ms=0)

router = build_probe_health_router("my-service", lambda: [FailingProbe()])
```

### Rate Limiter

Patch `create_cache` to inject an `AsyncMock` cache:

```python
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from nohiki_fastapi_utils import setup_rate_limiting

mock_cache = AsyncMock()
mock_cache.get = AsyncMock(return_value=0)
mock_cache.set = AsyncMock()

with patch("nohiki_fastapi_utils.rate_limiter.create_cache", return_value=mock_cache):
    app = FastAPI()
    setup_rate_limiting(app, "test-service", redis_url="redis://localhost")
```

## Design Decisions

### No double-submit CSRF tokens

The CSRF implementation relies on `Origin`/`Sec-Fetch-Site` header validation rather than
double-submit cookies or synchronizer tokens. This is sufficient because authentication relies
on `HttpOnly` cookies, which browser JavaScript cannot read or forge, and because modern browsers
send `Sec-Fetch-Site` on all cross-origin requests. Forged cross-site requests from pages on
other origins will have an `Origin` header that fails the allowlist check.

### JWKS caching in `PyJWKClient`

Key rotation is handled passively: `PyJWKClient` caches JWKS keys for `cache_ttl_seconds`. When
a request arrives with a JWT signed by a new key ID that is not in the cache, the client fetches
the JWKS document again immediately. This means key rotation in `user-auth-service` propagates
to `bff-service` within one token request cycle, with no restart required.

### Soft dependency on `jwt` extra

The JWKS module is imported inside a `try/except ImportError` block in `__init__.py`. Services
without the `jwt` extra install cleanly and get all other functionality. The rate limiter applies
the same pattern: it tries to import `JWKSVerifier` for user-ID extraction but falls back to
header and IP-based identification when the extra is absent.
