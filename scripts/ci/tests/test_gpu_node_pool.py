"""Static validation for the self-managed AKS GPU node pool.

Production Terraform lives in ``infra/terraform`` (``aks.tf`` + ``variables.tf``).
These tests pin the cost/scheduling contract that the Helm ml-compute workload
depends on (see ``test_gpu_helm_config.py``) so the two never drift:

* the minimum single-T4 AKS GPU SKU (``Standard_NC4as_T4_v3``),
* cluster-autoscaler bounds of ``0..1`` so idle GPU cost is bounded to zero,
* a dedicated node label (``workload=nohiki-ml-gpu``) and a ``sku=gpu:NoSchedule``
  taint so only GPU-tolerant pods that select the pool land there,
* prod-only default enablement that stays fully configurable, and
* the public outputs the Helm scheduling contract is validated against.

The repo has no ``.tftest.hcl`` location, so these mirror the existing static
``.tf`` assertions in ``test_azure_private_network.py`` rather than run a live
plan (which would need cloud credentials).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_IAC = _ROOT / "infra" / "terraform"

# Fixed scheduling contract shared with the Helm workload.
_GPU_VM_SIZE = "Standard_NC4as_T4_v3"
_GPU_LABEL_KEY = "workload"
_GPU_LABEL_VALUE = "nohiki-ml-gpu"
_GPU_TAINT_KEY = "sku"
_GPU_TAINT_VALUE = "gpu"


@cache
def _iac() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(_IAC.glob("*.tf")))


def _brace_block(document: str, header: re.Pattern[str]) -> str:
    """Return the ``{...}`` block whose opening line matches ``header``."""
    match = header.search(document)
    assert match, f"missing HCL block matching /{header.pattern}/"
    depth = 0
    for index in range(match.end() - 1, len(document)):
        char = document[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return document[match.start() : index + 1]
    pytest.fail("unterminated HCL block")


def _resource(document: str, kind: str, name: str) -> str:
    return _brace_block(
        document,
        re.compile(rf'(?m)^resource "{re.escape(kind)}" "{re.escape(name)}"\s*\{{'),
    )


def _variable(document: str, name: str) -> str:
    return _brace_block(document, re.compile(rf'(?m)^variable "{re.escape(name)}"\s*\{{'))


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _gpu_pool(document: str) -> str:
    return _resource(document, "azurerm_kubernetes_cluster_node_pool", "gpu")


def test_gpu_pool_defaults_to_minimum_single_t4_sku() -> None:
    variable = _variable(_iac(), "aks_gpu_node_vm_size")
    assert re.search(rf'default\s*=\s*"{re.escape(_GPU_VM_SIZE)}"', variable)
    # Reject non-NVIDIA sizes so a CPU SKU can never masquerade as the GPU pool.
    assert re.search(r'regex\("\^Standard_N"', variable)
    assert re.search(r"vm_size\s*=\s*var\.aks_gpu_node_vm_size", _gpu_pool(_iac()))


def test_gpu_pool_autoscales_between_zero_and_one_for_bounded_idle_cost() -> None:
    iac = _iac()
    minimum = _variable(iac, "aks_gpu_node_min_count")
    maximum = _variable(iac, "aks_gpu_node_max_count")

    # Idle floor of zero nodes -> zero idle GPU cost; ceiling of one T4.
    assert re.search(r"default\s*=\s*0\b", minimum)
    assert re.search(r"default\s*=\s*1\b", maximum)
    assert "var.aks_gpu_node_min_count >= 0" in _flat(minimum)
    assert "var.aks_gpu_node_max_count >= 1" in _flat(maximum)
    # Ceiling can never drop below the floor.
    assert "var.aks_gpu_node_max_count >= var.aks_gpu_node_min_count" in _flat(maximum)

    pool = _flat(_gpu_pool(iac))
    assert "auto_scaling_enabled = true" in pool
    assert "min_count = var.aks_gpu_node_min_count" in pool
    assert "max_count = var.aks_gpu_node_max_count" in pool
    assert "node_count = var.aks_gpu_node_min_count" in pool


def test_gpu_pool_carries_dedicated_label_and_noschedule_taint() -> None:
    iac = _iac()
    flat = _flat(iac)

    # The label/taint literals are the shared source of truth (Helm selects/tolerates them).
    assert f'gpu_node_label_key = "{_GPU_LABEL_KEY}"' in flat
    assert f'gpu_node_label_value = "{_GPU_LABEL_VALUE}"' in flat
    assert f'gpu_node_taint_key = "{_GPU_TAINT_KEY}"' in flat
    assert f'gpu_node_taint_value = "{_GPU_TAINT_VALUE}"' in flat
    # Effect must keep non-GPU workloads off the pool.
    assert ':NoSchedule"' in iac

    pool = _flat(_gpu_pool(iac))
    assert "node_labels =" in pool
    assert "node_taints =" in pool


def test_gpu_pool_is_prod_default_and_fully_configurable() -> None:
    iac = _iac()
    flat = _flat(iac)

    variable = _flat(_variable(iac, "aks_gpu_node_pool_enabled"))
    assert "type = bool" in variable
    assert "nullable = true" in variable
    assert re.search(r"default\s*=\s*null", variable)

    # Enabled by default only in prod, but any environment can force it on/off,
    # and the pool never exists outside an AKS deployment.
    assert 'coalesce(var.aks_gpu_node_pool_enabled, var.app_environment == "prod")' in flat
    assert 'var.deployment_type == "aks" && coalesce(var.aks_gpu_node_pool_enabled' in flat

    # The pool resource is count-gated on the effective enable -> absent when disabled.
    assert re.search(r"count\s*=\s*local\.gpu_node_pool_enabled\s*\?\s*1\s*:\s*0", _gpu_pool(iac))


def test_gpu_pool_is_production_hardened() -> None:
    iac = _iac()
    pool = _flat(_gpu_pool(iac))

    # No public IPs on GPU nodes.
    assert "node_public_ip_enabled = false" in pool
    # Shares the default node pool's subnet placement (prod VNet, else AKS-managed).
    assert 'vnet_subnet_id = var.app_environment == "prod" ? azurerm_subnet.aks[0].id : null' in pool

    disk = _variable(iac, "aks_gpu_node_os_disk_size_gb")
    assert re.search(r"default\s*=\s*128\b", disk)
    assert "var.aks_gpu_node_os_disk_size_gb >= 30" in _flat(disk)
    assert "os_disk_size_gb = var.aks_gpu_node_os_disk_size_gb" in pool


def test_gpu_pool_exposes_public_scheduling_outputs() -> None:
    iac = _iac()
    for output in (
        "aks_gpu_node_pool_enabled",
        "aks_gpu_node_pool_name",
        "aks_gpu_node_pool_vm_size",
        "aks_gpu_node_pool_min_count",
        "aks_gpu_node_pool_max_count",
        "aks_gpu_node_pool_node_label",
        "aks_gpu_node_pool_node_taint",
    ):
        assert re.search(rf'(?m)^output "{output}"\s*\{{', iac), f"missing output {output}"


# The exact boolean that gates the pool. Pinned so the Python mirror below provably
# tracks the real Terraform expression; if the .tf drifts, the pin test fails first
# and forces the mirror (and truth table) to be updated in lockstep.
_GPU_ENABLED_FORM = (
    'var.deployment_type == "aks" && coalesce(var.aks_gpu_node_pool_enabled, var.app_environment == "prod")'
)


def _gpu_pool_enabled(*, deployment_type: str, app_environment: str, forced: bool | None) -> bool:
    """Mirror of local.gpu_node_pool_enabled; see _GPU_ENABLED_FORM (pinned by its test)."""
    coalesced = forced if forced is not None else (app_environment == "prod")
    return deployment_type == "aks" and coalesced


def test_gpu_pool_enable_local_matches_pinned_boolean_form() -> None:
    """The enable local must equal the pinned form the truth table mirrors."""
    assert _GPU_ENABLED_FORM in _flat(_iac()), "GPU enable local drifted from the pinned boolean form"


@pytest.mark.parametrize(
    "case",
    [
        ("aks", "prod", None, True),
        ("aks", "dev", None, False),
        ("aks", "staging", None, False),
        ("aks", "prod", False, False),
        ("aks", "dev", True, True),
        ("compose", "prod", None, False),
        ("compose", "prod", True, False),
    ],
    ids=[
        "aks-prod-default-on",
        "aks-dev-default-off",
        "aks-staging-default-off",
        "aks-prod-forced-off",
        "aks-dev-forced-on",
        "nonaks-prod-default-off",
        "nonaks-prod-forced-off",
    ],
)
def test_gpu_pool_boolean_disable_path_toggles_pool_presence(
    case: tuple[str, str, bool | None, bool],
) -> None:
    """Disabled inputs create no pool; enabled inputs create exactly the 0..1 T4 pool.

    The pool resource is ``count``-gated on ``local.gpu_node_pool_enabled``, so a
    False evaluation renders zero instances (a clean boolean disable path with no
    orphaned pool) and a True evaluation renders the single pool whose autoscale
    bounds and T4 SKU are locked by the sibling tests.
    """
    deployment_type, app_environment, forced, expected = case
    enabled = _gpu_pool_enabled(deployment_type=deployment_type, app_environment=app_environment, forced=forced)
    assert enabled is expected

    # The rendered instance count is exactly this boolean projected onto 0/1.
    assert re.search(r"count\s*=\s*local\.gpu_node_pool_enabled\s*\?\s*1\s*:\s*0", _gpu_pool(_iac()))
    assert (1 if enabled else 0) == int(expected)
