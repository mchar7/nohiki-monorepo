#!/usr/bin/env python3
"""Generate the reviewed production network overlay from OpenTofu output."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
from pathlib import Path
from typing import NoReturn, cast
from urllib.parse import urlsplit

SERVICES = {
    "database": {"host", "port", "cidrs"},
    "redis": {"host", "port", "cidrs"},
    "s3": {"endpoint", "port", "cidrs"},
    "kafka": {"bootstrapServers", "dsn", "port", "cidrs"},
}
EXPECTED_TYPE = [
    "object",
    {
        "database": [
            "object",
            {"cidrs": ["list", "string"], "host": "string", "port": "number"},
        ],
        "redis": [
            "object",
            {"cidrs": ["list", "string"], "host": "string", "port": "number"},
        ],
        "s3": [
            "object",
            {"cidrs": ["list", "string"], "endpoint": "string", "port": "number"},
        ],
        "kafka": [
            "object",
            {
                "bootstrapServers": "string",
                "cidrs": ["list", "string"],
                "dsn": "string",
                "port": "number",
            },
        ],
    },
]
PORTS = {"database": 5432, "redis": 6380, "s3": 443, "kafka": 9093}
HOST_SUFFIXES = {
    "database": ".postgres.database.azure.com",
    "redis": ".redis.cache.windows.net",
    "kafka": ".servicebus.windows.net",
}
HOST_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\Z")
RFC1918 = tuple(ipaddress.ip_network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def _fail(message: str) -> NoReturn:
    raise ValueError(message)


def _canonical_host(value: object, service: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not HOST_RE.fullmatch(value):
        _fail(f"{service}.host must be a canonical lowercase hostname")
    if not value.endswith(HOST_SUFFIXES[service]):
        _fail(f"{service}.host must use the canonical Azure hostname")
    return value


def _private_cidrs(value: object, service: str) -> list[str]:
    if not isinstance(value, list) or not value:
        _fail(f"{service}.cidrs must be a non-empty list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            _fail(f"{service}.cidrs must contain strings")
        try:
            network = ipaddress.ip_network(item, strict=True)
        except ValueError as exc:
            _fail(f"{service}.cidrs contains invalid CIDR: {exc}")
        if (
            network.version != 4
            or network.prefixlen != 32
            or item != str(network)
            or not any(network.subnet_of(private) for private in RFC1918)
        ):
            _fail(f"{service}.cidrs must contain canonical RFC1918 IPv4 /32 networks")
        result.append(item)
    if len(result) != len(set(result)):
        _fail(f"{service}.cidrs must not contain duplicates")
    return sorted(result, key=lambda cidr: int(ipaddress.ip_network(cidr).network_address))


def _load_output(path: Path) -> dict[str, dict[str, object]]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"invalid OpenTofu output JSON: {exc}")
    if not isinstance(document, dict) or set(document) != {"production_network"}:
        _fail("OpenTofu output JSON must contain exactly production_network")
    output = document["production_network"]
    if not isinstance(output, dict) or set(output) != {"sensitive", "type", "value"}:
        _fail("production_network has an unexpected OpenTofu serialization")
    if output["sensitive"] is not False or output["type"] != EXPECTED_TYPE:
        _fail("production_network must be a non-sensitive object with the exact expected type")
    value = output["value"]
    if not isinstance(value, dict) or set(value) != set(SERVICES):
        _fail("production_network must contain exactly database, redis, s3, and kafka")

    validated: dict[str, dict[str, object]] = {}
    for service, keys in SERVICES.items():
        item = value[service]
        if not isinstance(item, dict) or set(item) != keys:
            _fail(f"production_network.{service} has unexpected keys")
        if type(item["port"]) is not int or item["port"] != PORTS[service]:
            _fail(f"{service}.port must be {PORTS[service]}")
        validated[service] = {**item, "cidrs": _private_cidrs(item["cidrs"], service)}

    for service in ("database", "redis"):
        validated[service]["host"] = _canonical_host(validated[service]["host"], service)

    endpoint = validated["s3"]["endpoint"]
    if not isinstance(endpoint, str):
        _fail("s3.endpoint must be a string")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".blob.core.windows.net")
        or parsed.hostname != parsed.hostname.lower()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        _fail("s3.endpoint must be a canonical credential-free HTTPS Azure Blob URL")
    validated["s3"]["endpoint"] = f"https://{parsed.hostname}"

    bootstrap = validated["kafka"]["bootstrapServers"]
    dsn = validated["kafka"]["dsn"]
    if not isinstance(bootstrap, str) or bootstrap.count(":") != 1:
        _fail("kafka.bootstrapServers must be an Azure Event Hubs hostname and port")
    host, port = bootstrap.rsplit(":", 1)
    _canonical_host(host, "kafka")
    if port != "9093" or dsn != f"kafka://{host}:9093":
        _fail("kafka endpoints must use the same canonical Event Hubs hostname on port 9093")
    return validated


def _generate(source: Path, destination: Path) -> None:
    values = _load_output(source)
    lines = [
        "# Generated from the allowlisted non-sensitive OpenTofu production_network output; do not edit.",
        "global:",
    ]
    for service in ("database", "redis"):
        lines += [
            f"  {service}:",
            f'    host: "{values[service]["host"]}"',
            f"    port: {values[service]['port']}",
        ]
    lines += [
        "  s3:",
        f'    endpoint: "{values["s3"]["endpoint"]}"',
        f"    port: {values['s3']['port']}",
        "  kafka:",
        f'    bootstrapServers: "{values["kafka"]["bootstrapServers"]}"',
        f'    dsn: "{values["kafka"]["dsn"]}"',
        f"    port: {values['kafka']['port']}",
        "  networkPolicy:",
        "    managedEgress:",
    ]
    for service in ("database", "redis", "s3", "kafka"):
        cidrs = ", ".join(cast(list[str], values[service]["cidrs"]))
        lines += [f"      {service}:", f"        cidrs: [{cidrs}]"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join((*lines, "")), encoding="utf-8")


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opentofu-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    _generate(args.opentofu_output, args.output)


if __name__ == "__main__":
    _main()
