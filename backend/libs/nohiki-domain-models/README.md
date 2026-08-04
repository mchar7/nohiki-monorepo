# Nohiki Domain Models

Auto-generated Python dataclasses for every message type that flows through Nohiki's Kafka event
bus. The source of truth for domain model design lives in `proto/nohiki/` as protobuf definitions;
this library is the compiled output consumed by all 18 backend services. No service defines its own
event types -- every Kafka message, snapshot, command, and callback payload is imported from here.

The library ships two Python packages: `nohiki` (generated dataclasses) and `nohiki_domain_utils`
(Pydantic integration helpers for betterproto2 enums). Only the generated files in `nohiki` should
ever be imported by services; `nohiki_domain_utils` is used when betterproto2 enums need to be
embedded in Pydantic models (e.g., SQLAlchemy column types, API request/response schemas).

---

## Quick Start

```python
from datetime import UTC, datetime
import uuid

from nohiki.common.v1 import EventMetadata, ListingReference, JobBoardSource
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot

# Construct a message -- dataclass syntax, native Python types throughout
event = ListingCreated(
    metadata=EventMetadata(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        source_service="job-storage-service",
        version="v1",
    ),
    listing=ListingReference(
        listing_url="https://example.com/jobs/123",
        source=JobBoardSource.LINKEDIN,
    ),
    listing_snapshot=ListingSnapshot(
        id=str(uuid.uuid4()),
        title="Senior Software Engineer",
        company_name="Acme Corp",
        listing_url="https://example.com/jobs/123",
        source=JobBoardSource.LINKEDIN,
        discovered_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    ),
    was_updated=False,
)

# Serialize for JSONB storage in PostgreSQL projection tables
jsonb_payload: dict = event.to_dict()

# Deserialize from JSONB
restored = ListingCreated.from_dict(jsonb_payload)

# Serialize to protobuf wire format for Kafka
wire_bytes: bytes = bytes(event)

# Deserialize from Kafka wire bytes
parsed = ListingCreated().parse(wire_bytes)
```

---

## Core Concepts

### betterproto2 Dataclasses

Every generated message is a Python `@dataclass` that inherits from `betterproto2.Message`.
This means:

- **Native Python types** -- `google.protobuf.Timestamp` fields are unwrapped to `datetime.datetime`.
  Never import or construct `Timestamp` objects; betterproto2 handles the mapping transparently.
- **Optional fields** -- Protobuf `optional` scalars become `str | None`, `int | None`, etc.
  Protobuf `oneof` groups become exclusive optional fields on the same dataclass.
- **Repeated fields** -- Protobuf `repeated` fields become `list[T]`.
- **Map fields** -- Protobuf `map<K, V>` fields become `dict[K, V]`.
- **Enums** -- Protobuf enums become `betterproto2.Enum` subclasses. Every enum has an
  `UNSPECIFIED = 0` variant as the protobuf default.

Generated files carry a `# DO NOT EDIT!` header. Never modify them -- they are fully overwritten
on each `just proto-gen` run.

### ECST Snapshots

The architecture enforces Event-Carried State Transfer: every event that signals a state change
embeds a complete snapshot of the entity at that moment. This eliminates any need for consumers
to query other services for context.

The pattern is consistent across all domains:

- `ListingCreated` embeds `listing_snapshot: ListingSnapshot`
- `ListingUpdated` embeds `listing_snapshot: ListingSnapshot`
- `AccountUpdated` embeds `account_snapshot: Account`
- `PrefCreated` / `PrefUpdated` embed `pref_snapshot: SearchPrefSnapshot`

Consumers store the snapshot locally (in a projection table or in-memory ledger) and use it for
all subsequent processing without ever calling back to the originating service. This is why
`ListingSnapshot` contains not just core listing fields but also pre-computed embeddings,
canonical skill requirements, and ML metadata -- everything a downstream service could need is
included at publish time.

### EventMetadata

Every event message carries `metadata: EventMetadata` as field 1. `EventMetadata` contains:

