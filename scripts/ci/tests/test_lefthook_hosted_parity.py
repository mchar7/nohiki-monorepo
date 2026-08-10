"""Parity contract between the local lefthook battery and the hosted check lanes.

The hosted workflow is the full-surface backstop; a local hook glob must be a
superset of the file surface that activates its mirrored hosted lane, restricted
to the inputs the local command actually reads. Hosted ownership is data, so the
drift tests import the change-gate tables and replay them over the tracked file
list rather than restating any pattern.
"""

from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from ci_checks.core.change_rules import (
    API_EXPORT_SERVICES,
    BROAD_RULES,
    FLAG_NAMES,
    SURFACE_RULES,
)
from ci_checks.core.packages import (
    REPO_ROOT,
    PackageType,
    Scope,
    build_reverse_dependency_index,
    expand_to_dependents,
    load_packages_with_deps,
)

_ROOT = Path(__file__).resolve().parents[3]
_LEFTHOOK = _ROOT / "lefthook.yml"
_CHECKS = _ROOT / ".github" / "workflows" / "checks.yml"
_JUSTFILE = _ROOT / "Justfile"
_PYPROJECT = _ROOT / "pyproject.toml"

# Every Python file, manifest and toolchain pin a workspace push lane must react to.
# `.python-version`, `pyproject.toml` and `uv.lock` reach the hosted broad Python
# class (change_rules.py:113-122), so a lock-only push must not skip the local lane.
# The shallow siblings are mandatory: gobwas reads `**` as "anything followed by a
# separator", so `tests/**/*.py` never selects `tests/conftest.py`.
_PYTHON_WORKSPACE_SURFACE = frozenset(
    {
        "backend/*.py",
        "backend/**/*.py",
        "backend/pyproject.toml",
        "backend/**/pyproject.toml",
        "scripts/*.py",
        "scripts/**/*.py",
        "scripts/pyproject.toml",
        "scripts/**/pyproject.toml",
        "infra/*.py",
        "infra/**/*.py",
        "infra/pyproject.toml",
        "infra/**/pyproject.toml",
        "tests/*.py",
        "tests/**/*.py",
        "tests/pyproject.toml",
        "tests/**/pyproject.toml",
        "pyproject.toml",
        "uv.lock",
        ".python-version",
    }
)
_NODE_TOOLCHAIN_SURFACE = frozenset({"package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", ".npmrc"})
_PROTO_CONTRACT_SURFACE = frozenset({"proto/*.proto", "proto/**/*.proto", "proto/buf.yaml", "proto/buf.lock"})

# The frontend app directory hosted assigns to the app lanes. Shallow and nested
# entries are both required for the same gobwas reason as the Python surface.
_FRONTEND_SRC_SURFACE = frozenset(
    {
        "typescript/apps/frontend/src/*.{ts,tsx}",
        "typescript/apps/frontend/src/**/*.{ts,tsx}",
    }
)
_FRONTEND_LOCALE_SURFACE = frozenset(
    {
        "typescript/apps/frontend/public/locales/*",
        "typescript/apps/frontend/public/locales/**/*",
    }
)

# Library entries of the api-schema hook, kept honest by the closure test below.
_API_EXPORT_LIB_GLOBS = frozenset(
    f"backend/libs/{name}/**/*.py"
    for name in (
        "nohiki-common-exceptions",
        "nohiki-core-settings",
        "nohiki-db-utils",
        "nohiki-domain-models",
        "nohiki-fastapi-utils",
        "nohiki-kafka-client",
        "nohiki-observability",
        "nohiki-redis-utils",
        "nohiki-s3-client",
        "nohiki-test-utils",
    )
)

# Every local hook is mapped so additions fail closed until their hosted parity is explicit.
_EXPECTED_SURFACES: dict[str, dict[str, frozenset[str]]] = {
    "pre-commit": {
        "python-check-format": frozenset({"*.py"}),
        "frontend-lint": frozenset({"*.{ts,tsx,js,jsx,mjs,css}"}),
        "proto-lint": _PROTO_CONTRACT_SURFACE,
        "markdown-lint": frozenset({"*.md", ".markdownlint-cli2.jsonc", ".markdownlintignore", ".markdownlint.json"}),
        "i18n-check": _FRONTEND_SRC_SURFACE
        | {
            "typescript/apps/frontend/public/locales/**",
            "typescript/apps/frontend/scripts/i18n-check.mjs",
            "typescript/apps/frontend/scripts/i18n/*",
            "typescript/apps/frontend/scripts/i18n/**/*",
        },
        "secrets-check": frozenset(),
        "actions-lint": frozenset({".github/workflows/*.{yml,yaml}", ".github/actions/**"}),
        "docker-lint": frozenset({"**/Dockerfile{,.*}", "Dockerfile", ".hadolint.yaml"}),
    },
    "pre-push": {
        # Not a check and has no hosted counterpart: it exists so the envelope can
        # tell "the gate ran" from "the gate selected no files and skipped
        # everything". Unglobbed on purpose, since an empty selection skips
        # unglobbed jobs too and that is precisely the condition being detected.
        "gate-liveness": frozenset(),
        "secrets-scan": frozenset(),
        "python-lint": frozenset(),
        "python-format": frozenset(),
        "python-typecheck": _PYTHON_WORKSPACE_SURFACE,
        "frontend-typecheck": _NODE_TOOLCHAIN_SURFACE
        | {
            "typescript/apps/frontend/**/*.{ts,tsx}",
            "typescript/apps/frontend/public/*",
            "typescript/apps/frontend/public/**/*",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/tsconfig*.json",
            "typescript/apps/frontend/vite.config.*",
            "typescript/apps/frontend/vitest.config.*",
            "typescript/libs/**",
        },
        "edge-typecheck": _NODE_TOOLCHAIN_SURFACE
        | {
            "typescript/edge/auth-listings-worker/src/*.ts",
            "typescript/edge/auth-listings-worker/src/**/*.ts",
            "typescript/edge/auth-listings-worker/package.json",
            "typescript/edge/auth-listings-worker/tsconfig.json",
            "typescript/libs/**",
        },
        "frontend-lint-all": _NODE_TOOLCHAIN_SURFACE
        | {
            "typescript/apps/frontend/src/*",
            "typescript/apps/frontend/src/**/*",
            "typescript/apps/frontend/scripts/*",
            "typescript/apps/frontend/scripts/**/*",
            "typescript/apps/frontend/e2e/*",
            "typescript/apps/frontend/e2e/**/*",
            "typescript/apps/frontend/public/theme-init.js",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/biome.jsonc",
            "typescript/apps/frontend/tsconfig*.json",
            "typescript/libs/**",
            "typescript/libs/biome-config/biome.json",
        },
        "edge-lint": _NODE_TOOLCHAIN_SURFACE
        | {
            "typescript/edge/auth-listings-worker/src/*",
            "typescript/edge/auth-listings-worker/src/**/*",
            "typescript/edge/auth-listings-worker/package.json",
            "typescript/edge/auth-listings-worker/biome.jsonc",
            "typescript/libs/**",
            "typescript/libs/biome-config/biome.json",
        },
        "nix-check": frozenset({"flake.nix", "flake.lock"}),
        # No glob: the affected-test runner owns the selection policy. Asserted by
        # test_affected_test_selection_is_delegated_to_the_runner.
        "python-tests": frozenset(),
        # No glob: this opt-in gate always reproduces the hosted package selection.
        "job-correlation-integration": frozenset(),
        "skylos-cache-tests": frozenset(
            {
                "scripts/ci/src/ci_checks/checks/skylos_cache.py",
                "scripts/ci/tests/test_skylos_cache.py",
            }
        ),
        "node-workspace-contract-tests": frozenset(),
        "frontend-tests": _NODE_TOOLCHAIN_SURFACE
        | _FRONTEND_LOCALE_SURFACE
        | {
            "typescript/apps/frontend/src/**/*.{ts,tsx}",
            "typescript/apps/frontend/__mocks__/*",
            "typescript/apps/frontend/__mocks__/**/*",
            "typescript/apps/frontend/scripts/*",
            "typescript/apps/frontend/scripts/**/*",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/tsconfig*.json",
            "typescript/apps/frontend/vite.config.*",
            "typescript/apps/frontend/vitest.config.*",
            "typescript/libs/**",
        },
        "edge-tests": _NODE_TOOLCHAIN_SURFACE
        | {
            "typescript/edge/auth-listings-worker/src/*.ts",
            "typescript/edge/auth-listings-worker/src/**/*.ts",
            "typescript/edge/auth-listings-worker/package.json",
            "typescript/edge/auth-listings-worker/tsconfig.json",
            "typescript/edge/auth-listings-worker/vitest.config.*",
            "typescript/libs/**",
        },
        "deadcode": _PYTHON_WORKSPACE_SURFACE,
        "deptry": _PYTHON_WORKSPACE_SURFACE,
        "semgrep": frozenset({"backend/**/*.py", "semgrep.yml", "semgrep-overrides.txt"}),
        "build-backend": _PYTHON_WORKSPACE_SURFACE,
        "frontend-fsd": _NODE_TOOLCHAIN_SURFACE
        | {
            "typescript/apps/frontend/src/*",
            "typescript/apps/frontend/src/**/*",
            "typescript/apps/frontend/package.json",
            "typescript/apps/frontend/steiger.config.ts",
            "typescript/apps/frontend/tsconfig*.json",
            "typescript/libs/**",
        },
        "api-schema-freshness": _API_EXPORT_LIB_GLOBS
        | _NODE_TOOLCHAIN_SURFACE
        | {
            "backend/services/bff-service/**/*.py",
            "backend/services/user-auth-service/**/*.py",
            "scripts/util/export-openapi.py",
            "docs/api/nohiki.openapi.json",
            "typescript/apps/frontend/src/api/schema.d.ts",
            "uv.lock",
            "pyproject.toml",
            "Justfile",
        },
        "image-matrix-parity": frozenset(
            {
                "Justfile",
                ".github/workflows/build-push.yml",
                "infra/k8s/local/images.json",
                "scripts/ci/image_inventory.json",
                "scripts/ci/image_matrix.py",
            }
        ),
        "proto-breaking": _PROTO_CONTRACT_SURFACE
        | {
            "proto/.breaking-allowlist.json",
            "scripts/proto_gen/*.py",
            "scripts/proto_gen/**/*.py",
            "scripts/proto_gen/pyproject.toml",
        },
    },
}

