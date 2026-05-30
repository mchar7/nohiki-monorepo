"""Sanity checks on the ci-checks constants passthrough."""

from __future__ import annotations

from nohiki_scaffold.core.canonical import (
    CANONICAL_BUILD_BACKEND,
    CANONICAL_REQUIRES,
    canonical_build_system_block,
)


def test_canonical_build_backend() -> None:
    assert CANONICAL_BUILD_BACKEND == "uv_build"


def test_canonical_requires_is_tuple() -> None:
    assert isinstance(CANONICAL_REQUIRES, tuple)
    assert any("uv_build" in r for r in CANONICAL_REQUIRES)


def test_canonical_block_is_parseable_toml() -> None:
    import tomllib

    block = canonical_build_system_block()
    parsed = tomllib.loads(block)
    assert parsed["build-system"]["build-backend"] == "uv_build"
    assert parsed["build-system"]["requires"] == list(CANONICAL_REQUIRES)
