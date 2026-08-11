from __future__ import annotations

import re
import tomllib
from functools import cache
from pathlib import Path
from typing import Any

import yaml

_ROOT = Path(__file__).resolve().parents[3]
_GITLEAKS = _ROOT / ".gitleaks.toml"
_LEFTHOOK = _ROOT / "lefthook.yml"
_JUSTFILE = _ROOT / "Justfile"
_GATEWAY_API_CRDS = _ROOT / "infra" / "k8s" / "gitops" / "gateway-api-crds" / "gateway-api-crds.yaml"
_ANCHORED_SHA256_REGEX = re.compile(r"\^[0-9a-f]{64}\$")
_EXPECTED_RULE_REGEXES = {
    "openrouter-api-key": r"sk-or-v1-[a-zA-Z0-9]{64}",
    "anthropic-api-key": r"sk-ant-api[a-zA-Z0-9\-_]{90,}",
}
_GATEWAY_DIGEST_ALLOWLIST = {
    "description": "Allow the public Gateway API bundle digest in its checksum-owner tests",
    "condition": "AND",
    "regexTarget": "line",
    "regexes": [r'''_GATEWAY_API_(?:BUNDLE_)?EXPECTED_HEX\s*=\s*"[0-9a-f]{64}"'''],
    "paths": [r"^scripts/ci/tests/test_(?:declarative_foundation|gateway_sse_route|workflow_download_checksums)\.py$"],
}
_FORBIDDEN_EXEMPTION_KEYS = {"paths", "commits", "stopwords", "disabled"}


@cache
def _load_toml(path: Path) -> dict[str, Any]:
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


@cache
def _load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value


def test_gitleaks_defaults_and_exact_custom_rules_are_active() -> None:
    config = _load_toml(_GITLEAKS)

    assert config["extend"]["useDefault"] is True
    rules = config["rules"]
    assert isinstance(rules, list)
    assert len(rules) == len(_EXPECTED_RULE_REGEXES) + 1
    rules_by_id = {rule["id"]: rule for rule in rules}
    assert set(rules_by_id) == {*_EXPECTED_RULE_REGEXES, "generic-api-key"}

    for rule_id, expected_regex in _EXPECTED_RULE_REGEXES.items():
        rule = rules_by_id[rule_id]
        assert rule["regex"] == expected_regex
        assert "disabled" not in rule
        assert "allowlists" not in rule

    generic_api_key = rules_by_id["generic-api-key"]
    assert set(generic_api_key) == {"id", "allowlists"}
    assert generic_api_key["allowlists"] == [_GATEWAY_DIGEST_ALLOWLIST]


def test_gitleaks_allows_only_the_anchored_public_checksums() -> None:
    config = _load_toml(_GITLEAKS)
    allowlist = config["allowlist"]

    assert set(allowlist) == {"regexes"}
    regexes = allowlist["regexes"]
    assert isinstance(regexes, list)
    provenance = _GATEWAY_API_CRDS.read_text(encoding="utf-8")
    approved_checksums = re.findall(r"(?m)^# sha256:\s*([0-9a-f]{64})\s*$", provenance)
    assert len(approved_checksums) == 1
    assert regexes == [f"^{approved_checksums[0]}$"]

    regex = regexes[0]
    assert _ANCHORED_SHA256_REGEX.fullmatch(regex)
    checksum = regex.removeprefix("^").removesuffix("$")
    matcher = re.compile(regex)
    assert matcher.fullmatch(checksum)
    assert not matcher.search(f"prefix-{checksum}")
    assert not matcher.search(f"{checksum}-suffix")
    replacement = "0" if checksum[-1] != "0" else "1"
    assert not matcher.search(checksum[:-1] + replacement)


def test_gitleaks_has_no_unreviewed_or_scope_level_exemptions() -> None:
    config = _load_toml(_GITLEAKS)
    rules = config["rules"]
    custom_rules = [rule for rule in rules if rule["id"] in _EXPECTED_RULE_REGEXES]
    scopes = [config, config["allowlist"], *custom_rules]

    for scope in scopes:
        assert not _FORBIDDEN_EXEMPTION_KEYS.intersection(scope)

    checksum_regexes = config["allowlist"]["regexes"]
    assert all(_ANCHORED_SHA256_REGEX.fullmatch(regex) for regex in checksum_regexes)
    assert all(rule["regex"] == _EXPECTED_RULE_REGEXES[rule["id"]] for rule in custom_rules)

    generic_api_key = next(rule for rule in rules if rule["id"] == "generic-api-key")
    assert generic_api_key["allowlists"] == [_GATEWAY_DIGEST_ALLOWLIST]


def test_lefthook_secrets_check_is_staged_redacted_and_fail_closed() -> None:
    config = _load_yaml(_LEFTHOOK)
    secrets_check = config["pre-commit"]["commands"]["secrets-check"]

    assert isinstance(secrets_check, dict)
    assert "exclude" not in secrets_check

    run = secrets_check["run"]
    assert isinstance(run, str)
    assert run == "just secrets-scan staged"

    match = re.search(r"(?ms)^secrets-scan .*?(?=^#|\Z)", _JUSTFILE.read_text(encoding="utf-8"))
    assert match is not None
    recipe = match.group()
    assert "gitleaks protect --staged" in recipe
    assert "--no-banner --redact" in recipe
    assert "|| true" not in recipe
