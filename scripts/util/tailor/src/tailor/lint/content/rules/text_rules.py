"""Text-family rule implementations.

Each rule operates on string items drawn from resolved scope paths. All rules
are stateless singletons registered via
``tailor.lint.registry.register_builtin_rules``. Rules narrow ``params`` via
``isinstance`` so ``ty`` recognises the narrowing without casts.

Rules in this module (high-level):

    banned_patterns
        Regex substring matches anywhere in a resolved item.

    banned_openers
        Regex matches restricted to the opening tokens of an item or sentence.

    max_structural_punctuation_per_sentence
        Caps the number of ``;`` / ``:`` (or any chosen set) per sentence.

    max_consecutive_opener
        Detects runs of consecutive items/sentences whose opening token matches
        a target (literal or regex).

    mention_count
        Enforces aggregate floor/ceiling occurrence counts of a literal or
        regex target (with ``{{ var }}`` substitution support) across the
        resolved scope.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import ClassVar, Literal

from pydantic import BaseModel, StrictInt, field_validator, model_validator

from tailor.lint.content.rules._helpers import (
    as_strings,
    compile_cached,
    split_sentences,
)
from tailor.lint.models import ROOT_PATH, BannedPattern, LintIssue, Severity

# banned_patterns


class BannedPatternsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``banned_patterns``.

    Attributes:
        patterns: Non-empty tuple of regex patterns. Each may carry a
            per-pattern message override. The rule's severity applies to every
            pattern uniformly -- to mix severities, declare multiple rule
            entries keyed by ``rule_id`` suffix (e.g. ``_warning`` / ``_info``).
    """

    patterns: tuple[BannedPattern, ...]

    @field_validator("patterns")
    @classmethod
    def _require_nonempty(cls, v: tuple[BannedPattern, ...]) -> tuple[BannedPattern, ...]:
        """A banned_patterns entry with zero patterns is a no-op and likely a YAML bug."""
        if not v:
            msg = "banned_patterns patterns must be non-empty"
            raise ValueError(msg)
        return v


class BannedPatternsRule:
    """Flags items whose text contains any of the configured regex patterns.

    Patterns are compiled once per ``check()`` call (not per item).
    Case-insensitive matching is applied.
    """

    TYPE_ID: ClassVar[str] = "banned_patterns"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = BannedPatternsParams
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
        """Emit one issue per (item, matching pattern) pair."""
        if not isinstance(params, BannedPatternsParams):
            msg = f"BannedPatternsRule expected BannedPatternsParams, got {type(params).__name__}"
            raise TypeError(msg)
        compiled = [(banned, compile_cached(banned.pattern, re.IGNORECASE)) for banned in params.patterns]

        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(items):
                if not isinstance(item, str):
                    continue
                item_path = f"{path_str}[{idx}]"
                for banned, pattern in compiled:
                    if pattern.search(item):
                        issues.append(
                            LintIssue(
                                rule=rule_id,
                                severity=severity,
                                path=item_path,
                                message=banned.message or f"Matches banned pattern: {banned.pattern!r}",
                                value=item,
                            )
                        )
        return issues


# banned_openers


class BannedOpenersParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``banned_openers``.

    Attributes:
        scope: ``"item"`` matches against the opening tokens of each resolved
            string item as a whole. ``"sentence"`` splits items into sentences
            first and matches the opening tokens of every sentence.
        max_token_check: Number of leading whitespace-split tokens to assemble
            before matching. ``1`` checks only the first word; ``3`` checks
            ``word1 word2 word3``.
        patterns: Non-empty tuple of ``BannedPattern``. Each pattern's regex
            is matched (``re.search``) against the opener string.
        case_sensitive: When ``False`` (default), each regex is compiled with
            ``re.IGNORECASE``. Per-pattern inline flags still win.
    """

    scope: Literal["item", "sentence"] = "item"
    max_token_check: StrictInt = 1
    patterns: tuple[BannedPattern, ...]
    case_sensitive: bool = False

    @field_validator("max_token_check")
    @classmethod
    def _require_positive_token_check(cls, v: int) -> int:
        if v < 1:
            msg = "max_token_check must be >= 1"
            raise ValueError(msg)
        return v

    @field_validator("patterns")
    @classmethod
    def _require_nonempty(cls, v: tuple[BannedPattern, ...]) -> tuple[BannedPattern, ...]:
        if not v:
            msg = "banned_openers patterns must be non-empty"
            raise ValueError(msg)
        return v


class BannedOpenersRule:
    """Flags AI-slop openers at the start of items or sentences."""

    TYPE_ID: ClassVar[str] = "banned_openers"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = BannedOpenersParams
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
        """Emit one issue per (unit, matching pattern) pair."""
        if not isinstance(params, BannedOpenersParams):
            msg = f"BannedOpenersRule expected BannedOpenersParams, got {type(params).__name__}"
            raise TypeError(msg)
        flags = 0 if params.case_sensitive else re.IGNORECASE
        compiled = [(banned, compile_cached(banned.pattern, flags)) for banned in params.patterns]

        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(as_strings(items)):
                issues.extend(
                    self._check_unit(rule_id, severity, path_str, idx, item, params, compiled),
                )
        return issues

    @staticmethod
    def _check_unit(
        rule_id: str,
        severity: Severity,
        path_str: str,
        idx: int,
        item: str,
        params: BannedOpenersParams,
        compiled: list[tuple[BannedPattern, re.Pattern[str]]],
    ) -> list[LintIssue]:
        """Check either the item itself or every sentence within it."""
        if params.scope == "item":
            opener = _leading_tokens(item, params.max_token_check)
            if not opener:
                return []
            return _match_openers(
                rule_id,
                severity,
                f"{path_str}[{idx}]",
                opener,
                item,
                compiled,
            )
        issues: list[LintIssue] = []
        for s_idx, sentence in enumerate(split_sentences(item)):
            opener = _leading_tokens(sentence, params.max_token_check)
            if not opener:
                continue
            issues.extend(
                _match_openers(
                    rule_id,
                    severity,
                    f"{path_str}[{idx}].sentence[{s_idx}]",
                    opener,
                    sentence,
                    compiled,
                ),
            )
        return issues


def _leading_tokens(text: str, n: int) -> str:
    """Return the first ``n`` whitespace-split tokens joined with single spaces."""
    tokens = text.split(maxsplit=n)
    return " ".join(tokens[:n])


def _match_openers(
    rule_id: str,
    severity: Severity,
    path: str,
    opener: str,
    full_text: str,
    compiled: list[tuple[BannedPattern, re.Pattern[str]]],
) -> list[LintIssue]:
    """Match every compiled pattern against ``opener``; emit one issue per match."""
    hits: list[LintIssue] = []
    for banned, pattern in compiled:
        if pattern.search(opener):
            hits.append(
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=path,
                    message=banned.message or f"Opener matches banned pattern: {banned.pattern!r}",
                    value=full_text,
                ),
            )
    return hits


# max_structural_punctuation_per_sentence


class MaxStructuralPunctuationPerSentenceParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``max_structural_punctuation_per_sentence``.

    Attributes:
        max: Inclusive ceiling on structural-punctuation occurrences per sentence.
        punctuation: Single-character tokens that count as structural
            punctuation. Defaults to ``{";", ":"}``.
    """

    max: StrictInt
    punctuation: frozenset[str] = frozenset({";", ":"})

    @field_validator("max")
    @classmethod
    def _require_nonneg(cls, v: int) -> int:
        if v < 0:
            msg = "max must be >= 0"
            raise ValueError(msg)
        return v

    @field_validator("punctuation")
    @classmethod
    def _require_single_chars(cls, v: frozenset[str]) -> frozenset[str]:
        for char in v:
            if len(char) != 1:
                msg = f"punctuation entries must be single characters, got {char!r}"
                raise ValueError(msg)
        if not v:
            msg = "punctuation set must be non-empty"
            raise ValueError(msg)
        return v


class MaxStructuralPunctuationPerSentenceRule:
    """Flags sentences that exceed the structural-punctuation ceiling."""

    TYPE_ID: ClassVar[str] = "max_structural_punctuation_per_sentence"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MaxStructuralPunctuationPerSentenceParams
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
        """Emit one issue per sentence whose structural-punctuation count exceeds ``max``."""
        if not isinstance(params, MaxStructuralPunctuationPerSentenceParams):
            msg = (
                "MaxStructuralPunctuationPerSentenceRule expected "
                f"MaxStructuralPunctuationPerSentenceParams, got {type(params).__name__}"
            )
            raise TypeError(msg)
        punct_set = params.punctuation
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(as_strings(items)):
                for s_idx, sentence in enumerate(split_sentences(item)):
                    count = sum(1 for ch in sentence if ch in punct_set)
                    if count > params.max:
                        issues.append(
                            LintIssue(
                                rule=rule_id,
                                severity=severity,
                                path=f"{path_str}[{idx}].sentence[{s_idx}]",
                                message=(
                                    f"Sentence has {count} structural-punctuation marks "
                                    f"(max {params.max}): {sorted(punct_set)}"
                                ),
                                value=sentence,
                            ),
                        )
        return issues


