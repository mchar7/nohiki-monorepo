# Contributing

Nohiki contributors use this guide for repository conventions, common commands,
architecture, service patterns, code style, and testing practices.

## Project overview

Nohiki is a job-search workspace built as an **event-driven microservices architecture**.
Services communicate ONLY via Kafka events. No HTTP/gRPC calls between internal services
(except external dependencies like S3, Gotenberg, etc).

## Repository layout

**uv workspace monorepo** with a single lockfile at root. All Python packages use the **src layout**.

```text
backend/
├── services/                    # Long-running Kafka-driven microservices
│   ├── user-auth-service/       # JWT auth, user identity (HTTP + Kafka)
│   ├── user-pref-service/       # Job target profiles (Kafka only)
│   ├── user-upload-service/     # S3 document storage (Kafka only)
│   ├── user-entitlement-service/# Billing/tier logic (Kafka only)
│   ├── job-storage-service/     # Canonical job data (Kafka only)
│   ├── job-correlation-evaluation-service/  # Job scoring, ML (Kafka only)
│   ├── job-ingest-discovery-service/        # Job scraping (Kafka only)
│   ├── job-ingest-schedule-service/         # Scheduled scraping (Kafka only)
│   ├── job-ingest-enrichment-service/       # LLM analysis (Kafka only)
│   ├── job-query-composition-service/       # Job queries (Kafka only)
│   ├── ml-gateway-service/      # ML routing (Kafka only)
│   ├── ml-compute-service/      # K8s ML compute (Kafka only)
│   ├── doc-template-service/    # Template storage + PDF rendering via Gotenberg (Kafka only)
│   ├── doc-content-service/     # Resume/Cover letter content generation (Kafka only)
│   ├── doc-process-service/     # Document processing with Docling (Kafka only)
│   ├── notification-service/    # Email notifications (Kafka only)
│   ├── skill-graph-service/     # Skill normalization and graph management (Kafka only)
│   └── bff-service/             # Backend-for-frontend (HTTP + Kafka)
├── jobs/                        # One-shot trigger scripts
│   └── sys-tick-job/            # Publishes tick event for scheduled tasks
└── libs/                        # Shared Python libraries (17 total)
    ├── nohiki-kafka-client/     # Consumer/Producer/Supervisor + DLQ/retry + circuit breaker
    ├── nohiki-domain-models/    # Protobuf dataclasses (betterproto2) + domain utils
    ├── nohiki-db-utils/         # SQLAlchemy async + outbox + migrations + health probes
    ├── nohiki-fastapi-utils/    # FastAPI helpers (health, JWT, CSRF, rate limiting)
    ├── nohiki-observability/    # OpenTelemetry + structured logging + Prometheus
    ├── nohiki-core-settings/    # Centralized Pydantic settings base classes
    ├── nohiki-common-exceptions/# Typed exception hierarchy
    ├── nohiki-redis-utils/      # Redis cache + circuit breaker
    ├── nohiki-s3-client/        # S3 operations
    ├── nohiki-llm-client/       # PydanticAI LLM client (retry, cost tracking, caching)
    ├── nohiki-ml-core/          # ML encoders (ColBERT, MUVERA, sparse)
    ├── nohiki-ml-manifest/      # ML encoding manifest / semantic representation IDs
    ├── nohiki-qdrant-client/    # Qdrant vector operations
    ├── nohiki-embedding-client/ # Embedding request/callback pattern helpers
    ├── nohiki-geo-utils/        # Redis-cached geocoding (GeoPy Nominatim)
    ├── nohiki-finance/          # ISO 4217 currency conversion + pay-period annualization
    └── nohiki-test-utils/       # Common test fixtures and utilities

proto/                           # Protobuf definitions
typescript/                      # TypeScript tree (mirrors backend/)
├── apps/
│   └── frontend/                # React SPA (Vite, TypeScript)
├── libs/                        # TypeScript shared libraries
├── services/                    # TypeScript long-running services
└── edge/
    └── auth-listings-worker/    # Cloudflare Worker (Hono + OTel)
infra/
├── compose/                     # Docker Compose (local dev)
├── k8s/
│   ├── helm/                    # Kubernetes Helm umbrella chart
│   ├── gitops/                  # Flux v2 sources, Kustomizations, HelmReleases
│   ├── observability/           # Kustomize CRDs (Grafana, OTel, ESO)
│   ├── kgateway/                # Gateway API implementation
│   └── kafka-connect/           # Kafka Connect CDC connectors
├── terraform/                   # OpenTofu configuration for Azure IaC
├── shared/
│   ├── dashboards/              # Grafana dashboard JSON (single source of truth)
│   ├── scripts/                 # Infrastructure scripts
│   ├── secrets/                 # Shared secrets (gitignored)
 │   └── qdrant-init/             # Qdrant collection initialization
tests/                           # Integration/E2E tests
```