- `event_id` -- UUIDv7, unique per event
- `timestamp` -- `datetime` of when the event was produced
- `source_service` -- name of the publishing service (e.g. `"job-storage-service"`)
- `version` -- schema version string (`"v1"`)
- `correlation_id` / `causation_id` -- optional tracing links between related events
- `trace_id` -- OpenTelemetry trace propagation

### Command/Callback Headers

Messages representing commands (BFF → domain service) carry a `CommandHeader` with a
`callback_topic` field. The consuming service publishes its result to that topic, enabling
the async request/response pattern without any direct HTTP coupling. Callback messages carry
a `CallbackHeader` that echoes the original command's correlation identifiers.

### JSONB Serialization

PostgreSQL projection tables store event payloads and snapshots as JSONB. betterproto2's
`to_dict()` and `from_dict()` are the correct serialization methods -- they handle datetime
conversion, enum name mapping, and optional field omission automatically.

```python
# Store snapshot as JSONB
snapshot_dict = pref_snapshot.to_dict()
record.pref_snapshot = snapshot_dict  # SQLAlchemy JSONB column

# Load snapshot from JSONB
pref_snapshot = SearchPrefSnapshot.from_dict(record.pref_snapshot)
```

Never write custom serializer functions for betterproto2 messages. Do not use `json.dumps` /
`json.loads` directly on message objects.

### BetterprotoEnumAdapter (Pydantic Integration)

betterproto2 enums are not natively compatible with Pydantic's validation. When you need to use
a domain enum as a Pydantic field (e.g., in a SQLAlchemy model with a Pydantic validator, or in
an API request schema), use `BetterprotoEnumAdapter` from `nohiki_domain_utils`:

```python
from typing import Annotated
from nohiki.common.v1 import SeniorityLevel, WorkArrangement
from nohiki_domain_utils import BetterprotoEnumAdapter
from pydantic import BaseModel

class ProfileSchema(BaseModel):
    seniority: Annotated[SeniorityLevel, BetterprotoEnumAdapter(exclude_unspecified=True)]
    arrangement: Annotated[WorkArrangement, BetterprotoEnumAdapter(exclude_unspecified=False)]
```

The adapter accepts strings (case-insensitive), integers (enum value), or enum instances as
input, and serializes to the enum's name string for JSON output. Pass
`exclude_unspecified=True` to strip the `UNSPECIFIED = 0` variant from JSON Schema output.

---

## Domain Organization

The `nohiki` package is organized as `nohiki.{domain}.{subdomain}.v{N}`. Import the leaf
`v1` module directly -- intermediate namespace packages are empty.

### `nohiki.common.v1`

Shared types used across all domains. Services import from here constantly.

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `EventMetadata` | Message | Base metadata on every event |
| `ListingReference` | Message | Lightweight job listing reference (URL + source) |
| `PrefReference` | Message | User search preference reference |
| `OperationOutcome` | Message | Structured result for async operations |
| `CommandHeader` | Message | Command routing header with callback topic |
| `CallbackHeader` | Message | Callback correlation header |
| `ErrorInfo` | Message | Structured error with code and details |
| `Location` | Message | Geocoded location with coordinates and precision |
| `Compensation` | Message | Salary range or fixed amount with per-bound sourcing |
| `MonetaryAmount` | Message | Atomic currency value (minor units + currency code) |
| `SkillsSet` | Message | Required / preferred / disqualifying skills arrays |
| `FeatureImportancePrefs` | Message | User-stated importance weights for L2R scoring |
| `ExperiencePreference` | Message | Experience years and target seniority levels |
| `SalaryPreference` | Message | Min and target salary expectations |
| `CommutePreferences` | Message | Max commute time and acceptable transit modes |
| `SearchPrefNotificationConfig` | Message | Per-preference notification settings |
| `EntitlementSnapshot` | Message | Effective per-user entitlement limits/capabilities embedded in events |
| `WorkArrangement` | Enum | `REMOTE`, `HYBRID`, `ON_SITE` |
| `SeniorityLevel` | Enum | `INTERN` through `EXECUTIVE` (9 values) |
| `EmploymentTerm` | Enum | `FULL_TIME`, `CONTRACT`, `INTERNSHIP`, etc. |
| `JobBoardSource` | Enum | `INDEED`, `LINKEDIN`, `ZIPRECRUITER`, `GOOGLE`, etc. |
| `ListingStatus` | Enum | `ACTIVE`, `STALE`, `EXPIRED` |
| `CorrelationStatus` | Enum | `PENDING` → `EVALUATED` → `VIEWED` → `SAVED` → `APPLIED` |
| `SubscriptionTier` | Enum | `FREE`, `BASIC`, `PRO`, `ENTERPRISE` |
| `SubscriptionStatus` | Enum | `NONE`, `TRIALING`, `ACTIVE`, `PAST_DUE`, `CANCELED`, etc. |
| `DocumentCategory` | Enum | `RESUME`, `COVER_LETTER`, `PORTFOLIO` |
| `ContentType` | Enum | `PDF`, `DOCX`, `HTML`, `MARKDOWN`, etc. |
| `CountryCode` | Enum | ISO 3166-1 alpha-3 (15 supported countries) |
| `CurrencyCode` | Enum | ISO 4217 (11 supported currencies) |
| `PaymentFrequency` | Enum | `HOURLY`, `DAILY`, `WEEKLY`, `BIWEEKLY`, `MONTHLY`, `ANNUALLY` |

