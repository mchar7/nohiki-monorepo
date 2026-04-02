# Nohiki Common Exceptions

Typed exception hierarchy and health probe protocol shared across all 18 backend services in the Nohiki monorepo.
The exception types carry retry semantics that `nohiki-kafka-client` uses to decide automatically, without
service-specific logic, whether a failed Kafka handler should be retried with backoff, retried immediately, or
routed to the DLQ. Without a shared hierarchy, each service would define its own types and the consumer
infrastructure would have no way to make generic retry decisions.

## Quick Start

```python
from nohiki_common_exceptions import (
    DataNotAvailableError,
    DataNotFoundError,
    DataIntegrityError,
    ExternalServiceError,
    RateLimitedError,
    ValidationError,
)

# Temporary unavailability: triggers exponential backoff retry
raise DataNotAvailableError(
    resource_type="SearchPrefSnapshot",
    resource_id=str(profile_id),
    source="redis",
)

# Entity does not exist: routes to DLQ immediately, no retry
raise DataNotFoundError(resource_type="Listing", resource_id=str(listing_id))

# External API failure: triggers exponential backoff retry
raise ExternalServiceError(
    service_name="jsearch",
    operation="search",
    original_error=exc,
)

# Rate limited by external API: triggers linear backoff retry
raise RateLimitedError(service_name="jsearch", retry_after_seconds=60.0)

# Invalid input: routes to DLQ immediately, no retry
raise ValidationError(
    field_name="listing_id",
    invalid_value=raw_value,
    constraint="must be a valid UUID",
)
```

To check retry semantics in generic exception-handling code:

```python
from nohiki_common_exceptions import NohikiError

try:
    await process_event(message)
except NohikiError as exc:
    if exc.is_retryable:
        logger.warning("Retryable failure", **exc.to_log_context())
    else:
        logger.error("Non-retryable failure -- routing to DLQ", **exc.to_log_context())
```

## Core Concepts

### Retry Semantics Are Encoded in the Type

Every `NohikiError` subclass sets `retry_strategy` in its `__post_init__`. The `nohiki-kafka-client`
inspects this field to determine handler behavior, with no configuration required in the service.
The mapping is:

| Exception | `retry_strategy` | Kafka handler behavior | Severity |
|---|---|---|---|
| `DataNotAvailableError` | `RETRY_EXPONENTIAL` | Retry with exponential backoff | HIGH |
| `StaleDataError` | `RETRY_IMMEDIATE` | Retry immediately (no delay) | MEDIUM |
| `ExternalServiceError` | `RETRY_EXPONENTIAL` | Retry with exponential backoff | HIGH |
| `RateLimitedError` | `RETRY_LINEAR` | Retry with linear backoff | MEDIUM |
| `DataNotFoundError` | `NO_RETRY` | Route to DLQ | MEDIUM |
| `DataIntegrityError` | `NO_RETRY` | Route to DLQ | CRITICAL |
| `ValidationError` | `NO_RETRY` | Route to DLQ | LOW |
| `SchemaVersionMismatchError` | `NO_RETRY` | Route to DLQ | HIGH |

The `is_retryable` property on `NohikiError` summarizes this: it returns `True` for any strategy
other than `NO_RETRY`.

### Structured Context for Logging

Every exception carries a `context` dict populated in `__post_init__` with fields relevant to that
exception type (e.g., `resource_type`, `resource_id`, `source` for `DataNotAvailableError`). Call
`to_log_context()` to get a flat dict suitable for passing to `nohiki-observability`'s structured logger:

```python
logger.error("Handler failed", **exc.to_log_context())
# Produces: error_type, error_message, severity, retry_strategy, resource_type, resource_id, source
```

### Choosing Between Data Exceptions

The three data-related exceptions cover distinct situations that require different responses:

- **`DataNotAvailableError`** -- The data should exist but is unreachable right now. The handler that
  published the upstream event may not have committed yet, or Redis/the database is momentarily
  unavailable. Retry with backoff.

- **`DataNotFoundError`** -- The entity definitively does not exist. A database query returned nothing
  for a valid query. Retrying with the same ID will produce the same result. Route to DLQ.

- **`DataIntegrityError`** -- The data was expected to exist based on prior successful writes but is
  missing. For example, Qdrant embeddings are absent for a skill that was indexed in a previous
  Kafka event. This is a system invariant violation requiring investigation, not a transient failure.
  Route to DLQ. Severity is `CRITICAL`.