# Which local jobs mirror each hosted lane flag. A flag gated on several hosted
# steps carries one group per step and every group must cover the surface on its
# own; a group of several jobs is one hosted step whose local surface is split,
# so there the union carries the hosted inputs. checks.yml gates two steps on
# `lint_frontend`: "Lint frontend" (:436-438) and "Check i18n keys" (:445-447).
_HOSTED_LANE_MIRRORS: dict[str, tuple[tuple[str, ...], ...]] = {
    "lint_python": (("python-check-format",),),
    "lint_frontend": (("frontend-lint",), ("i18n-check",)),
    "lint_proto": (("proto-lint",),),
    "lint_markdown": (("markdown-lint",),),
    "lint_workflows": (("actions-lint",),),
    "lint_docker": (("docker-lint",),),
    "lint_steiger": (("frontend-fsd",),),
    "typecheck_backend": (("python-typecheck",),),
    "typecheck_frontend": (("frontend-typecheck",),),
    "python_any": (("python-tests",),),
    "frontend_tests": (("frontend-tests",),),
    "build_backend": (("build-backend",),),
    "hygiene": (("deptry", "semgrep"),),
    "api_schema_freshness": (("api-schema-freshness",),),
    "image_matrix_parity": (("image-matrix-parity",),),
    "proto_breaking": (("proto-breaking",),),
    "nix": (("nix-check",),),
}

# The change gate's own sources and the devshell that runs every lane. Hosted fails
# these closed to the broad class; the local battery deliberately does not re-run
# every hook when the router or the toolchain image moves, and the Python jobs
# already own the router modules through the workspace surface.
_HOSTED_SELF_REFERENCE = frozenset(
    {
        "flake.nix",
        "flake.lock",
        ".github/workflows/checks.yml",
        ".github/actions/setup-ci/action.yml",
        "scripts/ci/src/ci_checks/core/change_gate.py",
        "scripts/ci/src/ci_checks/core/change_rules.py",
        "scripts/ci/src/ci_checks/checks/gate.py",
        "scripts/ci/src/ci_checks/checks/tests.py",
    }
)

# Hosted inputs a local command provably does not read, keyed by the job that
# leads the mirror group and a glob over the repository paths it excuses. Each
# entry states why, and both grounding tests below delete it once it stops
# describing an unclaimed hosted surface.
_NOT_EXERCISED_LOCALLY: dict[tuple[str, str], str] = {
    (
        "python-check-format",
        ".python-version",
    ): "the staged formatter reads Python files; toolchain pins are pre-push work",
    ("python-check-format", "pyproject.toml"): "a ruff config change is applied to the *.py surface of the same commit",
    ("python-check-format", "uv.lock"): "a lock entry carries no Python source for ruff to format",
    ("frontend-lint", "biome.json"): "a root biome config change applies to the staged surface",
    ("frontend-lint", "biome.jsonc"): "a root biome config change applies to the staged surface",
    ("frontend-lint", ".npmrc"): "biome resolves from the shared node_modules lock, not from registry config",
    ("frontend-lint", "package.json"): "root manifests carry no biome-linted source",
    ("frontend-lint", "pnpm-lock.yaml"): "root manifests carry no biome-linted source",
    ("frontend-lint", "pnpm-workspace.yaml"): "root manifests carry no biome-linted source",
    (
        "frontend-lint",
        "typescript/libs/**",
    ): "biome runs inside the frontend package; workspace libs are outside its file list",
    ("frontend-lint", "typescript/apps/frontend/biome.jsonc"): "a config change applies to the staged surface",
    ("frontend-lint", "typescript/apps/frontend/package.json"): "manifests carry no biome-linted source",
    ("frontend-lint", "typescript/apps/frontend/tsconfig*.json"): "biome does not read tsconfig",
    ("frontend-lint", "typescript/apps/frontend/public/**"): (
        "biome's file list is src, scripts and e2e (biome.jsonc:6-15); public assets are outside it"
    ),
    ("frontend-lint", "typescript/apps/frontend/e2e/*.md"): "biome has no markdown language",
    ("i18n-check", "{package.json,pnpm-lock.yaml,pnpm-workspace.yaml,.npmrc,biome.json,biome.jsonc}"): (
        "the key checker runs inside the frontend package and reads no root manifest"
    ),
    ("i18n-check", "typescript/libs/**"): "the key checker scans the frontend app tree, not the workspace libs",
    ("i18n-check", "typescript/apps/frontend/e2e/**"): "Playwright specs carry no translation namespace",
    ("i18n-check", "typescript/apps/frontend/__mocks__/**"): "module mocks carry no translation keys",
    ("i18n-check", "typescript/apps/frontend/scripts/generate-api*.mjs"): (
        "the schema generator is not imported by scripts/i18n-check.mjs"
    ),
    # Named exactly rather than as `scripts/*.test.mjs`: fnmatch wildcards cross separators here,
    # so that pattern would also exempt `scripts/i18n/*.test.mjs`, which tests the key checker
    # itself and must keep reaching it.
    ("i18n-check", "typescript/apps/frontend/scripts/worker-bound.test.mjs"): (
        "the worker-bound test is not imported by scripts/i18n-check.mjs and carries no keys"
    ),
    (
        "i18n-check",
        "typescript/apps/frontend/public/*",
    ): "the checker reads public/locales, not the static assets beside it",
    ("i18n-check", "typescript/apps/frontend/src/**/*.css"): "the key scanner reads TS and TSX sources",
    (
        "i18n-check",
        "typescript/apps/frontend/{biome.jsonc,package.json,tsconfig*.json,vite.config.ts,vitest.config.ts}",
    ): ("the checker reads locale files and sources, not the build and lint configuration"),
    ("frontend-typecheck", "typescript/apps/frontend/biome.jsonc"): "tsc does not read the biome config",
    ("frontend-typecheck", "typescript/apps/frontend/e2e/*.{md,json}"): (
        "tsconfig.node.json type-checks e2e TypeScript; its README and tsconfig are not program inputs"
    ),
    ("frontend-typecheck", "typescript/apps/frontend/e2e/*.mjs"): "the e2e runner script is JavaScript tsc never loads",
    ("frontend-typecheck", "typescript/apps/frontend/scripts/**"): (
        "no tsconfig include covers scripts/; the checker scripts are plain ESM"
    ),
    ("frontend-typecheck", "typescript/apps/frontend/src/**/*.css"): "tsc does not resolve stylesheets",
    ("frontend-tests", "typescript/apps/frontend/biome.jsonc"): "vitest does not read the biome config",
    ("frontend-tests", "typescript/apps/frontend/src/*.{ts,tsx}"): (
        "main.tsx, routeTree.gen.ts and vite-env.d.ts reach no vitest project: the node, dom and ui "
        "includes select test modules only, and `pnpm test --run` enables no coverage pass over src"
    ),
    ("frontend-tests", "typescript/apps/frontend/src/**/*.css"): "vitest.config.ts enables no CSS processing",
    (
        "frontend-tests",
        "typescript/apps/frontend/public/*",
    ): "the setup imports public/locales; the static assets beside it are unused",
    ("frontend-fsd", "typescript/apps/frontend/biome.jsonc"): "steiger does not read the biome config",
    ("frontend-fsd", "typescript/apps/frontend/vite.config.ts"): "steiger scans the FSD source tree, not build config",
    ("frontend-fsd", "typescript/apps/frontend/vitest.config.ts"): "steiger scans the FSD tree, not test config",
    ("frontend-fsd", "typescript/apps/frontend/{__mocks__,scripts,public,e2e}/**"): (
        "steiger.config.ts scans ./src; every sibling directory is outside the FSD root"
    ),
    (
        "docker-lint",
        "**/*.j2",
    ): "hadolint cannot parse a Jinja template; the hosted step excludes it too (checks.yml:453)",
    (
        "docker-lint",
        "**/*.dockerignore",
    ): "a dockerignore is not a Dockerfile; the hosted step excludes it too (checks.yml:453)",
    ("python-typecheck", "proto/*"): (
        "a proto edit moves no Python source until `just proto-gen` regenerates the dataclasses"
    ),
    ("python-typecheck", "proto/**/*"): (
        "a proto edit moves no Python source until `just proto-gen` regenerates the dataclasses"
    ),
    (
        "proto-lint",
        "proto/.breaking-allowlist.json",
    ): "buf lint does not consume the breaking-allowlist; only proto-breaking reads it",
}


