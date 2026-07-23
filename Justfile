# Nohiki Monorepo Task Runner
# Usage: just <recipe> [args]

set shell := ["bash", "-c"]

# Variables and settings

# Container runtime (defaults to docker to stay consistent, aliased systems work natively)
docker := env_var_or_default("CONTAINER_RUNTIME", "docker")

# Test environment defaults
k8s_e2e_url := env_var_or_default("E2E_BASE_URL", "http://localhost:8080")
monorepo_root := justfile_directory()
k8s_namespace := env_var_or_default("K8S_NAMESPACE", "nohiki")
# Local image registry endpoint: the single source of truth is
# infra/k8s/helm/values.local.yaml (global.nohikiImage.registry), read at push time
# so pushes and reconciler-rendered pulls cannot drift. Container bind settings stay overridable.
# Local OCI registry settings are environment-overridable.
registry_container_name := env_var_or_default("LOCAL_REGISTRY_NAME", "nohiki-local-registry")
registry_port := env_var_or_default("LOCAL_REGISTRY_PORT", "5000")
registry_image := env_var_or_default("LOCAL_REGISTRY_IMAGE", "registry:2")
# Stable, reused local tag (repushed in place, not immutable); must equal values.local.yaml global.imageTag. Never "latest".
dev_image_tag := env_var_or_default("DEV_IMAGE_TAG", "dev")
# Context the destructive reset may target; empty is fail-closed (no reset allowed).
k8s_local_context := env_var_or_default("K8S_LOCAL_CONTEXT", "")

# First-party release images. Release names/specs must match build-push.yml's matrix
# (all 27 rows, including verification runners and the ml-compute-service-gpu CUDA
# variant). Spec fields are name|context|dockerfile|build_args; build_args is optional
# and set only for the gpu row.
first_party_image_names := "user-auth-service user-pref-service user-upload-service user-entitlement-service job-storage-service job-ingest-discovery-service job-ingest-schedule-service job-ingest-enrichment-service job-query-composition-service job-correlation-evaluation-service skill-graph-service doc-template-service doc-content-service doc-process-service notification-service bff-service ml-gateway-service ml-compute-service ml-compute-service-gpu sys-tick-job snapshot-refresh-job qdrant-init kafka-connect frontend api-verification-runner playwright-verification-runner health-runner"
first_party_image_specs := "user-auth-service|.|backend/services/user-auth-service/Dockerfile user-pref-service|.|backend/services/user-pref-service/Dockerfile user-upload-service|.|backend/services/user-upload-service/Dockerfile user-entitlement-service|.|backend/services/user-entitlement-service/Dockerfile job-storage-service|.|backend/services/job-storage-service/Dockerfile job-ingest-discovery-service|.|backend/services/job-ingest-discovery-service/Dockerfile job-ingest-schedule-service|.|backend/services/job-ingest-schedule-service/Dockerfile job-ingest-enrichment-service|.|backend/services/job-ingest-enrichment-service/Dockerfile job-query-composition-service|.|backend/services/job-query-composition-service/Dockerfile job-correlation-evaluation-service|.|backend/services/job-correlation-evaluation-service/Dockerfile skill-graph-service|.|backend/services/skill-graph-service/Dockerfile doc-template-service|.|backend/services/doc-template-service/Dockerfile doc-content-service|.|backend/services/doc-content-service/Dockerfile doc-process-service|.|backend/services/doc-process-service/Dockerfile notification-service|.|backend/services/notification-service/Dockerfile bff-service|.|backend/services/bff-service/Dockerfile ml-gateway-service|.|backend/services/ml-gateway-service/Dockerfile ml-compute-service|.|backend/services/ml-compute-service/Dockerfile ml-compute-service-gpu|.|backend/services/ml-compute-service/Dockerfile|ML_COMPUTE_BUILDER=sync-gpu sys-tick-job|.|backend/jobs/sys-tick-job/Dockerfile snapshot-refresh-job|.|backend/jobs/snapshot-refresh-job/Dockerfile qdrant-init|.|infra/shared/qdrant-init/Dockerfile kafka-connect|infra/k8s/kafka-connect|infra/k8s/kafka-connect/Dockerfile frontend|.|typescript/apps/frontend/Dockerfile api-verification-runner|.|tests/Dockerfile.api-runner playwright-verification-runner|.|typescript/apps/frontend/Dockerfile.playwright-runner health-runner|.|scripts/util/health_check/Dockerfile"

