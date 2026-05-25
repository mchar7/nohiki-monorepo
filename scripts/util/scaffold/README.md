# nohiki-scaffold

Monorepo-compliant scaffolder for Nohiki backend services and shared libraries.
Emits canonical `uv_build` packages, wires them into the workspace, and runs
post-apply static checks, so a freshly scaffolded package passes `ruff`,
and `pytest --collect-only` without manual edits.

## Non-goals

The scaffolder has a **closed feature matrix**. It does NOT support:

- **Update-in-place.** Create-only; three-way merging is a maintenance sinkhole.
- **Plugin hooks or user templates.** The template set is curated; archetypes
  extend the codebase, not user config.
- **Auto-editing CODEOWNERS, docker-compose, Helm charts, or `AGENTS.md`.**
  These are emitted as Rich hints at the end of a scaffold run and left for
  human review.

Paved-road enforcement. If you need a new archetype, add it to the template set
rather than bolting on an escape hatch.

## Install

The CLI ships as a workspace member. After cloning the monorepo:

```bash
uv sync --package nohiki-scaffold
```

This installs the `nohiki-scaffold` console script.

## Quick start

### Scaffold a kafka-only consumer service with database + outbox

```bash
just new-service \
    --name skill-tagger-service \
    --description "Tags ingested listings with canonical skills." \
    --owner platform \
    --shape kafka-only \
    --kafka-role consumer-only \
    --handler commands \
    --db --outbox --alembic \
    --non-interactive --yes
```

### Scaffold a plain library

```bash
just new-lib \
    --name nohiki-demo-utils \
    --description "Shared demo utilities." \
    --owner platform \
    --non-interactive --yes
```

### Preview without writing

```bash
just preview-service --name demo --shape kafka-only --kafka-role consumer-only --non-interactive
just preview-lib --name nohiki-demo --non-interactive
```

`preview` is always dry-run; it renders the full build plan (files, workspace
edits, hints) without touching the filesystem.

## Flags vs interactive

Every command supports three modes:

| Mode | Trigger | Behaviour |
|------|---------|-----------|
| Interactive | default | Rich prompts walk through the spec; missing flags are asked for |
| Non-interactive | `--non-interactive` | All required values must come from flags; prompts are suppressed |
| Config-file | `--config-file spec.toml` | Load spec from TOML; flags override file values |

Run `uv run nohiki-scaffold new service --help` for the full flag surface.

## `--config-file` format

Specs can be checked in as TOML for reproducible scaffolding (useful when a
scaffold spec is PR-reviewed before any code lands).

**Service spec (`my-service.toml`):**

```toml
name = "my-service"
friendly_name = "My Service"
description = "Example service."
owner = "platform"
shape = "kafka-only"
env_prefix = "MY_SERVICE_"
module_name = "my_service"

[database]
enabled = true
schema_name = "my_service_schema"
outbox = true
alembic = true

[kafka]
role = "consumer-only"
handlers = ["commands"]
embedding_callback = false
max_concurrent_handlers = 10

[redis]
enabled = false

[s3]
enabled = false

[ml]
manifest = false
service_holder_pattern = false
fail_fast_validation = false

[ml.llm]
enabled = false

[ml.qdrant]
enabled = false
```

**Library spec (`nohiki-demo.toml`):**

```toml
name = "nohiki-demo"
description = "Demo library."
owner = "platform"
module_name = "nohiki_demo"
ships_testing_module = false
ships_exceptions_module = false
ships_console_script = false
namespace_package = false
```

Apply:

```bash
just new-service --config-file my-service.toml --non-interactive --yes
```

## Post-apply verification

After a scaffold run, the CLI invokes a verification pipeline against the new
package. `--verify-mode` selects behaviour:

- `default` (implicit): runs `uv sync --package <name>`, `ruff check`,
  `ruff format --check`, `ty check`, and `pytest --collect-only`
- `full`: DEFAULT plus `pytest` (actually executes tests)
- `none`: skip all post-apply checks (fast path for CI pipelines that
  already run their own gates)

Each check's exit code and timing is rendered as a Rich table.

## Git dirty guard

By default, the CLI refuses to scaffold into a working tree with uncommitted
changes. A partial scaffold plus pre-existing edits is a recipe for a messy
revert. Override with `--yes`. CI jobs that start from a clean checkout can use
`--yes` without risk.

## Regenerating goldens / invariant tests