# Nested globs whose shallow twin is deliberately absent, keyed by job and pattern.
_SHALLOW_SIBLING_WAIVERS: dict[tuple[str, str], str] = {
    ("frontend-tests", "typescript/apps/frontend/src/**/*.{ts,tsx}"): (
        "no vitest project collects the shallow src entrypoints; see the matching exemption above"
    ),
    ("frontend-typecheck", "typescript/apps/frontend/**/*.{ts,tsx}"): (
        "the shallow app-root TypeScript is vite.config.ts, vitest.config.ts, steiger.config.ts and "
        "knip.ts; the first two carry their own entries and the last two are in no tsconfig include"
    ),
}


def _as_mapping(value: object) -> Mapping[str, object]:
    """Narrow a parsed YAML node to a string-keyed mapping."""
    assert isinstance(value, Mapping)
    return {str(key): item for key, item in value.items()}


@cache
def _load_config() -> Mapping[str, object]:
    return _as_mapping(yaml.safe_load(_LEFTHOOK.read_text(encoding="utf-8")))


def _pre_push_jobs(node: object) -> Iterator[Mapping[str, object]]:
    """Yield every named job nested in the pre-push phase groups."""
    if isinstance(node, Mapping):
        mapping = _as_mapping(node)
        if isinstance(mapping.get("name"), str):
            yield mapping
        for child in mapping.values():
            yield from _pre_push_jobs(child)
    elif isinstance(node, list):
        for child in node:
            yield from _pre_push_jobs(child)


def _pattern_set(command: Mapping[str, object], key: str) -> frozenset[str]:
    """Return one glob-valued lefthook key as a set, empty when the key is absent."""
    value = command.get(key)
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value})
    assert isinstance(value, list)
    assert all(isinstance(pattern, str) for pattern in value)
    return frozenset(str(pattern) for pattern in value)


def _glob_set(command: Mapping[str, object]) -> frozenset[str]:
    """Return the glob patterns a lefthook command declares, empty when unconditional."""
    return _pattern_set(command, "glob")


@cache
def _configured_hooks() -> dict[str, dict[str, Mapping[str, object]]]:
    """Map each hook to its declared commands or named jobs."""
    config = _load_config()
    commands = _as_mapping(_as_mapping(config["pre-commit"])["commands"])
    return {
        "pre-commit": {name: _as_mapping(command) for name, command in commands.items()},
        "pre-push": {str(job["name"]): job for job in _pre_push_jobs(config["pre-push"])},
    }


def _job(name: str) -> Mapping[str, object]:
    """Return the sole command or job any hook declares under the given name."""
    matches = [hooks[name] for hooks in _configured_hooks().values() if name in hooks]
    assert len(matches) == 1, f"lefthook must declare exactly one {name} command"
    return matches[0]


def _run_command(name: str) -> str:
    """Return the shell command a named hook entry runs."""
    command = _job(name)["run"]
    assert isinstance(command, str)
    return command


def _hosted_owners(flag: str) -> frozenset[str]:
    """Every change-rule pattern that activates a hosted lane flag."""
    return frozenset(
        pattern for rule in (*BROAD_RULES, *SURFACE_RULES) if flag in rule.flags for pattern in rule.patterns
    )


