# Notification Service

Delivers user-facing email notifications triggered by meaningful events in the Nohiki pipeline --
specifically job correlation results and completed document generation. Kafka-only, stateful with
PostgreSQL and Redis. Uses a pluggable provider architecture (currently Resend and Twilio SendGrid)
behind a `BaseProvider` abstraction, routing outbound messages through a transactional outbox for
guaranteed delivery tracking.

## Role in the System

The notification service is the sole point of user communication in the Nohiki platform. No other
service sends email directly. It sits downstream of both the `job-correlation-evaluation-service`
(which produces `JOB_CORRELATION_EVALUATED`) and `doc-content-service` (which produces
`DOC_CONTENT_GENERATION_COMPLETED`), receiving events that carry ECST snapshots containing the
user's notification preferences (including the recipient email address and, for job matches,
a score threshold) embedded directly in the event. This eliminates any need for cache lookups or
cross-service calls to determine whether and where to send.

Within the job-matching flow, this service is on the user-visible critical path: it converts a
correlation score from `job-correlation-evaluation-service` into a "New Job Match" email, visible
to the user within seconds of the scoring pipeline completing. Similarly, when `doc-content-service`
completes generating a tailored resume or cover letter, this service fires the "Your Generated
Document is Ready" email that prompts the user to log in and download it.

The service publishes `NOTIFICATION_SENT` and `NOTIFICATION_FAILED` facts for every delivery
attempt. These events provide an audit trail consumable by any downstream service that needs to
track notification outcomes (e.g., BFF projections for delivery history).

## Event-Driven Integration

### Events Consumed

- **`JOB_CORRELATION_EVALUATED`** (`job-correlation.cdc.correlation-evaluated.v1`,
  `CorrelationEvaluated`): Fires after `job-correlation-evaluation-service` scores a
  job-user pair. The handler extracts the `pref_snapshot.notification_config` carried in the
  event (ECST) to obtain the recipient email and threshold. If `fit_score >= threshold`, it
  enqueues a "New Job Match" email using the `job_match` template. If the event carries no
  `pref_snapshot`, no `notification_config`, or no enabled email destination, the handler skips
  silently. Consumer group: configured via `NOTIFICATION_KAFKA__CONSUMER_GROUP`.

- **`DOC_CONTENT_GENERATION_COMPLETED`** (`doc-content.fct.generation-completed.v1`,
  `ContentGenerationCompleted`): Fires after `doc-content-service` successfully generates a
  resume or cover letter. The handler checks `result.status == COMPLETED` before proceeding --
  events with any other status are discarded. On success, it enqueues a "Your Generated Document
  is Ready" email using the `content_generation_completed` template. No score threshold applies
  to this event type. Consumer group: same as above.

### Events Published

- **`NOTIFICATION_SENT`** (`notification.fct.sent.v1`, `NotificationSent`): Published via the
  transactional outbox immediately after a provider confirms delivery. Carries `notification_id`,
  `channel`, `recipient`, `sent_at`, `provider_name`, `provider_message_id`, `user_id`, and
  `listing_id`. Written to the outbox in the same transaction that marks the `Message` row as
  `sent`, ensuring the event is published if and only if the status update commits.

- **`NOTIFICATION_FAILED`** (`notification.fct.failed.v1`, `NotificationFailed`): Published via
  the transactional outbox when a message exhausts all retry attempts. Carries `error_message`,
  `failure_cause`, `retry_count`, `will_retry`, and `failed_at`. Both sent and failed events are
  available for downstream consumers (e.g., BFF) to project delivery history.

### Notable Patterns

#### Template Registry

Rather than hard-coding event-specific logic in each handler, the service uses a declarative
`TEMPLATE_REGISTRY` (`services/template_registry.py`) that maps fully-qualified event type names
to `TemplateConfig` instances:

