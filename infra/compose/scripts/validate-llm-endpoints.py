#!/usr/bin/env python3
"""Validate rendered Compose LLM provider endpoint bindings without exposing values."""

from __future__ import annotations

import ipaddress
import json
import re
import sys
from pathlib import Path
from typing import Never
from urllib.parse import urlsplit

_MODEL_KEY = re.compile(r"^[A-Z0-9_]+_LLM__.*__MODELS__[0-9]+__MODEL$")
_BASE_URL_KEY = re.compile(r"^[A-Z0-9_]+_LLM__.*__MODELS__[0-9]+__BASE_URL$")
_LLM_BINDING_KEY = re.compile(r"^(?:NOHIKI_LLM_[A-Z0-9_]+|[A-Z0-9_]+_LLM__.+)$", re.IGNORECASE)
_ENVIRONMENT_LINE = re.compile(r"^\s+([A-Za-z_][A-Za-z0-9_]*):(?:\s+(.*))?$")
_DOUBLE_QUOTED_YAML_SCALAR = r'"(?:[^"\\]|\\(?:\r?\n[ \t]*|.))*"'
_DOUBLE_QUOTED_SCALAR_PATTERN = re.compile(_DOUBLE_QUOTED_YAML_SCALAR)
_STANDALONE_INCLUDE = re.compile(r"(?<![A-Za-z0-9_./-])include(?![A-Za-z0-9_./-])", re.IGNORECASE)
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_QUOTED_SCALAR_MIN_LENGTH = 2
_MIN_PORT = 1
_MAX_PORT = 65535
_MAX_DNS_LENGTH = 253
_DEFAULT_HTTPS_PORT = 443
_MIN_VALIDATE_ARG_COUNT = 3
_ENCODE_ACTION_ARG_COUNT = 4
_VALIDATE_SOURCES_MIN_ARG_COUNT = 3
_C0_LIMIT = 32
_DEL = 127
_ASCII_LIMIT = 128
_BRACKETED_AUTHORITY = re.compile(r"^\[([^\]]+)](?::([0-9]+))?$")
_URL_IN_DIAGNOSTIC = re.compile(r"(?i)\bhttps?://[^\s'\"<>]+")
_YAML_HEX_ESCAPE = re.compile(r"\\x([0-9A-Fa-f]{2})")
_YAML_LONG_UNICODE_ESCAPE = re.compile(r"\\U([0-9A-Fa-f]{8})")
_YAML_LINE_CONTINUATION = re.compile(r"\\\r?\n[ \t]*")
_SECRET_ASSIGNMENT = re.compile(r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET)[A-Z0-9_]*)=([^\s]+)")
_ENDPOINT_ASSIGNMENT = re.compile(r"(?im)\b([A-Z0-9_]*(?:BASE_URL|HEALTH_URL|TLS_CA_FILE))=.*$")
_BASE_BINDINGS = {
    "openai": "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}",
    "anthropic": "${NOHIKI_LLM_ANTHROPIC_BASE_URL:?set NOHIKI_LLM_ANTHROPIC_BASE_URL}",
}
_INPUT_BINDINGS = {
    "NOHIKI_LLM_OPENAI_BASE_URL": "${NOHIKI_LLM_OPENAI_BASE_URL:?set NOHIKI_LLM_OPENAI_BASE_URL}",
    "NOHIKI_LLM_ANTHROPIC_BASE_URL": "${NOHIKI_LLM_ANTHROPIC_BASE_URL:-}",
}


class ConfigurationError(ValueError):
    """Endpoint configuration is unsafe or internally inconsistent."""


def _invalid(message: str) -> Never:
    raise ConfigurationError(message)


def _scalar(value: str | None) -> str:
    """Decode the scalar forms emitted by Compose for environment values."""
    if value is None:
        return ""
    value = value.strip()
    if len(value) >= _QUOTED_SCALAR_MIN_LENGTH and value[0] == value[-1] == '"':
        try:
            decoded = json.loads(_YAML_HEX_ESCAPE.sub(r"\\u00\1", value))
        except json.JSONDecodeError:
            _invalid("invalid quoted environment value")
        if not isinstance(decoded, str):
            _invalid("environment value must be a string")
        return decoded
    if len(value) >= _QUOTED_SCALAR_MIN_LENGTH and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


