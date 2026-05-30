"""Pure naming derivations.

All functions are deterministic and side-effect-free; every result is a
pure function of the inputs. These are the same derivations that drive
Jinja filters in :mod:`nohiki_scaffold.templates.loader`.
"""

from __future__ import annotations

_SERVICE_SUFFIX = "-service"


def kebab_to_snake(name: str) -> str:
    """Convert kebab-case to snake_case.

    >>> kebab_to_snake("user-pref-service")
    'user_pref_service'
    """
    return name.replace("-", "_")


def snake_to_kebab(name: str) -> str:
    """Convert snake_case to kebab-case.

    >>> snake_to_kebab("user_pref_service")
    'user-pref-service'
    """
    return name.replace("_", "-")


def module_name(name: str) -> str:
    """Derive Python module name from a distribution name.

    >>> module_name("user-pref-service")
    'user_pref_service'
    >>> module_name("nohiki-foo-utils")
    'nohiki_foo_utils'
    """
    return kebab_to_snake(name)


def env_prefix(service_name: str) -> str:
    """Derive Pydantic settings ``env_prefix`` from a service name.

    Drops the trailing ``-service`` suffix (if present) before uppercasing.

    >>> env_prefix("user-pref-service")
    'USER_PREF_'
    >>> env_prefix("bff-service")
    'BFF_'
    >>> env_prefix("ml-gateway-service")
    'ML_GATEWAY_'
    """
    stem = service_name.removesuffix(_SERVICE_SUFFIX)
    return f"{stem.replace('-', '_').upper()}_"


def schema_name(service_name: str) -> str:
    """Derive PostgreSQL schema name from a service name.

    Drops the trailing ``-service`` suffix and appends ``_schema``.

    >>> schema_name("user-pref-service")
    'user_pref_schema'
    >>> schema_name("skill-graph-service")
    'skill_graph_schema'
    """
    stem = service_name.removesuffix(_SERVICE_SUFFIX)
    return f"{stem.replace('-', '_')}_schema"


def upper_const(name: str) -> str:
    """Convert a snake_case identifier to UPPER_SNAKE_CASE.

    >>> upper_const("max_handlers")
    'MAX_HANDLERS'
    """
    return name.upper()


__all__ = [
    "env_prefix",
    "kebab_to_snake",
    "module_name",
    "schema_name",
    "snake_to_kebab",
    "upper_const",
]