def _expand_braces(pattern: str) -> Iterator[str]:
    """Expand brace alternation, which fnmatch does not understand but the glob engine does."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if match is None:
        yield pattern
        return
    for alternative in match[1].split(","):
        yield from _expand_braces(pattern[: match.start()] + alternative + pattern[match.end() :])


def _claims(patterns: frozenset[str] | set[str], literal: str) -> bool:
    """Whether a glob set selects an exact repository path.

    fnmatch is the matcher the change rules themselves use and, like the default
    gobwas engine without separators, its wildcards cross directory boundaries.
    A `**/` segment therefore still demands a separator, which is why every
    directory surface needs a shallow entry beside its nested one.
    """
    return any(fnmatch.fnmatch(literal, candidate) for pattern in patterns for candidate in _expand_braces(pattern))


def _selects(job_name: str, path: str) -> bool:
    """Whether lefthook would hand a repository path to a named hook entry.

    Mirrors `Filter.Apply`: glob first, then exclude, then root, all against
    repository-root relative paths.
    """
    command = _job(job_name)
    globs = _glob_set(command)
    if globs and not _claims(globs, path):
        return False
    if _claims(_pattern_set(command, "exclude"), path):
        return False
    root = command.get("root")
    return not (isinstance(root, str) and not path.startswith(root.rstrip("/") + "/"))


def _group_selects(jobs: tuple[str, ...], path: str) -> bool:
    return any(_selects(name, path) for name in jobs)


def _exempt(lead_job: str, path: str) -> bool:
    return any(_claims({pattern}, path) for (exempt_job, pattern) in _NOT_EXERCISED_LOCALLY if exempt_job == lead_job)


@cache
def _tracked_files() -> tuple[str, ...]:
    """Every path git tracks, which is the population the hooks and the gate both filter."""
    listing = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files = tuple(path for path in listing.split("\0") if path)
    assert len(files) > 1000, "git ls-files returned an implausibly small tree"
    return files


@cache
def _workspace_package_dirs() -> tuple[str, ...]:
    packages = load_packages_with_deps(Scope.ALL)
    return tuple(package.path.relative_to(REPO_ROOT).as_posix() for package in packages.values())


def _hosted_effect(path: str) -> tuple[frozenset[str], bool, bool]:
    """Replay `change_gate.evaluate` for one path.

    Returns:
        The rule-declared lane flags, whether the path seeds an affected package,
        and whether any rule claimed it at all. An unclaimed path is the gate's
        fail-closed escape hatch: it selects the broad class, which the local
        battery does not mirror, so the coverage test skips it.
    """
    flags: set[str] = set()
    seeded = False
    matched = False
    for rule in (*BROAD_RULES, *SURFACE_RULES):
        if rule.matches(path):
            matched = True
            flags.update(rule.flags)
            seeded = seeded or bool(rule.packages)
    for directory in _workspace_package_dirs():
        if path == directory or path.startswith(f"{directory}/"):
            matched = True
            seeded = True
            break
    if path.endswith(".py"):
        flags.add("lint_python")
    return frozenset(flags), seeded, matched


def _mirrored_globs(job_names: tuple[str, ...]) -> set[str]:
    configured: set[str] = set()
    for name in job_names:
        configured |= _glob_set(_job(name))
    return configured


def test_local_hook_globs_cover_hosted_lane_surfaces() -> None:
    """Local file gates must include every input surface checked by their hosted counterpart."""
    configured = _configured_hooks()

    for hook, expected in _EXPECTED_SURFACES.items():
        actual = configured[hook]
        assert actual.keys() == expected.keys(), f"{hook} hooks require an explicit hosted-surface mapping"
        for name, required_globs in expected.items():
            configured_globs = _glob_set(actual[name])
            assert required_globs <= configured_globs, (
                f"{hook}.{name} does not cover its hosted surface: missing {sorted(required_globs - configured_globs)}"
            )


def test_hook_globs_cover_every_hosted_owned_file() -> None:
    """Every tracked file a hosted lane owns reaches each local mirror of that lane.

    This is the drift test proper: it replays the change-gate tables over the real
    tree instead of comparing pattern text, so a hosted rule that grows a surface
    and a local glob that silently misses one both fail here.
    """
    gaps: list[str] = []
    for path in _tracked_files():
        if path in _HOSTED_SELF_REFERENCE:
            continue
        flags, _, matched = _hosted_effect(path)
        if not matched:
            continue
        for flag in sorted(flags):
            for jobs in _HOSTED_LANE_MIRRORS.get(flag, ()):
                if _group_selects(jobs, path) or _exempt(jobs[0], path):
                    continue
                gaps.append(f"{flag} -> {'+'.join(jobs)} skips {path}")
    assert not gaps, "local hooks skip hosted-owned files:\n" + "\n".join(sorted(gaps))


def test_affected_test_selection_is_delegated_to_the_runner() -> None:
    """The push test job carries no glob, so nothing narrows the affected-package closure.

    Hosted seeds a package from a change-rule `packages=` entry or from the package
    directory that owns the path, then `_derive_package_flags` turns any non-empty
    closure into `python_any`. That policy has one authority, `ci-checks tests
    affected`, and a local glob restating it is what drifts.
    """
    job = _job("python-tests")
    assert "glob" not in job, "python-tests must not re-implement the affected-package policy as a glob"
    assert "ci-checks tests affected --mode push" in _run_command("python-tests")

    unreachable = sorted(
        path
        for path in _tracked_files()
        if path not in _HOSTED_SELF_REFERENCE and _hosted_effect(path)[1] and not _selects("python-tests", path)
    )
    assert not unreachable, f"the push test job cannot see files that seed a hosted package: {unreachable}"


def test_unconditional_hooks_declare_no_glob() -> None:
    """Secret scanners inspect commits, not a file surface, so they carry no glob."""
    for name in ("secrets-check", "secrets-scan"):
        assert "glob" not in _job(name), f"{name} must stay unconditional"
    commands = _as_mapping(_as_mapping(_load_config()["commit-msg"])["commands"])
    for name, command in commands.items():
        assert "glob" not in _as_mapping(command), f"commit-msg.{name} must stay unconditional"


def test_hook_glob_exemptions_stay_grounded_in_hosted_ownership() -> None:
    """An exemption is deleted once its files leave hosted ownership or become claimed."""
    leads = {jobs[0]: flag for flag, groups in _HOSTED_LANE_MIRRORS.items() for jobs in groups}
    jobs_by_lead = {jobs[0]: jobs for groups in _HOSTED_LANE_MIRRORS.values() for jobs in groups}

    unowned: list[str] = []
    redundant: list[str] = []
    for lead_job, pattern in _NOT_EXERCISED_LOCALLY:
        assert lead_job in leads, f"{lead_job} leads no mirror group; the exemption table is stale"
        flag = leads[lead_job]
        owned = [
            path
            for path in _tracked_files()
            if _claims({pattern}, path) and path not in _HOSTED_SELF_REFERENCE and flag in _hosted_effect(path)[0]
        ]
        if not owned:
            # A hosted rule may own a path the tree does not carry yet; the pattern
            # itself must then still appear in that lane's ownership table.
            if pattern not in _hosted_owners(flag):
                unowned.append(f"{lead_job}:{pattern}")
            continue
        if all(_group_selects(jobs_by_lead[lead_job], path) for path in owned):
            redundant.append(f"{lead_job}:{pattern}")

    assert not unowned, f"exemptions no longer describe a hosted surface: {sorted(unowned)}"
    assert not redundant, f"exemptions describe surfaces the hooks already claim: {sorted(redundant)}"


def test_hosted_lane_mirrors_name_real_flags_and_jobs() -> None:
    """The mirror table stays anchored to the hosted flag list and the configured jobs."""
    configured = {name for hooks in _configured_hooks().values() for name in hooks}
    for flag, groups in _HOSTED_LANE_MIRRORS.items():
        assert flag in FLAG_NAMES, f"{flag} is not a hosted lane flag; the mirror table is stale"
        assert groups, f"{flag} needs at least one mirror group"
        for jobs in groups:
            assert set(jobs) <= configured, f"{flag} mirrors jobs lefthook does not declare: {sorted(jobs)}"


def test_pre_commit_uses_scheduler_level_file_filtering() -> None:
    """Argument-taking tools consume staged inventories; no-argument tools use literal commands plus globs."""
    configured = _configured_hooks()["pre-commit"]

    # Mutators with potentially large inventories derive NUL-safe path lists directly
    # from Git; the frontend mutator can safely consume Lefthook's staged template.
    for name in ("python-check-format", "markdown-lint"):
        run = _run_command(name)
        assert "{staged_files}" not in run
        assert "git diff --cached" in run

    assert "{staged_files}" in _run_command("frontend-lint")

    for name in ("proto-lint", "i18n-check", "actions-lint", "docker-lint"):
        assert _glob_set(configured[name]), f"{name} needs a glob to drive the scheduler skip"
        assert "{staged_files}" not in _run_command(name)

    assert "glob" not in configured["secrets-check"]


def test_hook_globs_use_the_default_glob_engine() -> None:
    """Excludes stay globs and no hook opts into an alternative matcher."""
    assert "glob_matcher" not in _LEFTHOOK.read_text(encoding="utf-8")
    for hooks in _configured_hooks().values():
        for name, command in hooks.items():
            exclude = command.get("exclude")
            if exclude is None:
                continue
            assert isinstance(exclude, list), f"{name} exclude must be a glob list"
            assert all(isinstance(pattern, str) for pattern in exclude)


def test_directory_globs_carry_a_shallow_sibling() -> None:
    """Every `dir/**/...` entry needs a `dir/...` twin, because gobwas demands the separator.

    A nested entry hides the files sitting directly in its root, which is the defect
    class behind `tests/conftest.py`, `proto/*.proto` and the shallow `src` sources.
    Excludes stay outside the rule: a miss there widens the inspected set rather than
    narrowing it.
    """
    missing: list[str] = []
    for hooks in _configured_hooks().values():
        for name, command in hooks.items():
            globs = _glob_set(command)
            for pattern in globs:
                if "/**/" not in pattern:
                    continue
                shallow = pattern.replace("/**/", "/", 1)
                hidden = [path for path in _tracked_files() if _claims({shallow}, path) and not _claims(globs, path)]
                if hidden and (name, pattern) not in _SHALLOW_SIBLING_WAIVERS:
                    missing.append(f"{name}: {pattern} needs {shallow} for {sorted(hidden)[0]}")
    assert not missing, "nested globs hide the files directly inside their root:\n" + "\n".join(sorted(missing))


def _hosted_typecheck_step_run() -> str:
    steps = yaml.safe_load(_CHECKS.read_text(encoding="utf-8"))["jobs"]["worker"]["steps"]
    matches = [step["run"] for step in steps if step.get("name") == "Typecheck backend"]
    assert len(matches) == 1, "checks.yml must declare exactly one Typecheck backend step"
    return str(matches[0])


def _just_typecheck_recipe_run() -> str:
    match = re.search(r"(?m)^typecheck-all:\n(?P<body>(?:    .*\n)+)", _JUSTFILE.read_text(encoding="utf-8"))
    assert match is not None, "Justfile must declare typecheck-all"
    return " ".join(line.strip() for line in match["body"].splitlines())


def test_typecheck_entry_points_use_the_native_surface() -> None:
    """Every typecheck entry point must delegate its complete scope to ty."""
    commands = {
        "Justfile": _just_typecheck_recipe_run(),
        "lefthook.yml": _run_command("python-typecheck"),
        "checks.yml": _hosted_typecheck_step_run(),
    }
    for name, command in commands.items():
        effective = _expand_entrypoint(command)
        assert re.search(r"(?:^|\s)ty check(?:\s|$)", effective), (
            f"{name} diverges from the native ty surface: expected a delegated bare 'ty check', got {command!r}"
        )
        assert "--exclude" not in command

    config = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    ty_src = config["tool"]["ty"]["src"]
    assert {"infra/k8s/gitops", "tests"} <= set(ty_src["include"])
    assert {"**/alembic/**", "**/nohiki-domain-models/**"} <= set(ty_src["exclude"])


def test_api_schema_hook_glob_tracks_the_exporter_dependency_closure() -> None:
    """The hook's library entries must equal the closure hosted reverse expansion selects."""
    packages = load_packages_with_deps(Scope.ALL)
    reverse = build_reverse_dependency_index(packages)
    closure = {
        name
        for name, package in packages.items()
        if package.pkg_type is PackageType.LIB and expand_to_dependents({name}, reverse) & API_EXPORT_SERVICES
    }
    assert closure, "no library reaches an API export service; the closure derivation is wrong"

    configured = _glob_set(_job("api-schema-freshness"))
    pattern = re.compile(r"backend/libs/(?P<name>[^/]+)/\*\*/\*\.py")
    declared = {match["name"] for entry in configured if (match := pattern.fullmatch(entry))}
    assert declared == closure, (
        f"api-schema-freshness library globs drifted from the exporter closure: "
        f"missing {sorted(closure - declared)}, stale {sorted(declared - closure)}"
    )
    assert "backend/libs/**/*.py" not in configured, "the enumerated closure replaces the overbroad library glob"


