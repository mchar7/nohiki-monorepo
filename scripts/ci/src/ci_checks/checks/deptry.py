"""Dependency hygiene check using deptry.

Detects undeclared, unused, and transitive dependencies per workspace package.
Runs deptry via the Python executable to avoid a separate ephemeral install.
"""

from __future__ import annotations

import asyncio
import sys
import tomllib
from dataclasses import dataclass

from ci_checks.core.display import console, render_error_panel, render_summary_table
from ci_checks.core.packages import Package
from ci_checks.core.process_env import sanitized_python_env

_DEPTRY_PROCESS_WATCHDOG_SECONDS = 6 * 60 * 60

# DEP002 entries are runtime-selected adapters or deployment extras; DEP003
# entries are modules deliberately supplied through a declared workspace facade;
# DEP004 entries are imported by source-shipped test helpers. Keeping the list
# package-scoped means the same dependency remains visible everywhere else.
_PACKAGE_IGNORES: dict[str, dict[str, tuple[str, ...]]] = {
    "user-auth-service": {
        "DEP002": ("authlib",),
        "DEP003": (
            "fastapi",
            "pydantic_settings",
            "sqlalchemy",
            "starlette",
            "uvicorn",
        ),
    },
    "user-pref-service": {
        "DEP002": ("nohiki-ml-core",),
        "DEP003": (
            "fastapi",
            "nohiki_common_exceptions",
            "pydantic",
            "pydantic_settings",
            "sqlalchemy",
            "uvicorn",
        ),
    },
    "user-upload-service": {"DEP003": ("fastapi", "pydantic_settings", "sqlalchemy", "uvicorn")},
    "user-entitlement-service": {"DEP003": ("fastapi", "pydantic_settings", "sqlalchemy", "uvicorn")},
    "job-ingest-discovery-service": {
        "DEP003": (
            "fastapi",
            "opentelemetry",
            "pydantic",
            "pydantic_settings",
            "uvicorn",
        )
    },
    "job-ingest-schedule-service": {"DEP003": ("fastapi", "pydantic", "pydantic_settings", "sqlalchemy", "uvicorn")},
    "job-query-composition-service": {"DEP003": ("fastapi", "pydantic", "pydantic_settings", "sqlalchemy", "uvicorn")},
    "job-ingest-enrichment-service": {
        "DEP002": ("alembic", "nohiki-ml-core"),
        "DEP003": (
            "fastapi",
            "nohiki_common_exceptions",
            "pydantic",
            "pydantic_ai",
            "pydantic_settings",
            "sqlalchemy",
            "uvicorn",
        ),
    },
    "job-storage-service": {"DEP003": ("fastapi", "pydantic", "pydantic_settings", "sqlalchemy", "uvicorn")},
    "job-correlation-evaluation-service": {
        "DEP002": (
            "joblib",
            "nohiki-embedding-client",
            "nohiki-llm-client",
            "nohiki-ml-core",
        ),
        "DEP003": (
            "fastapi",
            "httpx",
            "opentelemetry",
            "pydantic",
            "pydantic_settings",
            "sqlalchemy",
            "uvicorn",
        ),
    },
    "doc-template-service": {
        "DEP003": (
            "fastapi",
            "nohiki_common_exceptions",
            "pydantic",
            "pydantic_settings",
            "sqlalchemy",
            "uvicorn",
        )
    },
    "doc-content-service": {"DEP003": ("fastapi", "pydantic", "pydantic_settings", "uvicorn")},
    "doc-process-service": {
        "DEP003": (
            "docling_core",
            "fastapi",
            "pydantic",
            "pydantic_settings",
            "uvicorn",
        )
    },
    "notification-service": {
        "DEP002": ("nohiki-common-exceptions",),
        "DEP003": (
            "fastapi",
            "opentelemetry",
            "pydantic",
            "pydantic_settings",
            "sqlalchemy",
            "uvicorn",
        ),
    },
    "bff-service": {
        "DEP003": (
            "betterproto2",
            "fastapi",
            "nohiki_common_exceptions",
            "pydantic",
            "pydantic_settings",
            "sqlalchemy",
            "starlette",
            "uvicorn",
        )
    },
    "ml-gateway-service": {
        "DEP002": ("nohiki-ml-core",),
        "DEP003": ("fastapi", "pydantic", "pydantic_settings", "uvicorn"),
    },
    "ml-compute-service": {
        "DEP002": ("huggingface-hub", "torch"),
        "DEP003": ("fastapi", "numpy", "pydantic", "pydantic_settings", "uvicorn"),
    },
    "skill-graph-service": {
        "DEP002": ("nohiki-ml-core",),
        "DEP003": (
            "fastapi",
            "nohiki_common_exceptions",
            "numpy",
            "opentelemetry",
            "pydantic",
            "pydantic_settings",
            "sqlalchemy",
            "uvicorn",
        ),
    },
    "sys-tick-job": {"DEP002": ("nohiki-observability",)},
    "nohiki-redis-utils": {
        "DEP003": ("nohiki_common_exceptions", "nohiki_test_utils", "opentelemetry"),
        "DEP004": ("pytest", "testcontainers"),
    },
    "nohiki-db-utils": {
        "DEP002": ("asyncpg", "nohiki-db-utils", "protobuf", "psycopg"),
        "DEP003": ("nohiki", "nohiki_test_utils"),
        "DEP004": ("pytest", "pytest_unused_fixtures", "testcontainers"),
    },
    "nohiki-fastapi-utils": {"DEP002": ("cryptography", "uvicorn")},
    "nohiki-domain-models": {"DEP003": ("dateutil", "pydantic_core")},
    "nohiki-kafka-client": {
        "DEP003": ("nohiki", "opentelemetry"),
        "DEP004": ("nohiki_test_utils", "pytest", "testcontainers"),
    },
    "nohiki-observability": {
        "DEP002": (
            "arize-phoenix-otel",
            "httpx",
            "nohiki-observability",
            "openinference-instrumentation-openai",
            "opentelemetry-instrumentation-confluent-kafka",
            "opentelemetry-instrumentation-grpc",
            "opentelemetry-instrumentation-redis",
            "opentelemetry-instrumentation-requests",
            "opentelemetry-instrumentation-system-metrics",
            "requests",
        ),
        "DEP003": ("google",),
    },
    "nohiki-s3-client": {
        "DEP002": ("types-aiobotocore",),
        "DEP003": (
            "botocore",
            "nohiki_common_exceptions",
            "nohiki_observability",
            "opentelemetry",
        ),
    },
    "nohiki-test-utils": {
        "DEP002": ("faker", "pytest-asyncio"),
        "DEP003": ("betterproto2", "fastapi", "sqlalchemy"),
    },
    "nohiki-ml-core": {
        "DEP002": (
            "fastembed",
            "nohiki-common-exceptions",
            "nohiki-redis-utils",
            "nohiki-s3-client",
            "onnxruntime",
            "pylate",
            "triton",
        ),
        "DEP003": ("opentelemetry",),
    },
    "nohiki-ml-manifest": {"DEP004": ("nohiki_test_utils",)},
    "nohiki-qdrant-client": {"DEP002": ("pydantic-settings",), "DEP003": ("nohiki",)},
    "nohiki-core-settings": {"DEP002": ("azure-keyvault-secrets",)},
    "nohiki-llm-client": {
        "DEP002": ("nohiki-core-settings",),
        "DEP003": ("google", "httpx", "nohiki_common_exceptions", "openai"),
    },
    "nohiki-geo-utils": {"DEP002": ("aiohttp",)},
    "qdrant-init": {"DEP002": ("nohiki-ml-core",)},
    "tailor": {"DEP003": ("httpx", "pydantic", "pydantic_ai", "pydantic_settings", "structlog")},
    "llm-benchmark": {"DEP003": ("click", "nohiki_test_utils", "pydantic", "pydantic_ai")},
    "nohiki-scaffold": {"DEP003": ("click",)},
    "job-embedding-finetuning": {"DEP002": ("accelerate",)},
}

