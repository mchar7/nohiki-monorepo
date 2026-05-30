"""Cross-path text rules.

Both rules in this module follow the convention of declaring
``scope_paths: ["$"]`` in their YAML entry: the paths the rule actually
compares are provided by the rule's ``params`` as ``source_paths`` /
``target_paths``. The engine resolves ``$`` to the document root and hands
``data`` / ``runtime`` to ``check()`` so the rule can resolve its params-level
paths (including ``sibling.<name>.<path>`` references).

Rules:
    repeated_literal_across_paths
        Numeric or single-word literals appearing in both source and target
        sets. Common use: flag a downstream paragraph that restates a numeric
        or word literal already introduced upstream.
    repeated_phrase_across_paths
        N-gram phrases repeated within or across path sets. Common uses:
        cross-section echo detection, and (via ``sibling.*``) detecting a
        passage that echoes content from a companion document.
"""

from __future__ import annotations

import re
from typing import ClassVar, Literal

from pydantic import BaseModel, StrictInt, field_validator, model_validator

from tailor.lint.content.rules._helpers import (
    STOPWORDS,
    as_strings,
    tokenize,
)
from tailor.lint.content.rules.path_resolver import resolve_glob_paths
from tailor.lint.models import LintIssue, Severity
from tailor.lint.runtime import LintRuntimeContext

# Shared helpers

_NUMBER_LITERAL_RE = re.compile(r"\b\d[\d,]*(?:\.\d+)?\b")


def _collect_strings(
    data: dict[str, object],
    paths: tuple[str, ...] | list[str],
    runtime: LintRuntimeContext,
) -> list[tuple[str, str]]:
    """Resolve ``paths`` and return a list of ``(concrete_path, text)`` pairs.

    Each resolved item that is a string becomes one tuple; non-string items
    (e.g. nested dicts) are skipped silently so rules remain compositional.
    """
    tuples: list[tuple[str, str]] = []
    for path_str, items in resolve_glob_paths(data, paths, runtime):
        for idx, text in enumerate(as_strings(items)):
            tuples.append((f"{path_str}[{idx}]", text))
    return tuples


# repeated_literal_across_paths


class RepeatedLiteralAcrossPathsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``repeated_literal_across_paths``.

    Attributes:
        source_paths: First path set. Literals found here are candidates.
        target_paths: Second path set. A literal appearing in both ``source``
            and ``target`` emits an issue.
        literal_type: ``"number"`` extracts numeric tokens (e.g. ``18``,
            ``3.14``); ``"word"`` extracts individual word tokens
            (case-insensitive).
        min_repeat_chars: Ignore literals shorter than this length to avoid
            trivial collisions (``"1"`` appearing in both paragraphs).
        exclude_stopwords: When ``literal_type="word"``, skip stopwords. Has
            no effect for ``"number"``.
        stopwords: Override stopword set. Defaults to the shared ``STOPWORDS``
            frozenset when ``exclude_stopwords=True``.
    """

    source_paths: tuple[str, ...]
    target_paths: tuple[str, ...]
    literal_type: Literal["number", "word"]
    min_repeat_chars: StrictInt = 2
    exclude_stopwords: bool = True
    stopwords: frozenset[str] | None = None

    @field_validator("source_paths", "target_paths")
    @classmethod
    def _require_nonempty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            msg = "source_paths / target_paths must be non-empty"
            raise ValueError(msg)
        return v

    @field_validator("min_repeat_chars")
    @classmethod
    def _require_positive(cls, v: int) -> int:
        if v < 1:
            msg = "min_repeat_chars must be >= 1"
            raise ValueError(msg)
        return v


class RepeatedLiteralAcrossPathsRule:
    """Flags literals that appear in both source and target paths."""

    TYPE_ID: ClassVar[str] = "repeated_literal_across_paths"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = RepeatedLiteralAcrossPathsParams
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset()

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        data: dict[str, object] | None = None,
        runtime: LintRuntimeContext | None = None,
        **_: object,
    ) -> list[LintIssue]:
        """Emit one issue per shared literal with its occurrences in both sides.

        ``data`` and ``runtime`` are declared as optional kwargs to satisfy the
        Rule Protocol's substitutability requirements, but the engine always
        supplies them. We fail loudly if they are missing so mis-dispatched
        invocations surface as bugs rather than silent no-ops.
        """
        # Cross-path rules source literals from ``data`` via explicit
        # ``source_paths``/``target_paths`` params, not from the resolved
        # scope tuples. ``resolved`` is still Protocol-mandatory (document
        # root for ``scope_paths: ["$"]``) but carries no rule-relevant data.
        del resolved
        if not isinstance(params, RepeatedLiteralAcrossPathsParams):
            msg = (
                f"RepeatedLiteralAcrossPathsRule expected RepeatedLiteralAcrossPathsParams, got {type(params).__name__}"
            )
            raise TypeError(msg)
        if data is None or runtime is None:
            msg = "RepeatedLiteralAcrossPathsRule requires data and runtime kwargs from the engine"
            raise RuntimeError(msg)

        source_strings = _collect_strings(data, params.source_paths, runtime)
        target_strings = _collect_strings(data, params.target_paths, runtime)

        source_literals = _index_literals(source_strings, params)
        target_literals = _index_literals(target_strings, params)

        shared = source_literals.keys() & target_literals.keys()
        issues: list[LintIssue] = []
        for literal in sorted(shared):
            src_paths = source_literals[literal]
            tgt_paths = target_literals[literal]
            issues.append(
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=tgt_paths[0],
                    message=(
                        f"Literal {literal!r} appears in both source and target "
                        f"(source: {sorted(set(src_paths))}, target: {sorted(set(tgt_paths))})"
                    ),
                    value=literal,
                ),
            )
        return issues


def _index_literals(
    pairs: list[tuple[str, str]],
    params: RepeatedLiteralAcrossPathsParams,
) -> dict[str, list[str]]:
    """Extract literals and map each → the list of concrete paths where it occurred."""
    index: dict[str, list[str]] = {}
    for path, text in pairs:
        for literal in _extract_literals(text, params):
            index.setdefault(literal, []).append(path)
    return index


def _extract_literals(text: str, params: RepeatedLiteralAcrossPathsParams) -> list[str]:
    """Pull numeric or word literals from ``text`` per configured rules."""
    if params.literal_type == "number":
        return [m for m in _NUMBER_LITERAL_RE.findall(text) if len(m) >= params.min_repeat_chars]

    stopwords = params.stopwords if params.stopwords is not None else STOPWORDS
    literals: list[str] = []
    for raw in tokenize(text):
        lowered = raw.lower()
        if len(lowered) < params.min_repeat_chars:
            continue
        if params.exclude_stopwords and lowered in stopwords:
            continue
        literals.append(lowered)
    return literals


# repeated_phrase_across_paths


class RepeatedPhraseAcrossPathsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``repeated_phrase_across_paths``.

    Attributes:
        min_phrase_words: Shortest N-gram length to consider.
        max_repeats: Any N-gram occurring more than ``max_repeats`` times
            triggers. ``1`` means a second occurrence is a violation.
        case_sensitive: Case-sensitivity for N-gram comparison.
        source_paths: Where to harvest candidate phrases. ``None`` means use
            the rule's resolved ``scope_paths`` (passed via ``resolved``).
        target_paths: Where to count occurrences. ``None`` mirrors
            ``source_paths``.
        ignore_within_same_item: When ``True`` (default), multiple occurrences
            within a single item are collapsed to one so that only
            cross-item / cross-path repetition triggers.
    """

    min_phrase_words: StrictInt = 4
    max_repeats: StrictInt = 1
    case_sensitive: bool = False
    source_paths: tuple[str, ...] | None = None
    target_paths: tuple[str, ...] | None = None
    ignore_within_same_item: bool = True

    @field_validator("min_phrase_words")
    @classmethod
    def _validate_min_phrase_words(cls, v: int) -> int:
        if v < 2:
            msg = "min_phrase_words must be >= 2"
            raise ValueError(msg)
        return v

    @field_validator("max_repeats")
    @classmethod
    def _validate_max_repeats(cls, v: int) -> int:
        if v < 1:
            msg = "max_repeats must be >= 1"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _paths_pair(self) -> RepeatedPhraseAcrossPathsParams:
        """Either both path sets are given, or both are None (scope-based)."""
        if (self.source_paths is None) != (self.target_paths is None):
            msg = "source_paths and target_paths must both be set or both be omitted"
            raise ValueError(msg)
        return self