_CHECK_PATTERNS: dict[str, str] = {
    "actionlint": r"\bactionlint\b",
    "api-schema": r"\bexport-openapi\.py\b",
    "build-backend": r"\bci-checks build-backend\b",
    "deadcode": r"\bci-checks deadcode\b",
    "deptry": r"\bci-checks deptry\b",
    "docker-lint": r"\bhadolint\b",
    "fixtures": r"\bci-checks (?:fixtures|tests)\b",
    "frontend-architecture": r"\bsteiger\b",
    "frontend-lint": r"\bbiome (?:check|ci)\b",
    "frontend-test": r"\bvitest\b",
    "frontend-typecheck": r"\btsc\b",
    "i18n": r"\bi18n-check\.mjs\b",
    "image-matrix": r"\bimage_matrix\.py\b",
    "markdown-lint": r"\bmarkdownlint-cli2\b",
    "nix": r"\bnix flake check\b",
    "node-contracts": r"\brequires_node_modules\b",
    "proto-breaking": r"\bbuf breaking\b",
    "proto-lint": r"\bbuf lint\b",
    "python-lint": r"\bruff check\b",
    "python-format": r"\bruff format\b",
    "python-test": r"\b(?:ci-checks tests|pytest)\b",
    "python-typecheck": r"\buv run --no-sync ty check(?:\s|$)",
    "secrets": r"\bgitleaks\b",
    "semgrep": r"\bsemgrep scan\b",
    "skylos-contracts": r"\brequires_skylos\b",
    "workflow-schema": r"\bcheck-jsonschema\b",
}

_ENTRYPOINT_EXCEPTIONS: dict[str, dict[str, str]] = {
    "Justfile": {
        "commit-policy": "requires a commit or pull-request title as input",
        "container-contracts": "requires hosted images built by upstream workflow jobs",
    },
    "lefthook.yml": {
        "container-contracts": "requires hosted images built by upstream workflow jobs",
        "protected-main-evidence": "requires GitHub artifacts and API state",
    },
    "checks.yml": {
        "autofix": "hosted checks must not mutate the checkout",
    },
}


@cache
def _just_recipes() -> dict[str, tuple[tuple[str, ...], str]]:
    declarations: dict[str, tuple[str, list[str]]] = {}
    current = ""
    for line in _JUSTFILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(?P<name>[a-z][a-z0-9-]*)(?: [^:]*)?:(?P<dependencies>.*)$", line)
        if match is not None:
            current = match["name"]
            declarations[current] = (match["dependencies"], [])
        elif current and (line.startswith(" ") or not line):
            declarations[current][1].append(line.strip())
        else:
            current = ""

    names = declarations.keys()
    return {
        name: (
            tuple(token for token in dependencies.split() if token in names),
            "\n".join(body),
        )
        for name, (dependencies, body) in declarations.items()
    }


def _just_recipe_text(name: str) -> str:
    recipes = _just_recipes()
    assert name in recipes, f"Justfile command delegates to missing recipe {name!r}"
    seen: set[str] = set()
    bodies: list[str] = []

    def visit(recipe: str) -> None:
        if recipe in seen:
            return
        seen.add(recipe)
        dependencies, body = recipes[recipe]
        for dependency in dependencies:
            visit(dependency)
        bodies.append(body)

    visit(name)
    return "\n".join(bodies)


@cache
def _package_scripts() -> dict[str, tuple[str, ...]]:
    scripts: dict[str, list[str]] = {}
    for relative in _tracked_files():
        if not relative.endswith("package.json"):
            continue
        config = json.loads((_ROOT / relative).read_text(encoding="utf-8"))
        declared = config.get("scripts", {})
        if not isinstance(declared, dict):
            continue
        for name, command in declared.items():
            if isinstance(name, str) and isinstance(command, str):
                scripts.setdefault(name, []).append(command)
    return {name: tuple(commands) for name, commands in scripts.items()}


def _expand_package_scripts(command: str) -> str:
    expanded = command
    included: set[tuple[str, str]] = set()
    while True:
        additions: list[str] = []
        for name, implementations in _package_scripts().items():
            invocation = re.compile(rf"\bpnpm\b[^\n]*(?:\brun\s+)?{re.escape(name)}(?=\s|$)")
            if invocation.search(expanded) is None:
                continue
            for implementation in implementations:
                key = (name, implementation)
                if key not in included:
                    included.add(key)
                    additions.append(implementation)
        if not additions:
            return expanded
        expanded = "\n".join((expanded, *additions))


def _expand_entrypoint(command: str) -> str:
    expanded = command
    for recipe in re.findall(
        r"(?m)^\s*(?:nix develop \S+ --command )?just\s+(?P<recipe>[a-z][a-z0-9-]*)",
        command,
    ):
        expanded = f"{expanded}\n{_just_recipe_text(recipe)}"
    return _expand_package_scripts(expanded)