# Local K3s deploy inventory: excludes ml-compute-service-gpu and kafka-connect, since
# neither is built or pushed for the GPU-less local cluster (local ml-compute uses the CPU image).
local_image_names := "user-auth-service user-pref-service user-upload-service user-entitlement-service job-storage-service job-ingest-discovery-service job-ingest-schedule-service job-ingest-enrichment-service job-query-composition-service job-correlation-evaluation-service skill-graph-service doc-template-service doc-content-service doc-process-service notification-service bff-service ml-gateway-service ml-compute-service sys-tick-job snapshot-refresh-job qdrant-init frontend"

# Common commands
pnpm := "corepack pnpm"
playwright := pnpm + " --filter nohiki-frontend exec playwright"
playwright_test := playwright + " test --config=e2e/playwright.config.ts"
ast_cmd := "cd scripts/util/ast_explorer && uv run ast-explorer"

# Aliases and defaults

default:
    @just --list

# Alias for lint
l: lint
# Alias for format
f: format
# Alias for sync
s: sync

# Workspace management

# Sync all workspace dependencies
sync:
    uv sync --all-packages

# Sync with all non-conflicting development extras
sync-dev:
    uv sync --all-packages --all-extras --no-extra cuda --group deadcode

# Lock dependencies without installing
lock:
    uv lock

# Update all dependencies
update:
    uv lock --upgrade

# Clean cache directories
clean:
    find . -type d \( -name "__pycache__" -o -name ".ruff_cache" -o -name ".cache" -o -name "*.egg-info" -o -name ".pytest_cache" \) -exec rm -rf {} + 2>/dev/null || true

# Deep clean including .venv (requires re-sync after)
clean-all: clean
    rm -rf .venv

# Linting and formatting

# Run both lint and format
fix: lint format

# Lint and format entire monorepo
check-all: lint fe-check lint-md

# Run ruff check with auto-fix on entire backend
lint:
    uv run ruff check --config pyproject.toml --fix --output-format=concise backend/

# Run ruff check on a specific service
lint-service service:
    uv run ruff check --config pyproject.toml --fix --output-format=concise backend/services/{{ service }}/

# Run ruff check on shared libraries
lint-libs:
    uv run ruff check --config pyproject.toml --fix --output-format=concise backend/libs/

# Format all Python files
format:
    uv run ruff format --config pyproject.toml backend/

# Format a specific service
format-service service:
    uv run ruff format --config pyproject.toml backend/services/{{ service }}/

# Lint and fix markdown files
lint-md:
    {{ pnpm }} exec markdownlint-cli2 --fix "**/*.md"
# Type checking

# Run ty on all backend code
typecheck-all:
    uv run ty check backend/ --exclude '**/alembic/**' --exclude '**/nohiki-domain-models/**'

# Run ty on a specific backend service
typecheck service:
    cd backend/services/{{ service }} && uv run --package {{ service }} ty check src/

# Run ty on a specific shared library
typecheck-lib lib:
    cd backend/libs/{{ lib }} && uv run --package {{ lib }} ty check src/

# Run ty on a job
typecheck-job job:
    cd backend/jobs/{{ job }} && uv run --package {{ job }} ty check src/

# Code hygiene

# Run all strict checks (lint + typecheck + hygiene)
check-strict: lint typecheck-all hygiene

