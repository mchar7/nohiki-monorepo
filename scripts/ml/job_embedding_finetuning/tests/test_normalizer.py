"""Tests for the local skill text normalizer.

Verifies that the reimplemented normalizer produces identical output
to the authoritative normalizer in skill-graph-service.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from pathlib import Path

import pytest
from job_embedding_finetuning.processing.normalizer import normalize_skill_text

# Load authoritative normalizer directly from disk (avoids cross-package import)
_AUTHORITATIVE_PATH = Path("backend/services/skill-graph-service/src/skill_graph_service/seeding/normalizer.py")


def _load_authoritative_normalizer() -> Callable[[str], str] | None:
    """Load the authoritative normalizer from skill-graph-service."""
    if not _AUTHORITATIVE_PATH.exists():
        return None
    spec = importlib.util.spec_from_file_location("skill_graph_normalizer", _AUTHORITATIVE_PATH)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod.normalize_skill_text


authoritative_normalize = _load_authoritative_normalizer()

KNOWN_PAIRS = [
    ("React.JS", "react.js"),
    ("résumé writing", "resume writing"),
    ("front-end development", "front end development"),
    ("'agile' methodology", "agile methodology"),
    ("Ｍachine Learning", "machine learning"),  # noqa: RUF001 -- intentional fullwidth M for unicode normalization test
    ("   ", ""),
    ("C++", "c++"),
    ("Node.JS", "node.js"),
    ("DevOps/SRE", "devops/sre"),
    ("a" * 200, "a" * 100),
]


class TestNormalizeSkillText:
    """Unit tests for normalize_skill_text."""

    @pytest.mark.parametrize(("raw", "expected"), KNOWN_PAIRS)
    def test_known_pairs(self, raw: str, expected: str) -> None:
        """Verify known input→output mappings."""
        assert normalize_skill_text(raw) == expected

    def test_normalize_basic(self) -> None:
        assert normalize_skill_text("React.JS") == "react.js"

    def test_normalize_diacritics(self) -> None:
        assert normalize_skill_text("résumé writing") == "resume writing"

    def test_normalize_hyphen(self) -> None:
        assert normalize_skill_text("front-end development") == "front end development"

    def test_normalize_quotes(self) -> None:
        assert normalize_skill_text("'agile' methodology") == "agile methodology"

    def test_normalize_unicode(self) -> None:
        assert normalize_skill_text("Ｍachine Learning") == "machine learning"  # noqa: RUF001 -- intentional fullwidth M

    def test_normalize_truncation(self) -> None:
        long_text = "a" * 200
        assert len(normalize_skill_text(long_text)) == 100

    def test_normalize_empty(self) -> None:
        assert normalize_skill_text("   ") == ""


@pytest.mark.skipif(
    authoritative_normalize is None,
    reason="Authoritative normalizer not found (not running from repo root)",
)
class TestNormalizerParity:
    """Verify local normalizer produces identical output to authoritative version."""

    @pytest.mark.parametrize(("raw", "expected"), KNOWN_PAIRS)
    def test_parity(self, raw: str, expected: str) -> None:
        """Both normalizers must produce identical output for all test cases."""
        local = normalize_skill_text(raw)
        prod = authoritative_normalize(raw)
        assert local == prod == expected, f"Mismatch for {raw!r}: local={local!r}, prod={prod!r}"
