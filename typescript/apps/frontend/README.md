# Nohiki Frontend

React single-page app for the Nohiki web UI.

The app talks to the backend through `/api`.
In development, Vite proxies that path using `VITE_API_PROXY_TARGET`, defaulting to `http://localhost:8000`.
Compose uses Traefik for BFF and auth routes; the frontend runs separately with Vite.
Kubernetes uses kgateway for public routes. The frontend container serves static files with Caddy.

## Where things live

```text
src/
├── app/                 # App shell, providers, generated route tree, route files
│   └── routes/          # TanStack Router file routes
├── pages/               # Route-level UI
├── widgets/             # Cross-page UI sections
├── features/            # User-facing flows and local feature state
├── entities/            # Domain-level UI and types
├── shared/              # API client, UI primitives, hooks, config
├── api/schema.d.ts      # OpenAPI TypeScript schema
└── test/                # Vitest setup and mocks
```

Imports use the aliases from `tsconfig.app.json`: `@`, `@app`, `@pages`, `@widgets`,
`@features`, `@entities`, `@shared`, and `@public`.

## Backend access

`src/shared/api/client.ts` builds the typed client with `openapi-fetch` and
`openapi-react-query`. The generated OpenAPI schema lives at `src/api/schema.d.ts`.

Authentication uses HttpOnly cookies. Frontend code does not read or store raw tokens.

Regenerate the schema from the committed `docs/api/nohiki.openapi.json` document.
Set `OPENAPI_SCHEMA_URL` to generate from a live BFF instead:

```bash
pnpm generate:api
OPENAPI_SCHEMA_URL=http://localhost:8000/openapi.json pnpm generate:api
```

## Routes

TanStack Router reads route files from `src/app/routes/` and writes the generated tree to
`src/routeTree.gen.ts`. Vite enables route-level code splitting.

## Local development

Run commands from this directory unless you use a workspace filter from the repo root.

```bash
pnpm install
pnpm dev
```

The dev server listens on `localhost:5173`. Start the BFF before using screens that call `/api`.

## Commands

```bash
pnpm dev              # Vite dev server
pnpm build            # Type-check, then build
pnpm preview          # Serve the built app
pnpm type-check       # TypeScript check
pnpm check            # Biome check
pnpm check:apply      # Biome write fixes
pnpm check:all        # Type-check, Biome check, unit tests
pnpm test             # Vitest single run
pnpm test:watch       # Vitest watch mode
pnpm test:coverage    # Vitest coverage run
pnpm test:e2e         # Playwright journeys
pnpm test:e2e:ui      # Playwright UI
pnpm test:e2e:debug   # Playwright debugger
pnpm test:e2e:report  # Show the Playwright report
pnpm i18n:check       # Check locale key coverage
pnpm generate:api     # Regenerate src/api/schema.d.ts
pnpm analyze          # Build with bundle visualizer
```

## Tests

Vitest tests live beside frontend code under `src/` and use the setup files in `src/test/`.

Playwright tests live in `e2e/journeys/`. The config runs a setup project first, stores auth
state under `e2e/.output/`, starts Vite with `VITE_E2E=true`, and runs the Chromium project.
See `e2e/README.md` for page objects and journey helpers.

## Build

```bash
pnpm build
```

The build runs `pnpm type-check` and then `vite build`.
The Docker image serves the built app with Caddy.
