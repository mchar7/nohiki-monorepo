#!/usr/bin/env python3
"""Generate the reviewed production identity overlay from OpenTofu outputs."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

BASE_OUTPUTS = {
    "external_secrets_workload_identity_client_id": "esoClientId",
    "external_secrets_workload_identity_tenant_id": "esoTenantId",
    "external_secrets_key_vault_url": "keyVaultUrl",
}
CERT_MANAGER_OUTPUTS = {
    "cert_manager_workload_identity_client_id": "certManagerClientId",
    "cert_manager_workload_identity_tenant_id": "certManagerTenantId",
    "cert_manager_dns_subscription_id": "certManagerSubscriptionId",
    "cert_manager_dns_resource_group": "certManagerResourceGroup",
    "cert_manager_dns_zone_name": "certManagerZoneName",
}
GUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z")


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _load_outputs(path: Path) -> dict[str, str]:
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"invalid OpenTofu output JSON: {exc}")
    if not isinstance(document, dict):
        _fail("OpenTofu output JSON must be an object")
    output_names = set(document)
    if output_names == set(BASE_OUTPUTS):
        outputs = BASE_OUTPUTS
    elif output_names == set(BASE_OUTPUTS) | set(CERT_MANAGER_OUTPUTS):
        outputs = BASE_OUTPUTS | CERT_MANAGER_OUTPUTS
    else:
        _fail("OpenTofu output JSON must contain exactly the allowlisted identity outputs")

    values: dict[str, str] = {}
    for output_name, yaml_name in outputs.items():
        item = document[output_name]
        if not isinstance(item, dict) or set(item) != {"sensitive", "type", "value"}:
            _fail(f"{output_name} has an unexpected OpenTofu serialization")
        if item["sensitive"] is not False or item["type"] != "string" or not isinstance(item["value"], str):
            _fail(f"{output_name} must be a non-sensitive string output")
        value = item["value"].strip()
        if not value:
            _fail(f"{output_name} must not be blank")
        values[yaml_name] = value

    guid_names = ["esoClientId", "esoTenantId"]
    if "certManagerClientId" in values:
        guid_names.extend(
            [
                "certManagerClientId",
                "certManagerTenantId",
                "certManagerSubscriptionId",
            ]
        )
    for name in guid_names:
        if not GUID_RE.fullmatch(values[name]):
            _fail(f"{name} must be a GUID")
    if "certManagerClientId" in values:
        if not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", values["certManagerResourceGroup"]):
            _fail("certManagerResourceGroup is not a valid Azure resource group name")
        if not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?",
            values["certManagerZoneName"],
        ):
            _fail("certManagerZoneName is not a valid DNS zone name")
    vault = urlsplit(values["keyVaultUrl"])
    if (
        vault.scheme != "https"
        or not vault.hostname
        or not vault.hostname.endswith(".vault.azure.net")
        or vault.username is not None
        or vault.password is not None
        or vault.port is not None
        or vault.query
        or vault.fragment
        or vault.path not in ("", "/")
    ):
        _fail("keyVaultUrl must be an HTTPS Azure Key Vault URL")
    values["keyVaultUrl"] = f"https://{vault.hostname}/"
    return values


def _generate(source: Path, destination: Path) -> None:
    values = _load_outputs(source)
    lines = [
        "# Generated from allowlisted non-sensitive OpenTofu outputs; do not edit.",
        "global:",
        "  eso:",
        "    azure:",
        f'      keyVaultUrl: "{values["keyVaultUrl"]}"',
        f'      clientId: "{values["esoClientId"].lower()}"',
        f'      tenantId: "{values["esoTenantId"].lower()}"',
    ]
    if "certManagerClientId" in values:
        lines.extend(
            [
                "cert-manager:",
                "  serviceAccount:",
                "    annotations:",
                f'      azure.workload.identity/client-id: "{values["certManagerClientId"].lower()}"',
                "  podLabels:",
                '    azure.workload.identity/use: "true"',
                "managedClusterIssuer:",
                "  enabled: true",
                "  name: letsencrypt-prod",
                "  azureDNS:",
                f'    clientID: "{values["certManagerClientId"].lower()}"',
                f'    subscriptionID: "{values["certManagerSubscriptionId"].lower()}"',
                f'    tenantID: "{values["certManagerTenantId"].lower()}"',
                f'    resourceGroupName: "{values["certManagerResourceGroup"]}"',
                f'    hostedZoneName: "{values["certManagerZoneName"].lower()}"',
            ]
        )
    lines.append("")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines))


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opentofu-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _generate(args.opentofu_output, args.output)


if __name__ == "__main__":
    _main()
