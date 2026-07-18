from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_WORKFLOWS = _REPOSITORY_ROOT / ".github" / "workflows"
_AKS_WORKFLOW = _WORKFLOWS / "cd_deploy-to-aks_nohiki.yml"
_FLUX_BOOTSTRAP = _REPOSITORY_ROOT / "infra" / "k8s" / "gitops" / "install" / "bootstrap.sh"
_LEGACY_AZURE_WORKFLOW = _WORKFLOWS / "cd_deploy-to-azure_nohiki.yml"
_DESTROY_WORKFLOW = _WORKFLOWS / "cd_destroy-aks_nohiki.yml"


@cache
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@cache
def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(_read(path))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML 1.1 parses the unquoted GitHub Actions `on` key as True.
    return workflow.get("on", workflow.get(True))


def _steps(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {step.get("id", step["name"]): step for step in job["steps"]}


def test_prod_source_stamp_reads_release_sha_from_quoted_heredoc_environment() -> None:
    workflow = _load(_AKS_WORKFLOW)
    stamp = _steps(workflow["jobs"]["activate-production-runtime"])["Stamp and activate production GitOps source"]
    script = stamp["run"]

    assert "python3 - <<'PY'" in script
    assert 'sha = os.environ["RELEASE_SHA"]' in script
    assert "${RELEASE_SHA}" not in script
    assert {"infrastructure.yaml", "platform.yaml", "observability.yaml"} <= set(script.split('"'))
    assert 'base / "release-source.yaml"' in script
    assert 'text.replace("commit: PROMOTION_REQUIRED", f"commit: {sha}")' in script
    assert 'text.replace("suspend: true", "suspend: false")' in script
    assert "git push" not in script


def test_dev_deploy_bootstraps_native_flux_with_complete_runtime_contract() -> None:
    workflow = _load(_AKS_WORKFLOW)
    job_steps = workflow["jobs"]["deploy-to-aks"]["steps"]
    steps = _steps(workflow["jobs"]["deploy-to-aks"])
    for name in (
        "Get dev AKS credentials",
        "Install Nix",
        "Resolve dev runtime coordinates",
        "Bootstrap dev GitOps",
        "Wait for dev GitOps convergence",
    ):
        assert name in steps, name
        assert "needs.prepare-deployment.outputs.env_name == 'dev'" in steps[name]["if"], name

    coordinates = steps["Resolve dev runtime coordinates"]["run"]
    assert 'repository="${GITHUB_REPOSITORY,,}"' in coordinates
    assert 'deployment_sha="${{ github.event.workflow_run.head_sha || github.sha }}"' in coordinates
    assert '[[ ! "$deployment_sha" =~ ^[0-9a-f]{40}$ ]]' in coordinates
    assert "NOHIKI_IMAGE_OWNER=${repository%%/*}" in coordinates
    assert "NOHIKI_IMAGE_REPOSITORY=${repository##*/}" in coordinates
    assert "NOHIKI_IMAGE_TAG=sha-${deployment_sha::7}" in coordinates
    assert {
        line.split("tofu output -raw ", 1)[1].split(")", 1)[0]
        for line in coordinates.splitlines()
        if "tofu output -raw " in line
    } == {
        "external_secrets_workload_identity_client_id",
        "external_secrets_workload_identity_tenant_id",
        "external_secrets_key_vault_url",
    }

    bootstrap = steps["Bootstrap dev GitOps"]
    assert bootstrap["env"] == {
        "GITHUB_TOKEN": "${{ secrets.FLUX_GITHUB_TOKEN }}",
        "GITOPS_GITHUB_OWNER": "${{ github.repository_owner }}",
        "GITOPS_GITHUB_REPOSITORY": "${{ github.event.repository.name }}",
        "GITOPS_GITHUB_BRANCH": "${{ github.event.workflow_run.head_branch || github.ref_name }}",
        "GITOPS_GITHUB_PERSONAL": "${{ github.event.repository.owner.type == 'User' }}",
        "NOHIKI_CLUSTER": "dev-aks",
        "NOHIKI_IMAGE_REGISTRY": "ghcr.io",
        "NOHIKI_IMAGE_OWNER": "${{ env.NOHIKI_IMAGE_OWNER }}",
        "NOHIKI_IMAGE_REPOSITORY": "${{ env.NOHIKI_IMAGE_REPOSITORY }}",
        "NOHIKI_IMAGE_TAG": "${{ env.NOHIKI_IMAGE_TAG }}",
        "NOHIKI_ESO_CLIENT_ID": "${{ env.NOHIKI_ESO_CLIENT_ID }}",
        "NOHIKI_ESO_TENANT_ID": "${{ env.NOHIKI_ESO_TENANT_ID }}",
        "NOHIKI_ESO_VAULT_URL": "${{ env.NOHIKI_ESO_VAULT_URL }}",
    }
    assert bootstrap["run"].splitlines()[-1] == "nix develop .#k8s --command just gitops-bootstrap"
    assert 'if [[ -z "${GITHUB_TOKEN:-}" ]]' in bootstrap["run"]

    bootstrap_script = _FLUX_BOOTSTRAP.read_text(encoding="utf-8")
    flux_argument_lines = bootstrap_script.split("flux_args=(", 1)[1].splitlines()
    flux_argument_block = []
    for line in flux_argument_lines:
        if line.strip() == ")":
            break
        flux_argument_block.append(line)
    else:
        message = "flux_args array is not terminated"
        raise AssertionError(message)
    flux_arguments = {line.strip().split("=", 1)[0] for line in flux_argument_block if line.strip().startswith("--")}
    assert next(line.strip() for line in flux_argument_block if line.strip()) == "bootstrap github"
    assert flux_arguments == {
        "--owner",
        "--repository",
        "--branch",
        "--path",
        "--read-write-key",
    }
    assert all("GITHUB_TOKEN" not in line for line in flux_argument_block)
    assert all("--token" not in line for line in flux_argument_block)
    assert "flux_args+=(--personal)" in bootstrap_script
    assert "require GITHUB_TOKEN" in bootstrap_script
    assert 'flux "${flux_args[@]}"' in bootstrap_script

    bootstrap_index = job_steps.index(bootstrap)
    wait = job_steps[bootstrap_index + 1]
    assert wait["name"] == "Wait for dev GitOps convergence"
    assert wait["env"] == {"NOHIKI_CLUSTER": "dev-aks"}
    assert wait["run"] == "nix develop .#k8s --command just gitops-wait"
    assert "continue-on-error" not in wait

    handoff = f"{bootstrap['run']}\n{wait['run']}"
    for forbidden in ("helm install", "helm upgrade", "kubectl apply", "|| true"):
        assert forbidden not in handoff, forbidden


def test_manual_production_dispatch_requires_explicit_confirmation() -> None:
    workflow = _load(_AKS_WORKFLOW)
    assert "production_confirmation" in _triggers(workflow)["workflow_dispatch"]["inputs"]

    gate = _steps(workflow["jobs"]["check-context"])["Require explicit confirmation for manual production dispatch"]
    assert gate["if"] == "github.event_name == 'workflow_dispatch' && github.event.inputs.environment == 'prod'"
    assert gate["env"]["PRODUCTION_CONFIRMATION"] == "${{ github.event.inputs.production_confirmation }}"
    run = gate["run"]
    assert '"$PRODUCTION_CONFIRMATION" != "deploy-production"' in run
    assert "exit 1" in run


def test_aks_plan_supplies_registry_and_production_durability_contract() -> None:
    workflow = _load(_AKS_WORKFLOW)
    plan_step = _steps(workflow["jobs"]["deploy-to-aks"])["iac-plan"]
    assert plan_step["env"] == {"DEPLOYMENT_ENVIRONMENT": "${{ needs.prepare-deployment.outputs.env_name }}"}
    plan = plan_step["run"]
    expected_arguments = (
        '-var "az_subscription_id=${{ secrets.AZURE_SUBSCRIPTION_ID }}"',
        '-var "container_registry=${{ vars.AZURE_CONTAINER_REGISTRY }}"',
        '-var "app_environment=$DEPLOYMENT_ENVIRONMENT"',
        (
            "-var \"azure_redis_sku_name=${{ needs.prepare-deployment.outputs.env_name == 'prod' && "
            "'Standard' || 'Basic' }}\""
        ),
        '-var "azure_redis_family=C"',
        '-var "azure_redis_capacity=0"',
        (
            "-var \"postgres_flexible_sku_name=${{ needs.prepare-deployment.outputs.env_name == 'prod' && "
            "'GP_Standard_D2s_v3' || 'B_Standard_B1ms' }}\""
        ),
        (
            "-var \"postgres_backup_retention_days=${{ needs.prepare-deployment.outputs.env_name == 'prod' && "
            "'14' || '7' }}\""
        ),
        (
            "-var \"postgres_geo_redundant_backup_enabled=${{ needs.prepare-deployment.outputs.env_name == 'prod' && "
            "'true' || 'false' }}\""
        ),
        (
            "-var \"storage_account_replication_type=${{ needs.prepare-deployment.outputs.env_name == 'prod' && "
            "'GRS' || 'LRS' }}\""
        ),
    )
    for argument in expected_arguments:
        assert argument in plan, argument
    assert "${needs." not in plan
    for removed in (
        "app_image_tag",
        "app_helm_chart_path",
        "app_helm_overrides_filename",
    ):
        assert removed not in plan, removed


def test_iac_schema_requires_azure_standard_c0_redis_in_production() -> None:
    iac_variables = (_REPOSITORY_ROOT / "infra" / "terraform" / "variables.tf").read_text(encoding="utf-8")
    assert 'var.app_environment != "prod" || var.redis_provider == "azure"' in iac_variables
    assert 'var.app_environment != "prod" || var.azure_redis_sku_name == "Standard"' in iac_variables
    assert 'var.app_environment != "prod" || var.azure_redis_family == "C"' in iac_variables
    assert 'var.app_environment != "prod" || var.azure_redis_capacity == 0' in iac_variables


def test_destroy_requires_confirmation_environment_gate_and_oidc() -> None:
    workflow = _load(_DESTROY_WORKFLOW)
    inputs = _triggers(workflow)["workflow_dispatch"]["inputs"]
    job = workflow["jobs"]["cleanup-environment"]
    steps = _steps(job)

    assert inputs["environment"]["options"] == ["dev", "staging"]
    assert inputs["confirm_destroy"]["required"] is True
    assert job["environment"] == "${{ inputs.environment }}"
    assert job["permissions"] == {"contents": "read", "id-token": "write"}

    serialized = _read(_DESTROY_WORKFLOW)
    assert "AZURE_CLIENT_SECRET" not in serialized
    login = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("azure/login@"))
    assert login["with"] == {
        "client-id": "${{ secrets.AZURE_CLIENT_ID }}",
        "tenant-id": "${{ secrets.AZURE_TENANT_ID }}",
        "subscription-id": "${{ secrets.AZURE_SUBSCRIPTION_ID }}",
    }

    confirmation = steps["confirm-destroy"]
    assert confirmation["env"]["CONFIRM_DESTROY"] == "${{ inputs.confirm_destroy }}"
    assert confirmation["env"]["TARGET_ENVIRONMENT"] == "${{ inputs.environment }}"
    assert '"$CONFIRM_DESTROY" != "$TARGET_ENVIRONMENT"' in confirmation["run"]

    init = steps["OpenTofu Init for destruction"]["run"]
    destroy = steps["OpenTofu Destroy"]["run"]
    assert "key=nohiki/${{ steps.determine-env-to-destroy.outputs.env_to_destroy }}.tfstate" in init
    assert '-var "app_environment=$envToDestroyValue"' in destroy
    assert '-var "deployment_type=aks"' in destroy
    assert "az_subscription_id" not in destroy
    assert "app_image_tag" not in destroy


def test_legacy_azure_deploy_workflow_is_removed() -> None:
    message = "cd_deploy-to-azure_nohiki.yml must be deleted; cd_deploy-to-aks_nohiki.yml is canonical"
    assert not _LEGACY_AZURE_WORKFLOW.exists(), message
