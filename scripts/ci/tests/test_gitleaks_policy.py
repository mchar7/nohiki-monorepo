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
_PUBLIC_CHECKSUM = "a557172e8348f758479e9ee4000bbbb4b4aa48302a6b73461823ea5349bad56d"
_EXPECTED_RULE_REGEXES = {
    "openrouter-api-key": r"sk-or-v1-[a-zA-Z0-9]{64}",
    "anthropic-api-key": r"sk-ant-api[a-zA-Z0-9\-_]{90,}",
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
    assert len(rules) == len(_EXPECTED_RULE_REGEXES)
    assert {rule["id"] for rule in rules} == set(_EXPECTED_RULE_REGEXES)

    for rule in rules:
        assert rule["regex"] == _EXPECTED_RULE_REGEXES[rule["id"]]
        assert "disabled" not in rule
        assert "allowlist" not in rule


def test_gitleaks_allows_only_the_anchored_public_checksum() -> None:
    config = _load_toml(_GITLEAKS)
    allowlist = config["allowlist"]

    assert set(allowlist) == {"regexes"}
    assert allowlist["regexes"] == [rf"^{_PUBLIC_CHECKSUM}$"]

    matcher = re.compile(allowlist["regexes"][0])
    assert matcher.fullmatch(_PUBLIC_CHECKSUM)
    assert not matcher.search(f"prefix-{_PUBLIC_CHECKSUM}")
    assert not matcher.search(f"{_PUBLIC_CHECKSUM}-suffix")
    assert not matcher.search("0" * 64)
    assert not matcher.search(_PUBLIC_CHECKSUM[:-1] + "0")


def test_gitleaks_has_no_broad_or_scope_level_exemptions() -> None:
    config = _load_toml(_GITLEAKS)
    scopes = [config, config["allowlist"], *config["rules"]]

    for scope in scopes:
        assert not _FORBIDDEN_EXEMPTION_KEYS.intersection(scope)
    assert all("allowlist" not in rule for rule in config["rules"])

    assert config["allowlist"]["regexes"] == [rf"^{_PUBLIC_CHECKSUM}$"]
    assert all(rule["regex"] == _EXPECTED_RULE_REGEXES[rule["id"]] for rule in config["rules"])


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
