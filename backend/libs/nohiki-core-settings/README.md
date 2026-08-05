# Nohiki Core Settings

Provides `NohikiBaseSettings` -- a Pydantic `BaseSettings` subclass that every Nohiki service
inherits, along with the `ObservabilitySettings` nested model that lives inside it. Domain-specific
settings (database, Kafka, Redis, S3, LLM, etc.) are contributed by their respective libraries
as mixins; this library defines the composition contract those mixins plug into. Every one of
the 18 backend services depends on `nohiki-core-settings` directly or transitively. Without it,
each service would independently implement `.env` loading, `__` nested delimiter handling,
file-secrets integration, and Azure Key Vault wiring, and almost certainly get them wrong
in different ways.

## Quick Start

```python
from functools import cache

from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaMixin
from nohiki_redis_utils import RedisMixin
from pydantic_settings import SettingsConfigDict


class Settings(DatabaseMixin, RedisMixin, KafkaMixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")

    service_name: str = "my-service"
    service_name_friendly: str = "My Service"
    service_desc_friendly: str = "What this service does"
    service_version: str = "0.1.0"


@cache
def get_settings() -> Settings:
    return Settings()
```

With the prefix `MY_SERVICE_`, environment variables like `MY_SERVICE_DATABASE__DSN` and
`MY_SERVICE_KAFKA__DSN` resolve to `settings.database.dsn` and `settings.kafka.dsn`. The `@cache`
decorator ensures a single settings instance per process.

## Core Concepts

### Settings Source Priority

`NohikiBaseSettings` loads configuration from four sources, evaluated in this order (first wins):

1. **Constructor arguments** -- values passed directly when instantiating `Settings()`
2. **Environment variables** -- `MY_SERVICE_*` prefixed vars, read from the process environment
3. **`.env` file** -- loaded from the working directory, UTF-8 encoded
4. **File secrets** -- mounted at `SECRETS_DIR` (default: `/run/secrets`), using
   `NestedSecretsSettingsSource` with subdirectory support

If `AZURE_KEY_VAULT_URL` is set, an Azure Key Vault source is appended after file secrets.
This source uses `DefaultAzureCredential`, which picks up Managed Identity in Azure or Azure CLI
credentials locally.

In production (any `ENVIRONMENT` value other than `development`, `dev`, or `local`), a missing
`SECRETS_DIR` raises an error at startup rather than silently ignoring it.

### Double-Underscore Nesting

`env_nested_delimiter = "__"` maps environment variable segments to nested Pydantic model fields:

```text
MY_SERVICE_DATABASE__DSN           → settings.database.dsn
MY_SERVICE_DATABASE__POOL_SIZE     → settings.database.pool_size
MY_SERVICE_OBSERVABILITY__LOGGING__LEVEL  → settings.observability.logging.level
MY_SERVICE_KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS → settings.kafka.consumer.max_concurrent_handlers
```

The service prefix (`MY_SERVICE_`) is stripped by `SettingsConfigDict(env_prefix=...)`. The
remainder is split on `__` and traversed as nested field names.

### Mixin Composition

Each shared library that contributes settings provides a mixin class inheriting `SettingsMixin`.
Services compose exactly the mixins they need using Python multiple inheritance:

```python
# Minimal Kafka-only service (no database, no Redis)
class Settings(KafkaMixin, NohikiBaseSettings): ...

# Full-stack service
class Settings(LLMMixin, RedisMixin, DatabaseMixin, KafkaMixin, S3Mixin, QdrantMixin, NohikiBaseSettings): ...
```

MRO determines which class provides `instrument_redis`. `NohikiBaseSettings` returns `False`;
`RedisMixin` overrides it to `True`, so any service that inherits `RedisMixin` automatically
enables Redis OpenTelemetry instrumentation without any extra configuration.

`SettingsMixin` declares `environment: str` on its body so that mixin validators can reference
the field provided by `NohikiBaseSettings` through MRO without requiring a shared Protocol or ABC.

### Observability Settings

`ObservabilitySettings` is embedded directly in `NohikiBaseSettings` under the `observability`
field. All services have it. It is not a mixin, so it is always present.

### Environment Detection

`is_development()` reads the bare `ENVIRONMENT` env var (no service prefix) and returns `True`
for `development`, `dev`, and `local`. It is called during settings construction, before a
settings instance exists, so it cannot use `settings.environment`. Services use it for
environment-aware defaults (e.g., cookie `__Host-` prefix, rate limit thresholds, CORS origins).

## API Reference

### NohikiBaseSettings

The base class all service settings classes inherit from.

