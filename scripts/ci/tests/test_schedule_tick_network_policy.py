"""Regression tests for the schedule-tick publisher's production network boundary."""

import json
import subprocess
from pathlib import Path

import pytest
import yaml
from test_image_digest_gitops import _digest_values

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_CHART = _REPOSITORY_ROOT / "infra" / "k8s" / "helm"
_NAME_LABEL = "app.kubernetes.io/name"
_PUBLISHER = "schedule-tick-publisher"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_RFC1918_EXCEPT = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
_DNS_RULE = {
    "to": [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "kube-system"}},
            "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
        }
    ],
    "ports": [
        {"port": 53, "protocol": "UDP"},
        {"port": 53, "protocol": "TCP"},
    ],
}


def _render_production(tmp_path: Path, kafka_cidrs: tuple[str, ...] = ()) -> tuple[dict, ...]:
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        "nohiki-prod",
        "--values",
        str(_CHART / "values.prod.yaml"),
        "--values",
        str(_IDENTITY),
        "--values",
        str(_NETWORK),
        "--values",
        str(_digest_values(tmp_path)),
    ]
    if kafka_cidrs:
        command.extend(
            [
                "--set-json",
                "global.networkPolicy.managedEgress.kafka.cidrs=" + json.dumps(kafka_cidrs),
            ]
        )
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _publisher_policy(documents: tuple[dict, ...]) -> dict:
    policies = [
        document
        for document in documents
        if document.get("kind") == "NetworkPolicy"
        and document.get("spec", {}).get("podSelector", {}).get("matchLabels", {}).get(_NAME_LABEL) == _PUBLISHER
    ]
    assert len(policies) == 1
    return policies[0]


def _publisher_pod_labels(documents: tuple[dict, ...]) -> list[dict[str, str]]:
    return [
        document["spec"]["jobTemplate"]["spec"]["template"]["metadata"]["labels"]
        for document in documents
        if document.get("kind") == "CronJob"
        and document.get("metadata", {}).get("labels", {}).get(_NAME_LABEL) == _PUBLISHER
    ]


def _assert_policy_contract(documents: tuple[dict, ...], kafka_cidrs: tuple[str, ...]) -> None:
    policy = _publisher_policy(documents)
    spec = policy["spec"]
    selector = spec["podSelector"]["matchLabels"]
    pod_labels = _publisher_pod_labels(documents)

    assert pod_labels
    assert all(labels.items() >= selector.items() for labels in pod_labels)
    assert spec["policyTypes"] == ["Ingress", "Egress"]
    assert spec["ingress"] == []

    kafka_rule = {
        "to": [
            {"ipBlock": {"cidr": cidr, "except": _RFC1918_EXCEPT}}
            if cidr == "0.0.0.0/0"
            else {"ipBlock": {"cidr": cidr}}
            for cidr in kafka_cidrs
        ],
        "ports": [{"port": 9093, "protocol": "TCP"}],
    }
    assert spec["egress"] == [_DNS_RULE, kafka_rule]

    ports = {(port["protocol"], port["port"]) for rule in spec["egress"] for port in rule.get("ports", [])}
    assert ports == {("UDP", 53), ("TCP", 53), ("TCP", 9093)}


@pytest.mark.parametrize(
    "kafka_cidrs",
    [
        pytest.param(("0.0.0.0/0",), id="configured-production-cidr"),
        pytest.param(("10.42.8.0/24", "10.42.9.16/28"), id="managed-cidr-override"),
    ],
)
def test_schedule_tick_production_network_policy_is_least_privilege(
    kafka_cidrs: tuple[str, ...], tmp_path: Path
) -> None:
    _assert_policy_contract(_render_production(tmp_path, kafka_cidrs), kafka_cidrs)
