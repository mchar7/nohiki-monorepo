"""Focused local LLM NetworkPolicy regressions."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"

# Only these workloads receive model-egress client credentials. Both call the
# in-cluster gateway; neither workload receives direct provider access.
_LLM_SERVICES = {
    "nohiki-doc-content-service",
    "nohiki-job-ingest-enrichment-service",
}
_MODEL_GATEWAY = "nohiki-model-egress"
_GATEWAY_SELECTOR = {"gateway.networking.k8s.io/gateway-name": _MODEL_GATEWAY}

# These non-model integrations intentionally need direct public HTTPS. Every
# other rendered workload must remain unable to reach a public IPv4 destination.
_DIRECT_PUBLIC_HTTPS_SERVICES = {
    "nohiki-job-ingest-discovery-service",
    "nohiki-job-ingest-enrichment-service",
    "nohiki-notification-service",
    "nohiki-skill-graph-service",
}
_NON_PUBLIC_IPV4_RANGES = [
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
]
_PUBLIC_HTTPS_RULE = {
    "to": [
        {
            "ipBlock": {
                "cidr": "0.0.0.0/0",
                "except": _NON_PUBLIC_IPV4_RANGES,
            }
        }
    ],
    "ports": [{"port": 443, "protocol": "TCP"}],
}


def _render_local() -> tuple[dict[str, Any], ...]:
    result = subprocess.run(
        [
            "helm",
            "template",
            "nohiki",
            str(_CHART),
            "--namespace",
            "nohiki-local",
            "--values",
            str(_CHART / "values.local.yaml"),
        ],
        cwd=_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _egress_by_deployment(
    documents: tuple[dict[str, Any], ...],
) -> dict[str, list[dict[str, Any]]]:
    deployments = {
        document["metadata"]["name"]: document["spec"]["template"]["metadata"]["labels"]
        for document in documents
        if document.get("kind") == "Deployment"
    }
    policies = [document for document in documents if document.get("kind") == "NetworkPolicy"]
    return {
        name: [
            rule
            for policy in policies
            if all(
                labels.get(key) == value for key, value in policy["spec"]["podSelector"].get("matchLabels", {}).items()
            )
            for rule in policy["spec"].get("egress", [])
        ]
        for name, labels in deployments.items()
    }


def _public_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        rule for rule in rules if any(peer.get("ipBlock", {}).get("cidr") == "0.0.0.0/0" for peer in rule.get("to", []))
    ]


def test_local_llm_services_use_gateway_and_public_egress_is_least_privilege() -> None:
    documents = _render_local()
    egress = _egress_by_deployment(documents)
    policies = {
        document["metadata"]["name"]: document for document in documents if document.get("kind") == "NetworkPolicy"
    }

    assert egress.keys() >= _LLM_SERVICES
    for service in _LLM_SERVICES:
        gateway_rules = [
            rule
            for rule in egress[service]
            if any(peer.get("podSelector", {}).get("matchLabels") == _GATEWAY_SELECTOR for peer in rule.get("to", []))
        ]
        assert gateway_rules == [
            {
                "to": [{"podSelector": {"matchLabels": _GATEWAY_SELECTOR}}],
                "ports": [{"port": 8443, "protocol": "TCP"}],
            }
        ], service

    # Provider traffic leaves only through the model-egress gateway.
    assert _public_rules(policies[_MODEL_GATEWAY]["spec"]["egress"]) == [_PUBLIC_HTTPS_RULE]

    # Preserve direct HTTPS only for declared external integrations. This also
    # keeps Kafka-only workers (including ml-compute) and every other workload private.
    for service, rules in egress.items():
        expected = [_PUBLIC_HTTPS_RULE] if service in _DIRECT_PUBLIC_HTTPS_SERVICES else []
        assert _public_rules(rules) == expected, service
