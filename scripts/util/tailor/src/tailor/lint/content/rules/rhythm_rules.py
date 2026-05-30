"""Rhythm-check rule — detects runs of similar-length sentences.

Prose with three or more consecutive sentences of near-identical length reads
as mechanical / monotonous. This rule surfaces that pattern deterministically
so authors can break up the rhythm before review.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, StrictInt, field_validator

from tailor.lint.content.rules._helpers import (
    as_strings,
    count_syllables,
    split_sentences,
    tokenize,
)
from tailor.lint.models import LintIssue, Severity


class RhythmCheckParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``rhythm_check``.

    Attributes:
        mode: ``"word_count"`` uses whitespace-token length per sentence;
            ``"syllable_count"`` sums syllables per sentence via the shared
            heuristic.
        max_consecutive_similar: Run-length ceiling. ``3`` means a run of 4+
            similar sentences triggers.
        tolerance: Maximum absolute difference between lengths that counts as
            "similar". Applied to whichever measurement ``mode`` selects.
        min_scope_size: Skip scopes with fewer than this many sentences. Small
            scopes produce too many false positives otherwise.
    """

    mode: Literal["word_count", "syllable_count"] = "word_count"
    max_consecutive_similar: StrictInt = 3
    tolerance: StrictInt = 5
    min_scope_size: StrictInt = 3

    @field_validator("max_consecutive_similar")
    @classmethod
    def _validate_run(cls, v: int) -> int:
        if v < 1:
            msg = "max_consecutive_similar must be >= 1"
            raise ValueError(msg)
        return v

    @field_validator("tolerance")
    @classmethod
    def _validate_tolerance(cls, v: int) -> int:
        if v < 0:
            msg = "tolerance must be >= 0"
            raise ValueError(msg)
        return v

    @field_validator("min_scope_size")
    @classmethod
    def _validate_min_scope(cls, v: int) -> int:
        if v < 1:
            msg = "min_scope_size must be >= 1"
            raise ValueError(msg)
        return v


class RhythmCheckRule:
    """Emits issues for runs of consecutive sentences within ``tolerance`` length."""

    TYPE_ID: ClassVar[str] = "rhythm_check"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = RhythmCheckParams
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
        """Emit one issue per run whose length > ``max_consecutive_similar``."""
        if not isinstance(params, RhythmCheckParams):
            msg = f"RhythmCheckRule expected RhythmCheckParams, got {type(params).__name__}"
            raise TypeError(msg)

        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(as_strings(items)):
                sentences = split_sentences(item)
                if len(sentences) < params.min_scope_size:
                    continue
                lengths = [_measure(s, params.mode) for s in sentences]
                issues.extend(
                    _flag_runs(rule_id, severity, path_str, idx, sentences, lengths, params),
                )
        return issues


def _measure(sentence: str, mode: Literal["word_count", "syllable_count"]) -> int:
    """Return length of ``sentence`` under the chosen measurement mode."""
    tokens = tokenize(sentence)
    if mode == "word_count":
        return len(tokens)
    return sum(count_syllables(token) for token in tokens)


def _flag_runs(
    rule_id: str,
    severity: Severity,
    path_str: str,
    item_idx: int,
    sentences: list[str],
    lengths: list[int],
    params: RhythmCheckParams,
) -> list[LintIssue]:
    """Walk ``lengths`` flagging any run of consecutive within-tolerance lengths."""
    issues: list[LintIssue] = []
    if not lengths:
        return issues

    run_start = 0
    run_min = lengths[0]
    run_max = lengths[0]
    for i in range(1, len(lengths)):
        candidate_min = min(run_min, lengths[i])
        candidate_max = max(run_max, lengths[i])
        if candidate_max - candidate_min <= params.tolerance:
            run_min, run_max = candidate_min, candidate_max
            continue
        run_length = i - run_start
        if run_length > params.max_consecutive_similar:
            issues.append(
                _rhythm_issue(rule_id, severity, path_str, item_idx, run_start, run_length, sentences, params.mode),
            )
        run_start = i
        run_min = run_max = lengths[i]

    run_length = len(lengths) - run_start
    if run_length > params.max_consecutive_similar:
        issues.append(
            _rhythm_issue(rule_id, severity, path_str, item_idx, run_start, run_length, sentences, params.mode),
        )
    return issues


def _rhythm_issue(
    rule_id: str,
    severity: Severity,
    path_str: str,
    item_idx: int,
    run_start: int,
    run_length: int,
    sentences: list[str],
    mode: Literal["word_count", "syllable_count"],
) -> LintIssue:
    """Build the issue for a flagged rhythm run."""
    preview = " | ".join(sentences[run_start : run_start + run_length])
    return LintIssue(
        rule=rule_id,
        severity=severity,
        path=f"{path_str}[{item_idx}].sentence[{run_start}]",
        message=(f"{run_length} consecutive sentences of similar {mode} (run starts at sentence {run_start})"),
        value=preview,
    )
