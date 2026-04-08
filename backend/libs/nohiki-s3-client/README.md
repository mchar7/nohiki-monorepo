# Nohiki S3 Client

Wraps `aiobotocore` to provide an async S3-compatible object storage client for Nohiki services.
Seven services depend on it: `bff-service`, `user-upload-service`, `doc-content-service`,
`doc-process-service`, `doc-template-service`, `job-correlation-evaluation-service`, and
`ml-compute-service`. The library targets RustFS (S3-compatible, used in development) and Azure
Blob Storage via its S3-compatible API (used in production) with identical code paths.

## Quick Start

```python
from nohiki_s3_client import get_s3_client, S3ObjectNotFoundError
from nohiki_s3_client import S3Mixin
from nohiki_core_settings import NohikiBaseSettings

# 1. Declare S3 settings in the service config
class Settings(S3Mixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="MY_SERVICE_")

settings = get_settings()

# 2. Get a cached client from settings
s3 = get_s3_client(settings.s3)

# Upload bytes to S3
await s3.put_object(
    key="user-uploads/abc123/resume.pdf",
    data=pdf_bytes,
    content_type="application/pdf",
    metadata={"user_id": "abc123"},
)

# Download bytes from S3
try:
    content = await s3.get_object("user-uploads/abc123/resume.pdf")
except S3ObjectNotFoundError:
    ...  # object does not exist

# Generate a presigned PUT URL for direct client-to-S3 upload
url = await s3.generate_presigned_url(
    key="user-uploads/abc123/resume.pdf",
    expires_in=3600,
    http_method="PUT",
)
```

## Core Concepts

### Per-call aiobotocore sessions

`S3Client` creates one `aiobotocore` session at construction time, then opens a new
`aiobotocore` client connection for every operation via an `asynccontextmanager`. There is no
persistent connection kept open between calls. This design avoids holding idle TCP connections
in services that perform S3 I/O infrequently, at the cost of a small connection establishment
overhead per operation. Services that need fine-grained connection control can construct
`S3Client` directly; all others should use `get_s3_client`.

### `get_s3_client` -- settings-keyed singleton

`get_s3_client(settings: S3Settings)` returns a cached `S3Client` instance keyed by the
`id()` of the `S3Settings` object. Because each service creates a single `S3Settings`
instance (via a `@cache`-decorated `get_settings()` function), a single `S3Client` is shared
for the lifetime of the process. Passing a freshly constructed `S3Settings` with different
options bypasses the cache and creates a new client: this is intentional for test isolation.

### `public_url` for presigned URL generation

`S3Settings` has two endpoint fields: `endpoint` and `public_url`. All operations
(`get_object`, `put_object`, etc.) use `endpoint` -- the internal, Docker-network-reachable
address. `generate_presigned_url` uses `public_url` instead when it is set, producing a URL
that external clients (browser, mobile) can reach directly.

In local development, `endpoint` is `http://nohiki-infra-rustfs:9000` (Docker-internal) and
`public_url` is `http://localhost:9002` (host-reachable). Without `public_url`, presigned
URLs would embed the Docker-internal hostname, which browsers cannot resolve. In production
on Azure Blob Storage, the S3-compatible API endpoint is the same for internal and external
access, so `public_url` can be left empty.

### Error hierarchy

All exceptions extend `S3Error`:

- **`S3ObjectNotFoundError`** -- `head_object` or `get_object` returned `NoSuchKey` / `404`.
  The `key` attribute holds the S3 object key that was not found.
- **`S3PermissionError`** -- The server returned `AccessDenied` or `403`. The `key` attribute
  holds the key or bucket name that was denied.
- **`S3ConnectionError`** -- Any other failure: network error, timeout, unrecognized
  `ClientError` code, or any unexpected exception. Wraps the original message as a string.

`object_exists` deliberately maps `NoSuchKey` / `404` to `False` instead of raising
`S3ObjectNotFoundError`, because checking existence without a required-to-succeed expectation
is the common case for deduplication and staleness checks.

## API Reference

### Client operations