**Required fields** (must be provided as class-level defaults or env vars):

- **`service_name`** (`str`) -- Machine-readable service identifier, e.g., `"bff-service"`
- **`service_name_friendly`** (`str`) -- Human-readable name for dashboards and alerts
- **`service_desc_friendly`** (`str`) -- One-line description of the service's purpose
- **`service_version`** (`str`) -- Semver string, e.g., `"0.1.0"`

**Optional fields with defaults:**

- **`environment`** (`str`, default: `"development"`) -- Runtime environment name. Reads
  `ENVIRONMENT` env var at startup.
- **`debug`** (`bool`, default: `False`) -- Enables debug mode
- **`host`** (`str`, default: `"127.0.0.1"`) -- Bind address for the HTTP server
- **`port`** (`int`, default: `8000`, range: 1-65535) -- Bind port for the HTTP server
- **`api_prefix`** (`str`, default: `"/api/v1"`) -- URL prefix for all API routes
- **`observability`** (`ObservabilitySettings`) -- OTel, logging, and Prometheus config

**Property:**

- **`instrument_redis`** (`bool`) -- Returns `False` unless `RedisMixin` is in the MRO.
  Used by `nohiki-observability` to decide whether to instrument Redis connections.

### ObservabilitySettings

Available as `settings.observability`. Configured via `OBSERVABILITY__*` env vars
(after the service prefix is stripped).

| Environment Variable | Type | Default | Description |
| --- | --- | --- | --- |
| `{PREFIX}__OBSERVABILITY__OTEL_ENDPOINT` | `str` | `""` | OTel Collector gRPC endpoint. Empty disables export. |
| `{PREFIX}__OBSERVABILITY__OTEL_INSECURE` | `bool` | `true` | Use non-TLS connection to OTel Collector |
| `{PREFIX}__OBSERVABILITY__OTEL_SERVICE_NAME` | `str \| null` | `null` | Override service name in traces. Defaults to `service_name`. |
| `{PREFIX}__OBSERVABILITY__LOGGING__LEVEL` | `str` | `"INFO"` | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `{PREFIX}__OBSERVABILITY__LOGGING__FORMAT` | `str` | `"json"` | Log format: `json` (production) or `console` (development) |
| `{PREFIX}__OBSERVABILITY__LOGGING__INCLUDE_TRACE_ID` | `bool` | `true` | Inject OTel trace ID into log records |
| `{PREFIX}__OBSERVABILITY__TRACING__ENABLED` | `bool` | `true` | Enable distributed tracing |
| `{PREFIX}__OBSERVABILITY__TRACING__SAMPLE_RATE` | `float` | `1.0` | Trace sampling rate (0.0-1.0) |
| `{PREFIX}__OBSERVABILITY__PROMETHEUS__ENABLED` | `bool` | `true` | Expose `/metrics` endpoint |
| `{PREFIX}__OBSERVABILITY__PROMETHEUS__ENDPOINT_PATH` | `str` | `"/metrics"` | Prometheus scrape path |

### SettingsMixin

```python
from nohiki_core_settings.mixins import SettingsMixin
```

Base class for all infrastructure settings mixins. `KafkaMixin`, `DatabaseMixin`, `RedisMixin`,
`S3Mixin`, `LLMMixin`, and `QdrantMixin` all inherit from it. Service code generally does not
import `SettingsMixin` directly. Shared library authors use it when implementing new mixins.

### Environment Utilities

```python
from nohiki_core_settings import DEVELOPMENT_ENVIRONMENTS, is_development
```

- **`is_development()`** -- Returns `True` when `ENVIRONMENT` is `development`, `dev`, or `local`.
  Safe to call before settings are constructed.
- **`DEVELOPMENT_ENVIRONMENTS`** -- `frozenset[str]` of all recognized non-production environment
  names. Import and extend if you need custom environment detection logic.

### Azure Key Vault

```python
from nohiki_core_settings import AzureKeyVaultNotInstalledError
```

The Azure Key Vault source is activated automatically when `AZURE_KEY_VAULT_URL` is set.
No code changes are required. The source is injected into the settings pipeline by
`settings_customise_sources`. If `AZURE_KEY_VAULT_URL` is set but `azure-identity` is not
installed, `AzureKeyVaultNotInstalledError` is raised at settings construction time.

Install the optional Azure dependency:

```toml
# pyproject.toml
dependencies = [
    "nohiki-core-settings[azure]==0.1.0",
]
```

`DefaultAzureCredential` resolves credentials automatically: Managed Identity in Azure
deployments, Azure CLI credentials in local development, or `AZURE_CLIENT_ID` /
`AZURE_TENANT_ID` / `AZURE_CLIENT_SECRET` environment variables in CI.