- **`StaleDataError`** -- The data exists but has exceeded its maximum acceptable age. A retry may
  succeed once a refresh is triggered. Use `data_age_seconds` and `max_age_seconds` to surface the
  specific violation in logs.

### Health Probe Protocol

The `HealthProbe` protocol (alongside `HealthProbeResult`, `HealthStatus`, and `HealthProbeTimer`)
lives in this library so it can be implemented by every infrastructure library (`nohiki-redis-utils`,
`nohiki-db-utils`, `nohiki-kafka-client`, etc.) without creating circular dependencies.
Services declare which probes they need; `nohiki-fastapi-utils` aggregates results into the `/health`
endpoint response.

```python
from nohiki_common_exceptions import HealthProbe, HealthProbeResult, HealthProbeTimer
from nohiki_common_exceptions import create_healthy_result, create_unhealthy_result

class RedisHealthProbe:
    @property
    def name(self) -> str:
        return "redis"

    async def check(self) -> HealthProbeResult:
        with HealthProbeTimer() as timer:
            try:
                await self._client.ping()
            except Exception as exc:
                return create_unhealthy_result("redis", str(exc), timer.elapsed_ms)
        return create_healthy_result("redis", "Connected", timer.elapsed_ms)
```

`HealthProbeResult.is_healthy()` returns `True` for both `HEALTHY` and `DEGRADED` -- the aggregator
uses this to compute overall service readiness.

### User-Facing Error Codes

`UserFacingErrorCode` is a `StrEnum` of stable, versioned error codes (e.g., `"PROFILE.NOT_FOUND"`,
`"AUTH.SESSION_EXPIRED"`) that the BFF maps from domain exceptions and returns to the frontend.
The frontend uses these codes for i18n message lookup. `DEFAULT_MESSAGES` provides the English
fallback strings. Use `get_default_message(code)` to retrieve a default.

This is the only part of this library that is BFF-specific. Kafka-only services do not need to
import `user_messages`.

## API Reference

### Base Classes and Enums

- **`NohikiError`** -- Dataclass base for all service exceptions. Fields: `message: str`,
  `severity: ErrorSeverity`, `retry_strategy: RetryStrategy`, `context: dict[str, Any]`.
  Property `is_retryable` returns `False` only for `NO_RETRY`. Method `to_log_context()` returns
  a flat dict merging base fields with `context` -- pass this directly to structured log calls.

- **`RetryStrategy`** -- Enum with four values: `NO_RETRY`, `RETRY_IMMEDIATE`, `RETRY_EXPONENTIAL`,
  `RETRY_LINEAR`. The kafka-client reads this field to select the correct backoff implementation.

- **`ErrorSeverity`** -- Enum with four values: `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`. Maps to
  logging levels and alerting thresholds in `nohiki-observability`.

### Data Exceptions

- **`DataNotAvailableError(resource_type, resource_id, source)`** -- Temporary unavailability.
  `source` identifies where the data was expected (e.g., `"redis"`, `"database"`, `"s3"`).
  Retry: exponential backoff. Severity: HIGH.

- **`DataNotFoundError(resource_type, resource_id)`** -- Entity definitively does not exist.
  No retry. Severity: MEDIUM. The BFF error handler maps `resource_type` to a `UserFacingErrorCode`
  (e.g., `"Listing"` → `LISTING.NOT_FOUND`).

- **`StaleDataError(resource_type, resource_id, data_age_seconds, max_age_seconds)`** -- Data exists
  but is too old. Both age fields are included in `context` for log-based alerting.
  Retry: immediate. Severity: MEDIUM.

- **`DataIntegrityError(resource_type, resource_ids)`** -- Invariant violation: data that prior
  writes guarantee should exist is missing. Accepts a `tuple[str, ...]` of IDs; messages with more
  than 5 IDs include an overflow count suffix. No retry. Severity: CRITICAL.

### External Service Exceptions

- **`ExternalServiceError(service_name, operation, original_error)`** -- Wraps failures from HTTP
  or any external API call. `original_error` is captured in `context` as type name and message
  for structured log correlation. Retry: exponential backoff. Severity: HIGH.

