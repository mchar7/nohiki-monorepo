"""Data models for the document linting system.

All models use Pydantic BaseModel (not dataclasses).
Models are frozen (immutable) since lint configs and issues are read-only after creation.
Config models use ``extra="forbid"`` to reject unknown YAML keys (catching typos).

Schema is the flat ``rules:`` list shape used across the system. Each rule entry
is a ``RuleConfig`` with a ``type`` field that dispatches to a registered ``Rule``
implementation at engine time.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

# Identifier regex for rule_id segments: dot-separated lowercase tokens.
_RULE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

# Root path literal for document-level rules.
ROOT_PATH = "$"


class Severity(StrEnum):
    """Lint issue severity level."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class LintIssue(BaseModel, frozen=True):
    """A single lint finding.

    Attributes:
        rule: Dot-separated rule identifier from the YAML config
            (e.g. ``content.<scope>.<type>``).
        severity: Issue severity level.
        path: JSON path to the offending data within the document
            (e.g. ``sections[0].items[2]`` or ``$`` for document-level issues).
        message: Human-readable description of the issue.
        value: The offending value, if applicable.
    """

    rule: str
    severity: Severity
    path: str
    message: str
    value: str | None = None


class BannedPattern(BaseModel, frozen=True, extra="forbid"):
    """A single banned text pattern, used inside ``banned_patterns`` rule params.

    Attributes:
        pattern: Regex pattern to flag. Validated at model creation.
        message: Optional per-pattern override of the rule's default message.
    """

    pattern: str
    message: str = ""

    @field_validator("pattern")
    @classmethod
    def _validate_regex(cls, v: str) -> str:
        """Validate the pattern compiles as a Python regex."""
        try:
            re.compile(v)
        except re.error as err:
            msg = f"Invalid regex pattern {v!r}: {err}"
            raise ValueError(msg) from err
        return v


class RuleConfig(BaseModel, frozen=True, extra="forbid"):
    """A single flat rule entry from a lint YAML config.

    Registry-aware validation (``type`` exists, ``params`` match the rule's
    ``PARAMS_MODEL``, ``applies_when`` parses) is performed by ``load_lint_config``.

    Attributes:
        rule_id: Globally-unique-per-(rule_id, scope_path) identifier.
        type: Rule type id; must match a registered rule's ``TYPE_ID``.
        severity: 3-level severity enum.
        scope_paths: Non-empty list of JSON path expressions. ``"$"`` = document root.
        scope_excludes: Paths to subtract from ``scope_paths`` matches.
        params: Rule-specific params; validated by the rule's ``PARAMS_MODEL``.
        requires_tags: All must be active in runtime for the rule to fire.
        excludes_tags: Any active match skips the rule.
        applies_when: Optional CEL-subset predicate string; evaluated at rule-check time.
        user_overridable: Reserved for future merge algebra. Default False.
        description: Human-facing description (not emitted in issues).
    """

    rule_id: str
    type: str
    severity: Severity
    scope_paths: tuple[str, ...]
    scope_excludes: tuple[str, ...] = ()
    params: dict[str, object] = Field(default_factory=dict)
    requires_tags: tuple[str, ...] = ()
    excludes_tags: tuple[str, ...] = ()
    applies_when: str | None = None
    user_overridable: bool = False
    description: str = ""

    @field_validator("rule_id")
    @classmethod
    def _validate_rule_id(cls, v: str) -> str:
        """Ensure rule_id is a dot-separated lowercase identifier."""
        if not _RULE_ID_RE.match(v):
            msg = f"Invalid rule_id {v!r}: must match {_RULE_ID_RE.pattern} (dot-separated lowercase identifiers)"
            raise ValueError(msg)
        return v

    @field_validator("scope_paths")
    @classmethod
    def _validate_scope_paths_nonempty(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        """Ensure scope_paths has at least one entry."""
        if not v:
            msg = "scope_paths must be non-empty"
            raise ValueError(msg)
        for path in v:
            if not path:
                msg = "scope_paths entries must be non-empty strings"
                raise ValueError(msg)
        return v

    @field_validator("applies_when")
    @classmethod
    def _validate_applies_when(cls, v: str | None) -> str | None:
        """Parse ``applies_when`` at load so syntax errors fail fast.

        The applies_when field is parsed against the minimal CEL grammar at
        config load; syntax errors raise ``LintConfigError``
        (Pydantic wraps this ``ValueError`` into a ``ValidationError`` that
        the config loader surfaces with file context). Compiling here is
        throwaway — the engine recompiles once and caches — but it guarantees
        load-time fail-fast instead of silent-lazy-failure at evaluation.

        The import is deferred to avoid a circular dependency: ``cel`` imports
        ``path_resolver.navigate`` which in turn imports ``ROOT_PATH`` from
        this module.
        """
        if v is None:
            return v
        from tailor.exceptions import LintConfigError
        from tailor.lint.cel import compile_predicate

        try:
            compile_predicate(v)
        except (LintConfigError, ValueError, SyntaxError) as err:
            msg = f"Invalid applies_when expression {v!r}: {err}"
            raise ValueError(msg) from err
        return v


class LayoutConfig(BaseModel, frozen=True, extra="forbid"):
    """Optional ``layout:`` block in a lint config -- same RuleConfig shape as content rules.

    Present only when the template opts into post-render layout linting.
    Layout rules dispatch by the same registry but operate on ``LayoutMetadata``
    extracted from the rendered PDF.
    """

    rules: tuple[RuleConfig, ...] = ()


class LintConfig(BaseModel, frozen=True, extra="forbid"):
    """Top-level lint configuration -- flat ``rules:`` list with optional layout block.

    Attributes:
        rules: Flat list of content rule entries (required, non-empty).
        layout: Optional layout rule block.
    """

    rules: tuple[RuleConfig, ...]
    layout: LayoutConfig | None = None

    @field_validator("rules")
    @classmethod
    def _validate_rules_nonempty(cls, v: tuple[RuleConfig, ...]) -> tuple[RuleConfig, ...]:
        """Ensure rules is required and non-empty.

        Templates that opt out of linting should omit the ``.lint.yaml`` file
        entirely rather than ship one with zero rules.
        """
        if not v:
            msg = "rules must be non-empty; omit the .lint.yaml file to opt out of linting"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def _validate_rules_unique(self) -> LintConfig:
        """Enforce ``(rule_id, scope_path)`` composite key uniqueness.

        The composite key is global across content rules AND layout rules — a
        layout rule_id at ``$`` may not clash with a content rule_id at ``$``.
        """
        seen: set[tuple[str, str]] = set()
        layout_rules = self.layout.rules if self.layout is not None else ()
        for rule in (*self.rules, *layout_rules):
            for path in rule.scope_paths:
                key = (rule.rule_id, path)
                if key in seen:
                    msg = f"Duplicate (rule_id, scope_path) pair: rule_id={rule.rule_id!r}, scope_path={path!r}"
                    raise ValueError(msg)
                seen.add(key)
        return self
