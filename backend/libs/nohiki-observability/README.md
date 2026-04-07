# Nohiki Observability

Provides the three observability pillars: structured logging, distributed tracing, and Prometheus
metrics for all 18 Nohiki backend services. Every service `main.py` calls
`Observability.from_settings(settings)` at module load time, ensuring uniform telemetry from
startup through shutdown.

## Quick Start

The typical pattern used by all services: initialize from settings, instrument FastAPI, expose
metrics, and shut down cleanly:

```python
from nohiki_observability import Observability, build_metrics_router

# At module level in main.py: runs before the FastAPI app is created
settings = get_settings()
obs = Observability.from_settings(settings)
obs.init()
logger = obs.get_logger(__name__)

# Instrument FastAPI (adds CorrelationIdMiddleware + OTel span per request)
obs.init_fastapi(app)

# Expose /metrics for Prometheus scraping
app.include_router(build_metrics_router())

# In lifespan shutdown: flushes pending spans/metrics before process exits
obs.shutdown()
```

Acquiring a logger anywhere else in the service:

```python
from nohiki_observability import get_logger

logger = get_logger(__name__)
logger.info("Listing accepted", listing_id=listing_id, source=source)
```

## Core Concepts

### Structured Logging

`get_logger(name)` returns a `Logger` instance backed by structlog. Every log call produces a
JSON object on stdout. The processor chain automatically enriches every event with:

- `timestamp` -- ISO 8601 UTC timestamp
- `service` and `version` -- injected by `ServiceInfoProcessor` from the `Observability` options
- `trace_id` and `span_id` -- extracted from the active OTel span context, enabling log/trace
  correlation in Grafana
- `correlation_id` -- the per-request UUID (see Correlation IDs below)

The `Logger` class accepts arbitrary keyword arguments on every call, which become structured
fields in the JSON output:

```python
logger.info("Job scored", listing_id=listing_id, score=0.87, stage="l2r")
logger.error("Embedding request failed", listing_id=listing_id, error=str(e))
logger.exception("Unexpected failure")  # Includes full traceback in the JSON
```

Use `logger.bind(**kwargs)` to produce a child logger with permanent context for a scope:

```python
handler_logger = logger.bind(listing_id=listing_id, profile_id=profile_id)
handler_logger.debug("Starting feature extraction")
```

Uvicorn's default access logger is silenced. Structured HTTP request logging is provided by
`HTTPAccessLogMiddleware`, registered automatically via `init_fastapi()`. Health and metrics
endpoints (`/healthz`, `/readyz`, `/metrics`) are excluded. Uvicorn error and alembic loggers
are routed through a structlog `ProcessorFormatter` so their output appears as structured JSON.

### Distributed Tracing

`obs.init()` configures a `TracerProvider` with a `BatchSpanProcessor` that exports spans to the
OTel collector via OTLP/gRPC. The collector endpoint is read from settings; when no endpoint is
configured the tracer still works but spans are dropped rather than exported.

Trace propagation uses W3C TraceContext + W3C Baggage. `obs.init_fastapi(app)` calls
`FastAPIInstrumentor.instrument_app()`, which creates a root span for every HTTP request and
propagates the `traceparent` header to downstream calls.

The sampler resolves based on configuration:

| `sample_rate` | `tracing_enabled` | Sampler |
|---|---|---|
| `1.0` (default) | `true` | `ALWAYS_ON` |
| `0.0` | `true` | `ALWAYS_OFF` |
| `0.0-1.0` | `true` | `ParentBasedTraceIdRatio` |
| any | `false` | `ALWAYS_OFF` |

Auto-instrumentation activates at `init()` time for httpx (always on by default) and optionally
for Redis and gRPC, controlled via builder flags or the `instrument_redis` setting:

```python
obs = (
    Observability.builder()
    .service("my-service", "1.0.0")
    .otel_endpoint("http://otel-collector:4317")
    .instrument_redis(enabled=True)
    .build()
)
```

SQLAlchemy instrumentation is not activated by `init()` automatically. Install the
`[sqlalchemy]` extra and the OTel SDK picks it up via the instrumentation registry.

### Prometheus Metrics

`build_metrics_router()` returns a FastAPI `APIRouter` with a single `GET /metrics` endpoint
that serves the default Prometheus registry in the text exposition format. All services include
this router:

```python
app.include_router(build_metrics_router())
```

Prometheus scrapes each service's `/metrics` endpoint. The OTel SDK also exports metrics to the
collector via `OTLPMetricExporter` on a 10-second interval when an endpoint is configured.