### `nohiki.job.listing.v1`

Canonical job listing lifecycle events. Consumed by `bff-service`, `job-correlation-evaluation-service`,
`job-ingest-enrichment-service`, and `notification-service`.

| Type | Kind | Topic |
| ------ | ------ | ------- |
| `ListingCreated` | Event | `listings.fct.listing-created.v1` |
| `ListingUpdated` | Event | `listings.cdc.listing-updated.v1` |
| `ListingDeleted` | Event | `listings.cdc.listing-deleted.v1` |
| `ListingAccepted` | Event | `job-listing.fct.accepted.v1` |
| `ListingSnapshot` | Snapshot | Embedded in `ListingCreated` and `ListingUpdated` |
| `ListingNotificationSnapshot` | Snapshot | Minimal listing data for notification templates |
| `BackfillRequested` | Command | `job-listing.cmd.backfill-requested.v1` |
| `BackfillCallback` | Callback | Dynamic (from `CommandHeader.callback_topic`) |
| `Listing` | Entity | Full listing entity (stored in `job-storage-service`) |

`ListingSnapshot` is the most-imported type in the codebase. It carries the full listing
state including pre-computed ML embeddings (`skills_embedding`, `title_embedding`,
`retrieval_embeddings`) and canonicalized skill requirements (`skill_requirements`) so that
downstream consumers never need to re-query the storage service.

### `nohiki.job.ingest.v1`

Job discovery and enrichment pipeline messages, produced and consumed by the three
`job-ingest-*` services.

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `ListingDiscovered` | Event | Raw listing found by the scraper |
| `DiscoveredListing` | Entity | Structured scraped data (replaces raw JSON blob) |
| `EnrichmentCompleted` | Event | LLM enrichment finished; carries structured data |
| `StoredListing` | Entity | Listing confirmed stored in job-storage-service |
| `IngestionTriggered` | Event | Scheduled discovery run started |
| `IngestionQuery` | Entity | A user's active job search query for scraping |
| `IngestionQueryChanged` | Event | Search query updated, scrapers need to adjust |

### `nohiki.job.correlation.v1`

Job-to-user match (correlation) evaluation results and feedback.

| Type | Kind | Topic |
| ------ | ------ | ------- |
| `CorrelationEvaluated` | Event | `job-correlation.cdc.evaluated.v1` |
| `FeedbackRecorded` | Event | `job-correlation.fct.feedback-recorded.v1` |
| `CorrelationSnapshot` | Snapshot | Full correlation state embedded in events |
| `TrainingExportRequested` | Command | ML training data export |

### `nohiki.user.auth.v1`

User account lifecycle. Published exclusively by `user-auth-service` via the transactional
outbox; consumed by BFF, pref-service, upload-service, and entitlement-service.

| Type | Kind | Topic |
| ------ | ------ | ------- |
| `AccountUpdated` | CDC Event | `user-auth.cdc.account-updated.v1` |
| `AccountDeleted` | Fact Event | `accounts.fct.account-deleted.v1` |
| `UserActivity` | Fact Event | `accounts.fct.user-activity.v1` |
| `Account` | Entity | Full account entity embedded in `AccountUpdated` |