**HTTP-exposed services:** Only `user-auth-service` and `bff-service` are exposed via Traefik.
All other services are Kafka-only with no API routers.

## Worktrees

Run parallel work in separate worktrees, kept as siblings of the main
checkout (not nested inside it):

```bash
git worktree add ../worktrees/<feature-domain-kebab> -b feat/<feature-domain-kebab>
```

The sibling layout keeps build tooling (`uv`, `pnpm`, `just`, `ty`,
`semgrep`, etc.) from accidentally recursing into worktree checkouts. Each
worktree carries its own venv / `node_modules` / build caches.

When a branch lands on `main`, remove the worktree:

```bash
git worktree remove ../worktrees/<feature-domain-kebab>
```

## Branches

Branch names match this regex:

```regex
^(feat|fix|chore|refactor|docs|test|ci|perf|build|revert)/[a-z0-9][a-z0-9-]{2,49}$
```

Type prefixes mirror Conventional Commits. The slug after the `/` describes
what the change does in feature-domain terms (a service, a library, a
function, a user-visible behaviour). Examples: `feat/user-profile-avatar`,
`fix/login-redirect-loop`, `refactor/extract-payment-validator`,
`chore/upgrade-dependencies`.

`main` only moves through pull requests; branch protection blocks direct
pushes. Even a one-line fix rides a short-lived branch.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/) format. The
`commit-msg` hook gives fast local feedback but is bypassable by design
(`git --no-verify`); the required PR check is the enforcement. Scope is the
affected service or library (`feat(correlation): ...`, `chore(ml-manifest): ...`).

One logical behaviour per commit. Tests live with the implementation they
exercise.

## Merging

Merge pull requests through GitHub's **Create a merge commit** option. Required
checks and review must pass before merge. Do not squash; the merge commit
preserves the reviewed branch tip and its semantic commits as ancestry.

PR titles must themselves be conventional: the repository is configured to use
the PR title as the merge commit subject (with a blank body), and the required
check lints the title with the same commitlint rules.

Branches are short-lived (target ≤1 week). Long-running branches rebase on
`main` weekly.

## Command reference

### Setup

```bash
just sync              # Sync all workspace dependencies
just sync-dev          # Sync with all CPU development extras
direnv allow           # Activate Nix environment (recommended)
```

### Lint / Format

```bash
just fix               # ruff lint + format (run this after every change)
just lint              # Lint only
just format            # Format only
just lint-service <name>  # Lint specific service
just lint-libs         # Lint shared libs only
just lint-md           # Lint markdown files
```

Aliases: `just l` (lint), `just f` (format), `just s` (sync)

### Type Checking

```bash
just typecheck-all                    # ty on all backend code (strict mode)
just typecheck <service-name>         # ty on specific service
just typecheck-lib <lib-name>         # ty on specific library
just typecheck-job <job-name>         # ty on specific job
```

### Testing

**Always use package-aware commands** to prevent pytest import collisions across the monorepo.

```bash
just test-all-packages        # All services + libs (recommended for full runs)
just test-backend-packages    # Backend services only
just test-libs-packages       # Shared libs only
just test <service-name>      # Single service (e.g., just test user-auth-service)
just test-cov <service-name>  # With coverage report
```

**Run a single test file or test function** (from repo root):

```bash
uv run --package <service-name> pytest tests/path/to/test_file.py --tb=short
uv run --package <service-name> pytest tests/path/to/test_file.py::test_function --tb=short
uv run --package <service-name> pytest tests/path/to/test_file.py::TestClass::test_method --tb=short
```

Or cd into the service directory first:

```bash
cd backend/services/<service-name>
uv run pytest tests/test_specific.py -v --tb=short
```

**Other test commands:**

```bash
just test-integration         # Integration tests (tests/integration/)
just test-api                 # API contract tests via BFF (tests/api/)
just test-e2e                 # Playwright browser tests
just test-all-e2e             # API + Playwright tests
just test-e2e-journey <name>  # Single Playwright journey
just test-e2e-headed / -ui / -debug / -report
```

### Hygiene

