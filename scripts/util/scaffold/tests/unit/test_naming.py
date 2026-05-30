"""Tests for pure naming derivations."""

from __future__ import annotations

import pytest
from nohiki_scaffold.core import naming


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("user-pref-service", "user_pref_service"),
        ("bff-service", "bff_service"),
        ("a-b-c", "a_b_c"),
        ("single", "single"),
    ],
)
def test_kebab_to_snake(raw: str, expected: str) -> None:
    assert naming.kebab_to_snake(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("user_pref_service", "user-pref-service"),
        ("bff", "bff"),
    ],
)
def test_snake_to_kebab(raw: str, expected: str) -> None:
    assert naming.snake_to_kebab(raw) == expected


@pytest.mark.parametrize(
    ("service_name", "expected"),
    [
        ("user-pref-service", "USER_PREF_"),
        ("bff-service", "BFF_"),
        ("ml-gateway-service", "ML_GATEWAY_"),
        ("skill-graph-service", "SKILL_GRAPH_"),
        ("no-suffix-here", "NO_SUFFIX_HERE_"),
    ],
)
def test_env_prefix(service_name: str, expected: str) -> None:
    assert naming.env_prefix(service_name) == expected


@pytest.mark.parametrize(
    ("service_name", "expected"),
    [
        ("user-pref-service", "user_pref_schema"),
        ("skill-graph-service", "skill_graph_schema"),
        ("bff-service", "bff_schema"),
    ],
)
def test_schema_name(service_name: str, expected: str) -> None:
    assert naming.schema_name(service_name) == expected


def test_module_name_for_lib() -> None:
    assert naming.module_name("nohiki-foo-utils") == "nohiki_foo_utils"


def test_upper_const() -> None:
    assert naming.upper_const("max_handlers") == "MAX_HANDLERS"