class RepeatedPhraseAcrossPathsRule:
    """Flags N-gram phrase repetition across configured path sets."""

    TYPE_ID: ClassVar[str] = "repeated_phrase_across_paths"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = RepeatedPhraseAcrossPathsParams
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset()

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        data: dict[str, object] | None = None,
        runtime: LintRuntimeContext | None = None,
        **_: object,
    ) -> list[LintIssue]:
        """Emit one issue per N-gram whose occurrence count exceeds ``max_repeats``.

        ``data`` / ``runtime`` are declared optional to stay substitutable for
        the Rule Protocol, but the engine always supplies them. We fail loudly
        when they are missing so misuse shows up as a bug, not a no-op.
        """
        if not isinstance(params, RepeatedPhraseAcrossPathsParams):
            msg = f"RepeatedPhraseAcrossPathsRule expected RepeatedPhraseAcrossPathsParams, got {type(params).__name__}"
            raise TypeError(msg)
        if data is None or runtime is None:
            msg = "RepeatedPhraseAcrossPathsRule requires data and runtime kwargs from the engine"
            raise RuntimeError(msg)

        source_pairs, target_pairs, scope_based = self._materialize_pairs(resolved, data, runtime, params)

        source_ngrams = _ngram_occurrences(source_pairs, params)
        # When source == target (scope-based, no param paths given), the two
        # pair lists are literally the same object; counting ngrams once
        # suffices and avoids double-counting every occurrence.
        if scope_based:
            merged = source_ngrams
        else:
            target_ngrams = _ngram_occurrences(target_pairs, params)
            merged = {}
            for ngram, paths in source_ngrams.items():
                merged.setdefault(ngram, []).extend(paths)
            for ngram, paths in target_ngrams.items():
                merged.setdefault(ngram, []).extend(paths)

        issues: list[LintIssue] = []
        for ngram in sorted(merged):
            paths = merged[ngram]
            if len(paths) > params.max_repeats:
                issues.append(
                    LintIssue(
                        rule=rule_id,
                        severity=severity,
                        path=paths[0],
                        message=(
                            f"Phrase {ngram!r} occurs {len(paths)} times "
                            f"(max {params.max_repeats}): {sorted(set(paths))}"
                        ),
                        value=ngram,
                    ),
                )
        return issues

    @staticmethod
    def _materialize_pairs(
        resolved: list[tuple[str, list[object]]],
        data: dict[str, object],
        runtime: LintRuntimeContext,
        params: RepeatedPhraseAcrossPathsParams,
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]], bool]:
        """Return ``(source_pairs, target_pairs, scope_based)``.

        ``scope_based`` is True when the caller passed no explicit path sets
        and the rule operates on its resolved scope; in that case source and
        target are aliases of the same list and the caller must only count
        ngrams once to avoid double-counting.
        """
        if params.source_paths is None:
            scope_pairs = [
                (f"{path_str}[{idx}]", text)
                for path_str, items in resolved
                for idx, text in enumerate(as_strings(items))
            ]
            return scope_pairs, scope_pairs, True

        source_pairs = _collect_strings(data, params.source_paths, runtime)
        # target_paths must be non-None here per model validator.
        if params.target_paths is None:
            msg = "target_paths was None despite source_paths being set (model validator should have rejected this)"
            raise RuntimeError(msg)
        target_pairs = _collect_strings(data, params.target_paths, runtime)
        return source_pairs, target_pairs, False


def _ngram_occurrences(
    pairs: list[tuple[str, str]],
    params: RepeatedPhraseAcrossPathsParams,
) -> dict[str, list[str]]:
    """Map each N-gram → list of paths it appears in (deduplicated per item)."""
    occurrences: dict[str, list[str]] = {}
    for path, text in pairs:
        tokens = tokenize(text)
        if not params.case_sensitive:
            tokens = [tok.lower() for tok in tokens]
        seen_in_item: set[str] = set()
        for i in range(len(tokens) - params.min_phrase_words + 1):
            ngram = " ".join(tokens[i : i + params.min_phrase_words])
            if params.ignore_within_same_item and ngram in seen_in_item:
                continue
            seen_in_item.add(ngram)
            occurrences.setdefault(ngram, []).append(path)
    return occurrences
