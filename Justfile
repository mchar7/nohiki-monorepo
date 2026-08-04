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

# Local K3s deploy inventory: excludes ml-compute-service-gpu and kafka-connect, since
# neither is built or pushed for the GPU-less local cluster (local ml-compute uses the CPU image).
local_image_names := "user-auth-service user-pref-service user-upload-service user-entitlement-service job-storage-service job-ingest-discovery-service job-ingest-schedule-service job-ingest-enrichment-service job-query-composition-service job-correlation-evaluation-service skill-graph-service doc-template-service doc-content-service doc-process-service notification-service bff-service ml-gateway-service ml-compute-service sys-tick-job snapshot-refresh-job qdrant-init frontend"

# Common commands
env_lock := monorepo_root + "/scripts/dev/env-lock.sh"
test_run := monorepo_root + "/scripts/dev/test-run.sh"
# The flake pins pnpm to the version package.json declares, so Corepack would only
# fetch a second copy, which hermetic shells forbid.
pnpm := "pnpm"
nix_flags := "--max-jobs " + env_var_or_default("NOHIKI_NIX_MAX_JOBS", "4") + " --cores " + env_var_or_default("NOHIKI_NIX_CORES", "5")
playwright := env_lock + " shared node_modules -- " + pnpm + " --filter nohiki-frontend exec playwright"
playwright_test := test_run + " " + playwright + " test --config=e2e/playwright.config.ts"
ast_cmd := "cd scripts/util/ast_explorer && " + env_lock + " shared venv -- uv run --no-sync ast-explorer"

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
    {{ env_lock }} exclusive venv -- uv sync --all-packages --all-extras --no-extra cuda --group deadcode

# Sync with all non-conflicting development extras
sync-dev:
    {{ env_lock }} exclusive venv -- uv sync --all-packages --all-extras --no-extra cuda --group deadcode

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

# Apply repository autofixes
fix: lint-fix format lint-md-fix

# Run the complete repository verification matrix
check-all: verify

# Check Python lint policy
lint:
    {{ env_lock }} shared venv -- uv run --no-sync ruff check .

# Apply Python lint fixes
lint-fix:
    {{ env_lock }} shared venv -- uv run --no-sync ruff check --fix .

# Run ruff check on a specific service
lint-service service:
    {{ env_lock }} shared venv -- uv run --no-sync ruff check --config pyproject.toml --fix --output-format=concise backend/services/{{ service }}/

# Run ruff check on shared libraries
lint-libs:
    {{ env_lock }} shared venv -- uv run --no-sync ruff check --config pyproject.toml --fix --output-format=concise backend/libs/

# Format all Python files (same surface as the CI lint lane)
format:
    {{ env_lock }} shared venv -- uv run --no-sync ruff format --config pyproject.toml .

# Check Python formatting
format-check:
    {{ env_lock }} shared venv -- uv run --no-sync ruff format --check .

# Format a specific service
format-service service:
    {{ env_lock }} shared venv -- uv run --no-sync ruff format --config pyproject.toml backend/services/{{ service }}/

# Check Markdown lint policy
lint-md:
    {{ env_lock }} shared node_modules -- {{ pnpm }} exec markdownlint-cli2 "**/*.md"

# Apply Markdown lint fixes
lint-md-fix:
    {{ env_lock }} shared node_modules -- {{ pnpm }} exec markdownlint-cli2 --fix "**/*.md"
# Type checking

# Run ty across the canonical native source surface
typecheck-all:
    {{ env_lock }} shared venv -- uv run --no-sync ty check

# Run ty on a specific backend service
typecheck service:
    {{ env_lock }} shared venv -- uv run --no-sync --package {{ service }} ty check src/

# Run ty on a specific shared library
typecheck-lib lib:
    {{ env_lock }} shared venv -- uv run --no-sync --package {{ lib }} ty check src/

# Run ty on a job
typecheck-job job:
    {{ env_lock }} shared venv -- uv run --no-sync --package {{ job }} ty check src/

# Code hygiene

# Run the complete repository verification matrix
check-strict: verify

# Run all strict hygiene checks
hygiene: hygiene-deps hygiene-arch hygiene-deadcode-strict hygiene-fixtures-strict hygiene-build-backend-strict

hygiene-deps packages="ALL":
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks deptry --scope all --packages '{{ packages }}' --ci

hygiene-deps-backend:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks deptry --scope services --ci

hygiene-deps-libs:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks deptry --scope libs --ci

hygiene-arch:
    env -u LD_LIBRARY_PATH uvx --override semgrep-overrides.txt semgrep scan --config semgrep.yml --error --no-git-ignore --metrics=off --disable-version-check backend/