```bash
just hygiene                      # All hygiene: deps + arch + deadcode + fixtures
just hygiene-deps                 # Unused/undeclared deps (deptry)
just hygiene-arch                 # Architecture rules (semgrep)
just hygiene-deadcode             # Dead code detection
just hygiene-deadcode-strict      # Dead code detection (fail mode)
just hygiene-fixtures             # Pytest fixture usage check
just hygiene-fixtures-strict      # Fail on fixture issues
just hygiene-build-backend        # Canonical [build-system] check (reports migration progress)
just hygiene-build-backend-strict # Fail on any package not on uv_build (post-rollout gate)
just check-strict                 # lint + typecheck-all + hygiene
```

### Build / Docker

```bash
just build <service>              # Build single backend service image
just build-all                    # Build all backend service images
just infra-up                     # Start postgres, valkey, kafka, and kafka init
just infra-down                   # Stop infrastructure
just compose-up / compose-down    # Start/stop all services
just compose-health               # Health check against compose stack
just logs <service>               # Follow service logs
```

### Kubernetes

```bash
just k8s-reconcile-local          # idempotent reconcile: check context, push images, hand off to GitOps controllers
just gitops-full                  # install GitOps controllers, bootstrap the cluster source, wait (hard) for reconciliation
just k8s-build / k8s-push-images  # build + push first-party images (LOCAL_REGISTRY, DEV_IMAGE_TAG)
just k8s-factory-reset-local --help # fresh-control-plane reset: checkpoint-bound, exactly acknowledged, explicitly executed
just k8s-status / k8s-logs <service> / k8s-port <service> <port>
just gitops-status / gitops-wait / gitops-logs
just k8s-health                   # Health check against the selected cluster
K8S_GATEWAY_URL=https://gateway.example K8S_NAMESPACE=nohiki just k8s-test  # API tests through the selected cluster Gateway
```

`k8s-test` requires `K8S_GATEWAY_URL`; `K8S_RELEASE` defaults to `nohiki`. The Gateway hostname
must resolve through system DNS or `/etc/hosts` to an address reported in Gateway status.

### Frontend

```bash
just fe-dev                       # Dev server (localhost:5173)
just fe-build                     # Production build
just fe-analyze                   # Bundle size analysis
just fe-check                     # tsc + biome + vitest
just check-all                    # lint + fe-check + lint-md
```

### Protobuf

```bash
just proto-gen                    # Generate Python dataclasses from .proto files
just proto-lint                   # Lint proto files
just proto-breaking               # Check breaking changes vs main
```

### Migrations

```bash
just migrate <service>            # Run Alembic migrations (upgrade head)
just migrate-new <service> "msg"  # Create new autogenerated migration
```

### AST Explorer (Codebase Analysis)

```bash
just ast-events                        # Kafka event flows across all services
just ast-events-service <service>      # Events for a specific service
just ast-events-topic <topic>          # Event flow for specific topic
just ast-trace <topic>                 # Trace event chain from a topic
just ast-deps-lib <lib>               # Shared library usage
just ast-impact <symbol>              # Impact of changing a symbol
just ast-scan <service>               # Service structure overview
just ast-query <kind>                 # Query symbols by kind
```

### Git hooks (Lefthook)

The configured hooks are:

- **Commit message:** Conventional Commit validation (`commitlint`) and the internal-reference check.
- **Pre-commit:** Python Ruff lint and format, frontend Biome lint and format, protobuf lint, Markdown lint,
  frontend i18n validation, staged-secret scanning, GitHub Actions lint, and Dockerfile lint. Lefthook skips this
  hook during merges and rebases.
- **Pre-push:**
  - Internal-reference range validation
  - Python lint
  - Python format
  - Python typecheck
  - Frontend typecheck
  - Nix flake check
  - Affected Python tests
  - Skylos cache tests
  - Node workspace contract tests
  - Frontend tests
  - Strict dead-code analysis
  - Deptry
  - Semgrep architecture checks
  - Strict backend build policy
  - Frontend architecture checks
  - API schema freshness
  - Image matrix parity
  - Protobuf breaking-change detection

The installed pre-push wrapper invokes the pinned Lefthook binary with `--force`, so every pre-push job above runs
on a normal push even when its configured glob does not match the change. Before invoking Lefthook, the wrapper
unsets `LEFTHOOK`, `LEFTHOOK_BIN`, `LEFTHOOK_VERBOSE`, `LEFTHOOK_CONFIG`, and `LEFTHOOK_EXCLUDE`. Those variables
therefore cannot disable a push that reaches the wrapper. There is no `SKIP_PREPUSH` override or branch-name skip.

Hooks remain client-side. `git push --no-verify` bypasses the pre-push hook completely, before the wrapper can run;
no client-side wrapper can prevent that. Use it only as a deliberate exception, knowing that it skips all local
pre-push checks and leaves the hosted checks to catch failures.

