"""Change-gate policy: which files activate which CI lanes.

Pure data, no I/O. The engine (`core.change_gate`) interprets these tables;
the CLI (`checks.gate`) supplies the diff. Contract tests pin the flag names
against .github/workflows/checks.yml.

Classification tiers:

1. ``BROAD_RULES`` identify policy and Python toolchain sources that require
   the broad class.
2. ``SURFACE_RULES`` contribute lane flags and package seeds; a file may
   match several rules and every match contributes (union semantics), so
   rule order can never suppress a lane.
3. Files matching nothing select the broad class within this workflow.
"""

import fnmatch
from dataclasses import dataclass

# Lane flags emitted to $GITHUB_OUTPUT. Every name must have a matching
# consumer in .github/workflows/checks.yml.
FLAG_NAMES: tuple[str, ...] = (
    "nix",
    "lint_python",
    "lint_frontend",
    "lint_steiger",
    "lint_proto",
    "lint_markdown",
    "lint_workflows",
    "lint_docker",
    "typecheck_backend",
    "build_backend",
    "typecheck_frontend",
    "python_any",
    "frontend_tests",
    "frontend_smoke",
    "frontend_e2e",
    "node_workspace_contracts",
    "edge_worker",
    "otel_collector",
    "hygiene",
    "api_schema_freshness",
    "image_matrix_parity",
    "proto_breaking",
)


# Services whose FastAPI apps feed scripts/util/export-openapi.py. A change
# reaching either one (directly or through a dependency) can move the merged
# OpenAPI spec, so the API schema freshness lane must run.
API_EXPORT_SERVICES: frozenset[str] = frozenset({"bff-service", "user-auth-service"})

# Static work performed by the broad policy worker. Container and frontend
# smoke remain path-selected rather than being implied by the commit class.
BROAD_PYTHON_FLAGS: tuple[str, ...] = (
    "lint_python",
    "typecheck_backend",
    "python_any",
    "hygiene",
)

# Application source and toolchain changes exercise every hosted app contract.
_FRONTEND_APP_FLAGS: tuple[str, ...] = (
    "lint_frontend",
    "lint_steiger",
    "typecheck_frontend",
    "frontend_tests",
)

# playwright-image is the one job that never calls the composite, so frontend_e2e cannot move.
_COMPOSITE_SETUP_FLAGS: tuple[str, ...] = tuple(flag for flag in FLAG_NAMES if flag != "frontend_e2e")


@dataclass(frozen=True, slots=True)
class SurfaceRule:
    """One pattern set with the complete effects it contributes."""

    patterns: tuple[str, ...]
    flags: tuple[str, ...] = ()
    packages: tuple[str, ...] = ()

    def matches(self, path: str) -> bool:
        """Return True when the posix repo-relative path matches any pattern."""
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.patterns)