# Run all hygiene checks
hygiene: hygiene-deps hygiene-arch hygiene-deadcode hygiene-fixtures hygiene-build-backend-strict

hygiene-deps:
    uv run --package ci-checks ci-checks deptry --scope all --ci

hygiene-deps-backend:
    uv run --package ci-checks ci-checks deptry --scope services --ci

hygiene-deps-libs:
    uv run --package ci-checks ci-checks deptry --scope libs --ci

hygiene-arch:
    uvx --override semgrep-overrides.txt semgrep scan --config semgrep.yml --error --no-git-ignore backend/

hygiene-arch-report:
    uvx --override semgrep-overrides.txt semgrep scan --config semgrep.yml --no-git-ignore backend/

hygiene-deadcode:
    uv run --package ci-checks --group deadcode ci-checks deadcode --scope all --ci

hygiene-deadcode-strict:
    uv run --package ci-checks --group deadcode ci-checks deadcode --scope all --ci --fail

hygiene-deadcode-llm:
    uv run --package ci-checks --group deadcode ci-checks deadcode --scope all --ci --llm

hygiene-fixtures:
    uv run --package ci-checks ci-checks fixtures --scope all --ci

hygiene-fixtures-strict:
    uv run --package ci-checks ci-checks fixtures --scope all --ci --fail

hygiene-fixtures-services:
    uv run --package ci-checks ci-checks fixtures --scope services --ci

hygiene-fixtures-libs:
    uv run --package ci-checks ci-checks fixtures --scope libs --ci

# Validate migrated packages against the canonical uv_build settings.
hygiene-build-backend:
    uv run --package ci-checks ci-checks build-backend --scope all --ci

# Require every buildable workspace package to use canonical uv_build settings.
hygiene-build-backend-strict:
    uv run --package ci-checks ci-checks build-backend --scope all --ci --strict

# Scaffold CLI

# Scaffold a new backend service.
new-service *ARGS:
    uv run --package nohiki-scaffold nohiki-scaffold new service {{ ARGS }}

# Scaffold a new shared library.
new-lib *ARGS:
    uv run --package nohiki-scaffold nohiki-scaffold new lib {{ ARGS }}

# Preview a service scaffold without writing files.
preview-service *ARGS:
    uv run --package nohiki-scaffold nohiki-scaffold preview service {{ ARGS }}

# Preview a library scaffold plan without writing anything.
preview-lib *ARGS:
    uv run --package nohiki-scaffold nohiki-scaffold preview lib {{ ARGS }}

# Run the scaffolder's own test suite (unit + invariant + integration).
test-scaffold:
    uv run --package nohiki-scaffold pytest scripts/util/scaffold/tests -q

# Testing

# Run package-aware unit tests across uv workspace members
test-all-packages:
    uv run --package ci-checks ci-checks tests all --scope all --ci

# Run package-aware unit tests for backend services only
test-backend-packages:
    uv run --package ci-checks ci-checks tests all --scope services --ci

# Run package-aware unit tests for shared libraries only
test-libs-packages:
    uv run --package ci-checks ci-checks tests all --scope libs --ci

# Run tests for a specific service
test service:
    #!/usr/bin/env bash
    set -euo pipefail
    dir=$(find backend/services backend/libs backend/jobs -maxdepth 1 -type d -name "{{ service }}" | head -1)
    uv run --package {{ service }} pytest "$dir/tests/" --tb=short

# Run tests with coverage for a specific service
test-cov service:
    #!/usr/bin/env bash
    set -euo pipefail
    dir=$(find backend/services backend/libs backend/jobs -maxdepth 1 -type d -name "{{ service }}" | head -1)
    # Coverage instruments the service's src tree; --cov=src failed because
    # pytest runs from the monorepo root where no top-level src/ exists.
    uv run --package {{ service }} pytest "$dir/tests/" --tb=short --cov="$dir/src" --cov-report=term-missing

