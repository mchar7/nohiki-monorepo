"""Dependency hygiene check using deptry.

Detects undeclared, unused, and transitive dependencies per workspace package.
Runs deptry via the Python executable to avoid a separate ephemeral install.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass

from ci_checks.core.display import console, render_error_panel, render_summary_table
from ci_checks.core.packages import Package
from ci_checks.core.process_env import sanitized_python_env

# Ignore lists for deptry rules

# Workspace packages appear as DEP001/DEP002/DEP003 but are resolved by uv.
_WORKSPACE_PKG_BASES: tuple[str, ...] = (
    "nohiki_common_exceptions",
    "nohiki_redis_utils",
    "nohiki_db_utils",
    "nohiki_fastapi_utils",
    "nohiki_domain_models",
    "nohiki_kafka_client",
    "nohiki_observability",
    "nohiki_s3_client",
    "nohiki_test_utils",
    "nohiki_ml_core",
    "nohiki_ml_manifest",
    "nohiki_core_settings",
    "nohiki_llm_client",
    "nohiki_geo_utils",
    "nohiki_qdrant_client",
    "nohiki_embedding_client",
    "nohiki_domain_utils",
    # betterproto2 generated namespace packages (from nohiki-domain-models)
    "nohiki_proto",
    "nohiki_proto_google",
    "nohiki",
    "tabiya_parser",
    "bootstrap_skill_graph",
    "skill_graph_service",
    "sentence_transformers",
    "torch",
)

# Test and runtime-loaded dependencies (legitimate DEP002 exceptions).
_TEST_AND_RUNTIME: tuple[str, ...] = (
    "pytest",
    "pytest-asyncio",
    "pytest-cov",
    "pytest-mock",
    "testcontainers",
    "respx",
    "freezegun",
    "faker",
    "moto",
    "nohiki-test-utils",
    "uvicorn",
    "alembic",
    "psycopg",
    "asyncpg",
    "psycopg2-binary",
    "types-aiobotocore",
    "aiohttp",
    "aiofiles",
    "pydantic-ai-slim",
    "azure-identity",
    "azure-keyvault-secrets",
    "boto3",
    "aiobotocore",
    "onnxruntime",
    "lightgbm",
    "joblib",
    "triton",
    "pylate",
    "fastembed",
    "opentelemetry-instrumentation-grpc",
    "opentelemetry-instrumentation-redis",
    "opentelemetry-instrumentation-requests",
    "opentelemetry-instrumentation-confluent-kafka",
    "opentelemetry-instrumentation-system-metrics",
    "openinference-instrumentation-openai",
    "arize-phoenix-otel",
    "pydantic",
    "pydantic-settings",
    "pydantic-extra-types",
    "authlib",
    "python-multipart",
    "slowapi",
    "sse-starlette",
    "email-validator",
    "grpcio",
    "protobuf",
    "protovalidate",
    "cryptography",
    "pycountry",
    "requests",
    "httpx",
    "structlog",
    "tenacity",
    "ruff",
    "huggingface-hub",
)

# Known transitive dependencies used indirectly (legitimate DEP003 exceptions).
_TRANSITIVE_DEPS: tuple[str, ...] = (
    "opentelemetry",
    "structlog",
    "pydantic",
    "pydantic_settings",
    "pydantic_core",
    "pydantic_ai",
    "starlette",
    "httpx",
    "redis",
    "sqlalchemy",
    "confluent_kafka",
    "betterproto2",
    "google",
    "botocore",
    "grpclib",
    "grpc",
    "qdrant_client",
    "numpy",
    "torch",
    "sentence_transformers",
    "sklearn",
    "dateutil",
    "aiohttp",
    "tenacity",
    "azure",
    "fastapi",
    "openai",
    "uvicorn",
    "docling_core",
    "click",
)


def _expand_pkg_names(bases: tuple[str, ...]) -> tuple[str, ...]:
    """Expand package names to include both underscore and hyphen forms."""
    expanded: list[str] = []
    for name in bases:
        expanded.append(name)
        hyphenated = name.replace("_", "-")
        if hyphenated != name:
            expanded.append(hyphenated)
    return tuple(expanded)


_WORKSPACE_PKGS: tuple[str, ...] = _expand_pkg_names(_WORKSPACE_PKG_BASES)


def _ignore_string() -> str:
    """Build the deptry --per-rule-ignores string.

    DEP001: workspace packages are resolved by uv, not PyPI.
    DEP002: workspace packages appear in optional-deps for extras composition;
            test/runtime deps are used but not directly imported.
    DEP003: workspace packages + known transitives used indirectly at runtime.
    """
    ws = "|".join(_WORKSPACE_PKGS)
    dep002 = "|".join([*_WORKSPACE_PKGS, *_TEST_AND_RUNTIME])
    dep003 = "|".join([*_WORKSPACE_PKGS, *_TRANSITIVE_DEPS])
    return f"DEP001={ws},DEP002={dep002},DEP003={dep003}"


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
        "--per-rule-ignores",
        _ignore_string(),
    ]
    start = asyncio.get_event_loop().time()
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=pkg.path,
        env=sanitized_python_env(),
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
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