# max_consecutive_opener


class MaxConsecutiveOpenerParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``max_consecutive_opener``.

    Attributes:
        token: Literal opening token (e.g. ``"I"``) or a regex when
            ``is_regex=True``. Matching is rooted at the beginning of the
            first whitespace-split token of each unit.
        is_regex: Toggle between literal equality and regex ``fullmatch``.
        max_consecutive: Ceiling on the run length. ``2`` means a run of 3 or
            more consecutive matches triggers.
        case_sensitive: When ``False`` (default), comparison is case-insensitive.
        granularity: ``"item"`` examines the first token of each resolved item;
            ``"sentence"`` splits each item into sentences first.
    """

    token: str
    is_regex: bool = False
    max_consecutive: StrictInt
    case_sensitive: bool = False
    granularity: Literal["item", "sentence"] = "item"

    @field_validator("max_consecutive")
    @classmethod
    def _require_positive(cls, v: int) -> int:
        if v < 1:
            msg = "max_consecutive must be >= 1"
            raise ValueError(msg)
        return v

    @field_validator("token")
    @classmethod
    def _require_nonempty_token(cls, v: str) -> str:
        if not v:
            msg = "token must be non-empty"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _compile_regex_once(self) -> MaxConsecutiveOpenerParams:
        """Validate regex syntax up front so YAML errors surface at config load."""
        if self.is_regex:
            try:
                re.compile(self.token)
            except re.error as err:
                msg = f"Invalid regex token {self.token!r}: {err}"
                raise ValueError(msg) from err
        return self


class MaxConsecutiveOpenerRule:
    """Detects runs of consecutive items or sentences sharing the same opening token."""

    TYPE_ID: ClassVar[str] = "max_consecutive_opener"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MaxConsecutiveOpenerParams
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
        """Emit one issue per run of length > ``max_consecutive``."""
        if not isinstance(params, MaxConsecutiveOpenerParams):
            msg = f"MaxConsecutiveOpenerRule expected MaxConsecutiveOpenerParams, got {type(params).__name__}"
            raise TypeError(msg)

        matcher = _build_token_matcher(params)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            units = list(_iter_units(path_str, items, params.granularity))
            issues.extend(
                _find_runs(
                    rule_id,
                    severity,
                    units,
                    matcher,
                    params.max_consecutive,
                    params.token,
                )
            )
        return issues


type _Matcher = Callable[[str], bool]


def _build_token_matcher(params: MaxConsecutiveOpenerParams) -> _Matcher:
    """Return a predicate that checks whether an opener matches the configured token."""
    flags = 0 if params.case_sensitive else re.IGNORECASE
    if params.is_regex:
        compiled = compile_cached(params.token, flags)

        def match_regex(opener: str) -> bool:
            return compiled.fullmatch(opener) is not None

        return match_regex

    needle = params.token if params.case_sensitive else params.token.lower()

    def match_literal(opener: str) -> bool:
        candidate = opener if params.case_sensitive else opener.lower()
        return candidate == needle

    return match_literal


def _iter_units(
    path_str: str,
    items: list[object],
    granularity: Literal["item", "sentence"],
) -> list[tuple[str, str]]:
    """Yield ``(unit_path, unit_text)`` tuples at the requested granularity."""
    units: list[tuple[str, str]] = []
    for idx, item in enumerate(as_strings(items)):
        if granularity == "item":
            units.append((f"{path_str}[{idx}]", item))
        else:
            for s_idx, sentence in enumerate(split_sentences(item)):
                units.append((f"{path_str}[{idx}].sentence[{s_idx}]", sentence))
    return units


def _find_runs(
    rule_id: str,
    severity: Severity,
    units: list[tuple[str, str]],
    matcher: _Matcher,
    max_consecutive: int,
    token_label: str,
) -> list[LintIssue]:
    """Emit one issue per run of length > max_consecutive."""
    issues: list[LintIssue] = []
    run_start: int | None = None
    run_length = 0
    for i, (_path, text) in enumerate(units):
        first_token = text.split(maxsplit=1)[0] if text.strip() else ""
        if first_token and matcher(first_token):
            if run_start is None:
                run_start = i
            run_length += 1
            continue
        if run_start is not None and run_length > max_consecutive:
            issues.append(_run_issue(rule_id, severity, units, run_start, run_length, token_label))
        run_start = None
        run_length = 0
    if run_start is not None and run_length > max_consecutive:
        issues.append(_run_issue(rule_id, severity, units, run_start, run_length, token_label))
    return issues


def _run_issue(
    rule_id: str,
    severity: Severity,
    units: list[tuple[str, str]],
    start: int,
    length: int,
    token_label: str,
) -> LintIssue:
    """Build an issue describing a consecutive-opener run."""
    first_path = units[start][0]
    return LintIssue(
        rule=rule_id,
        severity=severity,
        path=first_path,
        message=f"{length} consecutive units start with {token_label!r}",
        value=str(length),
    )


# mention_count


class MentionCountParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``mention_count``.

    Attributes:
        target: Literal substring or regex (when ``is_regex=True``). Supports
            ``{{ var }}`` substitution from the runtime variable map; missing
            variables fail at config load with ``LintConfigError``.
        is_regex: Treat ``target`` as a regex.
        min: Inclusive occurrence floor. ``None`` disables the floor check.
        max: Inclusive occurrence ceiling. ``None`` disables the ceiling check.
        case_sensitive: Control case-sensitivity. Regex inline flags win.
    """

    target: str
    is_regex: bool = False
    min: StrictInt | None = None
    max: StrictInt | None = None
    case_sensitive: bool = False

    @field_validator("target")
    @classmethod
    def _require_nonempty(cls, v: str) -> str:
        if not v:
            msg = "target must be non-empty"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _validate_bounds(self) -> MentionCountParams:
        if self.min is None and self.max is None:
            msg = "mention_count requires at least one of min or max"
            raise ValueError(msg)
        if self.min is not None and self.min < 0:
            msg = "min must be >= 0"
            raise ValueError(msg)
        if self.max is not None and self.max < 0:
            msg = "max must be >= 0"
            raise ValueError(msg)
        if self.min is not None and self.max is not None and self.min > self.max:
            msg = f"min ({self.min}) cannot exceed max ({self.max})"
            raise ValueError(msg)
        if self.is_regex:
            try:
                re.compile(self.target)
            except re.error as err:
                msg = f"Invalid regex target {self.target!r}: {err}"
                raise ValueError(msg) from err
        return self


