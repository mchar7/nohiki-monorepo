# Tests

Monorepo-level pytest and browser test entry points live here. Package unit tests stay with the
package that owns the code.

## Layout

```text
tests/
├── api/              # BFF API contract tests and HTTP client helpers
├── integration/      # Cross-service pytest tests
├── utils/            # Shared test helpers
├── conftest.py       # Root pytest fixtures
└── pyproject.toml    # Test package and pytest config
```

Frontend browser journeys live in `typescript/apps/frontend/e2e/`.

Backend package tests live under the owning package, for example
`backend/services/*/tests/`, `backend/libs/*/tests/`, and `backend/jobs/*/tests/`.

## Just commands

Run from the repo root.

```bash
just test-api                     # tests/api
just test-integration             # tests/integration
just test-all-e2e                 # API contract tests, then Playwright
just test-e2e                     # Playwright journeys
just test-e2e-ui                  # Playwright UI
just test-e2e-debug               # Playwright debugger
just test-e2e-report              # Show the Playwright report
just test-e2e-journey smoke       # One Playwright journey
just test-all-packages            # Package-aware backend tests
just test-backend-packages        # Backend service package tests
just test-libs-packages           # Backend library package tests
just test <package-name>          # One backend package
```

## Direct commands

```bash
uv run --package nohiki-integration-tests pytest tests/api --tb=short
uv run --package nohiki-integration-tests pytest tests/integration --tb=short
pnpm --filter nohiki-frontend run test:e2e
pnpm --filter nohiki-frontend test
```

## API contract tests

`tests/api/` uses pytest plus the `NohikiClient` wrapper in `tests/api/client.py`. The suite hits
the BFF over HTTP. Configuration lives in `tests/api/config.py`, and fixtures live in
`tests/api/conftest.py`.

Use `session_client` for authenticated API calls and `fresh_client` for unauthenticated auth-flow
coverage.

## Integration tests

`tests/integration/` covers cross-service behavior with pytest and testcontainers. The test
package config in `tests/pyproject.toml` sets pytest test paths to `integration` and `api`.

## Playwright tests

The Playwright config is `typescript/apps/frontend/e2e/playwright.config.ts`. Journey specs live
in `typescript/apps/frontend/e2e/journeys/`, page objects in `typescript/apps/frontend/e2e/pages/`,
and helpers in `typescript/apps/frontend/e2e/utils/`.

Install browsers if Playwright cannot launch Chromium:

```bash
pnpm --filter nohiki-frontend exec playwright install
```

## Local services

API and browser tests expect the backend stack to be reachable. Start the local compose stack
before running tests that call live services:

```bash
just compose-up
```

`E2E_BASE_URL` defaults differ by runner. Set it explicitly when targeting a non-default BFF URL.