The scaffolder's own test suite uses **invariant assertions** rather than
byte-for-byte snapshots. Tests under `tests/goldens/` render canonical archetype
specs and assert semantic invariants (mixin order, shutdown order, canonical
parameterized integration values), so template edits only break
tests when they break meaning, not cosmetics.

When you intentionally change a canonical pattern, update the invariants in
`tests/goldens/test_invariants.py` alongside the template change.

Run the scaffolder's full test suite:

```bash
just test-scaffold
```

## Architecture

```text
scripts/util/scaffold/
├── src/nohiki_scaffold/
│   ├── cli/
│   │   ├── app.py             Typer app root
│   │   ├── commands/          new service / new lib / preview
│   │   ├── prompts.py         Interactive spec builders
│   │   ├── display.py         Rich renderers (panels, tables, hints)
│   │   └── formatting.py      Formatting helpers
│   ├── core/
│   │   ├── models/            Per-concern spec dataclasses (SRP)
│   │   │   ├── _validation.py Regex + validator helpers
│   │   │   ├── database.py    DatabaseOptions
│   │   │   ├── redis.py       RedisOptions
│   │   │   ├── kafka.py       KafkaOptions
│   │   │   ├── s3.py          S3Options
│   │   │   ├── qdrant.py      QdrantOptions
│   │   │   ├── llm.py         LLMOptions
│   │   │   ├── ml.py          MLOptions (composes llm + qdrant)
│   │   │   ├── service.py     ServiceSpec
│   │   │   └── lib.py         LibSpec
│   │   ├── features.py        StrEnums (ServiceShape, KafkaRole, and related enums)
│   │   ├── exceptions.py      Typed exceptions
│   │   ├── naming.py          kebab/snake/module/schema/env_prefix helpers
│   │   ├── validators.py      Spec-vs-workspace collision checks
│   │   ├── canonical.py       Re-exports ci_checks canonical constants
│   │   ├── spec_loader.py     TOML → ServiceSpec / LibSpec
│   │   ├── build.py           BuildPlan, apply_plan (atomic writes)
│   │   ├── build_service.py   Service render context + file emission
│   │   └── build_lib.py       Library render context + file emission
│   ├── templates/
│   │   ├── loader.py          Jinja Environment (StrictUndefined + filters)
│   │   ├── lib/               Library Jinja templates
│   │   └── service/           Service Jinja templates (4 archetypes covered)
│   ├── verify/
│   │   └── runner.py          Subprocess-based post-apply checks
│   └── config/
│       ├── constants.py       Regex, size, and timeout limits
│       └── paths.py           get_repo_root() helper
└── tests/
    ├── unit/                  Data-model + validator + verify tests
    ├── goldens/               Invariant-assertion tests across 7 archetypes
    └── integration/           tmp-repo end-to-end + atomic rollback
```

## Supported archetypes

| Archetype | Shape | Kafka role | Typical flags |
|-----------|-------|-----------|---------------|
| kafka-only consumer | `kafka-only` | `consumer-only` | `--db --outbox --alembic --handler commands` |
| kafka-only producer | `kafka-only` | `producer-only` | (no DB or handler flags) |
| HTTP-only producer | `http-only` | `producer-only` | (FastAPI + JWT scaffolding) |
| HTTP + Kafka + ML | `http-and-kafka` | `both` | `--db --llm --qdrant --manifest --service-holder-pattern` |
| Plain lib | (library) | Not applicable | `just new-lib --name nohiki-demo --non-interactive --yes` |
| Namespace lib | (library) | Not applicable | `--namespace-package --module-name nohiki` |
| Lib with testing module | (library) | Not applicable | `--ships-testing-module` |

## Troubleshooting

**`WorkspaceEditError: target directory exists`**
: The target `backend/services/<name>/` or `backend/libs/<name>/` already exists.
  Delete it (and revert the root `pyproject.toml` workspace member entry) or
  choose a different name.

**`WorkspaceEditError: invalid TOML after applying edits`**
: The scaffolder validates the mutated root `pyproject.toml` via `tomllib.loads`
  before committing. If this fires, it means a tomlkit edit produced syntactically
  invalid TOML. Open an issue with the spec that triggered it.

**`FileNotFoundError: 'uv' not on PATH`**
: The verify pipeline couldn't find `uv`. Either install `uv` or pass
  `--verify-mode none` to skip post-apply checks.

**Verify step fails but scaffolded files look fine**
: Common causes: `uv sync` needs rerunning at the workspace level, or the new
  package declares a dep that isn't in `[tool.uv.sources]`. Run
  `uv sync --package <name>` manually and inspect the output.
