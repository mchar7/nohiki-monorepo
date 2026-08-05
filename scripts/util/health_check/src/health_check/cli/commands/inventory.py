"""Fail-closed health inventory and acceptance-evidence command."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from health_check.core.registry import CheckRegistry
from health_check.platform.models import PlatformTarget


def inventory_command(
    target: Annotated[
        str,
        typer.Option("--target", "-t", help="Inventory target (k8s only)"),
    ] = "k8s",
    as_json: Annotated[
        bool,
        typer.Option("--json", help="Emit deterministic machine-readable JSON"),
    ] = False,
) -> None:
    """Validate and print registry metadata plus required external evidence."""
    if target.lower() not in {"k8s", "kubernetes"}:
        message = "inventory target must be k8s"
        raise typer.BadParameter(message, param_hint="--target")

    registry = CheckRegistry()
    registry.discover()
    closure = registry.inventory()
    payload = {
        "target": PlatformTarget.KUBERNETES.value,
        "closed": closure.closed,
        "structurally_closed": closure.structurally_closed,
        "registry_ids": sorted(closure.registry_ids),
        "applicable_ids": sorted(closure.applicable_ids),
        "adapted_ids": sorted(closure.adapted_ids),
        "inapplicable_ids": sorted(closure.inapplicable_ids),
        "unknown_ids": sorted(closure.unknown_ids),
        "silent_skip_ids": sorted(closure.silent_skip_ids),
        "evidence_required_ids": sorted(closure.evidence_required_ids),
        "unexercised_ids": sorted(closure.unexercised_ids),
        "evidence_errors": list(closure.evidence_errors),
        "errors": list(closure.errors),
        "records": [
            {
                "id": record.check_id,
                "dependencies": sorted(record.dependencies),
                "endpoint_class": record.endpoint_class.value,
                "platforms": sorted(platform.value for platform in record.platforms),
                "k3s_disposition": record.k3s_disposition.value,
                "k3s_adaptation": record.k3s_adaptation,
                "k3s_reason": record.k3s_reason,
                "severity": record.severity.value,
                "timeout_seconds": record.timeout_seconds,
                "evidence": list(record.evidence),
            }
            for record in closure.records
        ],
    }
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        typer.echo(
            f"health inventory: {len(closure.registry_ids)} registered; "
            f"{len(closure.applicable_ids)} applicable; "
            f"{len(closure.adapted_ids)} adapted; "
            f"{len(closure.inapplicable_ids)} explicitly inapplicable; "
            f"{len(closure.unexercised_ids)} required evidence capabilities unexercised"
        )
        for error in (
            *closure.errors,
            *closure.evidence_errors,
            *sorted(closure.unknown_ids),
            *sorted(closure.silent_skip_ids),
            *(f"{check_id}: unexercised" for check_id in sorted(closure.unexercised_ids)),
        ):
            typer.echo(f"ERROR: {error}", err=True)
    if not closure.closed:
        raise typer.Exit(2)