hygiene-arch-report:
    uvx --override semgrep-overrides.txt semgrep scan --config semgrep.yml --no-git-ignore backend/

hygiene-deadcode:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks --group deadcode ci-checks deadcode --scope all --ci

hygiene-deadcode-strict packages="ALL":
    #!/usr/bin/env bash
    set -euo pipefail
    args=(--scope all --packages '{{ packages }}' --ci --fail --no-provenance)
    [[ -z ${GITHUB_STEP_SUMMARY:-} ]] || args+=(--summary "$GITHUB_STEP_SUMMARY")
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks --group deadcode ci-checks deadcode "${args[@]}"

hygiene-deadcode-llm:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks --group deadcode ci-checks deadcode --scope all --ci --llm

hygiene-fixtures:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks fixtures --scope all --ci

hygiene-fixtures-strict:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks fixtures --scope all --ci --fail

hygiene-fixtures-services:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks fixtures --scope services --ci

hygiene-fixtures-libs:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks fixtures --scope libs --ci

# Validate migrated packages against the canonical uv_build settings.
hygiene-build-backend:
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks build-backend --scope all --ci

# Require every buildable workspace package to use canonical uv_build settings.
hygiene-build-backend-strict packages="ALL":
    {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks build-backend --scope all --packages '{{ packages }}' --ci --strict

# Run every developer-reproducible CI check
verify: lint format-check lint-md typecheck-all test-all-packages test-skylos-cache test-node-contracts hygiene fe-check fe-fsd fe-i18n edge-check proto-lint proto-breaking workflow-lint docker-lint secrets-scan nix-check api-schema-check image-matrix-check

# Scaffold CLI

# Scaffold a new backend service.
new-service *ARGS:
    {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-scaffold nohiki-scaffold new service {{ ARGS }}

# Scaffold a new shared library.
new-lib *ARGS:
    {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-scaffold nohiki-scaffold new lib {{ ARGS }}

# Preview a service scaffold without writing files.
preview-service *ARGS:
    {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-scaffold nohiki-scaffold preview service {{ ARGS }}

# Preview a library scaffold plan without writing anything.
preview-lib *ARGS:
    {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-scaffold nohiki-scaffold preview lib {{ ARGS }}

# Run the scaffolder's own test suite (unit + invariant + integration).
test-scaffold:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-scaffold pytest scripts/util/scaffold/tests -q

# Testing

# Run package-aware unit tests across uv workspace members
test-all-packages:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks tests all --scope all --ci --workers 2

# Run Skylos cache contract tests
test-skylos-cache:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync pytest scripts/ci/tests -m requires_skylos

# Run Node workspace contract tests
test-node-contracts:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync pytest scripts/ci/tests -m requires_node_modules

# Run package-aware unit tests for backend services only
test-backend-packages:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks tests all --scope services --ci --workers 2

# Run package-aware unit tests for shared libraries only
test-libs-packages:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package ci-checks ci-checks tests all --scope libs --ci --workers 2

# Run tests for a specific service
test service:
    #!/usr/bin/env bash
    set -euo pipefail
    dir=$(find backend/services backend/libs backend/jobs -maxdepth 1 -type d -name "{{ service }}" | head -1)
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package {{ service }} pytest "$dir/tests/" --tb=short

# Run tests with coverage for a specific service
test-cov service:
    #!/usr/bin/env bash
    set -euo pipefail
    dir=$(find backend/services backend/libs backend/jobs -maxdepth 1 -type d -name "{{ service }}" | head -1)
    # Coverage instruments the service's src tree; --cov=src failed because
    # pytest runs from the monorepo root where no top-level src/ exists.
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package {{ service }} pytest "$dir/tests/" --tb=short --cov="$dir/src" --cov-report=term-missing

# Run monorepo integration tests
test-integration:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-integration-tests pytest tests/integration --tb=short

# Run API contract tests
test-api:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-integration-tests pytest tests/api --tb=short

# Run API tests with coverage
test-api-cov:
    {{ test_run }} {{ env_lock }} shared venv -- uv run --no-sync --package nohiki-integration-tests pytest tests/api --tb=short --cov=backend/services/bff-service --cov-report=term-missing

# --- E2E Playwright Tests ---

# Run all E2E tests (API contract + Playwright browser)
test-all-e2e: test-api test-e2e

# Run Playwright E2E tests
test-e2e:
    {{ playwright_test }}

# Run auth-listings tests with the feature enabled and deterministic worker routing
test-e2e-auth-listings:
    {{ test_run }} {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run test:e2e:auth-listings

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
    {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run dev

# Build frontend for production
fe-build:
    {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run build

# Build frontend and open bundle analyzer
fe-analyze:
    {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run analyze

# Run all frontend checks
fe-check: fe-typecheck fe-lint fe-fsd fe-i18n fe-test

# Type-check the frontend
fe-typecheck:
    {{ test_run }} {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run type-check

# Check frontend lint and formatting
fe-lint:
    {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run check

# Check frontend architecture
fe-fsd:
    {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run lint:fsd

# Check frontend translations
fe-i18n:
    {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run i18n:check

# Run frontend unit tests
fe-test:
    {{ test_run }} {{ env_lock }} shared node_modules -- {{ pnpm }} --filter nohiki-frontend run test

# Cloudflare edge worker

# Run all edge worker checks
edge-check: edge-typecheck edge-lint edge-test

# Type-check the Cloudflare edge worker
edge-typecheck:
    {{ test_run }} {{ env_lock }} shared node_modules -- {{ pnpm }} --filter @nohiki/auth-listings-worker exec tsc --noEmit

# Check edge worker lint and formatting
edge-lint:
    {{ env_lock }} shared node_modules -- {{ pnpm }} --filter @nohiki/auth-listings-worker exec biome ci src/

# Run edge worker unit tests
edge-test:
    {{ test_run }} {{ env_lock }} shared node_modules -- {{ pnpm }} --filter @nohiki/auth-listings-worker exec vitest run

# Service development

# Run a service locally
dev service port="8000":
    #!/usr/bin/env bash
    pkg_name=$(echo "{{ service }}" | tr '-' '_')
    cd backend/services/{{ service }} && {{ env_lock }} shared venv -- uv run --no-sync --package {{ service }} uvicorn "src.${pkg_name}.main:app" --reload --port {{ port }}

# Run database migrations for a service
migrate service:
    cd backend/services/{{ service }} && {{ env_lock }} shared venv -- uv run --no-sync alembic upgrade head

# Create a new migration for a service
migrate-new service message:
    cd backend/services/{{ service }} && {{ env_lock }} shared venv -- uv run --no-sync alembic revision --autogenerate -m "{{ message }}"

# Generate protobuf stubs from proto files
proto-gen:
    PYTHONPATH=scripts {{ env_lock }} shared venv -- uv run --no-sync python -m proto_gen generate

# Verify committed OpenAPI and frontend types match the canonical service exports
api-schema-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmpdir=$(mktemp -d)
    trap 'rm -rf "$tmpdir"' EXIT
    {{ env_lock }} shared venv -- uv run --no-sync python scripts/util/export-openapi.py --output "$tmpdir/nohiki.openapi.json"
    {{ env_lock }} shared node_modules -- sh -c 'test -x "$1" || { echo "error: openapi-typescript is not installed; run pnpm install" >&2; exit 1; }; "$1" "$2" -o "$3"' _ typescript/apps/frontend/node_modules/.bin/openapi-typescript "$tmpdir/nohiki.openapi.json" "$tmpdir/schema.d.ts"
    diff -u typescript/apps/frontend/src/api/schema.d.ts "$tmpdir/schema.d.ts"

# Lint proto files
proto-lint:
    nix develop .#ci {{ nix_flags }} --command bash -euc 'cd proto && buf lint'

# Check proto breaking changes
proto-breaking base_ref="main":
    #!/usr/bin/env bash
    set -euo pipefail
    if git cat-file -e '{{ base_ref }}^{commit}' && git ls-tree --name-only '{{ base_ref }}' proto/ | grep -q .; then
        nix develop .#ci {{ nix_flags }} --command bash -euc "cd proto && buf breaking --against '../.git#commit={{ base_ref }},subdir=proto'"
    else
        echo "Skipping: proto/ is absent from {{ base_ref }}"
    fi

# Lint GitHub workflows with their native validators
workflow-lint:
    nix develop .#ci {{ nix_flags }} --command actionlint -ignore '^step must run script with "run" section or run action with "uses" section$'
    nix develop .#ci {{ nix_flags }} --command check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/*.yml

# Lint every tracked Dockerfile
docker-lint:
    #!/usr/bin/env bash
    set -euo pipefail
    git ls-files -z -- '*Dockerfile' '*Dockerfile.*' ':(exclude)*.dockerignore' ':(exclude)*.j2' | xargs -0 -r nix develop .#ci {{ nix_flags }} --command hadolint

# Scan the repository or staged changes for secrets
secrets-scan mode="detect":
    #!/usr/bin/env bash
    set -euo pipefail
    case '{{ mode }}' in
        detect) nix develop .#ci {{ nix_flags }} --command gitleaks detect --source . --config .gitleaks.toml --no-banner --redact ;;
        staged) nix develop .#ci {{ nix_flags }} --command gitleaks protect --staged --config .gitleaks.toml --no-banner --redact ;;
        *) echo "mode must be detect or staged" >&2; exit 2 ;;
    esac

# Scan a pushed commit range for secrets
secrets-scan-range range:
    nix develop .#ci {{ nix_flags }} --command gitleaks detect --source . --config .gitleaks.toml --no-banner --redact --log-opts '{{ range }}'

# Evaluate the native Nix flake checks
nix-check:
    nix flake check {{ nix_flags }}

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
    while IFS=$'\t' read -r image context dockerfile build_arg; do
        if [[ "$image" == "{{ service }}" ]]; then
            if [[ -n "$build_arg" ]]; then
                exec {{ docker }} build -f "$dockerfile" --build-arg "$build_arg" -t "${image}:latest" "$context"
            fi
            exec {{ docker }} build -f "$dockerfile" -t "${image}:latest" "$context"
        fi
    done < <(python3 scripts/ci/image_matrix.py specs)
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
    pids=()
    while IFS=$'\t' read -r image context dockerfile build_arg; do
        if [[ -n "$build_arg" ]]; then
            {{ docker }} build -f "$dockerfile" --build-arg "$build_arg" -t "${image}:latest" "$context" &
        else
            {{ docker }} build -f "$dockerfile" -t "${image}:latest" "$context" &
        fi
        pids+=("$!")
    done < <(python3 scripts/ci/image_matrix.py specs)
    status=0
    for pid in "${pids[@]}"; do
        wait "$pid" || status=1
    done
    exit "$status"

# Ensure release image specs cannot drift between the canonical release inventory and the
# local-deployment view.
image-matrix-check:
    #!/usr/bin/env bash
    set -euo pipefail
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT

    python3 scripts/ci/image_matrix.py specs | sort > "$tmp/release"

    jq -r '
        .images[]
        | (.context // ".") as $context
        | [
            .name,
            $context,
            (if $context == "." then .dockerfile else $context + "/" + .dockerfile end),
            ((.buildArgs // {}) | to_entries | sort_by(.key) | map("\(.key)=\(.value)") | join(","))
        ]
        | @tsv
    ' infra/k8s/local/images.json | sort > "$tmp/local"
    diff -u --label release-inventory --label local-images "$tmp/release" "$tmp/local"

    python3 scripts/ci/image_matrix.py names | sort > "$tmp/names"
    cut -f1 "$tmp/release" | sort > "$tmp/spec-names"
    diff -u --label names --label specs "$tmp/names" "$tmp/spec-names"

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
    {{ env_lock }} shared venv -- uv run --no-sync --package health-check health-check run --target compose {{ args }}

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

# Validate the local load and resource-measurement substrate without sending traffic.
load-check:
    k6 inspect scripts/load/k6/scenarios/smoke.js
    {{ env_lock }} shared venv -- uv run --no-sync pytest -q scripts/load/tests/test_resource_probe.py

# Capture one complete-cluster resource point from an explicit local kind context.
load-resource-capture output phase tier fixture_version:
    scripts/load/resource_probe.py capture --context "{{ k8s_local_context }}" --phase "{{ phase }}" --tier "{{ tier }}" --fixture-version "{{ fixture_version }}" --output "{{ output }}"

# Capture repeated complete-cluster points and resource distributions.
load-resource-sample output phase tier fixture_version duration_seconds="60" interval_seconds="5":
    scripts/load/resource_probe.py sample --context "{{ k8s_local_context }}" --phase "{{ phase }}" --tier "{{ tier }}" --fixture-version "{{ fixture_version }}" --duration-seconds "{{ duration_seconds }}" --interval-seconds "{{ interval_seconds }}" --output "{{ output }}"

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
    {{ env_lock }} shared node_modules -- scripts/dev/install-hooks.sh {{ pnpm }} exec lefthook install

hooks-uninstall:
    {{ env_lock }} shared node_modules -- {{ pnpm }} exec lefthook uninstall

hooks-precommit:
    {{ env_lock }} shared node_modules -- {{ pnpm }} exec lefthook run pre-commit --force

hooks-prepush:
    {{ env_lock }} shared node_modules -- {{ pnpm }} exec lefthook run pre-push --force

hooks-test-msg message:
    echo "{{ message }}" | {{ env_lock }} shared node_modules -- {{ pnpm }} exec commitlint