# Run monorepo integration tests
test-integration:
    uv run --package nohiki-integration-tests pytest tests/integration --tb=short

# Run API contract tests
test-api:
    uv run --package nohiki-integration-tests pytest tests/api --tb=short

# Run API tests with coverage
test-api-cov:
    uv run --package nohiki-integration-tests pytest tests/api --tb=short --cov=backend/services/bff-service --cov-report=term-missing

# --- E2E Playwright Tests ---

# Run all E2E tests (API contract + Playwright browser)
test-all-e2e: test-api test-e2e

# Run Playwright E2E tests
test-e2e:
    {{ playwright_test }}

# Run auth-listings tests with the feature enabled and deterministic worker routing
test-e2e-auth-listings:
    {{ pnpm }} --filter nohiki-frontend run test:e2e:auth-listings

# Run specific Playwright journey test
test-e2e-journey journey:
    {{ playwright_test }} journeys/{{ journey }}.spec.ts

# Run Playwright tests headed
test-e2e-headed:
    {{ playwright_test }} --headed

# Playwright with UI mode
test-e2e-ui:
    {{ playwright_test }} --ui

# Playwright with debug mode
test-e2e-debug:
    {{ playwright_test }} --debug

# Show Playwright report
test-e2e-report:
    {{ playwright }} show-report e2e/.output/report

# Frontend

# Run frontend dev server
fe-dev:
    {{ pnpm }} --filter nohiki-frontend run dev

# Build frontend for production
fe-build:
    {{ pnpm }} --filter nohiki-frontend run build

# Build frontend and open bundle analyzer
fe-analyze:
    {{ pnpm }} --filter nohiki-frontend run analyze

# Run all frontend checks (type-check, biome lint, vitest)
fe-check:
    {{ pnpm }} --filter nohiki-frontend run check:all

# Service development

# Run a service locally
dev service port="8000":
    #!/usr/bin/env bash
    pkg_name=$(echo "{{ service }}" | tr '-' '_')
    cd backend/services/{{ service }} && uv run --package {{ service }} uvicorn "src.${pkg_name}.main:app" --reload --port {{ port }}

# Run database migrations for a service
migrate service:
    cd backend/services/{{ service }} && uv run alembic upgrade head

# Create a new migration for a service
migrate-new service message:
    cd backend/services/{{ service }} && uv run alembic revision --autogenerate -m "{{ message }}"

# Generate protobuf stubs from proto files
proto-gen:
    PYTHONPATH=scripts uv run python -m proto_gen generate

# Verify committed OpenAPI and frontend types match the canonical service exports
api-schema-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' EXIT
    uv run --no-sync python scripts/util/export-openapi.py --output "$tmpdir/nohiki.openapi.json"
    test -x typescript/apps/frontend/node_modules/.bin/openapi-typescript || { echo "error: openapi-typescript is not installed; run pnpm install" >&2; exit 1; }
    typescript/apps/frontend/node_modules/.bin/openapi-typescript "$tmpdir/nohiki.openapi.json" -o "$tmpdir/schema.d.ts"
    diff -u docs/api/nohiki.openapi.json "$tmpdir/nohiki.openapi.json"
    diff -u typescript/apps/frontend/src/api/schema.d.ts "$tmpdir/schema.d.ts"

# Lint proto files
proto-lint:
    cd proto && buf lint

# Check proto breaking changes
proto-breaking:
    #!/usr/bin/env bash
    set -euo pipefail
    if git ls-tree --name-only main proto/ 2>/dev/null | grep -q .; then
        cd proto && buf breaking --against '../.git#branch=main,subdir=proto'
    else
        echo "Skipping: proto/ not yet committed to main branch"
    fi

# Containers and builds

# Render and validate Compose without starting containers
compose-preflight:
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh

# Start infrastructure services from the exact validated render
infra-up:
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh up -d nohiki-infra-postgres nohiki-infra-valkey nohiki-cp-kafka nohiki-cp-kafka-init