- **`RateLimitedError(service_name, retry_after_seconds)`** -- HTTP 429 or quota exhaustion.
  `retry_after_seconds` is optional; when provided it is included in the auto-generated message
  and `context`. Retry: linear backoff. Severity: MEDIUM.

### Validation Exceptions

- **`ValidationError(field_name, invalid_value, constraint)`** -- Invalid input that will not
  become valid on retry. `invalid_value` is truncated to 100 characters in `context` to avoid
  exposing large payloads in logs. No retry. Severity: LOW.

- **`SchemaVersionMismatchError(expected_version, actual_version)`** -- Incompatible protobuf or
  JSON schema version on an incoming Kafka event. Requires a code change to resolve; retrying
  the same message will always fail. No retry. Severity: HIGH.

### Health Probe Types

- **`HealthProbe`** -- `@runtime_checkable` Protocol. Implement `name: str` (property) and
  `check() -> HealthProbeResult` (async method). Infrastructure libraries implement this; services
  pass instances to `nohiki-fastapi-utils` for aggregation.

- **`HealthProbeResult`** -- Frozen dataclass. Fields: `name`, `status`, `message`, `latency_ms`,
  `details`. Method `to_dict()` rounds `latency_ms` to 2 decimal places for JSON serialization.
  Use the factory helpers below instead of constructing directly.

- **`HealthProbeTimer`** -- Context manager. Measures elapsed wall time. Read `elapsed_ms` after
  the `with` block to get the duration to pass to a factory helper.

- **`create_healthy_result(name, message, latency_ms, details)`** -- Returns `HealthProbeResult`
  with `status=HEALTHY`.

- **`create_degraded_result(name, message, latency_ms, details)`** -- Returns `HealthProbeResult`
  with `status=DEGRADED`. `is_healthy()` returns `True` for degraded. The service is still
  accepting traffic, just impaired.

- **`create_unhealthy_result(name, message, latency_ms, details)`** -- Returns `HealthProbeResult`
  with `status=UNHEALTHY`. `is_healthy()` returns `False`.

### User-Facing Error Code API

- **`UserFacingErrorCode`** -- `StrEnum` of stable error codes grouped by domain (`AUTH.*`,
  `PROFILE.*`, `ATTACHMENT.*`, `LISTING.*`, `CORRELATION.*`, `DOCUMENT.*`, `VALIDATION.*`,
  `NETWORK.*`). Import only in BFF-layer code.

- **`DEFAULT_MESSAGES`** -- `dict[UserFacingErrorCode, str]` of English fallback messages.

- **`get_default_message(code)`** -- Returns the English string for a code, or `"An error occurred"`
  if the code is absent from `DEFAULT_MESSAGES`.

## Testing

This library has no external dependencies, so no mocking is required for unit tests. Raise exceptions
directly and assert on their fields:

```python
from nohiki_common_exceptions import DataNotAvailableError, RetryStrategy, ErrorSeverity

def test_missing_profile_triggers_retry() -> None:
    exc = DataNotAvailableError(
        resource_type="SearchPrefSnapshot",
        resource_id="prof-123",
        source="redis",
    )
    assert exc.is_retryable is True
    assert exc.retry_strategy == RetryStrategy.RETRY_EXPONENTIAL
    assert exc.severity == ErrorSeverity.HIGH
    assert exc.context["source"] == "redis"
```

For Kafka handler tests, simulate the retry/DLQ branch by catching `NohikiError` and branching on
`exc.is_retryable` -- the same logic the kafka-client applies at runtime. No kafka-client fixture is
needed to verify exception routing behavior.

## Design Decisions

**Zero dependencies.** The library has no runtime dependencies. This is intentional: every service
depends on it, so any dependency here becomes a transitive dependency of all 18 services. Keeping it
empty eliminates version conflict risk.

**Dataclass exceptions, not traditional subclasses.** Using `@dataclass` on exception classes allows
constructor keyword arguments without boilerplate `__init__` definitions, and makes fields visible
to type checkers without accessing `args`. The `__post_init__` pattern lets each subclass set its
`severity` and `retry_strategy` unconditionally. Callers cannot accidentally pass the wrong
strategy for a given exception type.

**Health probe protocol in this library.** The `HealthProbe` protocol needs to be implemented by
every infrastructure library but consumed by `nohiki-fastapi-utils`. Placing it in a
dependency-free library avoids a circular dependency between infrastructure libs.