Pre-push is not a 30 to 60 second check. Measured full runs took about 180 seconds with warm caches and 420 seconds
with cold caches. Strict dead-code analysis accounted for about 270 seconds of the cold run.

GitHub Actions uses `.github/workflows/checks.yml` for lint, commitlint, and pre-push parity; its `changes` job
change-gates every lane through `ci-checks gate` (dependency-graph package scoping, fail-closed on unmapped files)
and records the verdict in the run's step summary. Container builds and pushes live in
`.github/workflows/build-push.yml`; `.github/workflows/digest-freshness.yml` probes pinned base-image digests weekly;
there is no `test.yml` workflow.

```bash
just hooks-install                # Install hooks (run once after clone)
just hooks-precommit              # Run pre-commit hooks manually
just hooks-prepush                # Run pre-push hooks manually
```

**Commit format:** Conventional Commits (`type(scope?): description`)
Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

## Code Style: Python

- **Version:** 3.14 target (3.14 minimum)
- **Linter/Formatter:** ruff (`uv run ruff check --fix --output-format=concise`); zero errors, zero `# noqa` without justification
- **Type checker:** `ty` (Astral, strict mode); no `# type: ignore`, no `Any`
- **Line length:** 120 characters
- **Never use bare `python` or `pytest`**: always `uv run python` / `uv run pytest`
- **No `uv pip install`**: edit `pyproject.toml` then `uv sync`

### Typing

```python
# PEP 695 type aliases
type UserId = str

# PEP 604 unions (not Optional/Union)
def get(id: str) -> Item | None: ...

# Modern generics
def run[T: BaseModel](output_type: type[T]) -> T: ...
```

### Modern Python Patterns (mandatory)

```python
# match-case instead of if-elif chains
match status:
    case Status.ACTIVE: handle_active()
    case _: handle_unknown()

# Walrus operator to reduce nesting
if user := await get_user(uid):
    return user

# TaskGroup for 2+ concurrent tasks (NOT asyncio.gather)
async with asyncio.TaskGroup() as tg:
    t1 = tg.create_task(fetch_a())
    t2 = tg.create_task(fetch_b())
# Single task: just await directly, never TaskGroup for one task (SonarQube S7513)

# Dict merge operators (not {**a, **b} or .update())
config = defaults | overrides
params |= extra
```

### Frozen Dataclasses

When mutating `@dataclass(frozen=True)` in tests, use `setattr()`:

```python
# ✅ CORRECT
setattr(record, "field_name", new_value)

# ❌ WRONG (raises FrozenInstanceError)
record.field_name = new_value
```

### Imports

```python
# Domain models (betterproto2 dataclasses only)
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot
from nohiki.common.v1 import EventMetadata
from nohiki_domain_utils import BetterprotoEnumAdapter, parse_enum_string

# ❌ FORBIDDEN
from nohiki_grpc_stubs import listing_pb2      # No gRPC stubs
from google.protobuf import timestamp_pb2       # Use datetime directly
```

### Docstrings

All public functions/classes must have Google-style docstrings with Args/Returns/Raises sections.
Type hints go in the signature, not duplicated in docstrings. Private helpers are optional.

### Build Backend

All workspace packages must use the canonical `[build-system]` stanza:

```toml
[build-system]
requires = ["uv_build>=0.11.7,<0.12"]
build-backend = "uv_build"
```

**Rules:**

- `uv_build` is the only permitted backend. No `hatchling`, no `setuptools`.
- The pin must match exactly. Bump both the constant in
  `scripts/ci/src/ci_checks/checks/build_backend.py` (`CANONICAL_REQUIRES`) and
  every package's `pyproject.toml` in a single change.
- Never carry `[tool.hatch.*]` or `[tool.setuptools.*]` tables in a migrated
  package. uv_build uses the src layout by default with zero additional
  configuration.
- Workspace members that are intentionally never built (e.g. the `tests/`
  integration package) simply omit `[build-system]` entirely.

**Exceptions (require explicit `[tool.uv.build-backend]`):**

- Namespace packages (e.g. `nohiki-domain-models`): use
  `module-name = "nohiki"` and `namespace = true`, with no `__init__.py`
  at `src/nohiki/`.
- Non-standard module names where normalisation does not match the desired
  module (rare).

**Enforcement:** `just hygiene-build-backend` reports migration progress and
fails on drift (packages already on uv_build diverging from the canonical
stanza, or carrying residue from superseded `[tool.hatch.*]` /
`[tool.setuptools.*]` sections). `just hygiene-build-backend-strict` also
fails on any package not yet migrated to uv_build. Wire this
into `just hygiene` once the rollout is complete.

### Exceptions

