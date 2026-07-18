"""Contract coverage for the bootstrap OpenTofu identity root.

The bootstrap root at ``infra/terraform/bootstrap`` owns remote-state storage plus
the GitHub Actions Entra app, service principal, federated credentials, and role
assignments that the CD workflows authenticate with. These tests pin the invariants
that keep the root safe to hand a human operator: no personal or resource-identity
defaults, an exact GitHub OIDC trust configuration, least-privilege roles, an
isolated backend state key, and outputs whose names match the workflow secrets and
variables. They also assert the superseded imperative setup script is gone.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT / "infra" / "terraform" / "bootstrap"
_MAIN = _BOOTSTRAP / "main.tf"
_VARIABLES = _BOOTSTRAP / "variables.tf"
_BACKEND = _BOOTSTRAP / "backend.tf"
_README = _BOOTSTRAP / "README.md"
_WORKFLOWS = _ROOT / ".github" / "workflows"
_LEGACY_SCRIPT = _ROOT / "infra" / "shared" / "scripts" / "setup-oidc-authentication.sh"

# Identity- and uniqueness-bearing inputs a human must supply. A default here would
# either leak an owner/repo/app identity or silently target the wrong globally-unique
# resource. Generic knobs (region, container, branch, environments, state RG) keep
# conventional defaults on purpose and are intentionally excluded.
_REQUIRED_VARIABLES = frozenset(
    {
        "az_subscription_id",
        "github_repository",
        "app_display_name",
        "deployment_scope",
        "state_storage_account_name",
        "state_resource_group_name",
    }
)

_SECRET_OUTPUT_KEYS = frozenset({"AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"})
_VARIABLE_OUTPUT_KEYS = frozenset({"TF_STATE_RESOURCE_GROUP", "TF_STATE_STORAGE_ACCOUNT", "TF_STATE_CONTAINER"})

_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
_OIDC_AUDIENCE = "api://AzureADTokenExchange"


@cache
def _text(path: Path) -> str:
    assert path.is_file(), f"expected bootstrap file present: {path.relative_to(_ROOT)}"
    return path.read_text(encoding="utf-8")


def _variable_bodies(text: str) -> dict[str, str]:
    heads = list(re.finditer(r'(?m)^variable\s+"([^"]+)"\s*\{', text))
    bodies: dict[str, str] = {}
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        bodies[head.group(1)] = text[head.end() : end]
    return bodies


def _resource_bodies(text: str, resource_type: str) -> dict[str, str]:
    heads = list(re.finditer(r'(?m)^resource\s+"([^"]+)"\s+"([^"]+)"\s*\{', text))
    bodies: dict[str, str] = {}
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        if head.group(1) == resource_type:
            bodies[head.group(2)] = text[head.end() : end]
    return bodies


def _output_bodies(text: str) -> dict[str, str]:
    heads = list(re.finditer(r'(?m)^output\s+"([^"]+)"\s*\{', text))
    bodies: dict[str, str] = {}
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        bodies[head.group(1)] = text[head.end() : end]
    return bodies


def _has_default(body: str) -> bool:
    return re.search(r"(?m)^\s*default\s*=", body) is not None


def _map_keys(body: str) -> set[str]:
    return set(re.findall(r"(?m)^\s+([A-Z][A-Z_]+)\s*=", body))


@cache
def _workflow_text() -> str:
    files = sorted(_WORKFLOWS.glob("*.yml")) + sorted(_WORKFLOWS.glob("*.yaml"))
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def test_bootstrap_root_files_exist() -> None:
    for path in (_MAIN, _VARIABLES, _BACKEND, _README):
        assert path.is_file(), f"missing bootstrap file: {path.relative_to(_ROOT)}"


def test_identity_and_resource_variables_carry_no_defaults() -> None:
    bodies = _variable_bodies(_text(_VARIABLES))
    missing = _REQUIRED_VARIABLES - bodies.keys()
    assert not missing, f"bootstrap variables.tf is missing required inputs: {sorted(missing)}"
    defaulted = {name for name in _REQUIRED_VARIABLES if _has_default(bodies[name])}
    assert not defaulted, f"identity/resource inputs must not default: {sorted(defaulted)}"


def test_repository_branch_and_environments_are_configurable() -> None:
    bodies = _variable_bodies(_text(_VARIABLES))
    for name in ("github_repository", "github_default_branch", "github_environments"):
        assert name in bodies, f"bootstrap must expose configurable {name}"
    # github_repository is required identity; branch and environments are configurable
    # knobs with generic defaults.
    assert not _has_default(bodies["github_repository"])
    branch_default = re.search(r'default\s*=\s*"([^"]+)"', bodies["github_default_branch"])
    assert branch_default is not None, "github_default_branch must have a default"
    assert branch_default.group(1) == "main"
    env_default = re.search(r"default\s*=\s*\[([^\]]*)\]", bodies["github_environments"])
    assert env_default is not None, "github_environments must default to a list"
    for environment in ("dev", "staging", "prod"):
        assert f'"{environment}"' in env_default.group(1)


def test_github_oidc_issuer_audience_and_subjects_are_exact() -> None:
    main = _text(_MAIN)
    assert f'"{_OIDC_ISSUER}"' in main, "federated credential must use the GitHub OIDC issuer"
    assert f'"{_OIDC_AUDIENCE}"' in main, "federated credential must use the Entra exchange audience"
    # Default-branch subject tracks the configurable branch, not a hardcoded name.
    assert "repo:${var.github_repository}:ref:refs/heads/${var.github_default_branch}" in main, (
        "default-branch OIDC subject is not the expected repo ref claim"
    )
    # One environment credential per configured environment.
    assert "repo:${var.github_repository}:environment:${env}" in main, (
        "environment OIDC subject is not the expected repo environment claim"
    )
    assert "var.github_environments" in main, "environment credentials must iterate github_environments"
    assert '"main-branch"' in main, "stable main-branch credential name must be preserved for import"


def test_deploy_and_state_role_assignments_are_least_privilege() -> None:
    main = _text(_MAIN)
    blocks = _resource_bodies(main, "azurerm_role_assignment")
    assert blocks, "bootstrap must declare the GitHub Actions role assignments"
    roles: dict[str, tuple[str, str]] = {}
    for name, body in blocks.items():
        role = re.search(r'role_definition_name\s*=\s*"([^"]+)"', body)
        scope = re.search(r"(?m)^\s*scope\s*=\s*(\S+)", body)
        assert role is not None, f"role assignment {name} is missing role_definition_name"
        assert scope is not None, f"role assignment {name} is missing scope"
        roles[name] = (role.group(1), scope.group(1).strip())
    assert {role for role, _ in roles.values()} == {
        "Contributor",
        "Storage Blob Data Contributor",
    }, f"only Contributor and Storage Blob Data Contributor are permitted, got {roles}"
    for name, (role, scope) in roles.items():
        if role == "Contributor":
            assert scope == "var.deployment_scope", f"{name} Contributor must bind the narrow deployment scope"
        else:
            # Storage Blob Data Contributor is data-plane only, scoped to the state
            # container, never the subscription or the whole account.
            assert "azurerm_storage_container.state" in scope, f"{name} must scope to the state container"
            assert "deployment_scope" not in scope, f"{name} must not reuse the deployment scope"
            assert "subscription" not in scope.lower(), f"{name} must not be subscription-scoped"


def test_backend_is_azurerm_with_a_separate_documented_state_key() -> None:
    backend = _text(_BACKEND)
    assert 'backend "azurerm"' in backend, "bootstrap must use the azurerm backend"
    readme = _text(_README)
    assert "nohiki/bootstrap.tfstate" in readme, "README must document the separate bootstrap backend state key"


def test_outputs_match_workflow_secret_and_variable_names() -> None:
    outputs = _output_bodies(_text(_MAIN))
    assert "github_actions_secrets" in outputs, "bootstrap must output the workflow secret map"
    assert "github_actions_variables" in outputs, "bootstrap must output the workflow variable map"
    assert _map_keys(outputs["github_actions_secrets"]) == set(_SECRET_OUTPUT_KEYS)
    assert _map_keys(outputs["github_actions_variables"]) == set(_VARIABLE_OUTPUT_KEYS)
    workflows = _workflow_text()
    for key in _SECRET_OUTPUT_KEYS:
        assert f"secrets.{key}" in workflows, f"no workflow consumes secret {key}"
    for key in _VARIABLE_OUTPUT_KEYS:
        assert f"vars.{key}" in workflows, f"no workflow consumes variable {key}"


def test_import_before_apply_migration_gate_is_documented() -> None:
    readme = _text(_README)
    # Collapse wrapping so line breaks in the prose do not defeat substring anchors.
    flowed = re.sub(r"\s+", " ", readme)
    assert "tofu import" in flowed, "README must document the import commands"
    assert "import every resource before the first apply" in flowed, (
        "README must document the import-before-apply runbook"
    )
    assert "0 to add, 0 to destroy" in flowed, "README must document the no-add/no-destroy plan gate"


def test_legacy_oidc_setup_script_is_removed() -> None:
    assert not _LEGACY_SCRIPT.exists(), (
        "the imperative setup-oidc-authentication.sh must be deleted after the OpenTofu cutover"
    )
