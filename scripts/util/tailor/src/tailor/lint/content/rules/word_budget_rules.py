"""Word-budget-family rule implementations -- aggregate word counts across scope paths.

Implements ``min_total_words`` and ``max_total_words``. Each rule sums
whitespace-tokenized words across all string items in the resolved paths and
emits a single aggregate issue when the total falls outside the configured bound.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, StrictInt

from tailor.lint.models import ROOT_PATH, LintIssue, Severity


class MinTotalWordsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``min_total_words``."""

    value: StrictInt


class MaxTotalWordsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``max_total_words``."""

    value: StrictInt


def _total_words(resolved: list[tuple[str, list[object]]]) -> int:
    """Sum whitespace-token counts across every string item in every resolved path."""
    total = 0
    for _path, items in resolved:
        for item in items:
            if isinstance(item, str):
                total += len(item.split())
    return total


class MinTotalWordsRule:
    """Emits one issue when aggregate word count is below ``params.value``."""

    TYPE_ID: ClassVar[str] = "min_total_words"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MinTotalWordsParams
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
        """Emit a single aggregate issue if total words < ``value``."""
        if not isinstance(params, MinTotalWordsParams):
            msg = f"MinTotalWordsRule expected MinTotalWordsParams, got {type(params).__name__}"
            raise TypeError(msg)
        total = _total_words(resolved)
        if total < params.value:
            return [
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=ROOT_PATH,
                    message=f"Total word count {total} below minimum {params.value}",
                    value=str(total),
                )
            ]
        return []


class MaxTotalWordsRule:
    """Emits one issue when aggregate word count exceeds ``params.value``."""

    TYPE_ID: ClassVar[str] = "max_total_words"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = MaxTotalWordsParams
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
        """Emit a single aggregate issue if total words > ``value``."""
        if not isinstance(params, MaxTotalWordsParams):
            msg = f"MaxTotalWordsRule expected MaxTotalWordsParams, got {type(params).__name__}"
            raise TypeError(msg)
        total = _total_words(resolved)
        if total > params.value:
            return [
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=ROOT_PATH,
                    message=f"Total word count {total} above maximum {params.value}",
                    value=str(total),
                )
            ]
        return []
