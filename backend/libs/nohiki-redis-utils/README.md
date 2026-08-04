# Nohiki Redis Utils

Provides `RedisCache`, circuit breaker protection, distributed rate limiting, distributed locking,
idempotency checks, Kafka retry tracking, and health probes for Nohiki services. Used by 14 of 18
backend services; every service that interacts with Redis uses this library rather than the
`redis` client directly. Centralizing these concerns prevents each service from independently
implementing sliding-window Lua scripts, per-service key namespacing, event-loop-aware connection
management, and circuit breaker state machines.

## Quick Start

```python
from nohiki_redis_utils import create_cache, ensure_redis_ready, CacheFactory

# In FastAPI lifespan startup
async def startup():
    await ensure_redis_ready(settings.redis.connection_string)
    cache = create_cache(settings.service_name, redis_url=settings.redis.connection_string)
    await cache.set("user:123", {"name": "Alice"}, ttl=3600)
    value = await cache.get("user:123")   # returns {"name": "Alice"}

# In FastAPI lifespan shutdown
async def shutdown():
    await CacheFactory.close_all()  # closes all cached connection pools
```

For services with `RedisMixin` in their settings:

```python
from nohiki_core_settings import NohikiBaseSettings
from nohiki_redis_utils import RedisMixin

class Settings(RedisMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
    # Adds: settings.redis.dsn, settings.redis_url, SSL enforcement in production
```

## Core Concepts

### Service Isolation via Key Namespacing

`create_cache(service_name, redis_url=...)` returns a `RedisCache` that prefixes every key with
`{service_name}:`, so services sharing a Redis instance never collide. The DSN is used exactly
as configured.

`CacheFactory` is the singleton manager behind `create_cache`. It caches instances per
`service_name` and is event-loop-aware: if the loop changes (e.g., in test teardown), it
creates a fresh instance rather than reusing a stale connection. Call `CacheFactory.close_all()`
in your service shutdown lifespan; this is the canonical cleanup pattern used by all 14 services.

### Circuit Breaker on Every Operation

Every `RedisCache` method (`get`, `set`, `delete`, `exists`, `eval_script`, etc.) is wrapped
in a `CircuitBreaker`. The breaker tracks consecutive failures and transitions through three
states:

```text
CLOSED ──(failures >= threshold)──► OPEN
  ▲                                    │
  └──(successes >= threshold)── HALF_OPEN ◄──(timeout elapsed)──┘
```

When OPEN, all cache operations return their safe fallback (`None` for `get`, `False` for
`exists`, `[]` for `eval_script`) without touching Redis. This prevents a Redis outage from
cascading into handler timeouts across all pods. The circuit breaker is per-instance and
per-process; state is not shared via Redis (by design, to avoid coordination overhead).

Rate limiting operations fail open on Redis errors: if `eval_script` returns an unexpected
result or throws, the limiter allows the request rather than blocking legitimate traffic.

### Rate Limiting Hierarchy

Three rate limiting abstractions, each building on the one below:

**`RateLimiter`** (base): Atomic Lua-script-based sliding window or token bucket. Operates
against a single key. Use `create_sliding_window_limiter` or `create_token_bucket_limiter`
for direct construction, or `create_rate_limiter(cache, RateLimitConfig(...))` for
algorithm selection via config.

- Sliding window: Stores each request timestamp in a sorted set. O(requests/window) memory.
  Precise: the window is truly sliding, not fixed.
- Token bucket: Stores token count + last refill time in a hash. O(1) memory. Allows bursts
  up to `burst_size` while maintaining an average rate.

**`MultiTierRateLimiter`**: Applies multiple `RateLimiter` instances simultaneously, checked
in priority order. Used when an external API has both a monthly quota (hard limit) and an hourly
quota (soft limit). Each tier has a `TierExceededBehavior`: `REJECT` stops the check immediately,
`LOG_ONLY` records the violation but allows the request. `check()` returns a `MultiTierCheckResult`
with `allowed`, `exceeded_tier`, and `retry_after`.

**`AuthRateLimiter`**: Pre-configured `MultiTierRateLimiter` for authentication endpoints.
Wraps login (per-minute + per-hour), registration (per-hour + per-day), password reset
(per-hour), and failed login tracking into a single class with sensible defaults. This is what
`user-auth-service` uses rather than constructing individual limiters.

### Distributed Locking

