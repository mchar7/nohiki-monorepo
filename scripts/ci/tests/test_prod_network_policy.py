"""Focused first-party NetworkPolicy rendering regressions."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml
from ci_checks.core.image_inventory import load_inventory
from helm_test_utils import runtime_eso_args

_ROOT = Path(__file__).resolve().parents[3]
_CHART = _ROOT / "infra" / "k8s" / "helm"
_IDENTITY = Path(__file__).parent / "fixtures" / "values.prod.identity.yaml"
_NETWORK = Path(__file__).parent / "fixtures" / "values.prod.network.yaml"
_FIRST_PARTY_PREFIX = "ghcr.io/mchar7/nohiki-monorepo/"
_NON_PUBLIC_IPV4 = {
    "10.0.0.0/8",
    "100.64.0.0/10",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
}
_MANAGED_PORTS = {443, 5432, 6334, 6380, 9093}


def _digest_overlay(tmp_path: Path) -> Path:
    digests = {name: f"sha256:{index + 1:064x}" for index, name in enumerate(load_inventory().names)}
    path = tmp_path / "values.prod.digests.yaml"
    path.write_text(yaml.safe_dump({"global": {"imageDigests": digests}}), encoding="utf-8")
    return path


def _render(values_name: str, tmp_path: Path, *extra_args: str) -> tuple[dict[str, Any], ...]:
    command = [
        "helm",
        "template",
        "nohiki",
        str(_CHART),
        "--namespace",
        f"nohiki-{values_name.removeprefix('values.').removesuffix('.yaml')}",
        "--values",
        str(_CHART / values_name),
    ]
    if values_name == "values.prod.yaml":
        command.extend(
            (
                "--values",
                str(_IDENTITY),
                "--values",
                str(_NETWORK),
                "--values",
                str(_digest_overlay(tmp_path)),
            )
        )
    command.extend(runtime_eso_args(values_name.removeprefix("values.").removesuffix(".yaml")))
    result = subprocess.run([*command, *extra_args], cwd=_ROOT, check=True, capture_output=True, text=True)
    return tuple(document for document in yaml.safe_load_all(result.stdout) if isinstance(document, dict))


def _labels(document: dict[str, Any]) -> dict[str, str]:
    template = (
        document["spec"]["template"]
        if document["kind"] == "Deployment"
        else document["spec"]["jobTemplate"]["spec"]["template"]
    )
    return template["metadata"]["labels"]


def _selects(selector: dict[str, Any], labels: dict[str, str]) -> bool:
    match_labels = selector.get("matchLabels", {})
    return all(labels.get(key) == value for key, value in match_labels.items())


def _first_party_pods(documents: Iterable[dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {
        document["metadata"]["name"]: _labels(document)
        for document in documents
        if document.get("kind") in {"Deployment", "CronJob"}
        and any(
            container.get("image", "").startswith(_FIRST_PARTY_PREFIX)
            for container in (
                document["spec"]["template"]["spec"]["containers"]
                if document["kind"] == "Deployment"
                else document["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"]
            )
        )
    }


def _policy_union(
    documents: Iterable[dict[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    documents = tuple(documents)
    policies = [document for document in documents if document.get("kind") == "NetworkPolicy"]
    union: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for name, labels in _first_party_pods(documents).items():
        selected = [policy for policy in policies if _selects(policy["spec"]["podSelector"], labels)]
        union[name] = {
            direction: [rule for policy in selected for rule in policy["spec"].get(direction, [])]
            for direction in ("ingress", "egress")
        }
    return union


def _ports(rule: dict[str, Any]) -> set[tuple[str, int]]:
    return {(port.get("protocol", "TCP"), port["port"]) for port in rule.get("ports", [])}


def _pod_sources(rules: Iterable[dict[str, Any]]) -> set[tuple[tuple[str, str], ...]]:
    return {
        tuple(sorted(peer["podSelector"]["matchLabels"].items()))
        for rule in rules
        for peer in rule.get("from", [])
        if "podSelector" in peer
    }


def _public_ports(rules: Iterable[dict[str, Any]]) -> set[int]:
    return {
        port
        for rule in rules
        if any(peer.get("ipBlock", {}).get("cidr") == "0.0.0.0/0" for peer in rule.get("to", []))
        for _, port in _ports(rule)
    }


def test_prod_policy_union_has_only_exact_ingress_callers(tmp_path: Path) -> None:
    documents = _render("values.prod.yaml", tmp_path)
    union = _policy_union(documents)
    assert union
    expected_ingress_ports = {name: {("TCP", 8080)} if name == "nohiki-frontend" else {("TCP", 8000)} for name in union}
    for name, policy in union.items():
        for rule in policy["ingress"]:
            assert rule, name
            assert rule.get("from"), name
            assert rule.get("ports"), name
            assert not any(peer.get("namespaceSelector") == {} for peer in rule["from"]), name
            assert _ports(rule) == expected_ingress_ports[name], name

    auth = union["nohiki-user-auth-service"]["ingress"]
    bff = union["nohiki-bff-service"]["ingress"]
    auth_sources = _pod_sources(auth)
    bff_sources = _pod_sources(bff)
    assert auth_sources == {
        (
            ("app.kubernetes.io/instance", "nohiki"),
            ("app.kubernetes.io/name", "bff-service"),
        ),
        (("gateway.networking.k8s.io/gateway-name", "nohiki-gateway"),),
        (
            ("app.kubernetes.io/name", "prometheus"),
            ("operator.prometheus.io/name", "nohiki-kube-prometheus-stack-prometheus"),
        ),
    }
    assert bff_sources == {
        (("gateway.networking.k8s.io/gateway-name", "nohiki-gateway"),),
        (
            ("app.kubernetes.io/name", "prometheus"),
            ("operator.prometheus.io/name", "nohiki-kube-prometheus-stack-prometheus"),
        ),
    }
    gateway = (("gateway.networking.k8s.io/gateway-name", "nohiki-gateway"),)
    gateway_reachable = {name for name, policy in union.items() if gateway in _pod_sources(policy["ingress"])}
    assert gateway_reachable == {
        "nohiki-user-auth-service",
        "nohiki-bff-service",
        "nohiki-frontend",
    }
    assert _pod_sources(union["nohiki-frontend"]["ingress"]) == {gateway}


def test_prod_internal_dns_otel_and_external_egress_are_exact(tmp_path: Path) -> None:
    union = _policy_union(_render("values.prod.yaml", tmp_path))
    for name, policy in union.items():
        for rule in policy["egress"]:
            assert rule, name
            assert rule.get("to"), name
            assert rule.get("ports"), name
        dns = [rule for rule in policy["egress"] if _ports(rule) == {("TCP", 53), ("UDP", 53)}]
        assert dns == [
            {
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
        ], name
        if name in {"nohiki-schedule-tick-publisher", "nohiki-frontend"}:
            assert not [rule for rule in policy["egress"] if _ports(rule) == {("TCP", 4317)}], name
            continue
        otel = [rule for rule in policy["egress"] if _ports(rule) == {("TCP", 4317)}]
        assert otel == [
            {
                "to": [
                    {
                        "podSelector": {
                            "matchLabels": {
                                "app.kubernetes.io/name": "otel-collector",
                                "app.kubernetes.io/instance": "nohiki",
                            }
                        }
                    }
                ],
                "ports": [{"port": 4317, "protocol": "TCP"}],
            }
        ], name

    auth_destination = (
        ("app.kubernetes.io/instance", "nohiki"),
        ("app.kubernetes.io/name", "user-auth-service"),
    )
    bff_destination = (
        ("app.kubernetes.io/instance", "nohiki"),
        ("app.kubernetes.io/name", "bff-service"),
    )

    def internal(rules: Iterable[dict[str, Any]]) -> set[tuple[tuple[str, str], ...]]:
        return {
            tuple(sorted(peer["podSelector"]["matchLabels"].items()))
            for rule in rules
            if _ports(rule) == {("TCP", 8000)}
            for peer in rule["to"]
            if "podSelector" in peer
        }

    assert internal(union["nohiki-bff-service"]["egress"]) == {auth_destination}
    assert internal(union["nohiki-frontend"]["egress"]) == {bff_destination}
    assert all(
        not internal(policy["egress"])
        for name, policy in union.items()
        if name not in {"nohiki-bff-service", "nohiki-frontend"}
    )

    expected_public = {
        "nohiki-job-correlation-evaluation-service": {6334},
        "nohiki-job-ingest-discovery-service": {443},
        "nohiki-job-ingest-enrichment-service": {443},
        "nohiki-skill-graph-service": {443, 6334},
        "nohiki-job-storage-service": {6334},
        "nohiki-user-pref-service": {6334},
        "nohiki-notification-service": {443},
    }
    for name, ports in expected_public.items():
        assert _public_ports(union[name]["egress"]) == ports, name
    for name, policy in union.items():
        public_ports = _public_ports(policy["egress"])
        assert 587 not in public_ports, name
        assert not ({5432, 6380, 9093} & public_ports), name
        if name not in expected_public:
            assert not public_ports, name


def test_prod_managed_azure_egress_uses_exact_private_endpoints(tmp_path: Path) -> None:
    documents = _render("values.prod.yaml", tmp_path)
    union = _policy_union(documents)
    expected = {
        5432: "10.42.16.4/32",
        6380: "10.42.16.5/32",
        443: "10.42.16.6/32",
        9093: "10.42.16.7/32",
    }
    for port, cidr in expected.items():
        assert any(
            peer.get("ipBlock", {}).get("cidr") == cidr
            for policy in union.values()
            for rule in policy["egress"]
            if ("TCP", port) in _ports(rule)
            for peer in rule["to"]
        ), (port, cidr)

    overlay = yaml.safe_load(_NETWORK.read_text(encoding="utf-8"))["global"]
    assert overlay["database"] == {
        "host": "nohiki-prod-postgres.postgres.database.azure.com",
        "port": 5432,
    }
    assert overlay["redis"] == {
        "host": "nohiki-prod-redis.redis.cache.windows.net",
        "port": 6380,
    }
    assert overlay["s3"] == {
        "endpoint": "https://nohikiprod.blob.core.windows.net",
        "port": 443,
    }
    assert overlay["kafka"] == {
        "bootstrapServers": "nohiki-prod-eventhubs.servicebus.windows.net:9093",
        "dsn": "kafka://nohiki-prod-eventhubs.servicebus.windows.net:9093",
        "port": 9093,
    }


def test_public_https_rules_exclude_private_networks(tmp_path: Path) -> None:
    union = _policy_union(_render("values.prod.yaml", tmp_path))
    https_rules = [rule for policy in union.values() for rule in policy["egress"] if ("TCP", 443) in _ports(rule)]
    assert https_rules
    for rule in https_rules:
        public = [peer["ipBlock"] for peer in rule["to"] if peer.get("ipBlock", {}).get("cidr") == "0.0.0.0/0"]
        if public:
            assert set(public[0].get("except", ())) == _NON_PUBLIC_IPV4


@pytest.mark.parametrize("values_name", ["values.local.yaml", "values.staging.yaml"])
def test_non_prod_overlays_still_render(values_name: str, tmp_path: Path) -> None:
    assert _render(values_name, tmp_path)