### `nohiki.user.pref.v1`

User job search preferences. The largest domain module -- covers CRUD commands from BFF,
CDC events from pref-service, and the `SearchPrefSnapshot` consumed by the ML pipeline.

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `PrefCreated` / `PrefUpdated` / `PrefDeleted` | CDC Events | Preference lifecycle |
| `PrefCreateRequested` / `PrefUpdateRequested` / `PrefDeleteRequested` | Commands | BFF → pref-service |
| `SearchPrefSnapshot` | Snapshot | Full preference state for ECST; embedded in CDC events |
| `SearchPref` | Entity | Core preference entity |
| `UserPrefSettings` | Entity | Global notification and discovery settings per user |
| `UserPrefSettingsCreated` / `UserPrefSettingsUpdated` | Events | Settings lifecycle |

`SearchPrefSnapshot` is imported by `job-correlation-evaluation-service` (ML scoring),
`job-ingest-schedule-service` (discovery scheduling), and `job-query-composition-service`.

### `nohiki.user.upload.v1`

User-uploaded document management (resumes, cover letters). Commands flow from BFF;
CDC events are consumed by pref-service (to associate uploads with preferences) and
doc-process-service (to extract structured content).

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `UploadCreated` / `UploadDeleted` | CDC Events | Upload lifecycle |
| `UploadCreateRequested` | Command | BFF → upload-service |

### `nohiki.user.entitlement.v1`

Subscription and feature entitlement tracking. Published by `user-entitlement-service` in
response to `AccountUpdated` and payment webhook events.

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `EntitlementCreated` / `EntitlementChanged` | Events | Tier change lifecycle |
| `Entitlement` | Entity | Current subscription tier, limits, and feature flags |

### `nohiki.doc.template.v1`

Document template management and PDF rendering. `doc-template-service` handles both template
CRUD (via commands from BFF) and Gotenberg rendering (via `DocumentRenderRequested` commands).

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `TemplateCreated` / `TemplateUpdated` / `TemplateDeleted` | CDC Events | Template lifecycle |
| `DocumentRenderRequested` | Command | Trigger Gotenberg PDF/HTML/image rendering |
| `DocumentRenderCompleted` | Callback | Render result with S3 storage key |
| `DocumentTemplateSnapshot` | Snapshot | Full template + version data for ECST |

### `nohiki.doc.content.v1`

LLM-generated resume and cover letter content. `doc-content-service` consumes generation
commands and publishes structured content events consumed by doc-template-service for rendering.

### `nohiki.doc.process.v1`

Docling-based document processing for user-uploaded files. Extracts structured content from
uploaded PDFs/DOCX, enabling resume parsing for profile pre-population.

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `ProcessedDocumentSnapshot` | Snapshot | Extracted structured content from a document |
| `ProcessingLevel` | Enum | Depth of Docling extraction (`BASIC`, `FULL`, `OCR`) |

### `nohiki.skill.v1`

Canonical skill graph management. Skills are normalized from free-text mentions into canonical
identities by `skill-graph-service`. The types here flow through the normalization pipeline and
carry the results embedded in enriched listing snapshots.

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `SkillNormalizationRequested` | Command | Request skill normalization with callback |
| `SkillNormalizationCallback` | Callback | Normalized skill results |
| `CanonicalSkill` | Entity | A deduplicated, normalized skill node |
| `JobSkillRequirement` | Entity | A skill requirement from a listing, post-normalization |
| `SkillRelationship` | Entity | Relationship between canonical skills (parent, synonym, etc.) |
| `SkillCreated` | Event | New canonical skill added to the graph |

### `nohiki.ml.v1`

ML compute routing types shared between `ml-gateway-service`, `ml-compute-service`, and any
service that requests embeddings (via `nohiki-embedding-client`).

