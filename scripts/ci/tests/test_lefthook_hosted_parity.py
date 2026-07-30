"""Parity contract between the local lefthook battery and the hosted check lanes.

The hosted workflow is the full-surface backstop; a local hook glob must be a
superset of the file surface that activates its mirrored hosted lane, restricted
to the inputs the local command actually reads. Hosted ownership is data, so the
drift tests import the change-gate tables and replay them over the tracked file
list rather than restating any pattern.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
import tomllib
from collections.abc import Iterator, Mapping
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
        "internal-refs-range": frozenset(),
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
        # No glob: the affected-test runner owns the selection policy. Asserted by
        # test_affected_test_selection_is_delegated_to_the_runner.
        "python-tests": frozenset(),
        "skylos-cache-tests": frozenset(
            {
                "scripts/ci/src/ci_checks/checks/skylos_cache.py",
                "scripts/ci/tests/test_skylos_cache.py",
            }
        ),
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
        "scripts/ci/config/internal-reference-terms.toml",
        "scripts/ci/src/ci_checks/checks/gate.py",
        "scripts/ci/src/ci_checks/checks/internal_refs.py",
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
    ("python-check-format", "**/alembic/**"): "ruff excludes alembic through its own config (pyproject.toml:261)",
    ("python-check-format", "backend/libs/nohiki-domain-models/src/**"): (
        "ruff excludes the generated dataclasses through its own config (pyproject.toml:262)"
    ),
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
    ("python-check-format", "**/nohiki-domain-models/**"): (
        "the generated-model package is excluded by both hosted branches, so no local gap exists: broad "
        "passes `--exclude '**/nohiki-domain-models/**'` (checks.yml:387) and standard filters the package "
        "out of the file list with a git pathspec before ruff is invoked (checks.yml:390)"
    ),
    ("python-typecheck", "proto/*"): (
        "a proto edit moves no Python source until `just proto-gen` regenerates the dataclasses"
    ),
    ("python-typecheck", "proto/**/*"): (
        "a proto edit moves no Python source until `just proto-gen` regenerates the dataclasses"
    ),
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
    """Message and patch scanners inspect commits, not a file surface, so they carry no glob."""
    for name in ("secrets-check", "internal-refs-range"):
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
    """Argument-taking tools use templates; no-argument tools use literal commands plus globs."""
    configured = _configured_hooks()["pre-commit"]

    # The Python mutator reaches the staged inventory through a git-diff pathspec so a
    # huge commit cannot exceed ARG_MAX; the pathspec mirrors its glob and exclude set.
    python_run = _run_command("python-check-format")
    assert "{staged_files}" not in python_run
    assert "git diff --cached" in python_run

    for name in ("frontend-lint", "markdown-lint"):
        assert "{staged_files}" in _run_command(name)

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
        assert command.split()[-2:] == ["ty", "check"], (
            f"{name} diverges from the native ty surface: expected a bare 'ty check', got {command!r}"
        )

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