Use typed exceptions from `nohiki-common-exceptions`:

| Exception | Retry | When |
|-----------|-------|------|
| `DataNotAvailableError` | Exponential backoff | Temporary unavailability |
| `DataNotFoundError` | No retry → DLQ | Data doesn't exist |
| `ExternalServiceError` | Exponential backoff | External API failure |
| `RateLimitedError` | Linear backoff | Rate limited |
| `ValidationError` | No retry → DLQ | Invalid input |

## Code Style: TypeScript / Frontend

- **Linter/Formatter:** Biome (NOT ESLint/Prettier), `npx biome check --fix`
- **Framework:** React 19 + TypeScript strict mode
- **Styling:** Tailwind CSS v4, Shadcn/ui (new-york style, neutral color, CSS variables)
- **State:** Zustand + TanStack Query
- **Routing:** TanStack Router v1 (file-based routing, `routeTree.gen.ts`)
- **Testing:** Vitest + Testing Library
- **Build:** Vite 7.x
- **Package manager:** pnpm (NOT npm/yarn)
- React Compiler handles memoization; do NOT add manual `memo`/`useMemo`/`useCallback`
- Import aliases: `@/`, `@features/`, `@entities/`
- Feature-Sliced Design architecture: `app/`, `pages/`, `widgets/`, `features/`, `entities/`, `shared/`

## Architectural Principles

### Event-Driven Communication (MANDATORY)

**The "No Lookup" Rule:** Services MUST NOT make HTTP/gRPC calls to other internal services.

- ✅ Kafka events, S3, external APIs
- ❌ HTTP/gRPC between internal services

**Event-Carried State Transfer (ECST):** Events carry all necessary data. Services maintain
local snapshot ledgers instead of cross-service queries.

### Kafka Conventions

**Topic naming:** `{domain}.{classification}.{event-name}.v{version}`

| Classification | Purpose | Example |
|---------------|---------|---------|
| `cdc` | Change Data Capture (state with ECST snapshot) | `user-pref.cdc.pref-created.v1` |
| `cmd` | Command (request expecting callback) | `ml.cmd.embedding-requested.v1` |
| `sys` | Internal service events / callbacks | `job-correlation.sys.embedding-callback.v1` |
| `fct` | Immutable fact / artifact | `job-listing.fct.created.v1` |

Common patterns: `cmd` + `sys` for request/callback pairs; `cmd` + `fct` for command producing
an artifact; `cdc` for state propagation via transactional outbox.

Full topic registry: `backend/libs/nohiki-kafka-client/src/nohiki_kafka_client/topics.py`

**Consumer group naming:** `{service-short}-{responsibility}-{priority}`
(e.g., `job-correlation-embedding-primary`).
Every `@kafka_client.message_handler` **must** specify an explicit `group_id`.

### ML Compute (Event-Driven)

All ML operations route through `ml-gateway-service` via Kafka. Services publish
`ml.cmd.embedding-requested.v1` with a `callback_topic`; the gateway routes to Kubernetes
or Modal compute; the worker publishes results back to the callback topic.

Use `nohiki-embedding-client` for embedding requests (see `backend/libs/nohiki-embedding-client/`).

### Large Text Handling

Never embed text >1MB in Kafka events. Store in S3, pass `storage_key` + `content_hash`:

- Full text: `raw_texts/{entity_type}/{entity_id}/{content_hash}.txt`
- ColBERT tokens: `colbert_tokens/{entity_type}/{entity_id}/{content_hash}.npz`

### Embedding Staleness

Always check BOTH `content_hash` AND `collection_version` when determining if embeddings
are stale. Checking only `content_hash` misses encoding manifest changes.
See `backend/libs/nohiki-ml-manifest/` for details.

## Domain Model Imports

Use `nohiki` package (betterproto2 dataclasses), NOT `_pb2` imports:

```python
from nohiki.job.listing.v1 import ListingCreated, ListingSnapshot
from nohiki.common.v1 import EventMetadata

# ❌ FORBIDDEN: _pb2 imports, google.protobuf imports
```

Protobuf workflow: edit `.proto` in `proto/nohiki/` → `just proto-gen` → dataclasses appear
in `backend/libs/nohiki-domain-models/src/nohiki/`

**Field evolution rules:**

- When **removing** a field, add a `reserved` declaration for both its tag number and its
  name to prevent future reuse:

  ```proto
  message Listing {
    reserved 7;
    reserved "location_raw";
    // ...
  }
  ```

