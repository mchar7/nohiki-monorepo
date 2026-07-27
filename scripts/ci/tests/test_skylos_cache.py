"""Contracts for sound Skylos grep-verification caching."""

from __future__ import annotations

from pathlib import Path

import pytest
from ci_checks.checks.skylos_cache import _configure_grep_cache, _hash_file


class _Cache:
    def __init__(self) -> None:
        self.entries: dict[str, list[str]] = {}

    def get(self, key: str) -> list[str] | None:
        return self.entries.get(key)

    def put(self, key: str, results: list[str]) -> None:
        self.entries[key] = results


@pytest.mark.requires_skylos
def test_grep_cache_key_changes_when_search_corpus_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a usage outside the defining file must invalidate cached search results."""
    # The analyzer is a private distribution absent from the shared environment closure, so the
    # module must stay importable without it; only this test needs the real cache internals.
    from skylos.core import grep_cache, grep_verify

    defining_file = tmp_path / "definition.py"
    usage_file = tmp_path / "usage.py"
    defining_file.write_text("def target():\n    return 1\n", encoding="utf-8")
    usage_file.write_text("value = 1\n", encoding="utf-8")
    finding = {
        "simple_name": "target",
        "full_name": "definition.target",
        "type": "function",
        "file": str(defining_file),
    }
    cache = _Cache()
    monkeypatch.setattr(grep_cache, "file_content_hash", grep_cache.file_content_hash)
    monkeypatch.setattr(
        grep_verify,
        "_GREP_VERIFY_CACHE_VERSION",
        grep_verify._GREP_VERIFY_CACHE_VERSION,
    )

    first_namespace = _configure_grep_cache(tmp_path)
    first = grep_verify._cached_group_results(cache, "imports", finding, lambda: {"imports": []})
    usage_file.write_text("target()\n", encoding="utf-8")
    second_namespace = _configure_grep_cache(tmp_path)
    second = grep_verify._cached_group_results(
        cache,
        "imports",
        finding,
        lambda: {"imports": [str(usage_file)]},
    )

    assert first == {"imports": []}
    assert second == {"imports": [str(usage_file)]}
    assert first_namespace.startswith("v4:")
    assert first_namespace != second_namespace
    assert len(cache.entries) == 2


def test_defining_file_hash_covers_bytes_after_first_eight_kibibytes(
    tmp_path: Path,
) -> None:
    """Same-size edits anywhere in a defining file must invalidate its cache identity."""
    defining_file = tmp_path / "definition.py"
    defining_file.write_bytes(b"x" * 8192 + b"alive")
    before = _hash_file(defining_file)
    defining_file.write_bytes(b"x" * 8192 + b"dead!")

    assert _hash_file(defining_file) != before