# These sources define the router or the runtime in which that policy executes.
# They fail closed to the broad Python class.
BROAD_RULES: tuple[SurfaceRule, ...] = (
    SurfaceRule(
        ("flake.nix", "flake.lock"),
        # Every lane listed here runs its binary from the .#ci devshell, so a
        # flake bump can move its verdict: buf, actionlint, hadolint, just and
        # the CI Python come from flake.nix ciPolicyTools. container-contracts
        # runs its two pytest assertions the same way and, unlike the worker
        # steps, carries no broad disjunct, so its flags are the only thing that
        # can select it. playwright-image runs bare docker and remains excluded.
        flags=(
            "nix",
            *BROAD_PYTHON_FLAGS,
            "build_backend",
            "lint_proto",
            "lint_workflows",
            "lint_docker",
            "proto_breaking",
            "image_matrix_parity",
            "api_schema_freshness",
            "frontend_smoke",
            "otel_collector",
        ),
        packages=("ci-checks",),
    ),
    SurfaceRule(
        ("uv.lock", "pyproject.toml"),
        flags=(*BROAD_PYTHON_FLAGS, "build_backend", "api_schema_freshness"),
        packages=("ci-checks",),
    ),
    SurfaceRule(
        (".python-version",),
        flags=(*BROAD_PYTHON_FLAGS, "build_backend"),
        packages=("ci-checks",),
    ),
    SurfaceRule(
        (".github/workflows/checks.yml",),
        # Self-reference: this file decides which lanes run, so no run it produces is
        # evidence about a change to it.
        flags=FLAG_NAMES,
        packages=("ci-checks",),
    ),
    SurfaceRule(
        (".github/actions/setup-ci/action.yml",),
        flags=_COMPOSITE_SETUP_FLAGS,
        packages=("ci-checks",),
    ),
    SurfaceRule(
        (
            # Importing any core submodule executes the package initializer.
            "scripts/ci/src/ci_checks/core/__init__.py",
            "scripts/ci/src/ci_checks/core/change_gate.py",
            "scripts/ci/src/ci_checks/core/change_rules.py",
            "scripts/ci/src/ci_checks/core/display.py",
            "scripts/ci/src/ci_checks/core/image_inventory.py",
            "scripts/ci/src/ci_checks/core/packages.py",
        ),
        flags=BROAD_PYTHON_FLAGS,
        packages=("ci-checks",),
    ),
    SurfaceRule(
        (
            "scripts/ci/src/ci_checks/checks/gate.py",
            "scripts/ci/src/ci_checks/checks/internal_refs.py",
            # The runner controls every package's test invocation.
            "scripts/ci/src/ci_checks/checks/tests.py",
            "scripts/ci/config/internal-reference-terms.toml",
        ),
        flags=BROAD_PYTHON_FLAGS,
        packages=("ci-checks",),
    ),
)