def _llm_bindings(text: str) -> dict[str, str]:
    """Collect all protected LLM environment bindings from Compose YAML."""
    bindings: dict[str, str] = {}
    seen: set[str] = set()
    for line in text.splitlines():
        match = _ENVIRONMENT_LINE.match(line)
        if match is None:
            continue
        key, raw_value = match.groups()
        if _LLM_BINDING_KEY.fullmatch(key) is None:
            continue
        normalized_key = key.upper()
        if normalized_key in seen:
            _invalid(f"duplicate Compose environment binding for {key}")
        seen.add(normalized_key)
        bindings[key] = _scalar(raw_value)
    return bindings


def _provider(model_key: str, model: str) -> str:
    """Return a supported provider from a complete provider:model identifier."""
    provider, separator, model_name = model.partition(":")
    if not separator or not provider or not model_name or any(character.isspace() for character in model):
        _invalid(f"{model_key} must use a complete provider:model identifier")
    if provider not in {*_BASE_BINDINGS, "openrouter"}:
        _invalid(f"{model_key} uses an unsupported provider category")
    return provider


def _port(port_text: str | None, variable: str) -> int:
    if port_text is None:
        return _DEFAULT_HTTPS_PORT
    if not port_text.isascii() or not port_text.isdigit():
        _invalid(f"{variable} port must be numeric")
    port = int(port_text)
    if not _MIN_PORT <= port <= _MAX_PORT:
        _invalid(f"{variable} port must be between 1 and 65535")
    return port


def _bracketed_host(authority: str, variable: str) -> tuple[str, int]:
    match = _BRACKETED_AUTHORITY.fullmatch(authority)
    if match is None:
        _invalid(f"{variable} has malformed bracketed authority")
    literal, port_text = match.groups()
    try:
        host = ipaddress.IPv6Address(literal).compressed
    except ipaddress.AddressValueError:
        _invalid(f"{variable} has invalid IPv6 authority")
    return host.lower(), _port(port_text, variable)


def _dns_or_ipv4_host(host_text: str, variable: str) -> str:
    host_text = host_text.removesuffix(".")
    if not host_text:
        _invalid(f"{variable} has empty authority")
    if all(character.isdigit() or character == "." for character in host_text):
        try:
            return str(ipaddress.IPv4Address(host_text))
        except ipaddress.AddressValueError:
            _invalid(f"{variable} has invalid IPv4 authority")
    if len(host_text) > _MAX_DNS_LENGTH or any(_DNS_LABEL.fullmatch(label) is None for label in host_text.split(".")):
        _invalid(f"{variable} has invalid DNS authority")
    return host_text.lower()


def _normalized_host(authority: str, variable: str) -> tuple[str, int]:
    """Validate an HTTPS authority and return a canonical host/port pair."""
    if authority.startswith("["):
        return _bracketed_host(authority, variable)
    if "[" in authority or "]" in authority or authority.count(":") > 1:
        _invalid(f"{variable} must bracket IPv6 authorities")
    host_text, separator, port_text = authority.partition(":")
    if not host_text:
        _invalid(f"{variable} has empty authority")
    return _dns_or_ipv4_host(host_text, variable), _port(port_text if separator else None, variable)


def _validate_url_characters(variable: str, value: str) -> None:
    if not value:
        _invalid(f"required endpoint variable {variable} must be a non-empty absolute HTTPS URL")
    if any(ord(character) < _C0_LIMIT or ord(character) == _DEL for character in value):
        _invalid(f"{variable} must not contain C0 or DEL control characters")
    if any(ord(character) >= _ASCII_LIMIT for character in value):
        _invalid(f"{variable} must contain only ASCII characters")
    if any(character.isspace() for character in value):
        _invalid(f"{variable} must be an absolute HTTPS URL without whitespace")


