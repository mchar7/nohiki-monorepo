from __future__ import annotations

import re
import tomllib
from pathlib import Path

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


def _per_rule_ignores(project: str) -> dict[str, list[str]]:
    """Read a package's own deptry exceptions, which is where they live."""
    with (_ROOT / project / "pyproject.toml").open("rb") as project_file:
        config = tomllib.load(project_file)
    return config.get("tool", {}).get("deptry", {}).get("per_rule_ignores", {})


def _ignored_names(project: str) -> set[str]:
    """Every name a package excuses, across all rules."""
    return {name for names in _per_rule_ignores(project).values() for name in names}


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

    assert "nohiki_common_exceptions" not in _ignored_names("backend/libs/nohiki-db-utils")
    assert "opentelemetry" not in _ignored_names("backend/libs/nohiki-db-utils")
    assert _per_rule_ignores("backend/libs/nohiki-embedding-client") == {}
    assert "pydantic" not in _ignored_names("backend/libs/nohiki-fastapi-utils")
    assert "starlette" not in _ignored_names("backend/libs/nohiki-fastapi-utils")


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
    assert "fastapi" in _per_rule_ignores("backend/services/user-auth-service")["DEP003"]
    assert "fastapi" not in _ignored_names("backend/libs/nohiki-db-utils")
    assert _per_rule_ignores("scripts/ml/job_embedding_finetuning") == {"DEP002": ["accelerate"]}


def test_no_package_suppresses_missing_dependencies_or_a_whole_rule() -> None:
    with (_ROOT / "pyproject.toml").open("rb") as project_file:
        members = tomllib.load(project_file)["tool"]["uv"]["workspace"]["members"]

    for member in members:
        if not (_ROOT / member / "pyproject.toml").is_file():
            continue
        with (_ROOT / member / "pyproject.toml").open("rb") as project_file:
            deptry_config = tomllib.load(project_file).get("tool", {}).get("deptry", {})
        # A blanket --ignore would drop a rule for every name; exceptions must stay name-scoped.
        assert "ignore" not in deptry_config, member
        # DEP001 is the undeclared-import class and is never suppressed anywhere.
        assert "DEP001" not in deptry_config.get("per_rule_ignores", {}), member
