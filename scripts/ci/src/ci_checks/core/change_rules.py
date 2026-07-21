"""Change-gate policy: which files activate which CI lanes.

Pure data, no I/O. The engine (`core.change_gate`) interprets these tables;
the CLI (`checks.gate`) supplies the diff. Contract tests pin the flag names
against .github/workflows/checks.yml.

Fail-closed tiers:

1. ``GLOBAL_TRIGGERS`` force a full run.
2. ``SURFACE_RULES`` contribute lane flags and package seeds; a file may
   match several rules and every match contributes (union semantics), so
   rule order can never suppress a lane.
3. Files matching nothing force a full run.
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

# Files that invalidate every lane. Deliberately small: each entry is a root
# the whole pipeline depends on.
GLOBAL_TRIGGERS: tuple[str, ...] = (
    "flake.nix",
    "flake.lock",
    "uv.lock",
    "pyproject.toml",  # workspace members, ruff config, dev groups
    ".python-version",
    ".github/workflows/checks.yml",
    "scripts/ci/src/ci_checks/core/*",  # engine, policy, package graph, scanner
    "scripts/ci/src/ci_checks/checks/gate.py",
    "scripts/ci/src/ci_checks/checks/tests.py",
    "scripts/ci/src/ci_checks/app.py",  # Typer command wiring
    "scripts/ci/pyproject.toml",
)

# Application source and toolchain changes exercise every hosted app contract.
_FRONTEND_APP_FLAGS: tuple[str, ...] = (
    "lint_frontend",
    "typecheck_frontend",
    "frontend_tests",
    "frontend_smoke",
)

_FRONTEND_E2E_FLAGS: tuple[str, ...] = (
    "lint_frontend",
    "typecheck_frontend",
    "frontend_e2e",
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
            "typescript/apps/frontend/Caddyfile",
        ),
        flags=_FRONTEND_APP_FLAGS,
    ),
    SurfaceRule(
        ("typescript/apps/frontend/e2e/*", "typescript/apps/frontend/e2e/**/*"),
        flags=_FRONTEND_E2E_FLAGS,
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
            "frontend_e2e",
            "edge_worker",
            "api_schema_freshness",
        ),
    ),
    SurfaceRule(("biome.json", "biome.jsonc"), flags=("lint_frontend", "edge_worker")),
    SurfaceRule(
        ("Dockerfile", "**/Dockerfile", "**/Dockerfile.*", ".hadolint.yaml"),
        flags=("lint_docker",),
        # Image contract tests live in the ci-checks suite.
        packages=("ci-checks",),
    ),
    SurfaceRule(("typescript/apps/frontend/Dockerfile",), flags=("frontend_smoke",)),
    SurfaceRule(
        ("typescript/apps/frontend/Dockerfile.playwright-runner",),
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
        ("Justfile", "infra/k8s/local/images.json"),
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
