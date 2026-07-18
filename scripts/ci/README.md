# CI Checks (`ci-checks`)

Unified CI/CD hygiene tooling as a proper uv workspace package with a Typer CLI hub.

## Usage

```bash
# Dependency hygiene
just hygiene-deps                  # All packages
just hygiene-deps-backend          # Services only
just hygiene-deps-libs             # Libraries only

# Dead code detection (Skylos)
just hygiene-deadcode              # Report mode
just hygiene-deadcode-strict       # Hard failure gate
just hygiene-deadcode-llm          # LLM hybrid verification

# Unused pytest fixtures
just hygiene-fixtures              # Report mode
just hygiene-fixtures-strict       # Hard failure gate
just hygiene-fixtures-services     # Services only
just hygiene-fixtures-libs         # Libraries only

# Parallel test runner
just test-all-packages             # All packages
just test-backend-packages         # Services only
just test-libs-packages            # Libraries only
```

## Direct invocation

```bash
# All commands via entry point (after `uv sync`)
uv run ci-checks --help
uv run ci-checks deadcode --scope all --ci
uv run ci-checks deptry --scope services
uv run ci-checks fixtures --scope all --ci --fail
uv run ci-checks tests all --scope all --ci
uv run ci-checks tests affected --mode push
```

## Package structure

```text
ci_checks/
├── app.py               # Typer hub (deadcode, deptry, fixtures + tests sub-app)
├── core/
│   ├── packages.py      # PackageType, Scope, Package, load_packages: single source of truth
│   ├── scanner.py       # Generic scan_parallel() with asyncio.TaskGroup
│   └── display.py       # Console singleton + Rich summary helpers
└── checks/
    ├── deadcode.py      # Skylos dead code detection
    ├── deptry.py        # Dependency hygiene (deptry)
    ├── fixtures.py      # Unused pytest fixture detection
    └── tests.py         # Parallel test runner (affected + all sub-commands)
```

## Features

- **Parallel execution** with configurable worker count (`--workers`)
- **Live TUI** with Rich progress bars (suppressed in `--ci` mode)
- **TaskGroup-based** concurrency: exceptions surface immediately
- **Affected package detection** (test runner) -- git staged/push diff with transitive dependency expansion
- **Coverage gating** (test runner) -- per-file and per-module thresholds with `--strict`