def _validate_url(variable: str, value: str, provider: str) -> tuple[str, str, int]:
    """Validate one provider URL and return its normalized HTTPS origin."""
    _validate_url_characters(variable, value)
    try:
        parsed = urlsplit(value)
        parsed_port = parsed.port
    except ValueError:
        _invalid(f"{variable} has malformed authority")
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        _invalid(f"{variable} must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        _invalid(f"{variable} must not contain user information")
    if parsed.query or parsed.fragment:
        _invalid(f"{variable} must not contain a query or fragment")

    host, port = _normalized_host(parsed.netloc, variable)
    if parsed_port is not None and parsed_port != port:
        _invalid(f"{variable} has inconsistent port")
    route = parsed.path.rstrip("/")
    if provider == "openai" and not route.endswith("/v1"):
        _invalid("NOHIKI_LLM_OPENAI_BASE_URL must end in /v1")
    if provider == "anthropic" and route.endswith("/v1"):
        _invalid("NOHIKI_LLM_ANTHROPIC_BASE_URL must not end in /v1")
    return "https", host, port


def _provider_inputs(
    source_bindings: dict[str, str], rendered_bindings: dict[str, str]
) -> tuple[dict[str, str], dict[str, set[tuple[str, str, int]]]]:
    endpoints: dict[str, str] = {}
    origins: dict[str, set[tuple[str, str, int]]] = {provider: set() for provider in _BASE_BINDINGS}
    for variable, expected in _INPUT_BINDINGS.items():
        if source_bindings.get(variable) != expected:
            _invalid(f"Compose must declare provider input {variable}")
        provider = variable.removeprefix("NOHIKI_LLM_").removesuffix("_BASE_URL").lower()
        endpoint = rendered_bindings.get(variable, "")
        if provider == "openai" or endpoint:
            endpoints[provider] = endpoint
            origins[provider].add(_validate_url(variable, endpoint, provider))
    return endpoints, origins


def _source_provider(
    model_key: str,
    base_key: str,
    source_model: str,
    rendered_model: str,
    source_bindings: dict[str, str],
) -> str:
    if "${" not in source_model:
        provider = _provider(model_key, source_model)
        if rendered_model != source_model:
            _invalid(f"rendered model identity changed for {model_key}")
        return provider
    lanes = [provider for provider, binding in _BASE_BINDINGS.items() if source_bindings.get(base_key) == binding]
    if len(lanes) != 1:
        _invalid(f"{model_key} has no unambiguous provider lane")
    return lanes[0]


def _validate_models(
    source_bindings: dict[str, str],
    rendered_bindings: dict[str, str],
    provider_endpoints: dict[str, str],
) -> None:
    model_keys = {key for key in source_bindings if _MODEL_KEY.fullmatch(key)}
    base_keys = {key for key in source_bindings if _BASE_URL_KEY.fullmatch(key)}
    for model_key in model_keys:
        base_key = model_key.removesuffix("__MODEL") + "__BASE_URL"
        source_model = source_bindings[model_key]
        rendered_model = rendered_bindings.get(model_key)
        if rendered_model is None:
            _invalid(f"rendered configuration is missing model binding {model_key}")
        rendered_provider = _provider(model_key, rendered_model)
        source_provider = _source_provider(
            model_key,
            base_key,
            source_model,
            rendered_model,
            source_bindings,
        )
        if rendered_provider != source_provider:
            _invalid(f"rendered provider changed for {model_key}")
        if source_provider == "openrouter":
            if base_key in source_bindings or base_key in rendered_bindings:
                _invalid(f"public OpenRouter model {model_key} must omit BASE_URL")
            continue
        if source_bindings.get(base_key) != _BASE_BINDINGS[source_provider]:
            _invalid(f"{model_key} must use its provider-scoped BASE_URL binding")
        if rendered_bindings.get(base_key) != provider_endpoints.get(source_provider):
            _invalid(f"rendered endpoint does not match the provider binding for {model_key}")
    for base_key in base_keys:
        model_key = base_key.removesuffix("__BASE_URL") + "__MODEL"
        if model_key not in model_keys:
            _invalid(f"orphan endpoint binding {base_key}")


def _long_unicode_escape(match: re.Match[str]) -> str:
    try:
        return chr(int(match.group(1), 16))
    except ValueError:
        return match.group(0)


def _decode_double_quoted_scalar(scalar: str) -> str | None:
    scalar = _YAML_LINE_CONTINUATION.sub("", scalar)
    scalar = _YAML_HEX_ESCAPE.sub(r"\\u00\1", scalar)
    scalar = _YAML_LONG_UNICODE_ESCAPE.sub(_long_unicode_escape, scalar)
    try:
        decoded = json.loads(scalar)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, str) else None


def _canonicalize_double_quoted_scalar(match: re.Match[str]) -> str:
    decoded = _decode_double_quoted_scalar(match.group(0))
    return match.group(0) if decoded is None else json.dumps(decoded)


