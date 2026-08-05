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

    build_systems: list[dict[str, object]] = []
    for package in _SCRIPT_PACKAGES:
        with (_ROOT / package / "pyproject.toml").open("rb") as project_file:
            package_config = tomllib.load(project_file)
        build_system = package_config["build-system"]
        assert build_system["build-backend"] == "uv_build"
        assert len(build_system["requires"]) == 1
        assert re.fullmatch(r"uv_build>=\d+\.\d+\.\d+,<\d+\.\d+", build_system["requires"][0])
        build_systems.append(build_system)
        module_name = package.rsplit("/", maxsplit=1)[-1]
        assert (_ROOT / package / "src" / module_name / "__init__.py").is_file()
    assert all(build_system == build_systems[0] for build_system in build_systems[1:])


def test_deptry_exceptions_are_package_scoped() -> None:
    assert "DEP003=fastapi" in _ignore_string("user-auth-service")
    assert "fastapi" not in _ignore_string("nohiki-db-utils")
    assert _ignore_string("job-embedding-finetuning") == "DEP002=accelerate"
    assert _ignore_string("unknown-package") == ""