def _workflow_run_commands() -> Iterator[str]:
    workflow = yaml.safe_load(_CHECKS.read_text(encoding="utf-8"))

    def walk(value: object) -> Iterator[str]:
        if isinstance(value, Mapping):
            run = value.get("run")
            if isinstance(run, str):
                yield run
            for nested in value.values():
                yield from walk(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from walk(nested)

    yield from walk(workflow)


def _logical_checks(commands: Iterator[str]) -> set[str]:
    effective = "\n".join(_expand_entrypoint(command) for command in commands)
    return {name for name, pattern in _CHECK_PATTERNS.items() if re.search(pattern, effective)}


def test_every_entrypoint_resolves_the_complete_check_matrix() -> None:
    """Just, hooks and hosted CI must execute the same developer-reproducible checks."""
    hook_commands = (
        str(command["run"])
        for hooks in _configured_hooks().values()
        for command in hooks.values()
        if isinstance(command.get("run"), str)
    )
    resolved = {
        "Justfile": _logical_checks(iter(("just verify",))),
        "lefthook.yml": _logical_checks(hook_commands),
        "checks.yml": _logical_checks(_workflow_run_commands()),
    }
    expected = set(_CHECK_PATTERNS)
    for entrypoint, checks in resolved.items():
        assert checks == expected, (
            f"{entrypoint} effective check matrix drifted: "
            f"missing {sorted(expected - checks)}, unexpected {sorted(checks - expected)}"
        )


def test_pre_push_resolves_full_python_static_checks() -> None:
    commands = _configured_hooks()["pre-push"]
    resolved = _logical_checks(
        iter(str(command["run"]) for command in commands.values() if isinstance(command.get("run"), str))
    )
    assert {"python-lint", "python-format"} <= resolved
    assert _run_command("python-lint") == "just lint"
    assert _run_command("python-format") == "just format-check"


def test_entrypoint_exceptions_are_explicit_and_grounded() -> None:
    assert set(_ENTRYPOINT_EXCEPTIONS) == {"Justfile", "lefthook.yml", "checks.yml"}
    for exceptions in _ENTRYPOINT_EXCEPTIONS.values():
        assert exceptions
        assert all(reason.strip() for reason in exceptions.values())


# Hosted step inventory.
#
# Everything above answers "does some hook somewhere mention this tool?". That
# question is aggregate over all hooks, so pre-commit's staged-file Biome
# satisfied "Biome is present" while pre-push ran no whole-project Biome at all.
# The inventory below answers the question that actually matters: for each
# verification hosted CI performs, is there a local gate performing the
# equivalent verification at an equivalent scope, or a written reason there is
# not?
#
# The inventory is curated on purpose. Semantic equivalence between
# `nix develop .#ci --command just fe-lint` and a lefthook job is not
# recoverable by parsing shell, and a clever inference that is quietly wrong is
# worse than a table that fails closed. What is derived, not curated, is the
# hosted step list itself, so a new step in checks.yml fails this suite until a
# human classifies it.

# What a check looks at, on either side of the fence.
_WHOLE_PROJECT = "whole-project"  # the tool walks the repository, ignoring the diff
_CHANGED_FILES = "changed-files"  # the tool receives the BASE..HEAD file list
_PUSHED_RANGE = "pushed-range"  # the tool receives a commit range
_STAGED_FILES = "staged-files"  # the tool receives the staged file list only
_AFFECTED_PACKAGES = "affected-packages"  # the tool receives a package selection
_COMMIT_MESSAGE = "commit-message"  # the tool reads a message, not a file surface

_SCOPES = frozenset(
    {
        _WHOLE_PROJECT,
        _CHANGED_FILES,
        _PUSHED_RANGE,
        _STAGED_FILES,
        _AFFECTED_PACKAGES,
        _COMMIT_MESSAGE,
    }
)

# Substrings that prove a lefthook entry hands its tool the staged inventory and
# nothing else. These keep a declared local scope honest in both directions: a
# `staged-files` claim must show one, a `whole-project` claim must show none.
_STAGED_MARKERS = ("{staged_files}", "--cached", "--staged", "secrets-scan staged")


@dataclass(frozen=True)
class _LocalGate:
    """A lefthook entry claimed as the local counterpart of a hosted step."""

    hook: str
    job: str
    scope: str


@dataclass(frozen=True)
class _HostedStep:
    """One step of `.github/workflows/checks.yml`, classified.

    `verifies` false marks checkout, cache, timing, artifact and reporting
    steps: infrastructure whose failure says nothing about the tree. Those carry
    a `note` instead of a scope, so the category cannot swallow a real check
    without someone writing down that it runs no check.

    A verification carries `scope` plus either `gates`, a `waiver` (no local
    counterpart can exist) or a `gap` (one should exist and does not). `gap` is
    deliberately a separate field from `waiver`: a waiver is a closed question,
    a gap is an open defect this test refuses to let anyone forget.
    """

    verifies: bool
    note: str = ""
    scope: str = ""
    gates: tuple[_LocalGate, ...] = ()
    waiver: str = ""
    gap: str = ""


def _support(note: str) -> _HostedStep:
    return _HostedStep(verifies=False, note=note)


_SETUP = _support("environment setup, runs no check")
_TIMING = _support("cost accounting, runs no check")
_SUMMARY = _support("step-summary rendering, runs no check")
_ARTIFACT = _support("artifact transport, runs no check")

# Keyed by (workflow job id, step key). The step key is the step name, or
# `uses:<action>` for the unnamed marketplace steps.
_HOSTED_INVENTORY: dict[tuple[str, str], _HostedStep] = {
    # changes: the router. It classifies the diff and emits the lane flags. By
    # its own summary text it "runs no checks itself".
    ("changes", "Start router timing"): _TIMING,
    ("changes", "uses:actions/checkout"): _SETUP,
    ("changes", "Open router summary"): _SUMMARY,
    ("changes", "Set up uv and Python"): _SETUP,
    ("changes", "Prepare router environment"): _SETUP,
    ("changes", "Mark router work start"): _TIMING,
    ("changes", "Gather protected-main evidence"): _support("collects gate inputs, runs no check"),
    ("changes", "Compute change gate"): _support("emits the lane flags, runs no check"),
    ("changes", "Upload affected image record"): _ARTIFACT,
    ("changes", "Look up a reusable Checks proof"): _support("proof cache lookup, runs no check"),
    ("changes", "Derive worker guard"): _support("computes a timeout, runs no check"),
    ("changes", "Write Checks attestation"): _support("writes the proof document, runs no check"),
    ("changes", "Upload Checks attestation"): _ARTIFACT,
    ("changes", "Report router cost"): _TIMING,
    ("label-sync", "Sync area labels"): _support("advisory pull request metadata update, runs no check"),
    # worker: every verification of the tree lives here.
    ("worker", "Start worker timing"): _TIMING,
    ("worker", "Open worker summary"): _SUMMARY,
    ("worker", "uses:actions/checkout"): _SETUP,
    ("worker", "Set up selected environments"): _SETUP,
    ("worker", "Mark unique work start"): _TIMING,
    ("worker", "Protected-main smoke"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver=(
            "asserts the hosted devshell can import ci-checks at all. Locally every hook already "
            "runs inside that shell, so the same failure surfaces through whichever hook runs "
            "first rather than through a dedicated gate."
        ),
    ),
    ("worker", "Check flake"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "nix-check", _WHOLE_PROJECT),),
    ),
    ("worker", "Check Lefthook version"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver=(
            "compares the hosted lefthook binary against the min_version pin. A hook cannot check "
            "this: lefthook is the thing running the hook, so a wrong version is already in "
            "effect by the time any hook body executes."
        ),
    ),
    ("worker", "Lint Python"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(
            _LocalGate("pre-push", "python-lint", _WHOLE_PROJECT),
            _LocalGate("pre-commit", "python-check-format", _STAGED_FILES),
        ),
    ),
    ("worker", "Check Python formatting"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(
            _LocalGate("pre-push", "python-format", _WHOLE_PROJECT),
            _LocalGate("pre-commit", "python-check-format", _STAGED_FILES),
        ),
    ),
    ("worker", "Lint Markdown"): _HostedStep(
        verifies=True,
        # `git diff --name-only "$BASE_SHA..$HEAD_SHA" -- '*.md'` into markdownlint-cli2.
        scope=_CHANGED_FILES,
        gates=(_LocalGate("pre-commit", "markdown-lint", _STAGED_FILES),),
    ),
    ("worker", "Lint protos"): _HostedStep(
        verifies=True,
        # `just proto-lint` runs `buf lint` over all of proto/. The local hook is
        # glob-triggered but runs that same whole-directory command, which is why
        # its scope is whole-project rather than staged.
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-commit", "proto-lint", _WHOLE_PROJECT),),
    ),
    ("worker", "Lint workflows"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-commit", "actions-lint", _WHOLE_PROJECT),),
    ),
    ("worker", "Lint frontend"): _HostedStep(
        verifies=True,
        # `just fe-lint` -> `pnpm --filter nohiki-frontend run check` -> biome over the app.
        scope=_WHOLE_PROJECT,
        gates=(
            _LocalGate("pre-push", "frontend-lint-all", _WHOLE_PROJECT),
            _LocalGate("pre-commit", "frontend-lint", _STAGED_FILES),
        ),
    ),
    ("worker", "Lint frontend architecture (Steiger)"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "frontend-fsd", _WHOLE_PROJECT),),
    ),
    ("worker", "Check i18n keys"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-commit", "i18n-check", _WHOLE_PROJECT),),
    ),
    ("worker", "Lint Dockerfiles (hadolint)"): _HostedStep(
        verifies=True,
        # `just docker-lint` feeds hadolint every tracked Dockerfile, not the diff.
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-commit", "docker-lint", _WHOLE_PROJECT),),
    ),
    ("worker", "Scan changed content for secrets"): _HostedStep(
        verifies=True,
        # `git diff --binary "$BASE_SHA..$HEAD_SHA" | gitleaks ... stdin`.
        scope=_CHANGED_FILES,
        gates=(
            _LocalGate("pre-push", "secrets-scan", _PUSHED_RANGE),
            _LocalGate("pre-commit", "secrets-check", _STAGED_FILES),
        ),
    ),
    ("worker", "Scan repository for secrets"): _HostedStep(
        verifies=True,
        # `just secrets-scan` -> `gitleaks detect --source .`, the whole worktree.
        scope=_WHOLE_PROJECT,
        gates=(
            _LocalGate("pre-push", "secrets-scan", _PUSHED_RANGE),
            _LocalGate("pre-commit", "secrets-check", _STAGED_FILES),
        ),
        gap=(
            "hosted scans the entire worktree; both local gates are diff-scoped. A secret that "
            "predates the local gates, or one that arrives through a merge whose parent range "
            "the push gate does not walk, is caught only by hosted CI."
        ),
    ),
    ("worker", "Typecheck backend"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "python-typecheck", _WHOLE_PROJECT),),
    ),
    ("worker", "Check selected dead code"): _HostedStep(
        verifies=True,
        # hosted passes "$PACKAGE_SCOPE"; the local job takes the recipe default of ALL,
        # so the local gate is strictly wider than the hosted one.
        scope=_AFFECTED_PACKAGES,
        gates=(_LocalGate("pre-push", "deadcode", _WHOLE_PROJECT),),
    ),
    ("worker", "Save Skylos static analysis cache"): _support("cache write, runs no check"),
    ("worker", "Typecheck frontend"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "frontend-typecheck", _WHOLE_PROJECT),),
    ),
    ("worker", "Run selected Python tests"): _HostedStep(
        verifies=True,
        scope=_AFFECTED_PACKAGES,
        gates=(_LocalGate("pre-push", "python-tests", _AFFECTED_PACKAGES),),
    ),
    ("worker", "Run job correlation integration tests"): _HostedStep(
        verifies=True,
        scope=_AFFECTED_PACKAGES,
        gates=(
            _LocalGate(
                "pre-push",
                "job-correlation-integration",
                _AFFECTED_PACKAGES,
            ),
        ),
    ),
    ("worker", "Test JVM module"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver=(
            "runs the blocking Gradle build and static analysis; no local hook invokes the "
            "separate JVM devshell, so developers reproduce it explicitly with `just test-jvm`"
        ),
    ),
    ("worker", "Run Node workspace contract tests"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "node-workspace-contract-tests", _WHOLE_PROJECT),),
    ),
    ("worker", "Run Skylos cache contract tests"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "skylos-cache-tests", _WHOLE_PROJECT),),
    ),
    ("worker", "Test frontend"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "frontend-tests", _WHOLE_PROJECT),),
    ),
    ("worker", "Lint edge worker"): _HostedStep(
        verifies=True,
        # `pnpm --filter @nohiki/auth-listings-worker exec biome ci --reporter=github src/`.
        # `just edge-lint` runs the same `biome ci src/` inside the same package; only the
        # hosted-annotation reporter differs.
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "edge-lint", _WHOLE_PROJECT),),
    ),
    ("worker", "Typecheck edge worker"): _HostedStep(
        verifies=True,
        # `pnpm --filter @nohiki/auth-listings-worker exec tsc --noEmit`, which `just
        # edge-typecheck` reproduces against the same package tsconfig.json.
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "edge-typecheck", _WHOLE_PROJECT),),
    ),
    ("worker", "Test edge worker"): _HostedStep(
        verifies=True,
        # `pnpm --filter @nohiki/auth-listings-worker exec vitest run`, which `just edge-test`
        # reproduces; the hosted step only adds a step-summary heading around it.
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "edge-tests", _WHOLE_PROJECT),),
    ),
    ("worker", "Validate PR commit messages"): _HostedStep(
        verifies=True,
        scope=_PUSHED_RANGE,
        gates=(_LocalGate("commit-msg", "commitlint", _COMMIT_MESSAGE),),
    ),
    ("worker", "Validate PR title (merge commit subject)"): _HostedStep(
        verifies=True,
        scope=_COMMIT_MESSAGE,
        waiver=(
            "lints the pull request title, which becomes the squash subject. The title does not "
            "exist in the local repository, so no hook can read it."
        ),
    ),
    ("worker", "Check dependencies"): _HostedStep(
        verifies=True,
        scope=_AFFECTED_PACKAGES,
        gates=(_LocalGate("pre-push", "deptry", _WHOLE_PROJECT),),
    ),
    ("worker", "Scan architecture"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "semgrep", _WHOLE_PROJECT),),
    ),
    ("worker", "Check build backends"): _HostedStep(
        verifies=True,
        scope=_AFFECTED_PACKAGES,
        gates=(_LocalGate("pre-push", "build-backend", _WHOLE_PROJECT),),
    ),
    ("worker", "Check API schema freshness"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "api-schema-freshness", _WHOLE_PROJECT),),
    ),
    ("worker", "Check image matrix parity"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        gates=(_LocalGate("pre-push", "image-matrix-parity", _WHOLE_PROJECT),),
    ),
    ("worker", "Check proto compatibility"): _HostedStep(
        verifies=True,
        # hosted passes "$BASE_SHA"; the local recipe defaults its base_ref to main.
        scope=_PUSHED_RANGE,
        gates=(_LocalGate("pre-push", "proto-breaking", _PUSHED_RANGE),),
    ),
    ("worker", "Set up Docker Buildx"): _SETUP,
    ("worker", "Build production frontend image"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver=(
            "builds the production image through docker/build-push-action against the hosted "
            "layer cache. Reproducing it in a push hook would add an image build to every push; "
            "the container contract is deliberately a hosted-only lane."
        ),
    ),
    ("worker", "Smoke production frontend container"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver="consumes the image produced by the hosted-only build step above.",
    ),
    ("worker", "Validate OpenTelemetry collector image and configs"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver="runs the collector image; the local test runner deselects the requires_docker markers.",
    ),
    ("worker", "Attest container contract execution"): _support(
        "asserts the two container steps above actually ran; proof bookkeeping, not a tree check"
    ),
    ("worker", "Report worker cost"): _TIMING,
    # playwright-image: builds and smoke-tests the e2e runner image.
    ("playwright-image", "Start worker timing"): _TIMING,
    ("playwright-image", "uses:actions/checkout"): _SETUP,
    ("playwright-image", "Open Playwright runner image summary"): _SUMMARY,
    ("playwright-image", "Set up Docker Buildx"): _SETUP,
    ("playwright-image", "Mark unique work start"): _TIMING,
    ("playwright-image", "Build Playwright runner image"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver="hosted-only image build, for the same reason as the production frontend image.",
    ),
    ("playwright-image", "Verify Playwright runner"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver="runs the Playwright CLI inside the image the hosted-only step above produced.",
    ),
    ("playwright-image", "Report Playwright runner image cost"): _TIMING,
    # title-policy: the pull request title lane.
    ("title-policy", "Start title policy timing"): _TIMING,
    ("title-policy", "uses:actions/checkout"): _SETUP,
    ("title-policy", "Open title policy summary"): _SUMMARY,
    ("title-policy", "Set up commit policy environment"): _SETUP,
    ("title-policy", "Mark unique work start"): _TIMING,
    ("title-policy", "Validate PR title (merge commit subject)"): _HostedStep(
        verifies=True,
        scope=_COMMIT_MESSAGE,
        waiver="the same pull request title the worker lane checks; not present in the local repository.",
    ),
    ("title-policy", "Report title policy cost"): _TIMING,
    # checks: fan-in. Verifies the run, not the tree.
    ("checks", "uses:actions/checkout"): _SETUP,
    ("checks", "Open fan-in summary"): _SUMMARY,
    ("checks", "Require every selected check"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver="asserts every selected hosted job reached its conclusion. There is no hosted job graph locally.",
    ),
    ("checks", "Download router attestation"): _ARTIFACT,
    ("checks", "Validate router attestation"): _HostedStep(
        verifies=True,
        scope=_WHOLE_PROJECT,
        waiver="checks the router's own proof document against the run it claims to describe.",
    ),
    ("checks", "Report workflow accounting"): _TIMING,
}

