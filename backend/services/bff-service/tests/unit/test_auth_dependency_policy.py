from __future__ import annotations

import ast
from pathlib import Path


def test_protected_routers_do_not_import_shared_auth_dependencies() -> None:
    routers = Path(__file__).parents[2] / "src" / "bff_service" / "api" / "routers"
    forbidden = {"get_current_user_claims", "get_current_user_id_from_cookie"}
    violations: list[str] = []

    for path in routers.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "nohiki_fastapi_utils":
                imported = forbidden.intersection(alias.name for alias in node.names)
                violations.extend(f"{path.name}: {name}" for name in sorted(imported))

    assert violations == [], "Protected routers bypass BFF revocation checks: " + ", ".join(violations)
