"""Document-level structure rules -- ``scope_paths: ["$"]``.

Document-level rules receive a single ``("$", [data])`` tuple from the path
resolver where ``data`` is the full parsed document. The rules unwrap that
and inspect top-level keys.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel

from tailor.lint.content.rules._helpers import is_str_keyed_dict
from tailor.lint.models import LintIssue, Severity


class RequiredSectionsParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``required_sections``.

    Attributes:
        value: Top-level keys that must exist and be truthy on the document.
    """

    value: tuple[str, ...]


class SectionOrderParams(BaseModel, frozen=True, extra="forbid"):
    """Params for ``section_order``.

    Attributes:
        value: Expected top-level key ordering. Only keys present in both data
            and this list are compared.
    """

    value: tuple[str, ...]


def _document_from_resolved(
    resolved: list[tuple[str, list[object]]],
) -> dict[str, object] | None:
    """Unwrap the document dict from a resolved ``scope_paths: ["$"]``.

    Returns ``None`` when the resolved payload is malformed or the document is
    not a dict; callers should skip rule evaluation in that case.
    """
    if not resolved:
        return None
    _path, items = resolved[0]
    if not items:
        return None
    data = items[0]
    if not is_str_keyed_dict(data):
        return None
    return data


class RequiredSectionsRule:
    """Flags missing or empty required top-level document sections."""

    TYPE_ID: ClassVar[str] = "required_sections"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = RequiredSectionsParams
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
        """Emit one issue per required section that is missing or empty."""
        if not isinstance(params, RequiredSectionsParams):
            msg = f"RequiredSectionsRule expected RequiredSectionsParams, got {type(params).__name__}"
            raise TypeError(msg)
        data = _document_from_resolved(resolved)
        if data is None:
            return []
        return [
            LintIssue(
                rule=rule_id,
                severity=severity,
                path=section,
                message=f"Required section '{section}' is missing or empty",
                value=section,
            )
            for section in params.value
            if not data.get(section)
        ]


class SectionOrderRule:
    """Flags top-level sections that appear out of the configured order."""

    TYPE_ID: ClassVar[str] = "section_order"
    PARAMS_MODEL: ClassVar[type[BaseModel]] = SectionOrderParams
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
        """Emit one issue per section that violates the expected ordering."""
        if not isinstance(params, SectionOrderParams):
            msg = f"SectionOrderRule expected SectionOrderParams, got {type(params).__name__}"
            raise TypeError(msg)
        data = _document_from_resolved(resolved)
        if data is None:
            return []

        expected_order = params.value
        # Only consider sections present in both data and the expected order.
        present = {k for k in data if data[k]}
        expected_set = frozenset(expected_order)
        expected_filtered = [s for s in expected_order if s in present]
        actual_sections = [k for k in data if k in present and k in expected_set]

        if actual_sections == expected_filtered:
            return []

        # Precompute position maps so the per-section comparison is O(1)
        # instead of two O(n) ``list.index`` calls per section.
        actual_index: dict[str, int] = {s: i for i, s in enumerate(actual_sections)}
        expected_index: dict[str, int] = {s: i for i, s in enumerate(expected_filtered)}

        return [
            LintIssue(
                rule=rule_id,
                severity=severity,
                path=section,
                message=f"Section '{section}' is out of expected order",
                value=section,
            )
            for section in actual_sections
            if actual_index[section] != expected_index[section]
        ]