- When **changing a field's type**, allocate a new tag number rather than mutating the
  existing one. Reusing a tag with a different wire type silently corrupts decoders that
  still hold the old schema. Reserve the old tag/name and add the replacement at a fresh
  number. The recent `location_raw` (string) → `location` (Location message) migration on
  `ListingSnapshot` is the canonical example: the original `location_raw` tag was
  reserved and the structured `location` field added at a new tag.
- `just proto-breaking` runs the buf breaking-change check against `main` and is enforced
  in pre-push hooks when `.proto` files are touched.

### JSONB Storage Pattern

```python
# Store: .to_dict() on betterproto2 objects
data = snapshot.to_dict()

# Load: .from_dict() from JSONB
snapshot = ListingSnapshot.from_dict(data)

# ❌ FORBIDDEN: custom converter functions (betterproto2 handles serialization natively)
```

## Service Structure

Each service follows the **src layout**:

```text
backend/services/<service-name>/
├── src/<service_name>/
│   ├── main.py              # FastAPI app, lifespan, startup/shutdown
│   ├── core/
│   │   ├── config.py        # Pydantic settings
│   │   └── kafka.py         # kafka_client singleton
│   ├── events/handlers.py   # Kafka message handlers
│   ├── db/models.py         # SQLAlchemy models
│   └── services/            # Business logic
├── alembic/                 # Database migrations
├── tests/
└── pyproject.toml
```

Service initialization must follow conventions in `backend/libs/nohiki-fastapi-utils/`.
See any service's `main.py` for canonical lifespan, health probes, and metrics wiring.

## Key Patterns

### Kafka Message Handler

```python
# core/kafka.py (each service creates its own kafka_client singleton)
from nohiki_kafka_client import create_kafka_client
kafka_client = create_kafka_client(get_settings())

# events/handlers.py
@kafka_client.message_handler(
    Topics.JOB_LISTING_CREATED,
    ListingCreated,
    group_id="my-service-handler-primary",  # REQUIRED
)
async def handle_listing_created(message: ListingCreated, _context: MessageContext) -> None:
    # _context prefix = unused; context = used (e.g., context.publish())
    snapshot = message.listing_snapshot
    await process_listing(snapshot)
```

`create_kafka_client` defaults to `auto_start_consumers=False`, so callers must call
`start_consumers()` explicitly in service startup.

`max_concurrent_handlers` (default: 10, range 1-200) set per-service via
`KAFKA__CONSUMER__MAX_CONCURRENT_HANDLERS`. Tune per workload: CPU-bound (ML) 1-2;
I/O-bound (DB projections) 15-20.

### Transactional Outbox + Debezium CDC

All CDC events use the outbox pattern for atomic DB + Kafka publishing:

```python
await outbox.write_event(db=db, params=OutboxEventParams(...), event=event)
await db.commit()  # Both committed atomically; Debezium captures from WAL
```

### Embedding Client Pattern

```python
from nohiki_embedding_client import EmbeddingClient

client = EmbeddingClient(
    callback_topic="my-service.sys.embedding-callback.v1",
    service_name="my-service",
    collection_version="v1",
)

@kafka_client.message_handler(
    "my-service.sys.embedding-callback.v1",
    EmbeddingCallback,
    group_id="my-service-embedding-callback-primary",
)
async def handle_completed(msg: EmbeddingCallback, ctx: MessageContext) -> None:
    await client.handle_completed(msg, ctx)
```

### Database Utils

```python
from nohiki_db_utils import DatabaseDependencies
db_deps = DatabaseDependencies(settings.database, outbox_schema=settings.database.schema_name)
```

### Convergence Saga Pattern

Some services must wait for multiple async events before publishing a downstream event.
The saga primitives in `nohiki-db-utils.saga` (`SagaBaseMixin`, `SagaRepository`,
`StaleSagaDetector`) provide a generic table-backed convergence pattern with optimistic
locking, status state machine, and stale-row sweeping.

Two services use this pattern today:

- **`ListingIngestSaga`** (job-storage-service): tracks the lifecycle of a discovered
  listing from `ListingDiscovered` through enrichment to the canonical `listings` row.
- **`EnrichmentEmbeddingSaga`** (job-ingest-enrichment-service): waits for the retrieval,
  title, and skills embedding callbacks to converge before publishing
  `EnrichmentCompleted`.

#### Listing Ingest Saga Lifecycle

The listing ingest saga uses a partial unique index on `listing_url WHERE status = 'PENDING'`
so only one in-flight saga per URL can exist, while completed/expired rows remain queryable
for auditing.

1. Discovery publishes `ListingDiscovered` for a scraped URL.
2. job-storage-service inserts a `listing_ingest_saga` row with `status='PENDING'`. The
   saga's UUID becomes the canonical `listing_id` carried through the rest of the chain.
