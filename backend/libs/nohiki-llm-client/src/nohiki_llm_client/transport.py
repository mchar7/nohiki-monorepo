"""Model-scoped HTTP transport helpers."""

import ipaddress
import ssl
from typing import Final
from urllib.parse import urlsplit

import certifi

OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER: Final = "openai-compatible-no-auth"
OLLAMA_API_KEY_PLACEHOLDER: Final = "api-key-not-set"
LLAMACPP_API_KEY_PLACEHOLDER: Final = "none"
_MAX_DNS_HOSTNAME_LENGTH: Final = 253
_MAX_DNS_LABEL_LENGTH: Final = 63


def resolve_local_api_key(api_key: str | None, *, placeholder: str) -> str:
    """Return an explicit nonempty key, sealing provider environment fallbacks."""
    return api_key if api_key is not None and api_key.strip() else placeholder


def _validate_hostname(hostname: str, *, field_name: str) -> None:
    """Require an IP literal or canonical DNS hostname."""
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        return

    if all(character in "0123456789." for character in hostname) or ":" in hostname:
        msg = f"{field_name} contains an invalid IP address"
        raise ValueError(msg)
    try:
        ascii_hostname = hostname.encode("idna").decode("ascii").removesuffix(".")
    except UnicodeError as exc:
        msg = f"{field_name} contains an invalid hostname"
        raise ValueError(msg) from exc
    labels = ascii_hostname.split(".")
    if (
        not ascii_hostname
        or len(ascii_hostname) > _MAX_DNS_HOSTNAME_LENGTH
        or any(
            not label
            or len(label) > _MAX_DNS_LABEL_LENGTH
            or label.startswith("-")
            or label.endswith("-")
            or not all(character.isascii() and (character.isalnum() or character == "-") for character in label)
            for label in labels
        )
    ):
        msg = f"{field_name} contains an invalid hostname"
        raise ValueError(msg)


def resolve_google_vertex_base_url(
    configured_base_url: str | None,
    *,
    location: str | None,
    has_api_key: bool,
) -> str:
    """Resolve Gemini Vertex routing without its ambient endpoint override."""
    if configured_base_url is not None:
        return configured_base_url
    if has_api_key or location in {None, "global"}:
        return "https://aiplatform.googleapis.com/"
    if location in {"us", "eu"}:
        return f"https://aiplatform.{location}.rep.googleapis.com/"
    return f"https://{location}-aiplatform.googleapis.com/"


def resolve_vertex_anthropic_base_url(configured_base_url: str | None, *, region: str) -> str:
    """Resolve Anthropic Vertex routing without its ambient endpoint override."""
    if configured_base_url is not None:
        return f"{configured_base_url.rstrip('/')}/v1"
    if region == "global":
        return "https://aiplatform.googleapis.com/v1"
    if region == "us":
        return "https://aiplatform.us.rep.googleapis.com/v1"
    if region == "eu":
        return "https://aiplatform.eu.rep.googleapis.com/v1"
    return f"https://{region}-aiplatform.googleapis.com/v1"


def validate_http_base_url(value: str, *, field_name: str = "base_url") -> str:
    """Require a credential-free absolute HTTP(S) base URL."""
    if not value.strip():
        msg = f"{field_name} is required and must be nonblank"
        raise ValueError(msg)
    parsed = urlsplit(value)
    try:
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        msg = f"{field_name} must be a valid absolute http:// or https:// URL"
        raise ValueError(msg) from exc
    if parsed.scheme not in {"http", "https"} or hostname is None or not hostname.strip():
        msg = f"{field_name} must be an absolute http:// or https:// URL with a hostname"
        raise ValueError(msg)
    _validate_hostname(hostname, field_name=field_name)
    if parsed.username is not None or parsed.password is not None:
        msg = f"{field_name} must not contain userinfo credentials"
        raise ValueError(msg)
    if parsed.query or parsed.fragment:
        msg = f"{field_name} must not contain a query or fragment"
        raise ValueError(msg)
    return value


def create_model_ssl_context(tls_ca_file: str | None) -> ssl.SSLContext:
    """Create pinned public TLS trust, optionally extended by one internal CA."""
    context = ssl.create_default_context(cafile=certifi.where())
    if tls_ca_file is not None:
        context.load_verify_locations(cafile=tls_ca_file)
    return context
