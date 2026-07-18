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

from ci_checks.core.packages import Scope

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
    "hygiene",
    "generated_artifacts",
    "proto_breaking",
)

# Matrix lanes; must stay aligned with the python-tests matrix in checks.yml.
TEST_SCOPES: tuple[Scope, ...] = (
    Scope.SERVICES,
    Scope.LIBS,
    Scope.JOBS,
    Scope.SCRIPTS,
    Scope.OTHER,
)

# Services whose FastAPI apps feed scripts/util/export-openapi.py. A change
# reaching either one (directly or through a dependency) can move the merged
# OpenAPI spec, so the generated-artifacts lane must run.
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
    "scripts/ci/src/*",  # the gate and test runner themselves
    "scripts/ci/pyproject.toml",
)

# Any frontend source or toolchain change must lint, typecheck, unit-test,
# and container-smoke the frontend.
_FRONTEND_FLAGS: tuple[str, ...] = (
    "lint_frontend",
    "typecheck_frontend",
    "frontend_tests",
    "frontend_smoke",
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
    SurfaceRule(("*.md", "**/*.md", ".markdownlint-cli2.jsonc"), flags=("lint_markdown",)),
    SurfaceRule(
        ("proto/*", "proto/**/*"),
        flags=("lint_proto", "proto_breaking"),
        # Regenerated dataclasses land in nohiki-domain-models; rerun its dependents.
        packages=("nohiki-domain-models",),
    ),
    SurfaceRule(("typescript/*", "typescript/**/*"), flags=_FRONTEND_FLAGS),
    SurfaceRule(
        ("typescript/apps/frontend/src/api/schema.d.ts",),
        flags=("generated_artifacts",),
    ),
    SurfaceRule(
        # openapi-typescript and vitest versions move generated output and tests.
        ("pnpm-lock.yaml", "pnpm-workspace.yaml", "package.json", ".npmrc"),
        flags=(*_FRONTEND_FLAGS, "generated_artifacts"),
    ),
    SurfaceRule(("biome.json", "biome.jsonc"), flags=("lint_frontend",)),
    SurfaceRule(
        ("Dockerfile", "**/Dockerfile", "**/Dockerfile.*", ".hadolint.yaml"),
        flags=("lint_docker",),
        # Image contract tests live in the ci-checks suite.
        packages=("ci-checks",),
    ),
    SurfaceRule(("typescript/apps/frontend/Dockerfile",), flags=("frontend_smoke",)),
    SurfaceRule(
        (".github/workflows/*", ".github/workflows/**/*"),
        flags=("lint_workflows",),
        packages=("ci-checks",),
    ),
    SurfaceRule((".github/workflows/build-push.yml",), flags=("generated_artifacts",)),
    # Helm, compose, gitops, and Qdrant contract tests live in ci-checks.
    SurfaceRule(("infra/*", "infra/**/*"), packages=("ci-checks",)),
    # Migration-truth contract tests pin every service's Alembic head.
    SurfaceRule(("backend/services/*/alembic/**/*",), packages=("ci-checks",)),
    SurfaceRule(("lefthook.yml",), flags=("nix",), packages=("ci-checks",)),
    SurfaceRule(("Justfile",), flags=("generated_artifacts",), packages=("ci-checks",)),
    SurfaceRule(("docs/api/*", "docs/api/**/*"), flags=("generated_artifacts",)),
    SurfaceRule(("scripts/util/export-openapi.py",), flags=("generated_artifacts",)),
    SurfaceRule(("semgrep.yml", "semgrep-overrides.txt"), flags=("hygiene",)),
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
            ".markdownlintignore",
        ),
    ),
)