```python
TEMPLATE_REGISTRY: dict[str, TemplateConfig] = {
    "nohiki.job.correlation.v1.CorrelationEvaluated": TemplateConfig(
        template_name="job_match",
        subject_template="New Job Match: {listing_title} at {company_name}",
        context_extractor=extract_job_match_context,
        score_extractor=_job_match_score_extractor,
        uses_threshold=True,
        requires_completed_status=False,
    ),
    "nohiki.doc.content.v1.ContentGenerationCompleted": TemplateConfig(
        template_name="content_generation_completed",
        subject_template="Your Generated Document for {listing_title}",
        context_extractor=extract_content_generation_context,
        score_extractor=_no_score,
        uses_threshold=False,
        requires_completed_status=True,
    ),
}
```

`handle_notification_event` in `services/notification_handler.py` is a single generic function
called by both Kafka handlers. It looks up the config, validates the pref snapshot, applies
threshold and status checks, extracts context via the registered `context_extractor`, formats
the subject, and delegates to `NotificationService`. Adding a new notification type requires only
adding an entry to `TEMPLATE_REGISTRY` and a corresponding Kafka handler; no changes to the
generic handler logic.

#### Transactional Outbox for Delivery Tracking

The outbox worker (`services/outbox/worker.py`) polls the `messages` table every second for rows
in `pending` or `retrying` status. For each message, it dispatches via the active provider, then
writes the outcome event (`NOTIFICATION_SENT` or `NOTIFICATION_FAILED`) to the `outbox` table
**within the same database transaction** that updates the message status. Debezium captures the
outbox row from the PostgreSQL WAL and publishes to Kafka after the transaction commits. This makes
the message status and lifecycle event atomic. Provider delivery remains at-least-once across an
ambiguous database commit; Resend receives the message UUID as an idempotency key, while SendGrid
does not expose equivalent request deduplication.

#### Pluggable Provider Architecture

All email delivery is routed through `BaseProvider`, an abstract class in `core/providers.py`
that defines two abstract methods:

```python
class BaseProvider(ABC):
    channel: ClassVar[NotificationChannel]
    name: ClassVar[str]
    required_secrets: ClassVar[list[str]]

    @abstractmethod
    async def send(self, message: Message) -> ProviderResult: ...

    @abstractmethod
    async def validate_config(self) -> bool: ...
```

Providers are registered at startup via `register_provider(channel, ProviderClass)` and stored
in a module-level `_ProviderRegistry`. The active provider is selected by name via
`configure_email_provider(config, settings.email.provider)`. The worker calls `get_provider()`
at dispatch time, which returns a lazily-instantiated singleton for the selected provider name.

Two providers are currently registered: `ResendEmailProvider` (name: `"resend"`) and
`TwilioSendGridProvider` (name: `"twilio_sendgrid"`). Both use `httpx.AsyncClient` for HTTP calls,
implement 15-minute validation result caching with exponential-backoff DNS retry, and emit
OpenTelemetry spans wrapping their `send` and `validate_config` operations.

#### Exponential Backoff Retry

`RetryStrategy` (`services/outbox/retry_strategy.py`) computes retry delays as
`base_delay_seconds × 2^(retry_count - 1)`, capped at `max_retry_delay_seconds`. A provider
`Retry-After` value is treated as a minimum delay. The worker sets `retry_at` on the message row
and skips it until that timestamp passes. After `max_retries` attempts, or if
`ProviderResult.retryable` is `False` (for example, validation or authentication errors), the
message transitions to `failed` and a `NOTIFICATION_FAILED` outbox event is written.

#### ECST Notification Config

Both consumed events carry a `pref_snapshot` (`SearchPrefSnapshot`) from the producing service.
The notification service extracts recipient and threshold from
`pref_snapshot.notification_config` without any Redis lookups or cross-service calls:

```python
# notification_config.py -- extracts from ECST snapshot
def extract_notification_config(pref_snapshot: SearchPrefSnapshot) -> ExtractedNotificationConfig | None:
    config = pref_snapshot.notification_config
    email_address = next(
        (m.email.email_address for m in config.methods if m.enabled and m.email),
        None,
    )
    return ExtractedNotificationConfig(
        user_id=pref_snapshot.user_id,
        pref_id=pref_snapshot.id,
        threshold=config.threshold,
        email_address=email_address,
    )
```

## Email Templates

Each notification type maps to a Jinja2 HTML template in
`src/notification_service/templates/`. The event handler renders packaged templates with strict
undefined variables, HTML autoescaping, and HTTP(S)-only listing links before enqueue. Both
templates receive context extracted by their registered `context_extractor` function.

### `job_match.html`

Triggered by `CorrelationEvaluated` events that pass the score threshold.

**Context variables:**

| Variable | Source | Notes |
| --- | --- | --- |
| `listing_title` | `listing_snapshot.title` | Required |
| `company_name` | `listing_snapshot.company_name` | Optional; omitted if None |
| `listing_url` | `listing_snapshot.listing_url` | Optional; omitted if None |
| `fit_score` | `CorrelationEvaluated.fit_score` | Integer percentage, e.g. `87` |
| `correlation_id` | `CorrelationEvaluated.correlation_id` | For tracing |
| `listing_id` | `listing_snapshot.id` | Used for deduplication |

Subject template: `"New Job Match: {listing_title} at {company_name}"`

### `content_generation_completed.html`

Triggered by `ContentGenerationCompleted` events with `result.status == COMPLETED`.

**Context variables:**

| Variable | Source | Notes |
| --- | --- | --- |
| `listing_title` | `listing_snapshot.title` | Optional; None if snapshot absent |
| `company_name` | `listing_snapshot.company_name` | Optional |
| `request_id` | `ContentGenerationCompleted.request_id` | For tracing |
| `listing_id` | `ContentGenerationCompleted.listing_id` | Required; raises if empty |

Subject template: `"Your Generated Document for {listing_title}"`

## State & Persistence

### Database

Schema `notification_schema` stores every notification message enqueued for delivery, along with
its status transitions, retry metadata, and provider response data. The `outbox` table holds
`NOTIFICATION_SENT` and `NOTIFICATION_FAILED` events pending Debezium capture. A
`processed_events` table (from `nohiki-db-utils`) provides idempotency tracking for Kafka
handler deduplication.

See [DATABASE.md](./DATABASE.md) for complete schema documentation.

### Redis

Redis backs the token-bucket rate limiter applied per provider before each dispatch attempt.
The limiter key pattern is `provider:{provider_name}`, with `requests_per_window` (default: 10)
tokens refilling every `window_seconds` (default: 60). If the rate limit is exhausted for a
provider, the worker skips the message in the current poll cycle and retries it in the next.

## External Integrations

### Resend

- **What**: Transactional email API at `https://api.resend.com`
- **How**: `httpx.AsyncClient` POST to `/emails`; selected-provider key from
  `NOTIFICATION_EMAIL__API_KEY`, with `RESEND_API_KEY` as fallback
- **Config validation**: On first use, hits `/api-keys` to confirm the key is valid; result cached
  15 minutes with 3-attempt exponential-backoff retry for DNS resolution failures
- **Retryable errors**: HTTP 5xx and 429; non-retryable: validation errors, 4xx (except 429)
- **Headers added**: `X-Message-ID`, `X-Account-ID`, `List-Unsubscribe`

### Twilio SendGrid

- **What**: Transactional email API at `https://api.sendgrid.com/v3`
- **How**: `httpx.AsyncClient` POST to `/mail/send`; selected-provider key from
  `NOTIFICATION_EMAIL__API_KEY`, with `SENDGRID_API_KEY` as fallback
- **Config validation**: On first use, hits `/scopes` to confirm the key has `mail.send` permission;
  result cached 15 minutes with 3-attempt exponential-backoff retry for DNS resolution failures
