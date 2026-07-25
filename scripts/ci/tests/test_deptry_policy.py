from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ci_checks.checks.deptry import _ignore_string

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_PACKAGES = {
    "scripts/ml/calibrate_skill_thresholds",
    "scripts/ml/job_embedding_finetuning",
    "scripts/ml/skill_semantic_analysis",
    "scripts/util/ast_explorer",
}


def _dependencies(project: str) -> set[str]:
    with (_ROOT / project / "pyproject.toml").open("rb") as project_file:
        config = tomllib.load(project_file)
    return {re.split(r"[\s<>=!~;\[]", dependency, maxsplit=1)[0] for dependency in config["project"]["dependencies"]}


def test_fixed_workspace_dependencies_are_declared_and_not_ignored() -> None:
    assert {
        "nohiki-common-exceptions",
        "nohiki-observability",
        "opentelemetry-api",
    } <= _dependencies("backend/libs/nohiki-db-utils")
    assert "nohiki-observability" in _dependencies("backend/libs/nohiki-embedding-client")
    assert {
        "nohiki-common-exceptions",
        "nohiki-observability",
        "pydantic",
        "starlette",
    } <= _dependencies("backend/libs/nohiki-fastapi-utils")

    assert "nohiki_common_exceptions" not in _ignore_string("nohiki-db-utils")
    assert "opentelemetry" not in _ignore_string("nohiki-db-utils")
    assert _ignore_string("nohiki-embedding-client") == ""
    assert "pydantic" not in _ignore_string("nohiki-fastapi-utils")
    assert "starlette" not in _ignore_string("nohiki-fastapi-utils")


def test_script_dependencies_are_owned_by_workspace_packages() -> None:
    with (_ROOT / "pyproject.toml").open("rb") as project_file:
        root_config = tomllib.load(project_file)

    assert set(root_config["tool"]["uv"]["workspace"]["members"]) >= _SCRIPT_PACKAGES
    assert "tree-sitter-python" not in {
        re.split(r"[\s<>=!~;\[]", dependency, maxsplit=1)[0]
        for dependency in root_config["dependency-groups"]["workspace"]
    }
    assert "tree-sitter-python" in _dependencies("scripts/util/ast_explorer")

    canonical_build_system = {
        "requires": ["uv_build>=0.11.7,<0.12"],
        "build-backend": "uv_build",
    }
    for package in _SCRIPT_PACKAGES:
        with (_ROOT / package / "pyproject.toml").open("rb") as project_file:
            package_config = tomllib.load(project_file)
        assert package_config["build-system"] == canonical_build_system
        module_name = package.rsplit("/", maxsplit=1)[-1]
        assert (_ROOT / package / "src" / module_name / "__init__.py").is_file()


def test_deptry_exceptions_are_package_scoped() -> None:
    assert "DEP003=fastapi" in _ignore_string("user-auth-service")
    assert "fastapi" not in _ignore_string("nohiki-db-utils")
    assert _ignore_string("job-embedding-finetuning") == "DEP002=accelerate"
    assert _ignore_string("unknown-package") == ""
