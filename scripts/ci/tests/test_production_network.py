from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "scripts" / "ci" / "production_network.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("production_network_under_test", _SCRIPT)
assert _SCRIPT_SPEC is not None
assert _SCRIPT_SPEC.loader is not None
_PRODUCTION_NETWORK = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(_PRODUCTION_NETWORK)

_TYPE = [
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
_VALUE = {
    "database": {
        "host": "pg-nohiki-prod.postgres.database.azure.com",
        "port": 5432,
        "cidrs": ["10.42.16.4/32"],
    },
    "redis": {
        "host": "rc-nohiki-prod.redis.cache.windows.net",
        "port": 6380,
        "cidrs": ["10.42.16.5/32"],
    },
    "s3": {
        "endpoint": "https://stnohikiprod.blob.core.windows.net",
        "port": 443,
        "cidrs": ["10.42.16.6/32"],
    },
    "kafka": {
        "bootstrapServers": "nohiki-prod.servicebus.windows.net:9093",
        "dsn": "kafka://nohiki-prod.servicebus.windows.net:9093",
        "port": 9093,
        "cidrs": ["10.42.16.7/32"],
    },
}


def _document() -> dict[str, object]:
    return {
        "production_network": {
            "sensitive": False,
            "type": copy.deepcopy(_TYPE),
            "value": copy.deepcopy(_VALUE),
        }
    }


def _run_generator(tmp_path: Path, document: object) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "opentofu-output.json"
    destination = tmp_path / "values.prod.network.yaml"
    tmp_path.mkdir(parents=True, exist_ok=True)
    source.write_text(json.dumps(document), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--opentofu-output",
            str(source),
            "--output",
            str(destination),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_generator_emits_exact_runtime_network_values_and_is_idempotent(
    tmp_path: Path,
) -> None:
    first = _run_generator(tmp_path, _document())
    assert first.returncode == 0, first.stderr
    output = tmp_path / "values.prod.network.yaml"
    first_text = output.read_text(encoding="utf-8")
    assert first_text.startswith(
        "# Generated from the allowlisted non-sensitive OpenTofu production_network output; do not edit.\n"
    )
    _PRODUCTION_NETWORK._generate(tmp_path / "opentofu-output.json", output)
    assert output.read_text(encoding="utf-8") == first_text
    assert yaml.safe_load(first_text) == {
        "global": {
            "database": {"host": _VALUE["database"]["host"], "port": 5432},
            "redis": {"host": _VALUE["redis"]["host"], "port": 6380},
            "s3": {"endpoint": _VALUE["s3"]["endpoint"], "port": 443},
            "kafka": {
                "bootstrapServers": _VALUE["kafka"]["bootstrapServers"],
                "dsn": _VALUE["kafka"]["dsn"],
                "port": 9093,
            },
            "networkPolicy": {
                "managedEgress": {service: {"cidrs": value["cidrs"]} for service, value in _VALUE.items()}
            },
        }
    }


def _mutate(path: tuple[str, ...], value: object) -> dict[str, object]:
    document = _document()
    target: object = document
    for key in path[:-1]:
        assert isinstance(target, dict)
        target = target[key]
    assert isinstance(target, dict)
    target[path[-1]] = value
    return document


@pytest.mark.parametrize(
    ("document", "case", "match"),
    [
        ({}, "missing", "must contain exactly production_network"),
        (
            {**_document(), "extra": {}},
            "extra-output",
            "must contain exactly production_network",
        ),
        (
            _mutate(("production_network", "sensitive"), value=True),
            "sensitive",
            "non-sensitive object with the exact expected type",
        ),
        (
            _mutate(("production_network", "type"), ["object", {}]),
            "malformed-type",
            "non-sensitive object with the exact expected type",
        ),
        (
            _mutate(("production_network", "value", "database", "extra"), "x"),
            "extra-field",
            "unexpected keys",
        ),
        (
            _mutate(("production_network", "value", "database", "cidrs"), ["8.8.8.8/32"]),
            "public-ip",
            "RFC1918",
        ),
        (
            _mutate(("production_network", "value", "redis", "host"), "redis.example.com"),
            "wrong-host",
            "canonical Azure hostname",
        ),
        (
            _mutate(("production_network", "value", "database", "port"), 6432),
            "wrong-port",
            "port must be",
        ),
        (
            _mutate(
                ("production_network", "value", "s3", "endpoint"),
                "http://stnohikiprod.blob.core.windows.net",
            ),
            "insecure-endpoint",
            "credential-free HTTPS Azure Blob URL",
        ),
        (
            _mutate(
                ("production_network", "value", "kafka", "dsn"),
                "kafka://other.servicebus.windows.net:9093",
            ),
            "mismatched-kafka",
            "same canonical Event Hubs hostname",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and " " not in value else None,
)
def test_generator_rejects_malformed_or_non_private_opentofu_output(
    tmp_path: Path, document: dict[str, object], case: str, match: str
) -> None:
    case_path = tmp_path / case
    case_path.mkdir(parents=True)
    source = case_path / "opentofu-output.json"
    output = case_path / "values.prod.network.yaml"
    source.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        _PRODUCTION_NETWORK._generate(source, output)
    assert not output.exists()
