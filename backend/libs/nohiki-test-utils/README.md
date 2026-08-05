# Nohiki Test Utils

Shared testing utilities consumed by all 13+ Nohiki service test suites. Provides pytest
fixtures for HTTP clients and authentication, polyfactory-based factories for generating
valid betterproto2 domain model instances, a curated catalog of 16 job listing personas
and 7 user preference personas spanning five industries, pre-composed ECST-compliant Kafka
event fixtures, and match-quality scenarios for correlation scoring tests. Eliminates
per-service boilerplate for test environment setup, JWT creation, and domain object
construction. Development-only dependency: not included in any service runtime image.

## Quick Start

```python
# conftest.py: register the plugin to activate fixtures and markers
pytest_plugins = ["nohiki_test_utils.plugins"]

# Import curated personas directly: no factory calls needed for standard test data
from nohiki_test_utils.sample_data import SENIOR_PYTHON_REMOTE, BACKEND_ENGINEER_PREF
from nohiki_test_utils.sample_data import EXCELLENT_BACKEND_MATCH

# Use a factory when you need a one-off instance with specific field values
from nohiki_test_utils.factories import ListingSnapshotFactory, ListingCreatedFactory

listing = ListingSnapshotFactory.build(
    title="Principal ML Engineer",
    work_arrangement=WorkArrangement.REMOTE,
)

# Build a complete ListingCreated event carrying the snapshot (ECST-compliant)
event = ListingCreatedFactory.build(listing_snapshot=listing)

# copy_with creates a modified copy without mutating the original frozen dataclass
from nohiki_test_utils.sample_data import copy_with
modified = copy_with(SENIOR_PYTHON_REMOTE, title="Staff Python Engineer")
```

## Core Concepts

### Persona Catalog vs Factories

The library draws a deliberate distinction between two data-generation strategies:

- **Personas** (`sample_data.*`) are hand-authored, curated constants that represent
  realistic, internally-consistent domain objects. Skills, salary ranges, seniority levels,
  and work arrangements are set intentionally so that tests can make meaningful assertions
  about business logic (e.g., "this listing should score > 0.85 against this preference").
  Use personas when the test cares about the content of the data.