### Correlation IDs

`obs.init_fastapi(app)` adds `CorrelationIdMiddleware` to the FastAPI middleware stack. This
middleware extracts the `X-Correlation-ID` request header if present, or generates a new UUIDv7
if absent, stores it in a `ContextVar`, and echoes it back in the response headers.

The correlation ID is then automatically included in every log line via the `add_correlation_id`
processor. Kafka message handlers that need correlation tracking call `set_correlation_id()`
manually:

```python
from nohiki_observability import set_correlation_id

async def handle_listing_created(message: ListingCreated, context: MessageContext) -> None:
    set_correlation_id(str(message.metadata.request_id))
    logger.info("Handling listing", listing_id=message.listing_snapshot.listing_id)
```

### Domain Metrics

Services that need domain-specific Prometheus counters and histograms extend `DomainMetricsBase`
rather than calling the OTel metrics API directly. This pattern enforces consistent naming,
avoids duplicate instrument registration, and keeps metric definitions co-located with the
business logic.

To define service-specific metrics, subclass `DomainMetricsBase`:

```python
from nohiki_observability.metrics.builders import DomainMetricsBase, MetricDefinition

DEFINITIONS = [
    MetricDefinition("nohiki_doc_renders_total", "PDF renders completed", "1", "counter"),
    MetricDefinition("nohiki_doc_render_duration_seconds", "PDF render latency", "s", "histogram"),
]

class DocTemplateMetrics(DomainMetricsBase):
    def __init__(self) -> None:
        super().__init__("nohiki.doc_template", DEFINITIONS)

    def record_render(self, duration_seconds: float, *, success: bool) -> None:
        attrs = {"status": "success" if success else "error"}
        self._get_counter("nohiki_doc_renders_total").add(1, attrs)
        self._get_histogram("nohiki_doc_render_duration_seconds").record(duration_seconds, attrs)
```

### OTel Health Probe

`OTelHealthProbe` checks TCP reachability of the OTel collector gRPC port. It returns
`DEGRADED` (not `UNHEALTHY`) on failure. Observability problems should not cause K8s to
restart a service that is otherwise healthy:

```python
from nohiki_observability import OTelHealthProbe

probes = [
    DatabaseHealthProbe(engine),
    OTelHealthProbe(settings.observability.otel_endpoint),
]
```

### Event Loop Lag Metric

`init()` registers a `nohiki_runtime_event_loop_lag_seconds` observable gauge that measures
asyncio scheduling delay. A 100ms callback schedules itself recursively, compares actual vs
expected fire time, and records the delta. This metric surfaces situations where CPU-bound work
or blocking calls are starving the event loop.

## API Reference

### Initialization