# The gaps this contract knows about and refuses to carry silently. Closing one
# means deleting its line here, which is the point: the set is asserted exactly,
# so a new gap and a fixed gap both fail until the record is updated.
_KNOWN_OPEN_GAPS = frozenset(
    {
        ("worker", "Scan repository for secrets"),
    }
)


def _step_key(step: Mapping[str, object]) -> str:
    """The inventory key for one workflow step."""
    name = step.get("name")
    if isinstance(name, str):
        return name
    uses = step.get("uses")
    assert isinstance(uses, str), f"a step with neither name nor uses cannot be classified: {sorted(step)}"
    return "uses:" + uses.split("@", 1)[0]


def _job_steps(job: Mapping[str, object]) -> Iterator[Mapping[str, object]]:
    """Every step of a workflow job, descending into native `parallel:` groups.

    checks.yml puts eight steps inside `parallel:` blocks, "Lint frontend" among
    them. A walker that reads `job["steps"]` alone treats those as absent, which
    is precisely the class of blindness this file exists to prevent.
    """
    steps = job.get("steps")
    assert isinstance(steps, list)
    for step in steps:
        entry = _as_mapping(step)
        group = entry.get("parallel")
        if isinstance(group, list) and "name" not in entry:
            for nested in group:
                yield _as_mapping(nested)
        else:
            yield entry