- **Factories** (`factories.*`) use [polyfactory](https://polyfactory.litestar.dev) to
  generate structurally valid betterproto2 instances with random field values. Use factories
  when the test only cares that a valid object exists, not what it contains. Factories
  always produce timezone-aware datetimes and non-UNSPECIFIED enum values, both of which
  betterproto2 requires for correct serialization.

### Betterproto2 Quirks Handled by BetterprotoFactory

polyfactory generates `0` for `IntEnum` fields by default. Every betterproto2 enum defines
`FIELD_UNSPECIFIED = 0` as a sentinel value, so naively built objects have every enum field
set to UNSPECIFIED. `BetterprotoFactory` intercepts this in two places:

1. `get_provider_map()` registers a per-type provider that picks a random non-zero member.
2. `build()` calls `_fix_unspecified_enums()` as a post-build sweep over any fields that
   the provider map missed, skipping fields that were explicitly passed as keyword arguments.

### Pytest Plugin

Registering `nohiki_test_utils.plugins` in `conftest.py` does three things:

1. **Registers four custom markers** -- `requires_docker`, `integration`, `unit`, `slow`.
2. **Auto-skips `requires_docker` tests** when the Docker daemon socket is unreachable,
   checking both the Unix socket at `/var/run/docker.sock` and the `DOCKER_HOST` env var.
3. **Activates two fixture modules** -- `nohiki_test_utils.fixtures.auth` and
   `nohiki_test_utils.fixtures.clients` -- making their fixtures available to all tests in
   the suite without explicit imports.

The auth fixture module also runs a module-level side effect on import: it sets `TEST_MODE`,
disables all OTel exporters, and creates a temporary secrets directory with a
`jwt_secret_key` file. This ensures services that load config on import do not fail before
any test runs.

### Match Scenarios

`MatchScenario` is a frozen dataclass that pairs a `ListingSnapshot` with a
`SearchPrefSnapshot` and annotates the pair with an expected quality label
(`"excellent"`, `"good"`, `"poor"`) and an expected score range. The six pre-composed
software engineering scenarios in `sample_data.scenarios` serve as ground-truth fixtures
for `job-correlation-evaluation-service` scoring tests. They define the minimum bar the
ML pipeline must meet.

### Raw Job Postings and Enrichment Simulation

`RawJobPosting` holds the unmodified text scraped from a job board alongside a pipeline of
`TransformFn` callables. Calling `.simulate_enrichment()` applies the transforms in order,
mimicking the boilerplate-stripping and artifact-cleanup that the LLM enrichment step
performs. This allows `job-ingest-enrichment-service` integration tests to feed raw text
to the extraction agent while the enriched personas serve as ground-truth comparison points.

## API Reference

### Pytest Plugin and Fixtures

Register the plugin in `conftest.py`:

```python
pytest_plugins = ["nohiki_test_utils.plugins"]
```

#### Auth Fixtures (`nohiki_test_utils.fixtures.auth`)

- **`setup_test_secrets`** -- Session-scoped, `autouse=True`. Returns the temporary secrets
  directory `Path`. Sets `TEST_MODE=true`, disables OTel, and writes a
  `jwt_secret_key` file. Services that read secrets from disk during config loading
  need this to run before any import of service modules.

- **`valid_user_token`** -- Function-scoped. Returns a fresh HS256 JWT with a random
  `user_id` UUID and `username: "testuser"` claim. Use for authenticated endpoint tests
  that need a structurally valid token but do not verify signatures.

- **`sample_user_headers`** -- Function-scoped. Returns `{"Authorization": "Bearer <token>"}`
  composed from `valid_user_token`. Authorization is the only identity header the fixture
  emits, so a test that needs another header adds it explicitly.

- **`valid_internal_token`** -- Module-level constant (not a fixture). Pre-generated token
  with `service: "test-service"` and `role: "internal"` claims. Use when a test needs
  a stable token value across the session.

#### JWT Helpers (`nohiki_test_utils.utils.jwt_helpers`)

These are plain functions, not fixtures. Import directly when the test needs programmatic
token construction with a specific secret.

- **`create_jwt(secret, sub, exp_minutes, algorithm, additional_claims)`** -- Encodes a
  standard JWT with `sub`, `iat`, `exp` claims using PyJWT.
- **`create_user_jwt(secret, user_id, exp_minutes, claims)`** -- Thin wrapper that sets
  `sub` to `str(user_id)`.
- **`create_expired_jwt(secret, sub, algorithm, additional_claims)`** -- Sets `exp` to one
  hour in the past. Use for testing token rejection paths.

#### Client Fixtures (`nohiki_test_utils.fixtures.clients`)

These fixtures are overridable: services replace `fastapi_app` with their own app
instance, and the other fixtures compose from it automatically.

- **`fastapi_app`** -- Returns a minimal FastAPI app with a `/health` endpoint. Override
  this fixture in the service conftest to supply the real app.

- **`test_client(fastapi_app)`** -- Synchronous `TestClient` wrapping the app. Useful for
  simple endpoint tests where async is not needed.

- **`async_client(fastapi_app)`** -- `httpx.AsyncClient` using `ASGITransport`. Use for
  async endpoint tests.

- **`async_client_with_db(fastapi_app)`** -- Same as `async_client` but signals intent to
  test with a real database session. Services override this to inject their `get_async_db`
  dependency override before yielding.

### Factories (`nohiki_test_utils.factories`)

All factories inherit from `BetterprotoFactory` which itself extends polyfactory's
`DataclassFactory`.

```python
from nohiki_test_utils.factories import (
    ListingSnapshotFactory,
    SearchPrefSnapshotFactory,
    ListingCreatedFactory,
    PrefCreatedFactory,
    EventMetadataFactory,
    LocationFactory,
    CompensationFactory,
)
```

**Common usage patterns:**

```python
# Build one instance with field overrides
listing = ListingSnapshotFactory.build(title="Senior ML Engineer")

# Build multiple unique instances
listings = ListingSnapshotFactory.batch(10)

# Compose factories: build an event wrapping a specific snapshot
snapshot = ListingSnapshotFactory.build(work_arrangement=WorkArrangement.REMOTE)
event = ListingCreatedFactory.build(listing_snapshot=snapshot)
```

**Guarantees provided by all factories:**

- `datetime` fields are always timezone-aware (`UTC`).
- Enum fields are never `UNSPECIFIED` (value `0`), even for deeply nested sub-messages.
- Explicitly passed kwargs are never overridden by the post-build fixup.
- Generated instances pass `betterproto2` serialization round-trips (`.to_dict()` / `.from_dict()`).

### Sample Data Personas

Import from `nohiki_test_utils.sample_data` for direct access to all personas, or from
the sub-modules for selective imports.

#### Job Listing Personas

All personas are `ListingSnapshot` instances with deterministic UUIDs, fixed timestamps
(`2025-01-15T10:00:00Z`), pre-computed embeddings, and canonicalized skill requirements.

| Constant | Role | Arrangement | Seniority |
| --- | --- | --- | --- |
| `SENIOR_PYTHON_REMOTE` | Senior Python Engineer | Remote | Senior |
| `JUNIOR_FRONTEND_HYBRID` | Junior Frontend Developer | Hybrid | Entry |
| `STAFF_PLATFORM_HYBRID` | Staff Software Engineer, Platform | Hybrid | Staff |
| `DATA_SCIENTIST_REMOTE` | Data Scientist | Remote | Mid |
| `DEVOPS_ENGINEER_HYBRID` | DevOps Engineer | Hybrid | Mid |
| `MID_SOFTWARE_ONSITE` | Software Engineer | On-site | Mid |
| `NURSE_ICU_ONSITE` | ICU Nurse | On-site | Mid |
| `PHYSICAL_THERAPIST` | Physical Therapist | On-site | Mid |
| `PHARMACIST_HYBRID` | Pharmacist | Hybrid | Mid |
| `ELECTRICIAN_ONSITE` | Electrician | On-site | Mid |
| `HVAC_TECHNICIAN` | HVAC Technician | On-site | Entry |
| `FINANCIAL_ANALYST_HYBRID` | Financial Analyst | Hybrid | Mid |
| `MARKETING_MANAGER_REMOTE` | Marketing Manager | Remote | Mid |
| `HR_DIRECTOR_HYBRID` | HR Director | Hybrid | Director |
| `DIRECTOR_ENGINEERING` | Director of Engineering | Hybrid | Director |
| `VP_PRODUCT_REMOTE` | VP of Product | Remote | Director |

Salary values are stored as minor units (cents). `SENIOR_PYTHON_REMOTE` has
`min=$150,000 / max=$180,000` as a representative senior remote software role.

#### User Preference Personas

All personas are `SearchPrefSnapshot` instances with realistic `search_keywords`,
`disallowed_keywords`, skill lists, salary preferences, and `FeatureImportancePrefs`.

| Constant | Profile | Industry |
| --- | --- | --- |
| `BACKEND_ENGINEER_PREF` | Backend Engineering Roles | Software |
| `FRONTEND_DEVELOPER_PREF` | Frontend Development Positions | Software |
| `FULLSTACK_DEVELOPER_PREF` | Full-Stack Development | Software |
| `DATA_SCIENTIST_PREF` | Data Science & ML Roles | Software |
| `DEVOPS_ENGINEER_PREF` | DevOps & Infrastructure | Software |
| `EXPERIENCED_NURSE_PREF` | Nursing (RN, ICU/ER) | Healthcare |
| `FINANCE_ANALYST_PREF` | Financial Analysis | Business |

#### Raw Job Postings

Each listing persona has a paired `RawJobPosting` constant (e.g., `SENIOR_PYTHON_REMOTE_POSTING`).
These contain the unmodified scraper output text with `enrichment_transforms` pipelines.

```python
from nohiki_test_utils.sample_data import SENIOR_PYTHON_REMOTE_POSTING

# Feed raw text to the LLM extraction agent
raw_text = SENIOR_PYTHON_REMOTE_POSTING.raw

# Or apply the enrichment simulation for ground-truth comparison
enriched = SENIOR_PYTHON_REMOTE_POSTING.simulate_enrichment()
```

The enrichment transforms use functions from `nohiki_test_utils.sample_data._enrichment`:
`strip_paragraphs_containing()` (removes EEO/boilerplate paragraphs), `strip_html_tags()`,
`fix_unicode_artifacts()`, and `replace_text()`. `STRIP_EEO` is a pre-built transform
that removes paragraphs containing "equal opportunity".

#### Pre-Composed Kafka Events

Ready-to-use ECST-compliant event instances for handler integration tests:

```python
from nohiki_test_utils.sample_data import (
    LISTING_CREATED_SENIOR_PYTHON,   # ListingCreated
    LISTING_CREATED_DATA_SCIENTIST,  # ListingCreated
    PREF_CREATED_BACKEND_ENGINEER,   # PrefCreated
    PREF_UPDATED_BACKEND_ENGINEER,   # PrefUpdated
)
```

Each event has a deterministic `event_id`, the correct `source_service` set (`job-storage-service`
or `user-pref-service`), and carries the full snapshot in `listing_snapshot` / `pref_snapshot`.
`PREF_CREATED_BACKEND_ENGINEER` and `PREF_UPDATED_BACKEND_ENGINEER` share the same `pref_id`
and `user_id`, enabling tests that exercise the created → updated lifecycle.

#### Pre-Composed Match Scenarios

```python
from nohiki_test_utils.sample_data import (
    EXCELLENT_BACKEND_MATCH,           # score range: 0.85-1.0
    EXCELLENT_DATA_SCIENCE_MATCH,      # score range: 0.85-1.0
    GOOD_FRONTEND_MATCH,               # score range: 0.70-0.84
    GOOD_DEVOPS_MATCH,                 # score range: 0.70-0.84
    POOR_MISMATCH_BACKEND_TO_FRONTEND, # score range: 0.0-0.40
    POOR_MISMATCH_FRONTEND_TO_BACKEND, # score range: 0.0-0.40
    MatchScenario,
)

def test_scoring_meets_expectation(scorer, scenario: MatchScenario):
    score = scorer.score(scenario.listing, scenario.pref)
    min_score, max_score = scenario.expected_score_range
    assert min_score <= score <= max_score, scenario.notes
```

#### Document Test Data

`BACKEND_ENGINEER_RESUME` is a plain `dict` containing a full resume for "Alex Chen" --
a senior Python engineer with six years of experience. Use it as input to
`doc-template-service` and `doc-content-service` rendering tests.

```python
from nohiki_test_utils.sample_data.documents import BACKEND_ENGINEER_RESUME
```

### Utility Helpers

#### `copy_with(instance, **overrides)`

Returns a copy of any dataclass instance with the specified fields replaced. The return type
matches the input type exactly.

```python
from nohiki_test_utils.sample_data import copy_with, SENIOR_PYTHON_REMOTE

# Create a variant without mutating the shared constant
onsite_variant = copy_with(SENIOR_PYTHON_REMOTE, work_arrangement=WorkArrangement.ON_SITE)
```

This is the correct way to adapt a persona for a specific test case. Direct field assignment
on frozen betterproto2 dataclasses raises `FrozenInstanceError`.

#### `to_discovered_listing(snapshot, external_id=None)`

Converts a `ListingSnapshot` persona into a `DiscoveredListing` -- the input format used
by `job-ingest-enrichment-service` and `job-storage-service`. Copies listing URL, source,
title, company name, description, raw skills, compensation, and timestamps from the snapshot.

```python
from nohiki_test_utils.sample_data import to_discovered_listing, SENIOR_PYTHON_REMOTE

discovered = to_discovered_listing(SENIOR_PYTHON_REMOTE)
```

#### `get_repo_root()`

Returns the monorepo root as a `Path`, resolved via `PROJECT_ROOT` env var (set by `direnv`)
or by walking up the directory tree looking for the root `pyproject.toml` with
`[tool.uv.workspace]`. Result is cached with `@cache`. Repeated calls are free.

Used by services like `job-correlation-evaluation-service` to locate ML model files:

```python
from nohiki_test_utils import get_repo_root

models_dir = get_repo_root() / "models" / "l2r"
os.environ["JOB_CORRELATION_EVAL_ML__L2R__MODEL_PATH"] = str(models_dir / "l2r_lightgbm.txt")
```

#### `docker_daemon_available()`

Returns `True` if the Docker daemon endpoint is reachable. Checks the Unix socket at
`/var/run/docker.sock` or parses the `DOCKER_HOST` env var for a TCP endpoint. Result is
`lru_cache`-d to avoid repeated socket probes within a test session. Called automatically
by the plugin to gate `@pytest.mark.requires_docker` tests.

#### Async DB Utilities (`nohiki_test_utils.utils.async_db`)

Not re-exported from the top-level `__init__`. Import directly when writing service tests
that need a real database connection:

- **`get_async_engine(url)`** -- Creates or returns a cached `AsyncEngine` for the given DSN.
  Automatically upgrades `postgresql://` to `postgresql+asyncpg://`.
- **`get_async_sessionmaker(url)`** -- Returns a cached `async_sessionmaker` bound to the
  engine from `get_async_engine`.
- **`reset_db(engine, base_metadata)`** -- Drops and recreates all tables. Use in `autouse`
  fixtures to isolate each test from database state.

## Testing

### Activating the Plugin in a Service

Add to the service's top-level `conftest.py`:

```python
pytest_plugins = ["nohiki_test_utils.plugins"]
```

This activates the custom markers and both fixture modules. Services that import service
modules at collection time must also ensure the test environment is configured before any
import, since `setup_test_secrets` fires on module load:

```python
# conftest.py: job-correlation-evaluation-service pattern
import os
from nohiki_test_utils import get_repo_root, setup_test_secrets, valid_internal_token

def _setup_test_environment() -> None:
    os.environ["TEST_MODE"] = "true"
    os.environ.setdefault("MY_SERVICE_DATABASE__DSN", "postgresql://test:test@localhost:5432/test")
    # ... other required env vars ...
    os.environ.setdefault("MY_SERVICE_ML__MODEL_PATH", str(get_repo_root() / "models" / "model.txt"))

_setup_test_environment()  # Must run before any service module import
```

### Overriding the FastAPI App Fixture

Each service replaces `fastapi_app` with its own app instance. All client fixtures
then compose automatically:

```python
# conftest.py: service-specific
import pytest
from fastapi import FastAPI
from my_service.main import app as real_app

@pytest.fixture
def fastapi_app() -> FastAPI:
    return real_app
```

### Using Personas in Unit Tests

Import personas directly: no fixture injection needed for immutable constants:

```python
from nohiki_test_utils.sample_data import SENIOR_PYTHON_REMOTE, BACKEND_ENGINEER_PREF
from nohiki_test_utils.sample_data import copy_with

def test_score_remote_job(scorer):
    score = scorer.score(SENIOR_PYTHON_REMOTE, BACKEND_ENGINEER_PREF)
    assert score >= 0.85

def test_onsite_penalty(scorer):
    onsite = copy_with(SENIOR_PYTHON_REMOTE, work_arrangement=WorkArrangement.ON_SITE)
    score = scorer.score(onsite, BACKEND_ENGINEER_PREF)
    assert score < 0.85  # pref prefers remote
```

### Using Factories for Structural Tests

Use factories when a handler test needs a valid message but the specific field values
do not affect the assertion:

```python
from nohiki_test_utils.factories import ListingCreatedFactory, ListingSnapshotFactory

async def test_handler_stores_listing(handler, db_session):
    event = ListingCreatedFactory.build()
    await handler.handle_listing_created(event, mock_context)
    stored = await db_session.get(ListingProjection, event.listing_snapshot.id)
    assert stored is not None
    assert stored.title == event.listing_snapshot.title
```

### Integration Test Markers

Mark integration tests so they can be run selectively:

```python
@pytest.mark.integration
async def test_full_listing_pipeline(kafka_consumer, db_session):
    ...

@pytest.mark.requires_docker
async def test_with_real_postgres(container_db):
    ...
```

Run only integration tests:

```bash
uv run --package my-service pytest tests/ -m integration
```

`requires_docker` tests are automatically skipped when the Docker daemon is unreachable,
so the unit test suite remains fast in environments without Docker.

## Design Decisions

### Why Curated Personas Rather Than Only Factories

Random factory output is useless for ML scoring tests: you cannot assert that
`EXCELLENT_BACKEND_MATCH` scores above 0.85 if the listing and preference were generated
with random skills and salary ranges. The persona catalog gives the test suite a stable,
human-readable ground truth. Factories still serve a purpose for structural tests where
only object validity matters.

### Deterministic IDs and Timestamps

All persona IDs are UUIDv5-derived or hard-coded constants in `_ids.py`, and all timestamps
use `FIXED_TIMESTAMP = 2025-01-15T10:00:00Z`. This ensures test snapshots are stable across
runs and that serialization assertions (e.g., `stored.created_at == FIXED_TIMESTAMP`) do not
flake.

### Infrastructure Fixtures Live Elsewhere

Database session fixtures are in `nohiki-db-utils` (testing extra). Redis fixtures are in
`nohiki-redis-utils` (testing extra). This library deliberately excludes them to avoid pulling
infra dependencies (SQLAlchemy, aioredis) into services that do not need them. The
`async_db.py` utilities in this library are low-level helpers that services can use if they
already have SQLAlchemy in their runtime dependencies.