| Type | Kind | Purpose |
| ------ | ------ | --------- |
| `EmbeddingRequested` | Command | Single embedding request to ml-gateway |
| `EmbeddingCallback` | Callback | Single embedding result carrying `EmbeddingVector` values |
| `BatchEmbeddingCallback` | Callback | Batch embedding result for bulk embedding requests |
| `EmbeddingVector` | Message | Contains `DenseData`, `SparseData`, or `MultiVectorData` |
| `BatchEmbeddingRequested` | Command | Batch variant for bulk operations |
| `RerankRequested` / `RerankCallback` | Command/Callback | ColBERT reranking round-trip |
| `EmbeddingType` | Enum | `DENSE`, `SPARSE`, `MUVERA`, `COLBERT` |
| `EntityType` | Enum | What kind of entity is being embedded |
| `EncodingMode` | Enum | Query vs document encoding mode |

### `nohiki.feedback.v1`

ML score feedback signals used to improve the L2R ranking model. Separate from
`job.correlation` feedback (user interaction state) -- these carry explicit score quality signals.

### `nohiki.notification.v1`

Notification delivery tracking. Published by `notification-service` after send attempts.

### `nohiki.sys.v1`

Internal system tick events. Published by `sys-tick-job` to drive scheduled workflows.

---

## API Reference

### Import Pattern

```python
from nohiki.{domain}.{subdomain}.v{N} import MessageType

# Common examples
from nohiki.common.v1 import EventMetadata, WorkArrangement, SeniorityLevel
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot
from nohiki.job.correlation.v1 import CorrelationEvaluated, CorrelationSnapshot
from nohiki.user.auth.v1 import AccountUpdated
from nohiki.user.pref.v1 import PrefCreated, SearchPrefSnapshot
from nohiki.ml.v1 import EmbeddingVector, EmbeddingType
from nohiki.skill.v1 import JobSkillRequirement, SkillNormalizationCallback
from nohiki.doc.template.v1 import DocumentRenderRequested, DocumentRenderCompleted
from nohiki.doc.process.v1 import ProcessedDocumentSnapshot
from nohiki.feedback.v1 import ScoreFeedbackType
```

Forbidden patterns:

```python
# FORBIDDEN: _pb2 imports (gRPC stub style)
from nohiki.job.listing.v1 import listing_pb2

# FORBIDDEN: grpc stubs package (deleted)
from nohiki_grpc_stubs import listing_pb2

# FORBIDDEN: google.protobuf types (use datetime directly)
from google.protobuf import timestamp_pb2
```

### Serialization Methods

All `betterproto2.Message` subclasses provide:

- **`bytes(msg)`** -- Serialize to protobuf wire format for Kafka publishing.
- **`MyMessage().parse(data)`** -- Deserialize from protobuf wire bytes.
- **`msg.to_dict()`** -- Serialize to `dict` for JSONB storage or logging. Datetime fields
  become ISO 8601 strings; enums become their string names.
- **`MyMessage.from_dict(d)`** -- Deserialize from a `dict` (e.g., loaded from JSONB).
- **`msg.to_json()`** -- Serialize to JSON string.
- **`MyMessage.from_json(s)`** -- Deserialize from JSON string.

### nohiki_domain_utils

- **`BetterprotoEnumAdapter`** -- Pydantic annotation class. Wrap a betterproto2 enum type
  with `Annotated[MyEnum, BetterprotoEnumAdapter()]` to make it Pydantic-compatible.
  Accepts `str` (case-insensitive), `int`, or the enum instance itself.
- **`parse_enum_string(enum_cls, value)`** -- Parse a string to a betterproto2 enum with
  case-insensitive and separator-normalized matching (`"senior"`, `"SENIOR"`, `"Senior"` all
  resolve). Raises `ValueError` for unknown values.
- **`create_enum_validator(enum_cls)`** -- Returns a callable that validates str/int/enum.
  Used internally by `BetterprotoEnumAdapter`.
- **`create_enum_serializer(enum_cls)`** -- Returns a callable that serializes enums to name
  strings. Used internally by `BetterprotoEnumAdapter`.
- **`create_enum_json_schema(enum_cls, *, exclude_unspecified, description)`** -- Returns a
  Pydantic-compatible JSON Schema dict listing the valid enum name strings.

---

## Generation Workflow