@cache
def _hosted_steps() -> dict[tuple[str, str], Mapping[str, object]]:
    """Derive every step of checks.yml, keyed the way the inventory is keyed."""
    workflow = _as_mapping(yaml.safe_load(_CHECKS.read_text(encoding="utf-8")))
    derived: dict[tuple[str, str], Mapping[str, object]] = {}
    for job_id, job in _as_mapping(workflow["jobs"]).items():
        for step in _job_steps(_as_mapping(job)):
            key = (job_id, _step_key(step))
            assert key not in derived, f"duplicate step key {key}; the inventory cannot address both"
            derived[key] = step
    return derived


@cache
def _hook_entries() -> dict[str, dict[str, Mapping[str, object]]]:
    """Every lefthook entry of every hook, commit-msg included."""
    commit_msg = _as_mapping(_as_mapping(_load_config()["commit-msg"])["commands"])
    return {
        "commit-msg": {name: _as_mapping(command) for name, command in commit_msg.items()},
        **_configured_hooks(),
    }


def _gate_run(gate: _LocalGate) -> str:
    run = _hook_entries()[gate.hook][gate.job].get("run")
    assert isinstance(run, str)
    return run


def test_every_hosted_step_is_classified() -> None:
    """checks.yml is the source of truth for what hosted CI does.

    A step added to the workflow has no inventory entry, so it fails here until
    somebody records what it verifies and what covers it locally. This is the
    property aggregate presence checking cannot express at all.
    """
    derived = set(_hosted_steps())
    recorded = set(_HOSTED_INVENTORY)
    unclassified = derived - recorded
    stale = recorded - derived
    assert not unclassified, "hosted steps missing from _HOSTED_INVENTORY:\n" + "\n".join(
        f"  {job}: {step}" for job, step in sorted(unclassified)
    )
    assert not stale, "_HOSTED_INVENTORY names steps checks.yml no longer has:\n" + "\n".join(
        f"  {job}: {step}" for job, step in sorted(stale)
    )


def test_fan_in_checkout_is_file_sparse_and_shallow() -> None:
    """The required status context may fetch only its stdlib helper, never the monorepo."""
    checkout = _hosted_steps()[("checks", "uses:actions/checkout")]
    assert _as_mapping(checkout["with"]) == {
        "sparse-checkout": "scripts/ci/src/ci_checks/checks/workflow.py",
        "sparse-checkout-cone-mode": False,
        "fetch-depth": 1,
        "persist-credentials": False,
    }


def test_inventory_entries_are_well_formed() -> None:
    """Every entry states either what it verifies or why it verifies nothing."""
    for (job, step), entry in sorted(_HOSTED_INVENTORY.items()):
        where = f"{job}: {step}"
        if not entry.verifies:
            assert entry.note.strip(), f"{where} is classified as support with no reason"
            assert not entry.gates, f"{where} is classified as support but names local coverage"
            assert not entry.waiver, f"{where} is classified as support but carries a waiver"
            assert not entry.gap, f"{where} is classified as support but records an open gap"
            continue
        assert entry.scope in _SCOPES, f"{where} declares an unknown hosted scope {entry.scope!r}"
        assert entry.gates or entry.waiver or entry.gap, (
            f"{where} is a verification with no local counterpart, no waiver and no recorded gap"
        )
        assert not (entry.waiver and entry.gap), f"{where} cannot be both waived and an open gap"
        for gate in entry.gates:
            assert gate.scope in _SCOPES, f"{where} declares an unknown local scope {gate.scope!r}"


def test_inventory_local_gates_exist_in_lefthook() -> None:
    """Every named local counterpart is a real hook entry, not a wish."""
    entries = _hook_entries()
    missing = {
        f"  {job}: {step} -> {gate.hook}.{gate.job}"
        for (job, step), entry in _HOSTED_INVENTORY.items()
        for gate in entry.gates
        if gate.job not in entries.get(gate.hook, {})
    }
    assert not missing, "inventory names local jobs lefthook does not declare:\n" + "\n".join(sorted(missing))


def test_declared_local_scopes_match_the_hook_commands() -> None:
    """A staged-files claim needs staged plumbing; a whole-project claim must have none.

    Without this the scope column is free text, and the whole-project rule below
    could be satisfied by relabelling pre-commit's staged Biome job.
    """
    wrong: list[str] = []
    for (job, step), entry in sorted(_HOSTED_INVENTORY.items()):
        for gate in entry.gates:
            staged = any(marker in _gate_run(gate) for marker in _STAGED_MARKERS)
            where = f"  {job}: {step} -> {gate.hook}.{gate.job}"
            if gate.scope == _STAGED_FILES and not staged:
                wrong.append(f"{where} claims staged-files but hands over no staged list")
            if gate.scope == _WHOLE_PROJECT and staged:
                wrong.append(f"{where} claims whole-project but runs on the staged list")
    assert not wrong, "declared local scopes contradict lefthook:\n" + "\n".join(sorted(wrong))


def test_whole_project_hosted_checks_have_a_whole_project_local_gate() -> None:
    """The rule that would have caught the Biome gap.

    Hosted lints the entire project. A staged-file gate cannot see a violation in
    a file the commit did not touch, so it is not a counterpart for a
    whole-project check however loudly it mentions the same tool.
    """
    uncovered: list[str] = []
    for (job, step), entry in sorted(_HOSTED_INVENTORY.items()):
        if not entry.verifies or entry.scope != _WHOLE_PROJECT or entry.waiver or entry.gap:
            continue
        if any(gate.scope == _WHOLE_PROJECT for gate in entry.gates):
            continue
        covered = ", ".join(f"{gate.hook}.{gate.job} ({gate.scope})" for gate in entry.gates) or "nothing"
        uncovered.append(f"  {job}: {step} is whole-project hosted; local coverage is {covered}")
    assert not uncovered, (
        "hosted whole-project checks with no whole-project local gate:\n"
        + "\n".join(uncovered)
        + "\nAdd a whole-project local job, or record the gap with a written reason."
    )


def test_recorded_gaps_are_exactly_the_known_open_ones() -> None:
    """Gaps stay loud. Opening one and closing one both fail until the record moves."""
    recorded = {key for key, entry in _HOSTED_INVENTORY.items() if entry.gap}
    assert recorded == _KNOWN_OPEN_GAPS, (
        "open-gap record drifted:\n"
        f"  newly recorded: {sorted(recorded - _KNOWN_OPEN_GAPS)}\n"
        f"  no longer recorded: {sorted(_KNOWN_OPEN_GAPS - recorded)}"
    )
    for key in sorted(recorded):
        assert _HOSTED_INVENTORY[key].gap.strip(), f"{key} is a gap with no written reason"