# Stop infrastructure services
infra-down:
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh down

# Start all services from the exact validated render
compose-up:
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh up -d

# Explicitly remove legacy connector identities and replication state.
connect-migrate-legacy:
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh run --rm nohiki-cp-kafka-connect /kafka/scripts/register-connectors.sh migrate-legacy

# Trigger snapshot refresh for all listings (rebuilds ECST projections)
snapshot-refresh reason="manual trigger":
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh build nohiki-job-snapshot-refresh
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh run --rm -e REFRESH_REASON="{{reason}}" nohiki-job-snapshot-refresh

# Stop all services
compose-down:
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh down

# View logs for a service
logs service:
    CONTAINER_RUNTIME={{docker}} sh infra/compose/scripts/preflight.sh logs -f {{service}}

# Build a single first-party release image
build service:
    #!/usr/bin/env bash
    set -euo pipefail
    read -ra specs <<< "{{ first_party_image_specs }}"
    for spec in "${specs[@]}"; do
        IFS='|' read -r image context dockerfile build_arg <<< "$spec"
        if [[ "$image" == "{{ service }}" ]]; then
            if [[ -n "$build_arg" ]]; then
                exec {{ docker }} build -f "$dockerfile" --build-arg "$build_arg" -t "${image}:latest" "$context"
            fi
            exec {{ docker }} build -f "$dockerfile" -t "${image}:latest" "$context"
        fi
    done
    printf 'error: unknown first-party image: %s\n' "{{ service }}" >&2
    exit 1

# Build pilot services
build-pilots:
    #!/usr/bin/env bash
    set -uo pipefail
    pids=()
    for svc in user-auth-service job-correlation-evaluation-service ml-compute-service; do
        just build "$svc" &
        pids+=("$!")
    done
    status=0
    for pid in "${pids[@]}"; do
        wait "$pid" || status=1
    done
    exit "$status"

# Build all first-party release images in parallel (the full build-push.yml matrix,
# including the gpu variant and kafka-connect). Local exclusions live in the k8s recipes.
build-all:
    #!/usr/bin/env bash
    set -uo pipefail
    read -ra specs <<< "{{ first_party_image_specs }}"
    pids=()
    for spec in "${specs[@]}"; do
        IFS='|' read -r image context dockerfile build_arg <<< "$spec"
        if [[ -n "$build_arg" ]]; then
            {{ docker }} build -f "$dockerfile" --build-arg "$build_arg" -t "${image}:latest" "$context" &
        else
            {{ docker }} build -f "$dockerfile" -t "${image}:latest" "$context" &
        fi
        pids+=("$!")
    done
    status=0
    for pid in "${pids[@]}"; do
        wait "$pid" || status=1
    done
    exit "$status"