All operations are `async` and take a `key: str` as the S3 object key within the configured
bucket. The bucket is always taken from `S3Settings.bucket` -- it is never passed directly.

- **`get_object(key)`** → `bytes` -- Downloads the object body. Raises `S3ObjectNotFoundError`
  if the key does not exist.
- **`put_object(key, data, content_type, metadata)`** → `None` -- Uploads bytes. `content_type`
  defaults to `application/octet-stream`. `metadata` is a `dict[str, str]` of S3 object
  metadata attached to the object.
- **`delete_object(key)`** → `None` -- Deletes the object. S3's `delete_object` is idempotent;
  deleting a non-existent key succeeds silently.
- **`object_exists(key)`** → `bool` -- Issues a `head_object` and returns `True` / `False`
  without raising on a missing key.
- **`check_bucket_access()`** → `bool` -- Issues a `head_bucket` to verify the bucket is
  reachable and credentials are accepted. Returns `True` on success; raises `S3PermissionError`
  or `S3ConnectionError` on failure.
- **`list_objects_sample(max_keys)`** → `list[str]` -- Returns up to `max_keys` object keys
  from the bucket via `list_objects_v2`. Intended for health probes and debugging; not for
  paginated listing.
- **`generate_presigned_url(key, expires_in, http_method)`** → `str` -- Generates a presigned
  URL. `http_method` is `"GET"` (default) or `"PUT"`. `expires_in` defaults to `3600` seconds.
  Uses `public_url` as the endpoint when set, falling back to `endpoint`.

### Factory function

- **`get_s3_client(settings)`** → `S3Client` -- Returns a cached `S3Client` for the given
  `S3Settings` instance. Call this instead of constructing `S3Client` directly in production
  code.

### Health probe

- **`S3HealthProbe(s3_client, capabilities, health_check_key, timeout_seconds)`** -- Implements
  the `HealthProbe` protocol from `nohiki-common-exceptions`. Checks the capabilities
  specified at construction time:
  - `S3Capability.BUCKET_ACCESS` -- `head_bucket` (default)
  - `S3Capability.READ` -- `list_objects_v2` with `MaxKeys=1`
  - `S3Capability.WRITE` -- `put_object` + `delete_object` cycle using `health_check_key`

- **`ensure_s3_ready(s3_client, timeout_seconds, retry_interval_seconds)`** → `None` -- Blocks
  service startup by polling `S3Capability.BUCKET_ACCESS` until the bucket is reachable or
  `timeout_seconds` is exceeded (default: `30.0` s). Raises `RuntimeError` on timeout.

### Metrics

- **`get_s3_metrics()`** → `S3Metrics` -- Returns a singleton `S3Metrics` instance backed by
  OpenTelemetry. Exposes:
  - `nohiki_s3_operations_total` -- counter, labeled by `operation` and `status`
  - `nohiki_s3_operation_duration_seconds` -- histogram, labeled by `operation` and `status`
  - `nohiki_s3_bytes_uploaded_total` -- counter, labeled by `operation` and `bucket`
  - `nohiki_s3_bytes_downloaded_total` -- counter, labeled by `operation` and `bucket`
  - `nohiki_s3_errors_total` -- counter, labeled by `operation` and `status`

  Call `metrics.record_operation(operation, duration_seconds, success=True, bytes_count=0,
  bucket=None)` after each S3 operation to emit telemetry.

## Configuration

### `S3Mixin`

Adds an `s3: S3Settings` field to the service's Pydantic settings class. Include it alongside
`NohikiBaseSettings` and other mixins:

```python
from nohiki_s3_client import S3Mixin
from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaMixin
from pydantic_settings import SettingsConfigDict

class Settings(DatabaseMixin, KafkaMixin, S3Mixin, NohikiBaseSettings):
    model_config = SettingsConfigDict(env_prefix="USER_UPLOAD_")
```

Pydantic Settings then reads the following environment variables (with the service's prefix,
e.g. `USER_UPLOAD_`):

