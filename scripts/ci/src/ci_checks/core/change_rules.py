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
    "typecheck_frontend",
    "frontend_tests",
)


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
        flags=(
            "nix",
            *BROAD_PYTHON_FLAGS,
            *_FRONTEND_APP_FLAGS,
            "edge_worker",
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
        # Path-only routing cannot identify which YAML lane definition changed.
        flags=FLAG_NAMES,
        packages=("ci-checks",),
    ),
    SurfaceRule(
        (
            "scripts/ci/src/ci_checks/core/*",
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
        ("*.md", "**/*.md", ".markdownlint-cli2.jsonc", ".markdownlintignore"),
        flags=("lint_markdown",),
    ),
    SurfaceRule(
        ("proto/*", "proto/**/*"),
        flags=("lint_proto", "proto_breaking", "typecheck_backend"),
        # Regenerated dataclasses land in nohiki-domain-models; rerun its dependents.
        packages=("nohiki-domain-models",),
    ),
    SurfaceRule(
        (
            "typescript/apps/frontend/src/*",
            "typescript/apps/frontend/src/**/*",
            "typescript/apps/frontend/public/*",
            "typescript/apps/frontend/public/**/*",
            "typescript/apps/frontend/scripts/*",
            "typescript/apps/frontend/scripts/**/*",
            "typescript/apps/frontend/__mocks__/*",
            "typescript/apps/frontend/__mocks__/**/*",
            "typescript/apps/frontend/.ast-grep/*",
            "typescript/apps/frontend/.ast-grep/**/*",
            "typescript/apps/frontend/index.html",
            "typescript/apps/frontend/knip.ts",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/biome.jsonc",
            "typescript/apps/frontend/components.json",
            "typescript/apps/frontend/steiger.config.ts",
            "typescript/apps/frontend/tsconfig.json",
            "typescript/apps/frontend/tsconfig.app.json",
            "typescript/apps/frontend/tsconfig.node.json",
            "typescript/apps/frontend/tsconfig.test.json",
            "typescript/apps/frontend/vite.config.ts",
            "typescript/apps/frontend/vitest.config.ts",
            "typescript/apps/frontend/playwright.config.ts",
            "typescript/apps/frontend/Caddyfile",
        ),
        flags=_FRONTEND_APP_FLAGS,
    ),
    SurfaceRule(
        (
            "typescript/apps/frontend/index.html",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/vite.config.ts",
            "typescript/apps/frontend/Caddyfile",
        ),
        flags=("frontend_smoke",),
    ),
    SurfaceRule(
        ("typescript/apps/frontend/e2e/*", "typescript/apps/frontend/e2e/**/*"),
        flags=_FRONTEND_APP_FLAGS,
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
    SurfaceRule(
        (
            "package.json",
            "pnpm-lock.yaml",
            "pnpm-workspace.yaml",
            "typescript/apps/frontend/*",
            "typescript/apps/frontend/**/*",
            "typescript/libs/biome-config/**",
            "typescript/libs/tsconfig/**",
        ),
        flags=("frontend_e2e",),
    ),
    SurfaceRule(
        (".github/workflows/*", ".github/workflows/**/*"),
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
    SurfaceRule(("lefthook.yml",), flags=("nix",), packages=("ci-checks",)),
    SurfaceRule(
        ("Justfile",),
        flags=("image_matrix_parity", "api_schema_freshness", "proto_breaking"),
        packages=("ci-checks",),
    ),
    SurfaceRule(
        ("infra/k8s/local/images.json",),
        flags=("image_matrix_parity",),
        packages=("ci-checks",),
    ),
    SurfaceRule(("docs/api/*", "docs/api/**/*"), flags=("api_schema_freshness",)),
    SurfaceRule(("scripts/util/export-openapi.py",), flags=("api_schema_freshness",)),
    SurfaceRule(("semgrep.yml", "semgrep-overrides.txt"), flags=("hygiene",)),
    SurfaceRule(("scripts/ci/src/ci_checks/checks/*",), packages=("ci-checks",)),
    SurfaceRule(("scripts/ci/tests/*", "scripts/ci/tests/**/*"), packages=("ci-checks",)),
    # Understood, no CI effect. gitleaks runs unconditionally; commitlint
    # always runs on pull requests.
    SurfaceRule(
        (
            ".gitignore",
            ".gitattributes",
            ".editorconfig",
            ".envrc",
            "LICENSE",
            "LICENSE.*",
            ".github/CODEOWNERS",
            ".github/dependabot.yml",
            ".github/renovate.json5",
            ".gitleaks.toml",
            ".commitlintrc*",
            "commitlint.config.*",
            ".vscode/**",
            ".agents/**",
            ".windsurf/**",
            "docs/*",
            "docs/**/*",
        ),
    ),
)