3. job-storage-service publishes `ListingAccepted` anchored to `saga.id`.
4. job-ingest-enrichment-service consumes `ListingAccepted`, runs LLM enrichment + skill
   normalization + embeddings (via its own `EnrichmentEmbeddingSaga`), then publishes
   `EnrichmentCompleted`.
5. job-storage-service consumes `EnrichmentCompleted`, transitions the saga to `COMPLETED`,
   and INSERTs the canonical `listings` row with `id = saga.id` in the same transaction.
6. job-storage-service publishes `ListingCreated` via the outbox.

The canonical `listings` table only ever sees rows that have already been enriched,
so its NOT NULL constraints on structured location and validated description hold without
needing pre-enrichment placeholder data.

#### Stale Saga Sweep

`StaleSagaDetector.run(db)` runs periodically and transitions sagas past `expires_at`
from `PENDING → EXPIRED` (24h TTL for `ListingIngestSaga`, 30 min for
`EnrichmentEmbeddingSaga`). The partial unique index on PENDING rows lets re-discovery
of the same URL create a fresh saga without conflicting with expired rows.

## Shared Libraries

All libraries are in `backend/libs/`. The repository layout above lists them with descriptions.
Services depend on them via workspace references:

```toml
# In service pyproject.toml
dependencies = [
    "nohiki-kafka-client==0.1.0",
    "nohiki-db-utils[async,migrations,otel]==0.1.0",
    "nohiki-observability[fastapi,httpx,sqlalchemy]==0.1.0",
]
```

## BFF Service (Backend-for-Frontend)

The BFF is the single API gateway for the frontend, using CQRS with projection tables.

**API routes:**

```text
/api/v1/session            - Current user identity (from JWT)
/api/v1/account            - User account info
/api/v1/profiles           - Job target profiles
/api/v1/attachments        - Uploaded documents
/api/v1/schema-families    - Document schemas
/api/v1/template-families  - Document templates
/api/v1/documents          - Document generation tracking
/api/v1/listings           - Job listings (with FTS)
/api/v1/correlations       - Job match correlations and feedback
/api/v1/skills             - Canonical skills (with FTS)
/api/ping                  - Health check
```

**Write operations** publish commands to Kafka and return `202 Accepted` with `request_id`.
**Read operations** query local projection tables (NOT domain services).
Projections are updated via Kafka CDC/fct event handlers maintaining eventual consistency.

## Service Kafka Roles

| Service | Produces | Consumes | Pattern |
|---------|----------|----------|---------|
| user-auth-service | `user-auth.cdc.*` | (none) | Outbox writer |
| user-pref-service | `user-pref.cdc.*` | account-deleted, skill/embedding callbacks, commands | Command → CDC |
| user-upload-service | `user-upload.cdc.*` | account-deleted, commands | Command → CDC |
| user-entitlement-service | `user-entitlement.cdc.*` | account-updated/deleted | CDC |
| job-storage-service | `job-listing.*` | `job-ingest.fct.*`, backfill commands | Saga + Dedup + CDC |
| job-ingest-discovery-service | `job-ingest.fct.listing-discovered` | discovery commands | Discovery |
| job-ingest-enrichment-service | `job-ingest.fct.enrichment-completed` | `job-listing.fct.accepted`, callbacks | LLM enrichment |
| job-ingest-schedule-service | `job-ingest.cmd.discovery-requested` | schedule-tick, `job-query.cdc.*` | Scheduled commands |
| job-query-composition-service | `job-query.cdc.*` | user-pref, entitlement, auth events | ECST consumer |
| job-correlation-evaluation-service | `job-correlation.cdc.*` | listings, prefs, feedback, backfill | ECST consumer |
| skill-graph-service | `skill.fct.*`, ML commands | `skill.cmd.*`, embedding callbacks | Normalizer |
| doc-template-service | `doc-template.cdc/fct.*` | `doc-template.cmd.*` | Command → CDC |
| doc-content-service | `doc-content.fct.*` | `doc-content.cmd.*`, correlations | LLM generation |
| doc-process-service | `doc-process.fct.*` | `doc-process.cmd.*` | Document processing |
| notification-service | `notification.fct.*` | correlations, doc-content | Template-driven |
| bff-service | Commands (`*.cmd.*`) | All CDC/fct for projections | CQRS projections |
| ml-gateway-service | `ml.sys.*` | `ml.cmd.*` | Router |
| ml-compute-service | Callback topics | `ml.sys.kubernetes-compute` | Compute worker |

## Testing Best Practices