## Configuration

### Base Variables (all services)

These apply without a prefix when `NohikiBaseSettings` is used directly, or with
the service prefix when using a composed `Settings` class. Examples use `MY_SERVICE_` as
the prefix.

| Environment Variable | Type | Default | Description |
| --- | --- | --- | --- |
| `MY_SERVICE_ENVIRONMENT` | `str` | `"development"` | Runtime environment name |
| `MY_SERVICE_DEBUG` | `bool` | `false` | Debug mode |
| `MY_SERVICE_HOST` | `str` | `"127.0.0.1"` | HTTP server bind address |
| `MY_SERVICE_PORT` | `int` | `8000` | HTTP server bind port (1-65535) |
| `MY_SERVICE_API_PREFIX` | `str` | `"/api/v1"` | URL prefix for all API routes |
| `SECRETS_DIR` | `str` | `"/run/secrets"` | Path to mounted file secrets directory |
| `AZURE_KEY_VAULT_URL` | `str` | -- | Azure Key Vault URL. Activates Key Vault source when set. |
| `ENVIRONMENT` | `str` | `"development"` | Read unprefixed during settings construction for `is_development()` |

### Per-Service Prefix Convention

Every service sets `env_prefix` in its `model_config`. All service-specific environment
variables must be prefixed accordingly:

| Service | Prefix |
| --- | --- |
| `bff-service` | `BFF_` |
| `user-auth-service` | `USER_AUTH_` |
| `notification-service` | `NOTIFICATION_` |
| `job-correlation-evaluation-service` | `JOB_CORRELATION_EVAL_` |

The prefix applies to ALL fields, including nested ones via `__`. For example, the BFF service's
OTel endpoint is `BFF__OBSERVABILITY__OTEL_ENDPOINT`.

## Testing

`SECRETS_DIR` is read on every settings construction, so it can be redirected from a fixture. Every
pytest session already runs against an empty secrets tree: the `nohiki-test-utils` plugin points
`SECRETS_DIR` at a throwaway empty directory before any conftest loads, so no suite reads the
developer's `infra/shared/secrets`. Narrow the isolation further per package where it helps. The
`conftest.py` in this library's own test suite shows the pattern:

```python
@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("SECRETS_DIR", "/nonexistent/secrets/path")
    monkeypatch.delenv("AZURE_KEY_VAULT_URL", raising=False)
    yield
```

This pins the secrets directory for the test and ensures Azure Key Vault is never contacted.

For service-level tests, define a minimal concrete subclass with required fields as defaults so
tests can instantiate settings without any environment setup:

```python
class _TestSettings(NohikiBaseSettings):
    service_name: str = "test-service"
    service_name_friendly: str = "Test Service"
    service_desc_friendly: str = "Test"
    service_version: str = "0.0.1"
```

Override individual fields with `monkeypatch.setenv` rather than constructing settings with
kwargs. This exercises the same env-var resolution path the production service uses:

```python
def test_debug_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBUG", "true")
    settings = _TestSettings()
    assert settings.debug is True
```

For tests that need the Azure Key Vault path, patch `_azure_keyvault_source_factory` on
`nohiki_core_settings.base` to `None` to simulate the missing-dependency case, or mock
`DefaultAzureCredential` and `AzureKeyVaultSettingsSource` to avoid real network calls.

## Design Decisions

**Observability lives in base, not a mixin.** Every service emits traces, logs, and metrics.
Making observability opt-in via a mixin would mean every service adds it anyway, creating
pointless boilerplate and the risk that a service is accidentally deployed without it.

**Domain mixins live in their libraries, not here.** `DatabaseMixin` lives in `nohiki-db-utils`
rather than in `nohiki-core-settings` because it imports `DatabaseSettings`, which has
SQLAlchemy and asyncpg dependencies. Keeping those dependencies out of `nohiki-core-settings`
means this library stays lightweight: only `pydantic` and `pydantic-settings` are required.
Services that don't need a database don't pay for those transitive dependencies.

**`extra = "ignore"`.** Unknown environment variables are silently dropped. This means adding a
new env var to a service's Kubernetes deployment never breaks other services that happen to
share the same prefix namespace. Strict mode would make cross-service deployments fragile.

**`@cache` on `get_settings()`.** Settings construction involves disk reads (`.env`, secrets
directory) and potentially network I/O (Azure Key Vault). Caching ensures this happens exactly
once per process, not once per request. The pattern is consistent across all 18 services.
