"""Tests for tailor.lint.cel module.

Tests cover tokenization, parsing, compilation, and evaluation of CEL-subset predicates.
"""

from __future__ import annotations

from typing import cast

import pytest
from tailor.exceptions import LintConfigError
from tailor.lint.cel import compile_predicate
from tailor.lint.runtime import LintRuntimeContext


class TestCompilePredicateTokenization:
    """Tests for tokenization errors in compile_predicate."""

    def test_empty_string_raises_error(self) -> None:
        """Empty expression raises LintConfigError."""
        with pytest.raises(LintConfigError, match="Empty applies_when"):
            compile_predicate("")

    def test_invalid_character_raises_error(self) -> None:
        """Invalid characters raise LintConfigError."""
        with pytest.raises(LintConfigError, match="Unexpected character"):
            compile_predicate("has_tag('x') @ invalid")

    def test_unclosed_string_raises_error(self) -> None:
        """Unclosed string raises LintConfigError."""
        with pytest.raises(LintConfigError, match="Unexpected"):
            compile_predicate('has_tag("unclosed')


class TestCompilePredicateParsing:
    """Tests for parsing errors in compile_predicate."""

    def test_unknown_predicate_name_raises_error(self) -> None:
        """Unknown predicate name raises LintConfigError."""
        with pytest.raises(LintConfigError, match="Unknown predicate"):
            compile_predicate("unknown_pred('x')")

    def test_missing_parens_raises_error(self) -> None:
        """Missing parentheses raise LintConfigError."""
        with pytest.raises(LintConfigError):
            compile_predicate("has_tag 'x'")

    def test_unbalanced_parens_raises_error(self) -> None:
        """Unbalanced parentheses raise LintConfigError."""
        with pytest.raises(LintConfigError):
            compile_predicate("(has_tag('x')")
        with pytest.raises(LintConfigError):
            compile_predicate("has_tag('x'))")