def _canonicalize_source_scalars(source: str) -> str:
    return _DOUBLE_QUOTED_SCALAR_PATTERN.sub(_canonicalize_double_quoted_scalar, source)


def _reject_unsafe_source(source: str) -> None:
    """Reject the grammar-closed Compose include token before rendering."""
    canonical_source = _canonicalize_source_scalars(source)
    if _STANDALONE_INCLUDE.search(canonical_source) is not None:
        _invalid("Compose include is not allowed without complete source provenance")


def validate_sources(sources: list[str]) -> None:
    """Validate source provenance before Compose is allowed to render it."""
    for source in sources:
        _reject_unsafe_source(source)


def validate(sources: list[str], rendered: str) -> None:
    """Validate merged source bindings and their Compose-rendered endpoint values."""
    validate_sources(sources)
    source_bindings: dict[str, str] = {}
    for source in sources:
        source_bindings.update({key.upper(): value for key, value in _llm_bindings(source).items()})
    if not any(_MODEL_KEY.fullmatch(key) for key in source_bindings):
        _invalid("Compose must declare at least one protected __MODEL binding")
    rendered_collected = _llm_bindings(rendered)
    rendered_only = [key for key in rendered_collected if key.upper() not in source_bindings]
    rendered_only.sort(key=lambda key: not key.upper().endswith("__MODEL"))
    rendered_bindings = {key.upper(): value for key, value in rendered_collected.items()}
    if rendered_only:
        _invalid(f"rendered LLM binding has no validated source: {rendered_only[0]}")
    provider_endpoints, origins = _provider_inputs(source_bindings, rendered_bindings)
    _validate_models(source_bindings, rendered_bindings, provider_endpoints)
    if origins["openai"] & origins["anthropic"]:
        _invalid("OpenAI and Anthropic endpoints must use separate HTTPS origins")


def _redact_diagnostics(path: Path) -> int:
    try:
        diagnostic = path.read_text(errors="replace")
    except OSError:
        sys.stderr.write("compose configuration validation failed (diagnostics unavailable)\n")
        return 1
    diagnostic = _URL_IN_DIAGNOSTIC.sub("<redacted-url>", diagnostic)
    diagnostic = _SECRET_ASSIGNMENT.sub(r"\1=<redacted>", diagnostic)
    diagnostic = _ENDPOINT_ASSIGNMENT.sub(r"\1=<redacted>", diagnostic)
    sys.stderr.write(diagnostic or "compose configuration validation failed\n")
    if diagnostic and not diagnostic.endswith("\n"):
        sys.stderr.write("\n")
    return 1


def _validate_sources_cli(paths: list[str]) -> int:
    try:
        validate_sources([Path(path).read_text() for path in paths])
    except ConfigurationError, OSError:
        sys.stderr.write("preflight: Compose source provenance is invalid\n")
        return 1
    return 0


def _encode_action(source: str, destination: str) -> int:
    try:
        semantic_render = Path(source).read_text()
        Path(destination).write_text(semantic_render.replace("$", "$$"))
    except OSError:
        sys.stderr.write("could not encode validated Compose action configuration\n")
        return 1
    return 0


def _validate_cli(paths: list[str]) -> int:
    try:
        source_paths = [Path(path) for path in paths[:-1]]
        validate(
            [path.read_text() for path in source_paths],
            Path(paths[-1]).read_text(),
        )
    except (ConfigurationError, OSError) as error:
        sys.stderr.write(f"preflight: endpoint contract invalid: {error}\n")
        return 1
    return 0


def main() -> int:
    """Validate source and rendered Compose files supplied by preflight."""
    if len(sys.argv) == _MIN_VALIDATE_ARG_COUNT and sys.argv[1] == "--redact-errors":
        return _redact_diagnostics(Path(sys.argv[2]))
    if len(sys.argv) >= _VALIDATE_SOURCES_MIN_ARG_COUNT and sys.argv[1] == "--validate-sources":
        return _validate_sources_cli(sys.argv[2:])
    if len(sys.argv) == _ENCODE_ACTION_ARG_COUNT and sys.argv[1] == "--encode-action":
        return _encode_action(sys.argv[2], sys.argv[3])
    if len(sys.argv) < _MIN_VALIDATE_ARG_COUNT:
        sys.stderr.write("endpoint validation requires source and rendered Compose paths\n")
        return 2
    return _validate_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