| Variable | Default | Description |
|---|---|---|
| `{PREFIX}S3__BUCKET` | *(required)* | Bucket name: no default; service fails to start if unset |
| `{PREFIX}S3__ENDPOINT` | `""` | S3 endpoint URL; empty means AWS S3 |
| `{PREFIX}S3__PUBLIC_URL` | `""` | External endpoint for presigned URLs; empty falls back to `endpoint` |
| `{PREFIX}S3__ACCESS_KEY` | `None` | Access key; omit when using IAM roles |
| `{PREFIX}S3__SECRET_KEY` | `None` | Secret key; omit when using IAM roles |
| `{PREFIX}S3__REGION` | `us-east-1` | AWS region |
| `{PREFIX}S3__CONNECT_TIMEOUT` | `10` | Connection timeout in seconds |
| `{PREFIX}S3__READ_TIMEOUT` | `30` | Read timeout in seconds |

`bucket` intentionally has no default. The library raises a Pydantic `ValidationError` at
startup if it is not set, rather than silently writing to the wrong bucket.

`access_key` and `secret_key` are both `SecretStr | None`. When both are `None`, the client
omits them from the `aiobotocore` constructor, letting botocore fall through to its credential
chain (instance profile, environment, etc.). This is the intended mode for production on Azure
where credentials come from managed identity.

### `HasS3Settings` protocol

`HasS3Settings` is a `@runtime_checkable` protocol for type-checking settings objects that
expose `.s3: S3Settings` and `.service_name: str` without requiring inheritance from
`S3Mixin`:

```python
from nohiki_s3_client import HasS3Settings

def build_client(settings: HasS3Settings) -> S3Client:
    return S3Client(settings.s3)
```

## Testing

Tests mock at the `aiobotocore` session level using `unittest.mock.patch.object` on
`client._session.create_client`. The test suite does not use `moto` despite it being in the
`dev` extras; all tests use manual mocks.

To replicate the pattern used across the library's own tests:

```python
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch
from pydantic import SecretStr
from nohiki_s3_client import S3Settings
from nohiki_s3_client.client import S3Client
from nohiki_s3_client.exceptions import S3ObjectNotFoundError
from botocore.exceptions import ClientError


@pytest.fixture
def s3_settings() -> S3Settings:
    return S3Settings(
        endpoint="http://localhost:9000",
        access_key=SecretStr("test-key"),
        secret_key=SecretStr("test-secret"),
        bucket="test-bucket",
    )


async def test_get_object_not_found(s3_settings: S3Settings) -> None:
    mock_s3 = AsyncMock()
    mock_s3.get_object = AsyncMock(
        side_effect=ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )
    )

    @asynccontextmanager
    async def mock_create_client(*_args, **_kwargs):
        yield mock_s3

    client = S3Client(s3_settings)
    with (
        patch.object(client._session, "create_client", mock_create_client),
        pytest.raises(S3ObjectNotFoundError),
    ):
        await client.get_object("missing/key.txt")
```

Consumer service tests that need to stub S3 behavior inject a pre-constructed `S3Client`
instance with a patched session, or use `unittest.mock.AsyncMock` in place of the full
client where the test scope does not require real aiobotocore behavior.

## Design Decisions

### No connection pooling

`aiobotocore` does not support persistent connection pools the way `aiohttp` does. Each
`async with self._session.create_client(...)` block opens and closes an HTTP connection.
The library does not attempt to work around this because the overhead is acceptable for
Nohiki's access patterns (infrequent, large-object I/O rather than high-frequency small
requests). If connection overhead becomes a bottleneck, the right fix is switching to a
client library that manages its own pool rather than adding per-call caching here.

### `public_url` vs `endpoint` split

Presigned URL generation requires that the URL hostname be reachable by the client that will
use the URL. In local development, RustFS is inside Docker (reachable by services at
`http://nohiki-infra-rustfs:9000`) but the presigned URL is handed to a browser (which resolves
`localhost:9002` instead). A single `endpoint` field cannot serve both roles.
The `public_url` field solves this cleanly: operations that produce server-side data use
`endpoint`; operations that produce client-facing URLs use `public_url`. Services that do not
generate presigned URLs never set `public_url`.
