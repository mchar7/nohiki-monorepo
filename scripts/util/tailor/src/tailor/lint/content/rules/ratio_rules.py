"""Ratio rule — generic occurrence-per-100-words density metric.

Generalizes contraction-density checks, adverb density, passive-voice density,
or any per-100-words regex count. Single aggregate issue per bound violation.
"""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, StrictInt, field_validator, model_validator

from tailor.lint.content.rules._helpers import as_strings, compile_cached, tokenize
from tailor.lint.models import ROOT_PATH, LintIssue, Severity


class RatioParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``ratio``.

    Attributes:
        pattern: Regex whose match count becomes the numerator. ``re.IGNORECASE``
            is applied unless ``case_sensitive=True``.
        case_sensitive: Case-sensitivity for the regex.
        min_per_100_words: Inclusive floor. ``None`` disables the floor check.
        max_per_100_words: Inclusive ceiling. ``None`` disables the ceiling check.
        min_scope_words: Skip the rule entirely when the scope has fewer than
            this many words (avoids noise on tiny scopes).
    """

    pattern: str
    case_sensitive: bool = False
    min_per_100_words: float | None = None
    max_per_100_words: float | None = None
    min_scope_words: StrictInt = 50

    @field_validator("pattern")
    @classmethod
    def _validate_pattern(cls, v: str) -> str:
        if not v:
            msg = "pattern must be non-empty"
            raise ValueError(msg)
        try:
            re.compile(v)
        except re.error as err:
            msg = f"Invalid regex pattern {v!r}: {err}"
            raise ValueError(msg) from err
        return v

    @field_validator("min_scope_words")
    @classmethod
    def _require_positive_scope(cls, v: int) -> int:
        if v < 1:
            msg = "min_scope_words must be >= 1"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _require_at_least_one_bound(self) -> RatioParams:
        if self.min_per_100_words is None and self.max_per_100_words is None:
            msg = "ratio requires at least one of min_per_100_words or max_per_100_words"
            raise ValueError(msg)
        if self.min_per_100_words is not None and self.min_per_100_words < 0:
            msg = "min_per_100_words must be >= 0"
            raise ValueError(msg)
        if self.max_per_100_words is not None and self.max_per_100_words < 0:
            msg = "max_per_100_words must be >= 0"
            raise ValueError(msg)
        if (
            self.min_per_100_words is not None
            and self.max_per_100_words is not None
            and self.min_per_100_words > self.max_per_100_words
        ):
            msg = (
                f"min_per_100_words ({self.min_per_100_words}) cannot exceed "
                f"max_per_100_words ({self.max_per_100_words})"
            )
            raise ValueError(msg)
        return self


class RatioRule:
    """Emits at most two aggregate issues (floor and ceiling) per call.

    Word-count basis uses the shared ``tokenize`` helper (letter-only tokens,
    apostrophe-tolerant). Regex matches use ``re.findall`` against the
    concatenated resolved text.
    """

    TYPE_ID: ClassVar[str] = "ratio"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = RatioParams
    # ``pattern`` is substitutable so templates can use ``{{ var }}`` to inject
    # dynamic vocabulary (e.g. a company-name alternation). The pattern is still
    # regex-validated in the params model after substitution.
    SUBSTITUTABLE_PARAMS: ClassVar[frozenset[str]] = frozenset({"pattern"})

    def check(
        self,
        *,
        rule_id: str,
        severity: Severity,
        resolved: list[tuple[str, list[object]]],
        params: BaseModel,
        **_: object,
    ) -> list[LintIssue]:
        """Compute occurrence density and emit issues for out-of-bounds ratios."""
        if not isinstance(params, RatioParams):
            msg = f"RatioRule expected RatioParams, got {type(params).__name__}"
            raise TypeError(msg)

        full_text = "\n".join(s for _path, items in resolved for s in as_strings(items))
        word_count = len(tokenize(full_text))
        if word_count < params.min_scope_words:
            return []

        flags = 0 if params.case_sensitive else re.IGNORECASE
        # finditer + sum avoids the intermediate match-list ``re.findall`` builds,
        # and ``compile_cached`` amortises compilation across repeat invocations.
        occurrences = sum(1 for _ in compile_cached(params.pattern, flags).finditer(full_text))
        per_100 = occurrences / (word_count / 100.0)

        issues: list[LintIssue] = []
        if params.min_per_100_words is not None and per_100 < params.min_per_100_words:
            issues.append(
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=ROOT_PATH,
                    message=(
                        f"Density {per_100:.2f}/100 words below floor "
                        f"{params.min_per_100_words:.2f} (pattern={params.pattern!r}, "
                        f"occurrences={occurrences}, words={word_count})"
                    ),
                    value=f"{per_100:.2f}",
                ),
            )
        if params.max_per_100_words is not None and per_100 > params.max_per_100_words:
            issues.append(
                LintIssue(
                    rule=rule_id,
                    severity=severity,
                    path=ROOT_PATH,
                    message=(
                        f"Density {per_100:.2f}/100 words above ceiling "
                        f"{params.max_per_100_words:.2f} (pattern={params.pattern!r}, "
                        f"occurrences={occurrences}, words={word_count})"
                    ),
                    value=f"{per_100:.2f}",
                ),
            )
        return issues
