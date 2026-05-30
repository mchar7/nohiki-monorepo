"""Tests for document structure rules -- flat schema API."""

from __future__ import annotations

from tailor.lint.content.rules.structure_rules import (
    RequiredSectionsParams,
    RequiredSectionsRule,
    SectionOrderParams,
    SectionOrderRule,
)
from tailor.lint.models import Severity

Resolved = list[tuple[str, list[object]]]


def _resolved_doc(data: dict[str, object]) -> Resolved:
    """Wrap document as root-level resolved path."""
    return [("$", [data])]


class TestRequiredSectionsRule:
    """Tests for RequiredSectionsRule."""

    def test_passes_when_all_sections_present(self) -> None:
        rule = RequiredSectionsRule()
        params = RequiredSectionsParams(value=("header", "experience"))
        resolved = _resolved_doc({"header": {"name": "Alice"}, "experience": [{"title": "Dev"}]})
        result = rule.check(
            rule_id="test.required",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_flags_missing_section(self) -> None:
        rule = RequiredSectionsRule()
        params = RequiredSectionsParams(value=("header", "experience"))
        resolved = _resolved_doc({"header": {"name": "Alice"}})
        result = rule.check(
            rule_id="test.required",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1
        assert result[0].value == "experience"

    def test_flags_empty_list_section(self) -> None:
        rule = RequiredSectionsRule()
        params = RequiredSectionsParams(value=("header", "experience"))
        resolved = _resolved_doc({"header": {"name": "Alice"}, "experience": []})
        result = rule.check(
            rule_id="test.required",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_flags_empty_dict_section(self) -> None:
        rule = RequiredSectionsRule()
        params = RequiredSectionsParams(value=("header", "experience"))
        resolved = _resolved_doc({"header": {}, "experience": [{"title": "Dev"}]})
        result = rule.check(
            rule_id="test.required",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 1

    def test_multiple_missing_sections(self) -> None:
        rule = RequiredSectionsRule()
        params = RequiredSectionsParams(value=("header", "skills", "experience", "education"))
        resolved = _resolved_doc({})
        result = rule.check(
            rule_id="test.required",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert len(result) == 4

    def test_empty_resolved_returns_empty(self) -> None:
        rule = RequiredSectionsRule()
        params = RequiredSectionsParams(value=("header",))
        resolved: Resolved = []
        result = rule.check(
            rule_id="test.required",
            severity=Severity.ERROR,
            resolved=resolved,
            params=params,
        )
        assert result == []


class TestSectionOrderRule:
    """Tests for SectionOrderRule."""

    def test_passes_correct_order(self) -> None:
        rule = SectionOrderRule()
        params = SectionOrderParams(value=("header", "skills", "experience"))
        resolved = _resolved_doc({"header": 1, "skills": 2, "experience": 3})
        result = rule.check(
            rule_id="test.order",
            severity=Severity.INFO,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_flags_out_of_order(self) -> None:
        rule = SectionOrderRule()
        params = SectionOrderParams(value=("header", "skills", "experience"))
        resolved = _resolved_doc({"header": 1, "experience": 2, "skills": 3})
        result = rule.check(
            rule_id="test.order",
            severity=Severity.INFO,
            resolved=resolved,
            params=params,
        )
        assert len(result) > 0

    def test_ignores_sections_not_in_order_list(self) -> None:
        rule = SectionOrderRule()
        params = SectionOrderParams(value=("header", "skills"))
        resolved = _resolved_doc({"header": 1, "custom_section": 2, "skills": 3})
        result = rule.check(
            rule_id="test.order",
            severity=Severity.INFO,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_single_configured_section_no_issues(self) -> None:
        rule = SectionOrderRule()
        params = SectionOrderParams(value=("header", "skills", "experience"))
        resolved = _resolved_doc({"header": 1})
        result = rule.check(
            rule_id="test.order",
            severity=Severity.INFO,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_empty_data_no_issues(self) -> None:
        rule = SectionOrderRule()
        params = SectionOrderParams(value=("header", "skills"))
        resolved = _resolved_doc({})
        result = rule.check(
            rule_id="test.order",
            severity=Severity.INFO,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_all_configured_sections_absent_no_issues(self) -> None:
        rule = SectionOrderRule()
        params = SectionOrderParams(value=("header", "skills", "experience"))
        resolved = _resolved_doc({"custom": "value"})
        result = rule.check(
            rule_id="test.order",
            severity=Severity.INFO,
            resolved=resolved,
            params=params,
        )
        assert result == []

    def test_out_of_order_issue_has_path_and_value(self) -> None:
        rule = SectionOrderRule()
        params = SectionOrderParams(value=("header", "skills", "experience"))
        resolved = _resolved_doc({"header": 1, "experience": 2, "skills": 3})
        result = rule.check(
            rule_id="test.order",
            severity=Severity.INFO,
            resolved=resolved,
            params=params,
        )
        assert len(result) > 0
        for issue in result:
            assert issue.path in ("skills", "experience")
            assert issue.value in ("skills", "experience")