Proto source files live in `proto/nohiki/` organized as
`proto/nohiki/{domain}/{subdomain}/v1/{messages,entities,snapshots,commands,events,enums}.proto`.
Validation constraints are defined inline using `buf.validate` annotations. The generator
uses `buf` for linting and breaking-change detection, and `betterproto2` as the code generation
backend.

```bash
# Edit proto source
vim proto/nohiki/job/listing/v1/events.proto

# Regenerate Python dataclasses
just proto-gen

# Lint proto files (runs buf lint)
just proto-lint

# Check for breaking changes against main branch
just proto-breaking
```

`just proto-gen` runs `PYTHONPATH=scripts uv run python -m proto_gen generate`, which invokes
the `buf` compiler with the `betterproto2` plugin and writes generated dataclasses into
`backend/libs/nohiki-domain-models/src/nohiki/`. Each leaf `v1/__init__.py` consolidates all
messages from proto files in that package (e.g., `entities.proto`, `events.proto`,
`snapshots.proto`, `commands.proto`) into a single importable module.

After regenerating, run `just sync` to ensure any new dependencies introduced by the generated
code are resolved across the workspace. Then run `just typecheck-all` to catch any type errors
in services that import the changed types.

**Never edit generated files.** The `# DO NOT EDIT!` header in every `__init__.py` is not
advisory -- any manual changes will be silently overwritten the next time `just proto-gen` runs.

---

## Testing

Tests for this library live in `tests/` and cover only the `nohiki_domain_utils` module --
the generated `nohiki` dataclasses themselves have no unit tests here (the proto definitions
have `buf lint` validation; generated code correctness is tested indirectly through service
tests).

```bash
just test nohiki-domain-models
```

To construct domain messages in service tests, instantiate dataclasses directly:

```python
from datetime import UTC, datetime
import uuid
from nohiki.common.v1 import EventMetadata
from nohiki.job.listing.v1 import ListingSnapshot

def make_metadata(source: str = "test-service") -> EventMetadata:
    return EventMetadata(
        event_id=str(uuid.uuid4()),
        timestamp=datetime.now(UTC),
        source_service=source,
        version="v1",
    )

snapshot = ListingSnapshot(
    id=str(uuid.uuid4()),
    title="Test Engineer",
    company_name="Test Co",
    listing_url="https://example.com/job/1",
    source=JobBoardSource.INDEED,
    discovered_at=datetime.now(UTC),
    created_at=datetime.now(UTC),
    updated_at=datetime.now(UTC),
)
```

When mutating a frozen dataclass field in a test assertion context, use `setattr()`:

```python
# betterproto2 messages use eq=False and repr=False but are NOT frozen --
# direct assignment works. Use setattr() only when mutating @dataclass(frozen=True) instances
# from nohiki-test-utils fixtures.
setattr(record, "field_name", new_value)
```

---

## Design Decisions

### Why betterproto2 Instead of Standard Protobuf

Standard `protoc`-generated Python code produces `_pb2.py` files with a `google.protobuf`
runtime that has no native Python type integration. `datetime` fields require explicit
`Timestamp` construction; enums are plain integers with no IDE support; serialization
requires verbose `SerializeToString()` / `ParseFromString()` calls.

betterproto2 generates dataclasses with:

- `datetime.datetime` directly on timestamp fields (no `Timestamp` wrapper)
- `str | None` / `int | None` for optional scalars
- `list[T]` for repeated fields
- `dict[K, V]` for map fields
- `to_dict()` / `from_dict()` for JSONB-friendly serialization
- Full type checker and IDE support (all fields are properly annotated)

The only cost is that betterproto2 enums are not natively compatible with Pydantic, which
is why `nohiki_domain_utils.BetterprotoEnumAdapter` exists.

### One Module Per Domain Package

All messages from a domain's proto files (entities, events, snapshots, commands) are compiled
into a single `v1/__init__.py` per subdomain. This means imports never need to reference
individual proto filenames -- `from nohiki.job.listing.v1 import ListingCreated` works
regardless of whether `ListingCreated` was defined in `events.proto` or `commands.proto`.
The tradeoff is that the generated `__init__.py` files can be large (512+ lines for `job.listing.v1`),
but this is preferable to forcing service developers to know which proto file each message came from.
