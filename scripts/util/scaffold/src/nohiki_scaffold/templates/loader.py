"""Jinja2 environment factory for scaffold templates.

Uses `StrictUndefined` so any missing context variable fails loudly rather than
silently rendering an empty string. Custom filters are registered here and
exposed to all templates.
"""

from __future__ import annotations

from functools import lru_cache

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from nohiki_scaffold.core.naming import (
    env_prefix as _env_prefix,
)
from nohiki_scaffold.core.naming import (
    kebab_to_snake as _kebab_to_snake,
)
from nohiki_scaffold.core.naming import (
    module_name as _module_name,
)
from nohiki_scaffold.core.naming import (
    schema_name as _schema_name,
)
from nohiki_scaffold.core.naming import (
    snake_to_kebab as _snake_to_kebab,
)
from nohiki_scaffold.core.naming import (
    upper_const as _upper_const,
)


def _sort_alpha(values: list[str]) -> list[str]:
    """Return a new list sorted alphabetically (case-insensitive)."""
    return sorted(values, key=str.lower)


@lru_cache(maxsize=1)
def get_environment() -> Environment:
    """Return the singleton Jinja environment used to render templates.

    Configuration is non-negotiable: `StrictUndefined` + `keep_trailing_newline`
    are load-bearing for template correctness. HTML autoescaping is disabled
    via `select_autoescape` with an empty allow-list because we render Python,
    TOML, Dockerfile, and Markdown source -- escaping would corrupt output.
    """
    env = Environment(
        loader=PackageLoader("nohiki_scaffold", "templates"),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=select_autoescape(enabled_extensions=(), default_for_string=False, default=False),
    )
    env.filters["snake"] = _kebab_to_snake
    env.filters["kebab"] = _snake_to_kebab
    env.filters["env_prefix"] = _env_prefix
    env.filters["schema_name"] = _schema_name
    env.filters["module_name"] = _module_name
    env.filters["upper_const"] = _upper_const
    env.filters["sort_alpha"] = _sort_alpha
    return env