class MentionCountRule:
    """Enforces a floor / ceiling on how often a target appears across the resolved scope."""

    TYPE_ID: ClassVar[str] = "mention_count"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MentionCountParams
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset({"target"})

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        **_: object,
    ) -> list[LintIssue]:
        """Emit at most one aggregate issue per violation (min, max, or both)."""
        if not isinstance(params, MentionCountParams):
            msg = f"MentionCountRule expected MentionCountParams, got {type(params).__name__}"
            raise TypeError(msg)

        full_text = "\n".join(s for _path, items in resolved for s in as_strings(items))
        count = _count_mentions(full_text, params)

        issues: list[LintIssue] = []
        if params.min is not None and count < params.min:
            issues.append(
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=ROOT_PATH,
                    message=(f"Target {params.target!r} mentioned {count} times (min {params.min})"),
                    value=str(count),
                ),
            )
        if params.max is not None and count > params.max:
            issues.append(
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=ROOT_PATH,
                    message=(f"Target {params.target!r} mentioned {count} times (max {params.max})"),
                    value=str(count),
                ),
            )
        return issues


def _count_mentions(text: str, params: MentionCountParams) -> int:
    """Count occurrences of ``params.target`` in ``text`` per configured flags."""
    flags = 0 if params.case_sensitive else re.IGNORECASE
    if params.is_regex:
        # ``sum(1 for _ in finditer(...))`` streams match counting without
        # allocating the intermediate list ``re.findall`` builds.
        return sum(1 for _ in compile_cached(params.target, flags).finditer(text))
    needle = params.target if params.case_sensitive else params.target.lower()
    haystack = text if params.case_sensitive else text.lower()
    if not needle:
        return 0
    # Use non-overlapping count. This is consistent with regex findall behavior.
    return haystack.count(needle)
