"""Section-family rule implementations -- operate on list-of-items scope paths.

All nine rules are stateless singletons registered via
``tailor.lint.registry.register_builtin_rules``. Rules narrow ``params`` via
``isinstance`` + ``TypeError``; the type checker recognises the narrowing
without ``cast`` or ``# noqa``.

Currently, rules do not receive a ``runtime`` context in ``check()``, allowing
rules to operate purely on resolved scope items. Future extensions may thread
runtime context additively without breaking existing implementations.
"""

from __future__ import annotations

import re
from typing import ClassVar, Literal

from pydantic import BaseModel, StrictInt, field_validator

from tailor.lint.content.rules._helpers import compile_cached, is_str_keyed_dict
from tailor.lint.models import LintIssue, Severity

# Verb-tense helpers

_IRREGULAR_PAST_TENSE_VERBS: frozenset[str] = frozenset(
    {
        "brought",
        "bought",
        "built",
        "caught",
        "cut",
        "drew",
        "drove",
        "fought",
        "flew",
        "found",
        "gave",
        "got",
        "grew",
        "held",
        "kept",
        "knew",
        "led",
        "left",
        "let",
        "lost",
        "made",
        "met",
        "paid",
        "put",
        "ran",
        "read",
        "saw",
        "sent",
        "set",
        "sold",
        "sought",
        "taught",
        "thought",
        "told",
        "took",
        "won",
        "wore",
        "wrote",
    }
)


def _is_past_tense(word: str) -> bool:
    """Heuristic past-tense check: ``-ed`` suffix or curated irregular allowlist."""
    lower = word.lower().rstrip(".,;:!?")
    return lower.endswith("ed") or lower in _IRREGULAR_PAST_TENSE_VERBS


def _count_words(text: str) -> int:
    """Whitespace-token count."""
    return len(text.split())


# Dict narrowing in this module delegates to ``is_str_keyed_dict`` from
# ``_helpers``: it is a ``TypeGuard[dict[str, object]]``, so callers can use
# the item in place without allocating a fresh dict per scope element.


def _opening_word(item: str) -> tuple[str, str] | None:
    """Return ``(raw_first_word, lowercase_core)`` or ``None`` for empty input.

    ``lowercase_core`` strips trailing punctuation so openers like ``Built.``
    and ``Built`` collide, which matches how human readers perceive them.
    """
    words = item.split(maxsplit=1)
    if not words:
        return None
    raw = words[0]
    lowered = raw.rstrip(".,;:!?").lower()
    if not lowered:
        return None
    return raw, lowered


def _duplicate_issue(
    rule_id: str,
    severity: Severity,
    path_str: str,
    idx: int,
    raw_opener: str,
    item: str,
) -> LintIssue:
    """Build a ``LintIssue`` for a duplicate opener hit (shared across scope paths)."""
    return LintIssue(
        rule=rule_id,
        severity=severity,
        path=f"{path_str}[{idx}]",
        message=f"Duplicate opening word '{raw_opener}'",
        value=item,
    )


# Params models


class MinItemsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``min_items``."""

    value: StrictInt


class MaxItemsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``max_items``."""

    value: StrictInt


class MinWordsPerItemParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``min_words_per_item``."""

    value: StrictInt


class MaxWordsPerItemParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``max_words_per_item``."""

    value: StrictInt


class UniqueOpeningWordsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``unique_opening_words``.

    The ``scope`` field controls the uniqueness window. ``entry`` tracks
    openers per resolved path (e.g. per ``entries[*].bullets``), ``section``
    aggregates across all items in the same scope call, and ``document``
    aggregates across every invocation of this rule.
    """

    scope: Literal["entry", "section", "document"] = "entry"


class VerbTenseParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``verb_tense``."""

    require: Literal["past"] = "past"


class MaxChildItemsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``max_child_items``."""

    child_key: str
    value: StrictInt


class BannedChildNamesParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``banned_child_names``.

    Attributes:
        name_key: The dict key holding the object's name string.
        patterns: Non-empty tuple of regex patterns, each case-insensitive.
    """

    name_key: str
    patterns: tuple[str, ...]

    @field_validator("patterns")
    @classmethod
    def _validate_patterns(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        """Require non-empty and compile each pattern; fail fast on invalid regex."""
        if not v:
            msg = "banned_child_names patterns must be non-empty"
            raise ValueError(msg)
        for pattern in v:
            try:
                re.compile(pattern)
            except re.error as err:
                msg = f"Invalid regex pattern {pattern!r}: {err}"
                raise ValueError(msg) from err
        return v


class FirstItemCapitalizationParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``first_item_capitalization``.

    Attributes:
        child_key: If set, drill into ``item[child_key]`` and check its first
            element; otherwise check the first element of each resolved list.
    """

    child_key: str | None = None


# Rule classes


class MinItemsRule:
    """Flags resolved paths whose list length is below ``params.value``."""

    TYPE_ID: ClassVar[str] = "min_items"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MinItemsParams
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
        """Emit one issue per path whose item count is below ``value``."""
        if not isinstance(params, MinItemsParams):
            msg = f"MinItemsRule expected MinItemsParams, got {type(params).__name__}"
            raise TypeError(msg)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            count = len(items)
            if count < params.value:
                issues.append(
                    LintIssue(
                        rule=rule_id,
                        severity=severity,
                        path=path_str,
                        message=f"Section has {count} items (min {params.value})",
                        value=str(count),
                    )
                )
        return issues


class MaxItemsRule:
    """Flags resolved paths whose list length exceeds ``params.value``."""

    TYPE_ID: ClassVar[str] = "max_items"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MaxItemsParams
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
        """Emit one issue per path whose item count exceeds ``value``."""
        if not isinstance(params, MaxItemsParams):
            msg = f"MaxItemsRule expected MaxItemsParams, got {type(params).__name__}"
            raise TypeError(msg)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            count = len(items)
            if count > params.value:
                issues.append(
                    LintIssue(
                        rule=rule_id,
                        severity=severity,
                        path=path_str,
                        message=f"Section has {count} items (max {params.value})",
                        value=str(count),
                    )
                )
        return issues


class MinWordsPerItemRule:
    """Flags string items with fewer words than ``params.value``."""

    TYPE_ID: ClassVar[str] = "min_words_per_item"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MinWordsPerItemParams
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
        """Emit one issue per short item."""
        if not isinstance(params, MinWordsPerItemParams):
            msg = f"MinWordsPerItemRule expected MinWordsPerItemParams, got {type(params).__name__}"
            raise TypeError(msg)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(items):
                if not isinstance(item, str):
                    continue
                word_count = _count_words(item)
                if word_count < params.value:
                    issues.append(
                        LintIssue(
                            rule=rule_id,
                            severity=severity,
                            path=f"{path_str}[{idx}]",
                            message=f"Item has {word_count} words (min {params.value})",
                            value=str(word_count),
                        )
                    )
        return issues


class MaxWordsPerItemRule:
    """Flags string items with more words than ``params.value``."""

    TYPE_ID: ClassVar[str] = "max_words_per_item"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MaxWordsPerItemParams
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
        """Emit one issue per over-long item."""
        if not isinstance(params, MaxWordsPerItemParams):
            msg = f"MaxWordsPerItemRule expected MaxWordsPerItemParams, got {type(params).__name__}"
            raise TypeError(msg)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(items):
                if not isinstance(item, str):
                    continue
                word_count = _count_words(item)
                if word_count > params.value:
                    issues.append(
                        LintIssue(
                            rule=rule_id,
                            severity=severity,
                            path=f"{path_str}[{idx}]",
                            message=f"Item has {word_count} words (max {params.value})",
                            value=str(word_count),
                        )
                    )
        return issues


class UniqueOpeningWordsRule:
    """Flags duplicate opening words across the configured uniqueness scope.

    Scopes:
      - ``entry`` — uniqueness is enforced **within** each resolved path.
        Two different ``experience.entries[*].bullets`` lists may each start a
        bullet with ``Built`` without triggering.
      - ``section`` — uniqueness is enforced **across all resolved paths in a
        single call**. Any opening word that appears in more than one item —
        regardless of which path it came from — is flagged on the second and
        subsequent occurrences.
       - ``document`` — in the flat (one-rule-per-``RuleConfig``) schema this
         collapses to the same semantics as ``section``: the rule has no
         cross-rule state, and all items reachable through this rule's
         ``scope_paths`` are the document-level population. The distinction is
         preserved for forward compatibility with future enhancements to the
         linting model.
    """

    TYPE_ID: ClassVar[str] = "unique_opening_words"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = UniqueOpeningWordsParams
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
        """Emit one issue per item whose opening word repeats within the chosen scope."""
        if not isinstance(params, UniqueOpeningWordsParams):
            msg = f"UniqueOpeningWordsRule expected UniqueOpeningWordsParams, got {type(params).__name__}"
            raise TypeError(msg)

        if params.scope == "entry":
            return self._check_per_path(rule_id, severity, resolved)
        # section and document both aggregate across the full resolved scope.
        return self._check_aggregated(rule_id, severity, resolved)

    @staticmethod
    def _check_per_path(
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
    ) -> list[LintIssue]:
        """Track duplicates independently within each resolved path."""
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            seen: dict[str, int] = {}
            for idx, item in enumerate(items):
                if not isinstance(item, str):
                    continue
                opener = _opening_word(item)
                if opener is None:
                    continue
                raw, lowered = opener
                if lowered in seen:
                    issues.append(_duplicate_issue(rule_id, severity, path_str, idx, raw, item))
                else:
                    seen[lowered] = idx
        return issues

    @staticmethod
    def _check_aggregated(
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
    ) -> list[LintIssue]:
        """Track duplicates across every item in every path (section / document scopes)."""
        issues: list[LintIssue] = []
        seen: set[str] = set()
        for path_str, items in resolved:
            for idx, item in enumerate(items):
                if not isinstance(item, str):
                    continue
                opener = _opening_word(item)
                if opener is None:
                    continue
                raw, lowered = opener
                if lowered in seen:
                    issues.append(_duplicate_issue(rule_id, severity, path_str, idx, raw, item))
                else:
                    seen.add(lowered)
        return issues


class VerbTenseRule:
    """Flags string items whose first word is not past tense."""

    TYPE_ID: ClassVar[str] = "verb_tense"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = VerbTenseParams
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
        """Emit one issue per non-past-tense opener."""
        if not isinstance(params, VerbTenseParams):
            msg = f"VerbTenseRule expected VerbTenseParams, got {type(params).__name__}"
            raise TypeError(msg)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(items):
                if not isinstance(item, str):
                    continue
                words = item.split()
                if not words:
                    continue
                if not _is_past_tense(words[0]):
                    issues.append(
                        LintIssue(
                            rule=rule_id,
                            severity=severity,
                            path=f"{path_str}[{idx}]",
                            message="Item should use past tense",
                            value=item,
                        )
                    )
        return issues


class MaxChildItemsRule:
    """Flags objects whose named child array exceeds ``params.value``."""

    TYPE_ID: ClassVar[str] = "max_child_items"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MaxChildItemsParams
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
        """Emit one issue per object whose child array is too long."""
        if not isinstance(params, MaxChildItemsParams):
            msg = f"MaxChildItemsRule expected MaxChildItemsParams, got {type(params).__name__}"
            raise TypeError(msg)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(items):
                if not is_str_keyed_dict(item):
                    continue
                raw_child = item.get(params.child_key)
                if not isinstance(raw_child, list):
                    continue
                count = len(raw_child)
                if count > params.value:
                    issues.append(
                        LintIssue(
                            rule=rule_id,
                            severity=severity,
                            path=f"{path_str}[{idx}].{params.child_key}",
                            message=f"Child array has {count} items (max {params.value})",
                            value=str(count),
                        )
                    )
        return issues


class BannedChildNamesRule:
    """Flags objects whose named string field matches a banned regex pattern."""

    TYPE_ID: ClassVar[str] = "banned_child_names"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = BannedChildNamesParams
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
        """Emit one issue per object whose name field matches any banned pattern."""
        if not isinstance(params, BannedChildNamesParams):
            msg = f"BannedChildNamesRule expected BannedChildNamesParams, got {type(params).__name__}"
            raise TypeError(msg)
        compiled = [compile_cached(p, re.IGNORECASE) for p in params.patterns]
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            for idx, item in enumerate(items):
                if not is_str_keyed_dict(item):
                    continue
                name_val = item.get(params.name_key)
                if not isinstance(name_val, str):
                    continue
                for pattern in compiled:
                    if pattern.search(name_val):
                        issues.append(
                            LintIssue(
                                rule=rule_id,
                                severity=severity,
                                path=f"{path_str}[{idx}].{params.name_key}",
                                message=f"Banned name: {name_val!r}",
                                value=name_val,
                            )
                        )
                        break  # One issue per object even if multiple patterns match.
        return issues


class FirstItemCapitalizationRule:
    """Warns when the first string item (or first child item) starts lowercase."""

    TYPE_ID: ClassVar[str] = "first_item_capitalization"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = FirstItemCapitalizationParams
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
        """Emit one issue per violating first element."""
        if not isinstance(params, FirstItemCapitalizationParams):
            msg = f"FirstItemCapitalizationRule expected FirstItemCapitalizationParams, got {type(params).__name__}"
            raise TypeError(msg)
        issues: list[LintIssue] = []
        for path_str, items in resolved:
            if params.child_key is not None:
                issues.extend(self._check_child_keys(rule_id, severity, path_str, items, params.child_key))
            else:
                issues.extend(self._check_first_element(rule_id, severity, path_str, items))
        return issues

    @staticmethod
    def _check_child_keys(
        rule_id: str,
        severity: Severity,
        path_str: str,
        items: list[object],
        child_key: str,
    ) -> list[LintIssue]:
        """Check each object's ``item[child_key][0]`` for lowercase start."""
        issues: list[LintIssue] = []
        for idx, item in enumerate(items):
            if not is_str_keyed_dict(item):
                continue
            raw_child = item.get(child_key)
            if not isinstance(raw_child, list) or not raw_child:
                continue
            first = raw_child[0]
            if isinstance(first, str) and first and first[0].islower():
                issues.append(
                    LintIssue(
                        rule=rule_id,
                        severity=severity,
                        path=f"{path_str}[{idx}].{child_key}[0]",
                        message=f"First item starts with lowercase: {first!r}",
                        value=first,
                    )
                )
        return issues

    @staticmethod
    def _check_first_element(
        rule_id: str,
        severity: Severity,
        path_str: str,
        items: list[object],
    ) -> list[LintIssue]:
        """Check the first element of the resolved list for lowercase start."""
        if not items:
            return []
        first = items[0]
        if isinstance(first, str) and first and first[0].islower():
            return [
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=f"{path_str}[0]",
                    message=f"First item starts with lowercase: {first!r}",
                    value=first,
                )
            ]
        return []
