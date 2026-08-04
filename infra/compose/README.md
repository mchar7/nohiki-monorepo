# Local stack (Compose)

Everything Nohiki needs to run locally: the backend services, Kafka, and the data stores, orchestrated with
Docker Compose or Podman Compose. The service inventory lives in the [root README](../../README.md).

## Bring it up

From the repo root:

```bash
cp infra/compose/.env.example infra/compose/.env   # non-secret config; adjust as needed
just compose-up
just compose-health
```

`just compose-up` and `just infra-up` use one fail-closed wrapper invocation to render Compose, validate provider endpoints
and the file-secret contract, start from that exact mode-`0600` render, and remove it afterward. This prevents configuration
changes between validation and startup. Run the validation phase alone with `just compose-preflight`.

The wrapper deliberately exposes only this action grammar: no arguments (validation/status),
`up [-d|--detach] [--build] [SERVICE ...]`, `run --rm [-e|--env REFRESH_REASON=VALUE] SERVICE [COMMAND ...]`,
`build [SERVICE ...]`, `down [-v|--volumes]`, and `logs [-f|--follow] [SERVICE ...]`. `up` always adds
`--force-recreate`; `run` first recreates its service and dependencies from the validated render. Full `config` output,
container-reusing lifecycle actions, dependency skipping, arbitrary environment injection, and alternate Compose files are
rejected.

`just` recipes respect `CONTAINER_RUNTIME` (`docker` or `podman`). Secrets are not in `.env`: they live as files
under `infra/shared/secrets/` and mount read-only into `/run/secrets/<category>/` in the containers that need
them. See [`infra/shared/secrets/README.md`](../shared/secrets/README.md) for provisioning.

LLM provider endpoints require HTTPS by default. A local proxy that exposes only HTTP requires the explicit
`NOHIKI_ALLOW_HTTP_LLM_LOCAL=1` opt-in in this checkout's `.env`; validation resolves the endpoint and accepts it only
when every address is loopback or RFC1918. The opt-in never permits plaintext transport to an external address.

### Isolated startup and profiles

For dependency work that does not need application containers, start only the stateful platform with
`just infra-up`. The normal `just compose-up` starts the complete application stack. Optional tools stay
isolated behind explicit profiles: `dev` (pgAdmin and Kafka UI), `tools` (one-shot jobs), `mlops`, and
`observability`. Use the same validated wrapper for a profile, for example
`COMPOSE_PROFILE=dev sh infra/compose/scripts/preflight.sh up -d`.

Compose scopes container, network, and volume names to `COMPOSE_PROJECT_NAME` (default `nohiki`). Set a distinct project
name for a disposable checkout or configuration test; its resources will not collide with another Nohiki project. Every
host-published port is overrideable via `NOHIKI_PORT_*` (and the bind interface via `NOHIKI_HOST_IP`), so two complete
stacks can listen concurrently by selecting disjoint port sets in each checkout's `.env`. Advertised URLs
(`NOHIKI_PUBLIC_API_URL`, `NOHIKI_S3_PUBLIC_URL`, `NOHIKI_FRONTEND_ORIGIN`) default to `localhost` on those ports and
track any remap. See `.env.example` for the full list and defaults.

`just compose-health` runs the health-check CLI against the live stack and validates containers, HTTP surfaces,
Kafka, and the data stores end to end. Other useful recipes: `just logs <service>`, `just compose-down`,
`just snapshot-refresh` (rebuilds ECST projections).

## What listens where

| Endpoint | Port |
| --- | --- |
| Traefik (API gateway; routes BFF + auth only) | `8000`, `8443` |
| PostgreSQL | `5432` |
| pgAdmin | `5050` |
| Kafka (external listener) | `29092` |
| Kafka UI | `8082` |
| Kafka Connect | `8083` |
| Valkey | `6379` |
| RustFS (S3 API / console) | `9002` / `9003` |
| Qdrant (REST / gRPC) | `6333` / `6334` |
| MLflow | `5000` |
| Gotenberg | `3000` |
| Docling | `5001` |

The frontend is not part of the stack; run it with `pnpm --filter nohiki-frontend dev` (port `5173`, proxying
`/api` to Traefik).

BFF API docs: <http://localhost:8000/api/docs>. Auth docs: <http://localhost:8000/api/v1/auth/docs>. Traefik routes
only those edge APIs; other services keep internal HTTP readiness and metrics surfaces on the private Compose network.

## Observability

The observability stack is a second compose file. Start it through the validated wrapper so the merged render is the
configuration that actually runs:

```bash
COMPOSE_PROFILE=observability COMPOSE_OVERRIDE_FILE=docker-compose.observability.yml \
  sh infra/compose/scripts/preflight.sh up -d
```

That adds the OTel collector (`4317`/`4318`), Grafana (`3001`, `admin`/`admin`), Prometheus (`9090`), Loki,
Tempo, Mimir, Pyroscope, and Phoenix (`6006`, LLM traces). Grafana ships provisioned datasources and seven
dashboards (overview, services, database, infrastructure, LLM, providers, skill canonicalization); no manual
setup. The app runs fine without any of this.

## Data and resets

Postgres bootstrap idempotently creates dedicated non-superuser `mlflow` and `phoenix` database owners on every startup,
including when reusing an existing Postgres volume. Their generated local credentials persist in
`${COMPOSE_PROJECT_NAME}_nohiki-vol-postgres-service-secrets`; Compose injects them from files and
verifies both connections before dependents start.
Application schemas remain owned by the services themselves (Alembic). State persists in project-scoped named volumes
such as `${COMPOSE_PROJECT_NAME}_nohiki-vol-postgres`. Full reset of the selected Compose project:

```bash
CONTAINER_RUNTIME=podman sh infra/compose/scripts/preflight.sh down --volumes
just compose-up
```

## Rebuilding a service

Code changes need an image rebuild:

```bash
CONTAINER_RUNTIME=podman sh infra/compose/scripts/preflight.sh up -d --build nohiki-svc-doc-content
```

Container names follow `nohiki-svc-*` for services, `nohiki-job-*` for jobs, `nohiki-infra-*`/`nohiki-cp-*`/
`nohiki-obs-*` for infrastructure, Kafka, and observability.