class TestCompiledPredicateEvaluation:
    """Tests for evaluation of compiled predicates."""

    def test_has_tag_true_when_present(self) -> None:
        """has_tag('x') returns True when tag in active_tags."""
        pred = compile_predicate("has_tag('tag1')")
        runtime = LintRuntimeContext(active_tags=frozenset(("tag1", "tag2")))
        result = pred.evaluate({}, runtime)
        assert result is True

    def test_has_tag_false_when_absent(self) -> None:
        """has_tag('x') returns False when tag not in active_tags."""
        pred = compile_predicate("has_tag('tag_missing')")
        runtime = LintRuntimeContext(active_tags=frozenset(("tag1",)))
        result = pred.evaluate({}, runtime)
        assert result is False

    def test_schema_has_path_true_when_present(self) -> None:
        """schema_has_path('a.b') returns True when path exists with non-None value."""
        pred = compile_predicate("schema_has_path('info.name')")
        data = cast("dict[str, object]", {"info": {"name": "Alice"}})
        runtime = LintRuntimeContext()
        result = pred.evaluate(data, runtime)
        assert result is True

    def test_schema_has_path_false_when_missing(self) -> None:
        """schema_has_path('a.b') returns False when path missing."""
        pred = compile_predicate("schema_has_path('info.name')")
        data = cast("dict[str, object]", {"info": {}})
        runtime = LintRuntimeContext()
        result = pred.evaluate(data, runtime)
        assert result is False

    def test_schema_has_path_with_array_indices(self) -> None:
        """schema_has_path handles array indices (e.g., items[0])."""
        pred = compile_predicate("schema_has_path('items[0]')")
        data = cast("dict[str, object]", {"items": [{"id": 1}]})
        runtime = LintRuntimeContext()
        result = pred.evaluate(data, runtime)
        assert result is True

    def test_has_sibling_true_when_loaded(self) -> None:
        """has_sibling('reference') returns True when sibling loaded."""
        pred = compile_predicate("has_sibling('reference')")
        runtime = LintRuntimeContext(sibling_documents={"reference": {"name": "Alice"}})
        result = pred.evaluate({}, runtime)
        assert result is True

    def test_has_sibling_false_when_not_loaded(self) -> None:
        """has_sibling('reference') returns False when sibling not loaded."""
        pred = compile_predicate("has_sibling('reference')")
        runtime = LintRuntimeContext(sibling_documents={})
        result = pred.evaluate({}, runtime)
        assert result is False

    def test_not_negation(self) -> None:
        """Not has_tag('x') negates the result."""
        pred_true = compile_predicate("not has_tag('x')")
        pred_false = compile_predicate("not has_tag('x')")
        runtime_with = LintRuntimeContext(active_tags=frozenset(("x",)))
        runtime_without = LintRuntimeContext(active_tags=frozenset())

        assert pred_true.evaluate({}, runtime_without) is True
        assert pred_false.evaluate({}, runtime_with) is False

    def test_and_both_required(self) -> None:
        """has_tag('a') and has_tag('b') requires both."""
        pred = compile_predicate("has_tag('a') and has_tag('b')")

        # Both present
        runtime_both = LintRuntimeContext(active_tags=frozenset(("a", "b")))
        assert pred.evaluate({}, runtime_both) is True

        # Only one present
        runtime_a = LintRuntimeContext(active_tags=frozenset(("a",)))
        assert pred.evaluate({}, runtime_a) is False

        # Neither present
        runtime_none = LintRuntimeContext(active_tags=frozenset())
        assert pred.evaluate({}, runtime_none) is False

    def test_or_either_required(self) -> None:
        """has_tag('a') or has_tag('b') requires either."""
        pred = compile_predicate("has_tag('a') or has_tag('b')")

        # Both present
        runtime_both = LintRuntimeContext(active_tags=frozenset(("a", "b")))
        assert pred.evaluate({}, runtime_both) is True

        # Only a
        runtime_a = LintRuntimeContext(active_tags=frozenset(("a",)))
        assert pred.evaluate({}, runtime_a) is True

        # Only b
        runtime_b = LintRuntimeContext(active_tags=frozenset(("b",)))
        assert pred.evaluate({}, runtime_b) is True

        # Neither
        runtime_none = LintRuntimeContext(active_tags=frozenset())
        assert pred.evaluate({}, runtime_none) is False

    def test_short_circuit_and_false(self) -> None:
        """has_tag('a') and has_tag('b') short-circuits when first is False."""
        pred = compile_predicate("has_tag('a') and has_tag('b')")
        runtime = LintRuntimeContext(active_tags=frozenset())
        # Should return False without error even though 'b' is missing
        result = pred.evaluate({}, runtime)
        assert result is False

    def test_short_circuit_or_true(self) -> None:
        """has_tag('a') or has_tag('b') short-circuits when first is True."""
        pred = compile_predicate("has_tag('a') or has_tag('b')")
        runtime = LintRuntimeContext(active_tags=frozenset(("a",)))
        # Should return True without checking second operand
        result = pred.evaluate({}, runtime)
        assert result is True

    def test_parenthesization_changes_meaning(self) -> None:
        """Parenthesization affects evaluation order."""
        pred1 = compile_predicate("not (has_tag('a') and has_tag('b'))")
        pred2 = compile_predicate("not has_tag('a') and has_tag('b')")

        runtime_a = LintRuntimeContext(active_tags=frozenset(("a",)))

        # With tag 'a' only:
        # not (a and b) = not (True and False) = not False = True
        # (not a) and b = (not True) and False = False and False = False
        assert pred1.evaluate({}, runtime_a) is True
        assert pred2.evaluate({}, runtime_a) is False

    def test_double_quoted_string_arg(self) -> None:
        """Double-quoted strings are parsed correctly."""
        pred = compile_predicate('has_tag("mytag")')
        runtime = LintRuntimeContext(active_tags=frozenset(("mytag",)))
        assert pred.evaluate({}, runtime) is True

    def test_single_quoted_string_arg(self) -> None:
        """Single-quoted strings are parsed correctly."""
        pred = compile_predicate("has_tag('mytag')")
        runtime = LintRuntimeContext(active_tags=frozenset(("mytag",)))
        assert pred.evaluate({}, runtime) is True

    def test_literal_true(self) -> None:
        """Literal 'true' evaluates to True."""
        pred = compile_predicate("true")
        runtime = LintRuntimeContext()
        assert pred.evaluate({}, runtime) is True

    def test_literal_false(self) -> None:
        """Literal 'false' evaluates to False."""
        pred = compile_predicate("false")
        runtime = LintRuntimeContext()
        assert pred.evaluate({}, runtime) is False

    def test_source_retained_on_compiled_predicate(self) -> None:
        """CompiledPredicate retains source for diagnostics."""
        source = "has_tag('x')"
        pred = compile_predicate(source)
        assert pred.source == source

    def test_complex_expression_evaluation(self) -> None:
        """Complex expressions with mixed operators evaluate correctly."""
        pred = compile_predicate("(has_tag('reference') and schema_has_path('experience')) or has_sibling('ref')")

        # Case 1: has reference tag and path exists
        runtime1 = LintRuntimeContext(active_tags=frozenset(("reference",)))
        data1 = cast("dict[str, object]", {"experience": []})
        assert pred.evaluate(data1, runtime1) is True

        # Case 2: has sibling but no reference tag
        runtime2 = LintRuntimeContext(active_tags=frozenset(), sibling_documents={"ref": {}})
        data2 = cast("dict[str, object]", {})
        assert pred.evaluate(data2, runtime2) is True

        # Case 3: nothing matches
        runtime3 = LintRuntimeContext(active_tags=frozenset())
        data3 = cast("dict[str, object]", {})
        assert pred.evaluate(data3, runtime3) is False

    def test_whitespace_handling_in_placeholders(self) -> None:
        """Whitespace in predicate arguments is handled correctly."""
        pred1 = compile_predicate("has_tag('x')")
        pred2 = compile_predicate("has_tag( 'x' )")
        pred3 = compile_predicate("has_tag(  'x'  )")

        runtime = LintRuntimeContext(active_tags=frozenset(("x",)))
        assert pred1.evaluate({}, runtime) is True
        assert pred2.evaluate({}, runtime) is True
        assert pred3.evaluate({}, runtime) is True