`RedisCache.distributed_lock(operation_name)` is an async context manager that acquires a Redis
lock via `SETNX` with TTL. Raises `DistributedLockError` if the lock cannot be acquired within
`timeout_seconds` (default 30). The lock value is `f"{timestamp}:{id(cache_instance)}"`; release
is ownership-verified (only the acquiring instance can release).

Used by `doc-template-service` to ensure only one pod seeds default templates on startup.

### Idempotency for Stateless Services

`check_and_mark_processed_redis(cache, event_id, handler_name)` provides lightweight event
deduplication for services without a database. Uses `SETNX` with a 7-day TTL. Returns `True`
if the event is new (and marks it), `False` if already processed. Used by `ml-gateway-service`
and similar stateless Kafka consumers.

### Kafka Retry Tracking

`RedisRetryTracker` persists Kafka message retry counts across pod restarts. The problem it
solves: if retry counts are in-memory and a pod restarts mid-retry, a message can retry
indefinitely without ever reaching the DLQ. `RedisRetryTracker` stores retry counts keyed by
`{topic}:{partition}:{offset}` with a 24-hour TTL. Uses atomic pipelines (`INCR` + `EXPIRE`)
to prevent race conditions under concurrent handler execution.

`InMemoryRetryTracker` provides the same interface without Redis; use it in tests.

## API Reference

### Cache Operations

- **`create_cache(service_name, *, redis_url)`**: Creates (or retrieves from cache) a
  `RedisCache` instance for the named service. The primary entry point for all services.
- **`CacheFactory.close_all()`**: Closes all open Redis connections. Call during service shutdown.
- **`RedisCache.get(key)`** → `object | None`: Returns deserialized value. JSON objects/arrays
  are deserialized; strings are returned as-is.
- **`RedisCache.set(key, value, ttl=None)`**: Serializes dicts/lists to JSON, all other values
  to `str`.
- **`RedisCache.set_bytes(key, value, ttl=None)`** / **`get_bytes(key)`**: Raw bytes storage,
  bypassing JSON serialization. Used for binary payloads.
- **`RedisCache.setnx(key, value, ttl=None)`** → `bool`: Set only if key absent. Backbone of
  distributed locking and idempotency.
- **`RedisCache.incr(key)`** → `int`: Atomic increment. Creates key at 1 if absent.
- **`RedisCache.eval_script(script, keys, args)`**: Executes a Lua script atomically. Keys are
  automatically prefixed with the service namespace. Used internally by rate limiters.
- **`RedisCache.distributed_lock(operation_name, ttl_seconds=300, timeout_seconds=30.0)`**:
  Async context manager. Raises `DistributedLockError` on timeout.

### Rate Limiting

- **`create_sliding_window_limiter(cache, requests, window_seconds)`**: Returns a
  `SlidingWindowRateLimiter`. Best for precise limits where accuracy matters more than memory.
- **`create_token_bucket_limiter(cache, requests, window_seconds, burst_size=None)`**: Returns a
  `TokenBucketRateLimiter`. Best for APIs where short bursts are acceptable.
- **`RateLimiter.check(key)`** → `RateLimitResult`: Atomically checks and consumes one slot.
  `RateLimitResult.allowed` is `True` if the request is permitted; `retry_after` gives seconds
  until next slot when blocked.
- **`RateLimiter.reset(key)`**: Clears the counter for a key.
- **`MultiTierRateLimiter(cache, key_prefix, tiers)`**: Constructs a multi-tier limiter. Tiers
  are checked in ascending `priority` order.
- **`AuthRateLimiter.create(cache, config=None)`**: Factory for the pre-configured auth limiter.
  `check_login(identifier)`, `check_register(ip)`, `check_password_reset(email)` return
  `MultiTierCheckResult`. `record_failed_login(identifier)` returns the failure count.
- **`rate_limit_config`** helpers: `per_second(n)`, `per_minute(n)`, `per_hour(n)`,
  `per_day(n, count=1)` return `RateLimit` dataclasses with a `.window_seconds` property.
  Used to construct `MultiTierRateLimiter` tiers with readable units.

### Circuit Breaker

- **`@circuit_breaker(name, *, fallback=None, excluded_exceptions=(), on_state_change=None)`** --
  Decorator for async functions. When the circuit opens, returns `fallback` (or raises
  `CircuitOpenError` if `fallback=None`). `excluded_exceptions` are re-raised without tripping
  the counter. The decorated function gains a `.circuit_breaker` proxy for state inspection and
  manual `reset()`.

