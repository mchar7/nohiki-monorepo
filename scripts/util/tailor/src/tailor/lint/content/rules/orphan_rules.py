"""Orphan content-heuristic rule — surfaces risky final-word patterns.

The *true* layout orphan detector lives in ``layout/`` because it needs the
rendered PDF. This content-side heuristic is a pre-render stopgap: the YAML
config supplies a curated list of words known to orphan at the end of
paragraphs for a given template, and the rule flags any scope item that ends
with one of those words. The rule carries no domain vocabulary of its own —
every risky word comes from the config.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, field_validator

from tailor.lint.content.rules._helpers import as_strings, split_sentences
from tailor.lint.models import LintIssue, Severity


class OrphanFinalWordHeuristicParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``orphan_final_word_heuristic``.

    Attributes:
        risky_final_words: Words known to orphan at end of paragraphs. The
            comparison is done against the final whitespace-split token with
            surrounding punctuation stripped.
        case_sensitive: Whether matching respects case. ``False`` is the
            sensible default for English prose.
        check_last_sentence_only: When ``True``, inspects the final sentence
            of each item (more conservative). When ``False``, inspects the
            final word of the whole item.
    """

    risky_final_words: tuple[str, ...]
    case_sensitive: bool = False
    check_last_sentence_only: bool = False

    @field_validator("risky_final_words")
    @classmethod
    def _require_nonempty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            msg = "risky_final_words must be non-empty"
            raise ValueError(msg)
        for word in v:
            if not word or word.strip() != word:
                msg = f"risky_final_words entries must be non-empty and stripped: {word!r}"
                raise ValueError(msg)
        return v


_WORD_EDGE_STRIP = "'\".,;:!?()[]{}"


class OrphanFinalWordHeuristicRule:
    """Flags items whose final word is in the risky-final-words list."""

    TYPE_ID: ClassVar[str] = "orphan_final_word_heuristic"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = OrphanFinalWordHeuristicParams
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset()

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        **_: object,
    ) -> list[LintIssue]:
        """Emit one issue per item whose final word matches the risky list."""
        if not isinstance(params, OrphanFinalWordHeuristicParams):
            msg = f"OrphanFinalWordHeuristicRule expected OrphanFinalWordHeuristicParams, got {type(params).__name__}"
            raise TypeError(msg)

        risky_lookup = _build_lookup(params.risky_final_words, case_sensitive=params.case_sensitive)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(as_strings(items)):
                final_word = _final_word(item, check_last_sentence_only=params.check_last_sentence_only)
                if final_word is None:
                    continue
                lookup_key = final_word if params.case_sensitive else final_word.lower()
                if lookup_key in risky_lookup:
                    issues.append(
                        LintIssue(
                            rule=rule_id,
                            severity=severity,
                            path=f"{path_str}[{idx}]",
                            message=f"Item ends on risky final word: {final_word!r}",
                            value=final_word,
                        ),
                    )
        return issues


def _build_lookup(words: tuple[str, ...], *, case_sensitive: bool) -> frozenset[str]:
    """Return a set suitable for O(1) membership checking per ``case_sensitive`` flag."""
    if case_sensitive:
        return frozenset(words)
    return frozenset(w.lower() for w in words)


def _final_word(item: str, *, check_last_sentence_only: bool) -> str | None:
    """Extract the orthographic final word of ``item`` (or its last sentence)."""
    source = item
    if check_last_sentence_only:
        sentences = split_sentences(item)
        if not sentences:
            return None
        source = sentences[-1]
    tokens = source.split()
    if not tokens:
        return None
    stripped = tokens[-1].strip(_WORD_EDGE_STRIP)
    return stripped or None
