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


def test_script_dependencies_are_owned_by_workspace_packages() -> None:
    with (_ROOT / "pyproject.toml").open("rb") as project_file:
        root_config = tomllib.load(project_file)

    assert set(root_config["tool"]["uv"]["workspace"]["members"]) >= _SCRIPT_PACKAGES
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


def test_runtime_loaded_trainer_dependency_stays_declared_and_exempt() -> None:
    assert "accelerate" in _dependencies("scripts/ml/job_embedding_finetuning")

    dep002 = next(rule for rule in _ignore_string().split(",") if rule.startswith("DEP002="))
    assert "accelerate" in dep002.removeprefix("DEP002=").split("|")