- Use `just test-all-packages` for monorepo-wide runs (prevents import collisions)
- Mark integration tests `@pytest.mark.integration`, Docker tests `@pytest.mark.requires_docker`
- Use `nohiki-test-utils` for shared fixtures
- Test desired behavior based on design intent; if code is wrong, fix the code first
- Never weaken or delete tests to make them pass
- Use `setattr()` to mutate frozen dataclass fields in tests (direct assignment raises `FrozenInstanceError`)
- For bot-managed dependencies, test observable contracts: dependency identity, immutable pin shape,
  required major-version capabilities, and parity between duplicate consumers. Derive or compare
  current values instead of copying updater-managed SHAs or versions. Permit an exact current value
  only as an explicit manual compatibility or security-review gate whose test names the
  version-specific invariant to revalidate when the pin moves.

## E2E Testing

API contract tests in `tests/api/` test the full system via BFF. Playwright browser tests
in `typescript/apps/frontend/e2e/` use journey-based specs with Page Object Model.

```bash
just test-api      # API contract tests
just test-e2e      # Playwright browser tests
just test-all-e2e  # Both
```

## Service-Specific Notes

- **user-auth-service**: RS256 JWT with JWKS at `/.well-known/jwks.json`; HttpOnly cookies; producer-only (no Kafka consumers)
- **skill-graph-service**: Skill normalization/deduplication; canonical skill graph + aliases; Qdrant for skill similarity
- **job-correlation-evaluation-service**: ML scoring pipeline; snapshot ledgers from ECST; L2R features + FeatureComposer
- **doc-template-service**: Gotenberg PDF generation; seeds default templates with distributed lock; S3 storage
- **notification-service**: Template-driven; token bucket rate limiting; Resend/SendGrid; outbox + worker
- **doc-content-service**: LLM resume/cover letter generation; consumes generation commands + correlations

## Development Workflow

1. Make changes to service or shared library
2. `just fix` (lint and format)
3. `just typecheck-all` or `just typecheck <service>` (type check)
4. `just test <service>` or `just test-all-packages` (run tests)
5. Commit (hooks auto-run ruff, Biome, markdownlint, buf lint, gitleaks, actionlint, and hadolint)
6. Push (hooks auto-run ty, pytest, hygiene, strict deadcode, backend build checks, and proto breaking)

## Important Notes

- **No `type: ignore`**: fix the actual type issue
- **No `Any`**: use specific types, generics, or protocols
- **No `{**a, **b}` dict merge**: use `a | b`
- **No `asyncio.gather` for 2+ tasks**: use `asyncio.TaskGroup`
- **No TaskGroup for a single task**: just `await` directly (SonarQube S7513)
- **No raw `pytest` or `python`**: always `uv run pytest` / `uv run python`
- **No `uv pip install`**: edit `pyproject.toml` + `uv sync`
- **No build backends other than `uv_build`**: canonical `[build-system]` stanza enforced by `just hygiene-build-backend`
- **No secrets committed**: use `infra/shared/secrets/` (gitignored)
- **Never commit ignored local scratch state**
- **No `_pb2` imports**: use `from nohiki.domain.v1 import ...` (betterproto2)
- **Qdrant lifecycle-owner direct writes**: application-data mutations use `nohiki-qdrant-client`
  in the entity lifecycle owner only (jobs → `job-storage-service`, profiles → `user-pref-service`,
  skills/occupations → `skill-graph-service`). Collection/index/alias bootstrap remains infra/admin.
  Do not add new Qdrant Kafka Sink Connector usage.

## Further Reference

For detailed domain-specific information beyond this guide:

- **Kafka topics**: Full topic registry in `backend/libs/nohiki-kafka-client/src/nohiki_kafka_client/topics.py`
- **Observability**: OTel, structured logging, Prometheus metrics, Grafana dashboards (`backend/libs/nohiki-observability/`)
- **ML pipeline**: 4-stage scoring (MUVERA ANN → ColBERT MaxSim → LLM Rerank → L2R), LightGBM LambdaMART (`backend/services/job-correlation-evaluation-service/`)
- **ML encoders**: ColBERT, MUVERA, sparse encoders (`backend/libs/nohiki-ml-core/`)
- **Embedding manifests**: Semantic representation IDs (`backend/libs/nohiki-ml-manifest/`)
- **LLM client**: PydanticAI agent, retry, cost tracking, caching, eval framework (`backend/libs/nohiki-llm-client/`)
- **FastAPI conventions**: Health probes, JWT, CSRF, rate limiting, canonical service init (`backend/libs/nohiki-fastapi-utils/`)
- **Container images**: `nohiki-{service-name}:latest` naming; `just build <service>` / `just build-all`