_DEV_OPTIONAL_GROUPS = ("dev", "test", "testing")
_DOMAIN_MODEL_MODULES = "nohiki-domain-models=nohiki|nohiki_proto_google|nohiki_domain_utils|message_pool"


def _ignore_string(package_name: str) -> str:
    """Build package-scoped deptry exceptions."""
    rules = _PACKAGE_IGNORES.get(package_name, {})
    return ",".join(f"{rule}={'|'.join(names)}" for rule, names in rules.items())


def _dev_optional_groups(pkg: Package) -> tuple[str, ...]:
    """Return optional dependency groups that contain test tooling."""
    with (pkg.path / "pyproject.toml").open("rb") as project_file:
        config = tomllib.load(project_file)
    project = config.get("project")
    if not isinstance(project, dict):
        return ()
    optional = project.get("optional-dependencies")
    if not isinstance(optional, dict):
        return ()
    return tuple(group for group in _DEV_OPTIONAL_GROUPS if group in optional)


@dataclass(slots=True)
class DeptryResult:
    """Scan result carrying raw deptry output and issue count."""

    name: str
    passed: bool
    duration_ms: int = 0
    error: str = ""
    output: str = ""
    issues_found: int = 0


async def scan_package(pkg: Package) -> DeptryResult:
    """Run deptry on a single package.

    Args:
        pkg: Package to scan.

    Returns:
        DeptryResult with output and issue count.
    """
    cmd = [
        sys.executable,
        "-m",
        "deptry",
        str(pkg.src_dir),
        "--no-ansi",
        "--extend-exclude",
        "alembic|tests",
        "--package-module-name-map",
        _DOMAIN_MODEL_MODULES,
    ]
    if dev_groups := _dev_optional_groups(pkg):
        cmd.extend(("--optional-dependencies-dev-groups", ",".join(dev_groups)))
    if ignores := _ignore_string(pkg.name):
        cmd.extend(("--per-rule-ignores", ignores))
    start = asyncio.get_event_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=pkg.path,
        env=sanitized_python_env(),
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(),
        timeout=_DEPTRY_PROCESS_WATCHDOG_SECONDS,
    )
    duration_ms = int((asyncio.get_event_loop().time() - start) * 1000)

    output = stdout.decode() + stderr.decode()
    issues = len([line for line in output.split("\n") if "DEP00" in line])

    return DeptryResult(
        name=pkg.name,
        passed=proc.returncode == 0,
        duration_ms=duration_ms,
        output=output,
        issues_found=issues,
    )


def ci_suffix(result: DeptryResult) -> str:
    """CI-mode suffix showing issue count when non-zero."""
    return f" ({result.issues_found} issues)" if result.issues_found else ""


def render_results(results: list[DeptryResult]) -> bool:
    """Render the deptry summary and per-package output panels.

    Args:
        results: All scan results to summarise.

    Returns:
        True if all packages passed.
    """
    passed_count = sum(1 for r in results if r.passed)
    failed = [r for r in results if not r.passed]
    total_issues = sum(r.issues_found for r in results)

    render_summary_table(
        "Dependency Hygiene Summary",
        clean_count=passed_count,
        failed_count=len(failed),
        total_issues=total_issues,
    )

    for r in failed:
        render_error_panel(r.name, r.output)

    if any(r.error for r in results):
        error_pkgs = [r for r in results if r.error]
        console.print(f"\n[red]⚠ {len(error_pkgs)} package(s) had errors[/red]")

    return len(failed) == 0
