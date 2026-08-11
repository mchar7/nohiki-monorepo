"""Shared rendered-consumer contracts for local Secret authoring and validation."""

from collections.abc import Mapping
from pathlib import Path
from typing import cast

import yaml


class LocalSecretContractError(ValueError):
    """A local Helm Secret consumer contract could not be derived."""


def _values_mapping(values: Mapping[str, object] | Path) -> Mapping[str, object]:
    if isinstance(values, Path):
        loaded = yaml.safe_load(values.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            message = "Helm values are malformed"
            raise LocalSecretContractError(message)
        return cast("dict[str, object]", loaded)
    return values


def local_oauth_enabled(values: Mapping[str, object]) -> bool:
    """Return the explicit local OAuth consumer switch from one values snapshot."""
    service = values.get("user-auth-service")
    service_secrets = service.get("secrets") if isinstance(service, dict) else None
    enabled = service_secrets.get("oauth") if isinstance(service_secrets, dict) else None
    if not isinstance(enabled, bool):
        message = "local OAuth enablement must be explicit"
        raise LocalSecretContractError(message)
    return enabled


def enabled_provider_credentials(
    base: Mapping[str, object] | Path,
    environment: Mapping[str, object] | Path,
) -> tuple[str, ...]:
    """Return exact credential names reachable through enabled environment routes."""
    base = cast("dict[str, object]", _values_mapping(base))
    environment = cast("dict[str, object]", _values_mapping(environment))
    base_global = base.get("global")
    environment_global = environment.get("global")
    base_egress = base_global.get("modelEgress") if isinstance(base_global, dict) else None
    environment_egress = environment_global.get("modelEgress") if isinstance(environment_global, dict) else None
    if not isinstance(base_egress, dict) or not isinstance(environment_egress, dict):
        message = "modelEgress values are missing"
        raise LocalSecretContractError(message)
    disabled = environment_egress.get("disabledBackends", [])
    declared = environment_egress.get("providerCredentials", base_egress.get("providerCredentials"))
    backends = base_egress.get("backends")
    if (
        not isinstance(disabled, list)
        or not all(isinstance(name, str) for name in disabled)
        or not isinstance(declared, list)
        or not all(isinstance(name, str) for name in declared)
        or not isinstance(backends, list)
    ):
        message = "modelEgress provider declaration is malformed"
        raise LocalSecretContractError(message)
    enabled: set[str] = set()
    for backend in backends:
        if not isinstance(backend, dict) or backend.get("enabled") is False or backend.get("name") in disabled:
            continue
        groups = backend.get("groups", [])
        if not isinstance(groups, list):
            message = "modelEgress provider groups are malformed"
            raise LocalSecretContractError(message)
        for group in groups:
            providers = group.get("providers", []) if isinstance(group, dict) else []
            if not isinstance(providers, list):
                message = "modelEgress providers are malformed"
                raise LocalSecretContractError(message)
            for provider in providers:
                if not isinstance(provider, dict) or provider.get("enabled") is False:
                    continue
                credential = provider.get("credentialName")
                if not isinstance(credential, str) or not credential:
                    message = "enabled modelEgress provider has no credentialName"
                    raise LocalSecretContractError(message)
                enabled.add(credential)
    if set(declared) != enabled or len(declared) != len(enabled):
        message = "modelEgress providerCredentials do not match enabled routes"
        raise LocalSecretContractError(message)
    return tuple(sorted(enabled))