SURFACE_RULES: tuple[SurfaceRule, ...] = (
    SurfaceRule(
        (
            "scripts/ci/src/ci_checks/core/process_env.py",
            "scripts/ci/src/ci_checks/core/repository.py",
            "scripts/ci/src/ci_checks/core/scanner.py",
        ),
        packages=("ci-checks",),
    ),
    SurfaceRule(
        ("*.md", "**/*.md", ".markdownlint-cli2.jsonc", ".markdownlint.json", ".markdownlintignore"),
        flags=("lint_markdown",),
    ),
    SurfaceRule(
        ("proto/*", "proto/**/*"),
        flags=("lint_proto", "proto_breaking", "typecheck_backend"),
        # Regenerated dataclasses land in nohiki-domain-models; rerun its dependents.
        packages=("nohiki-domain-models",),
    ),
    SurfaceRule(
        # Biome's own file list (biome.jsonc `files.includes`), vitest's project
        # includes and the three tsconfig `include` sets are each narrower than
        # the app directory. These are the paths at least one of them reads.
        (
            "typescript/apps/frontend/src/*",
            "typescript/apps/frontend/src/**/*",
            "typescript/apps/frontend/public/*",
            "typescript/apps/frontend/public/**/*",
            "typescript/apps/frontend/scripts/*",
            "typescript/apps/frontend/scripts/**/*",
            "typescript/apps/frontend/__mocks__/*",
            "typescript/apps/frontend/__mocks__/**/*",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/biome.jsonc",
            "typescript/apps/frontend/tsconfig.json",
            "typescript/apps/frontend/tsconfig.app.json",
            "typescript/apps/frontend/tsconfig.node.json",
            "typescript/apps/frontend/tsconfig.test.json",
            "typescript/apps/frontend/vite.config.ts",
            "typescript/apps/frontend/vitest.config.ts",
        ),
        flags=_FRONTEND_APP_FLAGS,
    ),
    SurfaceRule(("typescript/apps/frontend/steiger.config.ts",), flags=("lint_steiger",)),
    # Frontend app files no hosted lane opens: ast-grep and knip have no step in
    # checks.yml, and components.json is shadcn CLI input that biome, tsc and
    # vitest all exclude. Classified so they stay off the broad path.
    SurfaceRule(
        (
            "typescript/apps/frontend/.ast-grep/*",
            "typescript/apps/frontend/.ast-grep/**/*",
            "typescript/apps/frontend/components.json",
            "typescript/apps/frontend/knip.ts",
        ),
    ),
    SurfaceRule(
        ("package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml"),
        flags=("lint_steiger",),
    ),
    SurfaceRule(
        # The production image COPYs the root manifests and the whole typescript
        # tree, then runs pnpm install --frozen-lockfile and
        # `pnpm --filter nohiki-frontend build`. That build is
        # `tsc -p tsconfig.app.json` (src, public/locales), then
        # `tsc -p tsconfig.node.json` (vite.config.ts, vitest.config.ts, e2e),
        # then `vite build` (index.html, public). Every workspace manifest is an
        # input of the frozen-lockfile check, and .dockerignore shapes the
        # context the build sees.
        (
            ".dockerignore",
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "typescript/*/*/package.json",
            "typescript/apps/frontend/index.html",
            "typescript/apps/frontend/tsconfig*.json",
            "typescript/apps/frontend/vite.config.ts",
            "typescript/apps/frontend/vitest.config.ts",
            "typescript/apps/frontend/Caddyfile",
            "typescript/apps/frontend/src/*",
            "typescript/apps/frontend/src/**/*",
            "typescript/apps/frontend/public/*",
            "typescript/apps/frontend/public/**/*",
            "typescript/apps/frontend/e2e/*",
            "typescript/apps/frontend/e2e/**/*",
            "typescript/libs/tsconfig/*",
        ),
        flags=("frontend_smoke",),
    ),
    SurfaceRule(
        # vitest.config.ts:48 excludes **/e2e/**, so a Playwright spec cannot
        # move the vitest verdict. Biome lints e2e/** and tsconfig.node.json
        # type-checks e2e/**/*.ts, so those two lanes stay.
        ("typescript/apps/frontend/e2e/*", "typescript/apps/frontend/e2e/**/*"),
        flags=("lint_frontend", "typecheck_frontend"),
    ),
    SurfaceRule(
        (
            "typescript/edge/auth-listings-worker/*",
            "typescript/edge/auth-listings-worker/**/*",
        ),
        flags=("edge_worker",),
    ),
    SurfaceRule(
        ("typescript/libs/*", "typescript/libs/**/*"),
        flags=(*_FRONTEND_APP_FLAGS, "edge_worker"),
    ),
    SurfaceRule(
        ("typescript/apps/frontend/src/api/schema.d.ts",),
        flags=("api_schema_freshness",),
        # The committed types are asserted by test_upload_api_schema.
        packages=("ci-checks",),
    ),
    SurfaceRule(
        # Root toolchain changes can affect every TypeScript consumer.
        ("pnpm-lock.yaml", "pnpm-workspace.yaml", "package.json", ".npmrc"),
        flags=(
            *_FRONTEND_APP_FLAGS,
            "edge_worker",
            "api_schema_freshness",
        ),
    ),
    SurfaceRule(("biome.json", "biome.jsonc"), flags=("lint_frontend", "edge_worker")),
    SurfaceRule(("**/pyproject.toml",), flags=("build_backend",)),
    SurfaceRule(
        ("Dockerfile", "**/Dockerfile", "**/Dockerfile.*", ".hadolint.yaml"),
        flags=("lint_docker",),
        # Image contract tests live in the ci-checks suite.
        packages=("ci-checks",),
    ),
    SurfaceRule(("typescript/apps/frontend/Dockerfile",), flags=("frontend_smoke",)),
    # requires_docker assertions that the Python lane deselects: the
    # container-contracts job is their only executor, so each file must select
    # the job that runs it.
    SurfaceRule(
        ("scripts/ci/tests/test_frontend_delivery.py",),
        flags=("frontend_smoke",),
    ),
    SurfaceRule(
        ("scripts/ci/tests/test_otel_collector_manifest.py",),
        flags=("otel_collector",),
    ),
    SurfaceRule(
        # The Playwright runner image's last RUN is `pnpm install
        # --frozen-lockfile` at Dockerfile.playwright-runner:11-12, ahead of the
        # source COPYs at :13-15, and the job overrides the entrypoint with
        # `playwright --version`. Only the manifests that install resolves, the
        # Dockerfile itself (which carries both pinned base digests) and the
        # context filter can move the verdict.
        (
            ".dockerignore",
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "typescript/apps/frontend/Dockerfile.playwright-runner",
            "typescript/apps/frontend/package.json",
            "typescript/libs/biome-config/package.json",
            "typescript/libs/tsconfig/package.json",
        ),
        flags=("frontend_e2e",),
    ),
    SurfaceRule(
        # `pytest scripts/ci/tests -m requires_node_modules` executes the k8s Playwright
        # config rather than reading it: two tests import it under node and a third runs
        # `playwright test --list` and compares the collection against e2e/journeys. So the
        # inputs are that config and everything it imports, every journey the listing
        # collects, the manifests that resolve the Playwright version, and the test module
        # itself. The Python suite deselects the marker, so this step is their only executor.
        (
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/e2e/*",
            "typescript/apps/frontend/e2e/**/*",
            "scripts/ci/tests/test_local_verification_jobs.py",
        ),
        flags=("node_workspace_contracts",),
    ),
    SurfaceRule(
        (".github/workflows/*", ".github/workflows/**/*"),
        flags=("lint_workflows",),
        packages=("ci-checks",),
    ),
    SurfaceRule(
        # actionlint checks a caller's `with:` keys against the composite's own `inputs:`.
        (".github/actions/*", ".github/actions/**/*"),
        flags=("lint_workflows",),
        packages=("ci-checks",),
    ),
    SurfaceRule((".github/workflows/build-push.yml",), flags=("image_matrix_parity",)),
    # Helm, compose, gitops, and Qdrant contract tests live in ci-checks.
    SurfaceRule(("infra/*", "infra/**/*"), packages=("ci-checks",)),
    SurfaceRule(
        (
            "infra/k8s/observability/*",
            "infra/k8s/observability/**/*",
            "infra/compose/docker-compose.yml",
            "infra/compose/observability/otel/*",
            "infra/compose/observability/otel/**/*",
        ),
        flags=("otel_collector",),
    ),
    # Migration-truth contract tests pin every service's Alembic head.
    SurfaceRule(("backend/services/*/alembic/**/*",), packages=("ci-checks",)),
    # `nix flake check` evaluates flake.nix:268-274 against the built binary and
    # the version step compares a workflow literal; neither reads lefthook.yml.
    SurfaceRule(("lefthook.yml",), packages=("ci-checks",)),
    SurfaceRule(
        # Both steps shell out to `just`. Proto compatibility does not: the
        # workflow runs `buf breaking` inline and Justfile:335-342 is local-only.
        ("Justfile",),
        flags=("image_matrix_parity", "api_schema_freshness"),
        packages=("ci-checks",),
    ),
    SurfaceRule(
        ("infra/k8s/local/images.json",),
        flags=("image_matrix_parity",),
        packages=("ci-checks",),
    ),
    # just api-schema-check diffs only schema.d.ts and never reads the committed
    # spec; test_upload_api_schema is what asserts it.
    SurfaceRule(("docs/api/*", "docs/api/**/*"), packages=("ci-checks",)),
    SurfaceRule(("scripts/util/export-openapi.py",), flags=("api_schema_freshness",)),
    SurfaceRule(("semgrep.yml", "semgrep-overrides.txt"), flags=("hygiene",)),
    SurfaceRule(("scripts/ci/src/ci_checks/checks/*",), packages=("ci-checks",)),
    SurfaceRule(("scripts/ci/tests/*", "scripts/ci/tests/**/*"), packages=("ci-checks",)),
    # Read inputs of ci-checks contract tests that no lane flag covers.
    SurfaceRule(
        (
            ".dockerignore",
            ".github/dependabot.yml",
            ".github/renovate.json5",
            ".gitignore",
            ".gitleaks.toml",
            "backend/services/ml-compute-service/pyproject.toml",
            "package.json",
            "pnpm-lock.yaml",
            "semgrep-overrides.txt",
            "typescript/edge/auth-listings-worker/wrangler.toml",
        ),
        packages=("ci-checks",),
    ),
    # Understood, no CI effect: commitlint always runs on pull requests and no
    # lane or contract test reads the rest.
    SurfaceRule(
        (
            ".gitattributes",
            ".editorconfig",
            ".envrc",
            "LICENSE",
            "LICENSE.*",
            ".github/CODEOWNERS",
            ".commitlintrc*",
            "commitlint.config.*",
            ".vscode/**",
            ".agents/**",
            "docs/*",
            "docs/**/*",
        ),
    ),
)