```python
from nohiki_redis_utils import circuit_breaker, CircuitOpenError

@circuit_breaker("gotenberg-pdf", fallback=None)
async def render_pdf(html: str) -> bytes:
    return await gotenberg_client.post("/forms/chromium/convert/html", content=html)

# Access state
if render_pdf.circuit_breaker.is_closed:
    ...
```

- **`CircuitBreaker(name, config=None)`**: Lower-level class for granular control. Methods:
  `can_execute()`, `record_success()`, `record_failure(exc)`, `reset()`, `get_retry_after()`.
  Used when the decorator pattern doesn't fit (e.g., retry loops that own the outcome decision).

### Caching Decorators

Both decorators require a `cache_factory` callable (not the cache instance directly) to
support lazy initialization and event-loop-safe construction.

```python
from nohiki_redis_utils import cached, create_cache

def _get_cache() -> RedisCache:
    return create_cache("doc-template-service", redis_url=settings.redis_url)

@cached(key_prefix="template", ttl=3600, cache_factory=_get_cache)
async def get_template(template_id: str) -> TemplateSnapshot | None:
    return await repo.find(template_id)

# Bypass cache for one call
result = await get_template("abc", bypass_cache=True)

# Invalidate a specific entry
await get_template.invalidate("abc")
```

- **`@cached(key_prefix, ttl, *, cache_factory, skip_kwarg="bypass_cache", key_builder=None)`**:
  Read-through async cache. The default key is `{key_prefix}:{arg0}:{arg1}:...`.
- **`@cached_sync(...)`**: Same interface for synchronous functions. Uses `asyncio.run()` for
  each Redis operation; appropriate for non-hot-path config loading.

### Idempotency and Retry Tracking

- **`check_and_mark_processed_redis(cache, event_id, handler_name, ttl_seconds=604800)`** →
  `bool`: Returns `True` if new (and atomically marks it). Returns `False` if duplicate.
  Key format: `processed:{handler_name}:{event_id}`.
- **`RedisRetryTracker(redis, key_prefix="retry", ttl_seconds=86400)`**: Requires a raw
  `redis.asyncio.Redis` client (not `RedisCache`). Methods: `get_retry_count`, `increment_retry_count`,
  `clear_retry_count`, `get_first_failure_time`, `set_first_failure_time`.
- **`InMemoryRetryTracker()`**: Drop-in test replacement for `RedisRetryTracker`.

### Health

- **`ensure_redis_ready(redis_url, *, timeout_seconds=30.0, retry_interval_seconds=2.0)`**:
  Blocks until Redis responds to PING. Call in service lifespan startup before creating caches.
  Raises `RuntimeError` if Redis is unavailable after `timeout_seconds`.
- **`RedisHealthProbe(redis_url, *, timeout_ms=1000.0, degraded_threshold_ms=100.0, require_write=True)`**:
  Implements the `HealthProbe` protocol for K8s readiness integration. `require_write=True`
  runs a full SET/GET/DELETE cycle; `False` runs PING only.
- **`check_cache_health(cache, timeout_ms=1000.0, degraded_threshold_ms=100.0)`** →
  `CacheHealthResult`: Performs a read/write/delete cycle and classifies the result as
  `HEALTHY`, `DEGRADED`, or `UNHEALTHY` based on latency thresholds.

### Metrics

- **`get_redis_metrics()`** → `RedisMetrics`: Returns the process-singleton OTel metrics
  instance. `RedisCache` calls this internally on every operation. Emits:
  `nohiki_redis_operations_total`, `nohiki_redis_operation_duration_seconds`,
  `nohiki_redis_cache_hits_total`, `nohiki_redis_cache_misses_total`, `nohiki_redis_errors_total`.

## Configuration

### RedisMixin

Add to the service settings class to declare Redis as required:

```python
from nohiki_core_settings import NohikiBaseSettings
from nohiki_redis_utils import RedisMixin

class Settings(RedisMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")
```

`RedisMixin` adds:

- `redis: RedisSettings`, parsed from the `REDIS__DSN` environment variable.
- `redis_url` property: shorthand for `settings.redis.connection_string`.
- `instrument_redis` property: overrides the base class default to `True`, enabling OTel Redis
  instrumentation automatically.
- SSL enforcement: raises `ValueError` at startup if `REDIS__DSN` uses `redis://` (non-SSL)
  in any non-development environment.

### RedisSettings