- **`Observability.from_settings(settings)`** -- Primary factory. Accepts any object satisfying
  `ObservabilitySettingsProvider` (a service's Pydantic settings class) or `ObservabilityConfig`
  directly. Reads `settings.service_name`, `settings.service_version`, `settings.debug`,
  `settings.instrument_redis`, and `settings.observability` (the nested OTel/logging/tracing
  config). `debug=True` sets `environment="development"`.

- **`Observability.builder()`** -- Returns an `ObservabilityBuilder` for programmatic
  configuration. Useful in tests or tools that don't have a settings object.

- **`obs.init()`** -- Configures structlog, TracerProvider, MeterProvider, LoggerProvider, and
  auto-instrumentation. Safe to call multiple times. Subsequent calls are no-ops.

- **`obs.init_fastapi(app)`** -- Calls `init()` if needed, then adds `CorrelationIdMiddleware`
  and instruments the FastAPI app with OTel. Call this after all other middleware is added.

- **`obs.shutdown()`** -- Flushes pending spans and metrics, then disposes all providers.
  Call from the FastAPI lifespan shutdown block. Safe to call before `init()` or multiple times.

### Logging

- **`get_logger(name)`** -- Module-level convenience function. Returns a `Logger` wrapping
  `structlog.get_logger(name)`. Call before `obs.init()` is fine; the logger will work but
  without the full processor chain until `init()` runs.

- **`obs.get_logger(name)`** -- Same as `get_logger(name)`. Equivalent shorthand when the
  `Observability` instance is in scope.

- **`Logger`** -- Typed structlog wrapper. Methods: `debug`, `info`, `warning`, `error`,
  `exception`, `critical`. All accept `**kwargs` as structured fields. `info()` accepts
  `flush=True` to force an immediate `sys.stdout.flush()`. `bind(**kwargs)` returns a new
  `Logger` with the given fields permanently attached.

### Correlation IDs

- **`CORRELATION_ID_HEADER`** -- The string constant `"X-Correlation-ID"`.
- **`CorrelationIdMiddleware`** -- Starlette `BaseHTTPMiddleware`. Added automatically by
  `obs.init_fastapi(app)`. Requires the `[fastapi]` extra.
- **`get_correlation_id()`** -- Returns the current correlation ID from the `ContextVar`, or
  `None` if not set.
- **`set_correlation_id(id)`** -- Sets the correlation ID in the current async context. Use
  in Kafka handlers to propagate the ID from message metadata.

### Metrics

- **`build_metrics_router()`** -- Returns a FastAPI `APIRouter` exposing `GET /metrics`.
  Lazily imported; requires the `[fastapi]` extra. The endpoint is excluded from OpenAPI schema.

- **`OTelHealthProbe(otel_endpoint, *, timeout_seconds=2.0)`** -- Health probe for the OTel
  collector. Returns `DEGRADED` on connectivity failure, `HEALTHY` when the endpoint is
  reachable or not configured.

### Domain Metrics

- **`DomainMetricsBase(meter_name, definitions)`** -- Base class for domain metric collections.
  Creates OTel instruments from `MetricDefinition` entries at construction time.

- **`MetricDefinition(name, description, unit, metric_type)`** -- Frozen dataclass describing
  a single instrument. `metric_type` is one of `"counter"`, `"histogram"`, `"up_down_counter"`.

### Builder API

`ObservabilityBuilder` (returned by `Observability.builder()`) exposes:

- `.service(name, version)` -- Required. Sets `service.name` and `service.version` OTel resource attributes.
- `.environment(env)` -- Defaults to `"development"`. Set to `"production"` in production deploys.
- `.otel_endpoint(url, *, insecure=True)` -- OTLP/gRPC collector URL. Pass `None` or `""` to disable export.
- `.otel_headers(headers)` -- Additional gRPC headers (e.g., for managed collectors requiring auth).
- `.log_level(level)` -- Minimum log level string (`"DEBUG"`, `"INFO"`, etc.). Default: `"INFO"`.
- `.sample_rate(rate)` -- Float between 0.0 and 1.0. Default: 1.0 (sample everything).
- `.tracing_enabled(enabled=True)` -- Master switch for tracing. Overrides `sample_rate`.
- `.instrument_redis(enabled=False)` -- Enable Redis auto-instrumentation.
- `.instrument_httpx(enabled=True)` -- Enable httpx auto-instrumentation (on by default).
- `.instrument_grpc(enabled=False)` -- Enable gRPC client/server auto-instrumentation.
- `.resource_attributes(attrs)` -- Extra OTel resource attributes (e.g., `{"k8s.pod.name": "..."}`).
- `.build()` -- Returns the configured `Observability` instance. Raises `ValueError` if `service_name` is empty.

## Configuration

Services provide observability configuration through their Pydantic settings class. The class
must satisfy the `ObservabilitySettingsProvider` protocol, which requires a nested
`observability` attribute satisfying `ObservabilityConfig`.

The `nohiki-core-settings` library provides the concrete Pydantic settings mixins that implement
these protocols. Key environment variables:

### `ObservabilityConfig` protocol fields

- `OBSERVABILITY__OTEL_ENDPOINT` -- OTLP/gRPC collector address (e.g., `http://otel-collector:4317`).
  Empty string disables export. No default: must be set explicitly.
- `OBSERVABILITY__OTEL_INSECURE` -- Whether to use an insecure gRPC channel. Default: `true`.
  Set to `false` for TLS-authenticated collectors.
- `OBSERVABILITY__OTEL_SERVICE_NAME` -- Overrides `service_name` in OTel resource attributes.
  Useful when the process name differs from the Kafka/Prometheus service name.
- `OBSERVABILITY__LOGGING__LEVEL` -- Log level threshold. Default: `"INFO"`.
- `OBSERVABILITY__TRACING__ENABLED` -- Whether tracing is active. Default: `true`.
- `OBSERVABILITY__TRACING__SAMPLE_RATE` -- Sampling rate (0.0-1.0). Default: `1.0`.

### Service-level fields read by `from_settings()`

- `service_name` -- Becomes `service.name` in OTel resource attributes.
- `service_version` -- Becomes `service.version` in OTel resource attributes.
- `debug` -- When `true`, sets `environment="development"` and typically raises log level to DEBUG.
- `instrument_redis` -- Enables Redis auto-instrumentation for services that use Redis heavily
  (e.g., `bff-service`, `nohiki-redis-utils` consumers).

## Optional Extras

Install only the instrumentation packages your service needs:

| Extra | Adds | When to use |
|---|---|---|
| `[fastapi]` | FastAPI + OTel FastAPI instrumentor | All HTTP-serving services (all 18 currently) |
| `[sqlalchemy]` | OTel SQLAlchemy instrumentor | Services with a database (via `nohiki-db-utils`) |
| `[httpx]` | OTel httpx instrumentor | Services making outbound HTTP calls |
| `[redis]` | OTel Redis instrumentor | Services using `nohiki-redis-utils` heavily |
| `[grpc]` | OTel gRPC client + server instrumentors | Services using gRPC (not currently used) |
| `[kafka]` | OTel Confluent Kafka instrumentor | Optional Kafka trace propagation |
| `[system]` | OTel system metrics (CPU, memory, GC) | All services via auto-detection in `init()` |
| `[phoenix]` | Arize Phoenix + OpenInference OpenAI | LLM tracing in `nohiki-llm-client` services |
| `[http]` | Shorthand for `[fastapi,httpx,requests]` | HTTP-heavy services |
| `[database]` | Shorthand for `[sqlalchemy,redis]` | Stateful services |
| `[full]` | All extras | Development / local compose stack |

`user-auth-service` is the only service currently using `[fastapi,httpx,sqlalchemy]`. All other
services declare `[fastapi]` and rely on the core instrumentation.

## Testing

`Observability.init()` and `obs.shutdown()` are safe to call in tests. No network connections
are made unless an OTel endpoint is configured.

To test service code that uses `get_logger()`, call it directly. Structlog works without any
initialization:

```python
from nohiki_observability import get_logger

logger = get_logger(__name__)
logger.info("This just works in tests")  # No setup needed
```

To test code that depends on `Observability` initialization, build a no-export instance:

```python
from nohiki_observability import Observability

obs = Observability.builder().service("test-service", "0.0.0").build()
obs.init()  # No OTLP endpoint → no network I/O
```

To test code that reads OTel exporters or processors (as in the test suite itself), mock the
OTLP exporter classes to prevent gRPC connection attempts:

```python
from unittest.mock import patch

with (
    patch("nohiki_observability.observability.OTLPSpanExporter"),
    patch("nohiki_observability.observability.OTLPMetricExporter"),
    patch("nohiki_observability.observability.OTLPLogExporter"),
):
    obs = (
        Observability.builder()
        .service("my-service", "1.0.0")
        .otel_endpoint("http://collector:4317")
        .build()
    )
    obs.init()
```

For testing `CorrelationIdMiddleware`, use the FastAPI `TestClient` -- the middleware works
normally in synchronous test contexts:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nohiki_observability import CORRELATION_ID_HEADER
from nohiki_observability.correlation import CorrelationIdMiddleware

app = FastAPI()
app.add_middleware(CorrelationIdMiddleware)

client = TestClient(app)
response = client.get("/", headers={CORRELATION_ID_HEADER: "my-id"})
assert response.headers[CORRELATION_ID_HEADER] == "my-id"
```

Domain metrics classes (`DomainMetricsBase` subclasses) can be tested by patching
`nohiki_observability.metrics.builders.ot_metrics` to return mock meter instances, avoiding
OTel SDK global state interference between test cases.

## Design Decisions

**`from_settings()` vs `builder()`**: Services always use `from_settings()` because it maps the
standard Pydantic settings structure (provided by `nohiki-core-settings`) to the builder calls.
The builder exists for programmatic use in tests and tools where a full settings object would
be over-engineered.

**`init()` is idempotent, module-level**: All service `main.py` files call `obs.init()` at
module load time, before the `asynccontextmanager` lifespan runs. This means logging and tracing
are active from the first import, including during Alembic migrations and startup validation.
The idempotency guard prevents double-initialization if `init_fastapi()` is called before the
lifespan starts.

**Shutdown as last lifespan step**: `obs.shutdown()` always runs last in the lifespan teardown,
after Kafka consumers, Redis, and database pools are closed. Log lines and spans emitted
during those shutdown steps are still captured and flushed before the OTLP exporters are disposed.

**OTel failure as degraded, not fatal**: The `OTelHealthProbe` returns `DEGRADED` rather than
`UNHEALTHY`, and all OTel configuration errors are caught and logged as warnings rather than
raised. A service continues to function correctly even if the collector is unreachable. It just
loses telemetry.