- **Retryable errors**: HTTP 5xx and 429; non-retryable: validation, authentication, and other 4xx errors
- **Headers added**: `X-Message-ID`, `X-Account-ID`, `List-Unsubscribe`

Only one provider is active at a time, selected by `NOTIFICATION_EMAIL__PROVIDER`
(`"resend"` or `"twilio_sendgrid"`). Both providers are registered at startup; the inactive one is
instantiated only if circuit-breaker fallback routing needs it. Both support an optional plain-text
alternative in `message.provider_payload["text_alt"]`.

## Configuration

Settings use `DatabaseMixin`, `RedisMixin`, and `KafkaMixin` from the shared settings infrastructure,
all under the `NOTIFICATION_` env prefix.

**Key variables:**

| Variable | Default | Purpose |
| --- | --- | --- |
| `NOTIFICATION_EMAIL__PROVIDER` | `"resend"` | Active email provider (`"resend"` or `"twilio_sendgrid"`) |
| `NOTIFICATION_EMAIL__API_KEY` | -- | API key for the selected provider |
| `NOTIFICATION_EMAIL__FROM_ADDRESS` | `"noreply@nohiki.com"` | Sender address |
| `NOTIFICATION_EMAIL__FROM_NAME` | `"Nohiki"` | Sender display name |
| `NOTIFICATION_EMAIL__UNSUBSCRIBE_DOMAIN` | `"nohiki.com"` | Domain used in `List-Unsubscribe` header |
| `RESEND_API_KEY` | -- | Resend fallback key, including when Resend is used only for failover |
| `SENDGRID_API_KEY` | -- | SendGrid fallback key, including when SendGrid is used only for failover |
| `NOTIFICATION_OUTBOX__POLL_INTERVAL_SEC` | `5` | Worker database poll interval |
| `NOTIFICATION_OUTBOX__MAX_RETRIES` | `3` | Maximum delivery attempts before `failed` |
| `NOTIFICATION_OUTBOX__RETRY_BASE_DELAY_SECONDS` | `5` | Base delay for exponential backoff |
| `NOTIFICATION_OUTBOX__MAX_RETRY_DELAY_SECONDS` | `300` | Delay cap (5 minutes) |
| `NOTIFICATION_OUTBOX__BATCH_SIZE` | `10` | Messages fetched per poll cycle |
| `NOTIFICATION_RATE_LIMIT__REQUESTS_PER_WINDOW` | `10` | Token bucket capacity per provider |
| `NOTIFICATION_RATE_LIMIT__WINDOW_SECONDS` | `60` | Token bucket refill window |
| `NOTIFICATION_KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS` | `5` | Concurrent Kafka handler coroutines |
| `NOTIFICATION_START_WORKERS` | `True` | Set `False` in tests to skip Kafka and outbox workers |

The selected provider may use `NOTIFICATION_EMAIL__API_KEY`; provider-specific environment keys
remain available for fallback providers. `BaseProvider._validate_required_secrets()` rejects a
provider instance when neither source supplies its credential.

## Development

### Local Setup

```bash
uv sync
alembic upgrade head
```

### Testing

```bash
just test notification-service
just test-cov notification-service
```

### Linting & Type Checking

```bash
uv run ruff check --fix --output-format=concise
uv run ty check
```

### Service-Specific Notes

- Set `NOTIFICATION_START_WORKERS=false` in test environments to prevent Kafka consumer and
  outbox worker startup.
- Configure `NOTIFICATION_EMAIL__API_KEY` for the selected provider, or its provider-specific
  fallback environment key. Credentials are validated when the lazily instantiated provider is
  first used.
- The outbox worker runs as an `asyncio.Task` in the same process, polling every second. Worker
  metrics (`messages_processed`, `messages_sent`, `messages_failed`, `messages_retried`) are
  available via `OutboxWorker.get_metrics()`.