| Field | Env var | Default | Description |
| ------- | --------- | --------- | ------------- |
| `dsn` | `REDIS__DSN` | `redis://localhost:6379` | Full connection string |
| `socket_timeout` | `REDIS__SOCKET_TIMEOUT` | `5.0` | Read/write timeout (seconds) |
| `socket_connect_timeout` | `REDIS__SOCKET_CONNECT_TIMEOUT` | `5.0` | Connection timeout (seconds) |
| `retry_on_timeout` | `REDIS__RETRY_ON_TIMEOUT` | `true` | Retry on socket timeout |
| `max_connections` | `REDIS__MAX_CONNECTIONS` | `10` | Connection pool size |
| `default_ttl_seconds` | `REDIS__DEFAULT_TTL_SECONDS` | `3600` | Default TTL if not specified |

Use `rediss://` scheme for SSL connections. In production environments, `redis://` raises a
validation error at startup.

### CachingSettings

`CachingSettings` is a composable Pydantic model services add to their settings for standardized
TTL presets and rate limit configuration:

```python
from nohiki_redis_utils import CachingSettings

class Settings(RedisMixin, NohikiBaseSettings):
    caching: CachingSettings = Field(default_factory=CachingSettings)
```

Key sub-models and their environment variable prefixes:

- **`CachingSettings.ttls`** (`CACHING__TTLS__*`): Semantic TTL presets: `short` (300s),
  `medium` (3600s), `long` (86400s), `projection` (86400s), `rate_limit_window` (60s),
  `circuit_breaker` (300s), `token` (3600s).
- **`CachingSettings.rate_limit`** (`CACHING__RATE_LIMIT__*`): `enabled`, `requests_per_window`,
  `window_seconds`, `key_prefix`.
- **`CachingSettings.circuit_breaker`** (`CACHING__CIRCUIT_BREAKER__*`): `failure_threshold` (5),
  `success_threshold` (2), `timeout_seconds` (30), `half_open_max_calls` (3).

Services extend `CachingSettings` to add service-specific keys:

```python
class BFFCachingSettings(CachingSettings):
    search_results_ttl: int = Field(default=120)
```

### AuthRateLimitConfig

| Field | Default | Description |
| ------- | --------- | ------------- |
| `login_per_minute` | `5` | Max login attempts per minute per identifier |
| `login_per_hour` | `20` | Max login attempts per hour per identifier |
| `register_per_hour` | `3` | Max registration attempts per hour per IP |
| `register_per_day` | `10` | Max registration attempts per day per IP |
| `reset_per_hour` | `3` | Max password reset requests per hour per email |
| `max_failed_logins` | `10` | Failed attempts before lockout |
| `failed_login_window_seconds` | `3600` | Window for failed login counting |

## Testing

The library provides pytest fixtures in `nohiki_redis_utils.testing`:

```python
from nohiki_redis_utils.testing import redis_cache, redis_container
# redis_container: session-scoped fixture that starts a Redis 8 testcontainer
# redis_cache: function-scoped RedisCache connected to the container
```

These fixtures skip automatically if Docker is unavailable.

For unit tests that do not need real Redis, use `InMemoryRetryTracker` instead of
`RedisRetryTracker`, and pass a `RedisCache` mock or construct one against the testcontainer:

```python
async def test_rate_limiter(redis_cache: RedisCache) -> None:
    limiter = create_sliding_window_limiter(redis_cache, requests=5, window_seconds=60)
    for _ in range(5):
        result = await limiter.check("test-key")
        assert result.allowed
    result = await limiter.check("test-key")
    assert not result.allowed
    assert result.retry_after is not None
```

Tag integration tests with `@pytest.mark.requires_docker` to exclude them from CI environments
without Docker. Run the library's own tests via:

```bash
just test nohiki-redis-utils
```

## Design Decisions

**Per-process circuit breaker state**: The `CircuitBreaker` in `RedisCache` is in-process.
If 3 of 10 pods see Redis failures and open their circuit, the other 7 continue serving cached
data. This is intentional: coordinating circuit state via Redis would create a dependency
on the very resource being protected, and the Prometheus metrics surface per-pod circuit state
for observability.

**Fail-open for rate limiting**: When the Lua script fails (Redis unavailable, wrong result
shape), the rate limiter allows the request. The alternative (blocking all traffic when rate
limiting is unavailable) would mean a Redis hiccup takes down all API endpoints.

**Key-prefix isolation**: Every operation prefixes keys with the service name, and the DSN is
used exactly as configured. Logical-DB sharding is deliberately avoided: `SELECT` does not
exist in cluster mode and several managed providers disable it. The prefix is a namespace
boundary, not a security boundary.