# Ensure release image specs cannot drift across their three canonical inventories
image-matrix-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT

    yq -r '
        .jobs."build-push".strategy.matrix.include[]
        | [.name, (.context // "."), .dockerfile, (.build_args // "")]
        | join("|")
    ' .github/workflows/build-push.yml | sort > "$tmp/workflow"

    jq -r '
        .images[]
        | (.context // ".") as $context
        | [
            .name,
            $context,
            (if $context == "." then .dockerfile else $context + "/" + .dockerfile end),
            ((.buildArgs // {}) | to_entries | sort_by(.key) | map("\(.key)=\(.value)") | join(","))
        ]
        | join("|")
    ' infra/k8s/local/images.json | sort > "$tmp/inventory"

    read -ra specs <<< "{{ first_party_image_specs }}"
    printf '%s\n' "${specs[@]}" | awk -F'|' 'BEGIN { OFS="|" } { print $1, $2, $3, $4 }' | sort > "$tmp/just"
    diff -u --label workflow --label inventory "$tmp/workflow" "$tmp/inventory"
    diff -u --label workflow --label justfile "$tmp/workflow" "$tmp/just"

    printf '%s\n' {{ first_party_image_names }} | sort > "$tmp/names"
    cut -d'|' -f1 "$tmp/just" | sort > "$tmp/spec-names"
    diff -u --label first_party_image_names --label first_party_image_specs "$tmp/names" "$tmp/spec-names"

# Measure image size after build
build-measure service:
    just build {{ service }}
    {{ docker }} images {{ service }}:latest --format "table {{{{.Repository}}}}\t{{{{.Size}}}}"

# Kubernetes and GitOps

# Read-only validation of the selected local cluster, trust root, image mirror, manifests, and health inventory.
k8s-preflight-local:
    infra/k8s/local/lifecycle.sh preflight

# One-time Flux/trust-root installation after the complete read-only preflight.
k8s-bootstrap-local:
    infra/k8s/local/lifecycle.sh bootstrap

# Sole image build/push and bounded runtime-control Git writer; commits only generated digest values.
k8s-publish-local-images:
    infra/k8s/local/lifecycle.sh publish

# Request and observe the ordered Flux source/stack convergence; no direct workload mutation.
k8s-reconcile-local:
    infra/k8s/local/lifecycle.sh reconcile

# Prove convergence, migrations, health, API/browser Jobs, observability, image pulls, and drift closure.
k8s-verify-local:
    infra/k8s/local/lifecycle.sh verify

# Print read-only, redacted local cluster diagnostics.
k8s-diagnostics-local:
    infra/k8s/local/lifecycle.sh diagnostics

# Delegate guarded local control-plane factory reset/dry-run to the evidence-preserving reset boundary.
k8s-factory-reset-local *args:
    infra/k8s/local/lifecycle.sh factory-reset {{ args }}

compose-health *args:
    uv run --package health-check health-check run --target compose {{ args }}

# Observability

generate-dashboard-crds:
    chmod +x infra/shared/scripts/generate-dashboard-crds.sh
    infra/shared/scripts/generate-dashboard-crds.sh

validate-dashboards:
    #!/usr/bin/env bash
    set -uo pipefail
    status=0
    for file in infra/shared/dashboards/*.json; do
        if jq empty "$file"; then
            echo "PASS: $(basename "$file")"
        else
            echo "FAIL: $(basename "$file")"
            status=1
        fi
    done
    exit "$status"

kustomize-validate env="local":
    kustomize build infra/k8s/observability/overlays/{{ env }}

kustomize-validate-all: (kustomize-validate "local") (kustomize-validate "staging") (kustomize-validate "prod")

# AST explorer

ast-events:
    {{ ast_cmd }} events ../../..

ast-events-service service:
    {{ ast_cmd }} events ../../.. --service {{ service }}

ast-events-topic topic:
    {{ ast_cmd }} events ../../.. --topic {{ topic }}

ast-trace topic:
    {{ ast_cmd }} events ../../.. --topic {{ topic }} --trace

ast-deps-lib lib:
    {{ ast_cmd }} deps ../../.. --lib {{ lib }}

ast-deps-pkg package:
    {{ ast_cmd }} deps ../../.. --package {{ package }}

ast-impact symbol:
    {{ ast_cmd }} impact {{ symbol }} --path ../../..

ast-scan service:
    {{ ast_cmd }} scan ../../../backend/services/{{ service }} --tree

ast-query kind:
    {{ ast_cmd }} query ../../.. --kind {{ kind }}

# Git hooks

hooks-install:
    {{ pnpm }} exec lefthook install

hooks-uninstall:
    {{ pnpm }} exec lefthook uninstall

hooks-precommit:
    {{ pnpm }} exec lefthook run pre-commit --force

hooks-prepush:
    {{ pnpm }} exec lefthook run pre-push --force

hooks-test-msg message:
    echo "{{ message }}" | {{ pnpm }} exec commitlint
