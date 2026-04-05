"""Unit tests for tracing utilities module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nohiki_llm_client.observability.tracing import (
    llm_span_context,
    prompt_template_context,
    set_llm_span_feedback,
)


class TestLlmSpanContext:
    """Tests for llm_span_context function."""

    @patch("nohiki_llm_client.observability.tracing.using_attributes")
    def test_context_includes_use_case(self, mock_using: MagicMock) -> None:
        """Context includes use_case in metadata."""
        with llm_span_context(use_case="test_case"):
            mock_using.assert_called_once()

        call_kwargs = mock_using.call_args.kwargs
        assert call_kwargs["metadata"]["use_case"] == "test_case"

    @patch("nohiki_llm_client.observability.tracing.using_attributes")
    def test_context_sets_user_id(self, mock_using: MagicMock) -> None:
        """Context sets user_id when provided."""
        with llm_span_context(use_case="test", user_id="user123"):
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["user_id"] == "user123"

    @patch("nohiki_llm_client.observability.tracing.using_attributes")
    def test_context_sets_session_id(self, mock_using: MagicMock) -> None:
        """Context sets session_id when provided."""
        with llm_span_context(use_case="test", session_id="session456"):
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["session_id"] == "session456"

    @patch("nohiki_llm_client.observability.tracing.using_attributes")
    def test_context_merges_metadata(self, mock_using: MagicMock) -> None:
        """Context merges additional metadata."""
        extra_meta = {"key": "value", "number": 42}
        with llm_span_context(use_case="test", metadata=extra_meta):
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["metadata"]["key"] == "value"
            assert call_kwargs["metadata"]["number"] == 42
            assert call_kwargs["metadata"]["use_case"] == "test"

    @patch("nohiki_llm_client.observability.tracing.using_attributes")
    def test_context_uses_empty_strings_for_none(self, mock_using: MagicMock) -> None:
        """Context uses empty strings when user_id/session_id are None."""
        with llm_span_context(use_case="test"):
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["user_id"] == ""
            assert call_kwargs["session_id"] == ""


class TestPromptTemplateContext:
    """Tests for prompt_template_context function."""

    @patch("nohiki_llm_client.observability.tracing.using_prompt_template")
    def test_context_sets_template(self, mock_using: MagicMock) -> None:
        """Context sets template parameter."""
        with prompt_template_context(
            template="Hello {name}",
            variables={"name": "World"},
        ):
            mock_using.assert_called_once()
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["template"] == "Hello {name}"

    @patch("nohiki_llm_client.observability.tracing.using_prompt_template")
    def test_context_sets_variables(self, mock_using: MagicMock) -> None:
        """Context sets variables parameter."""
        variables = {"name": "Test", "count": 5}
        with prompt_template_context(template="test", variables=variables):
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["variables"] == variables

    @patch("nohiki_llm_client.observability.tracing.using_prompt_template")
    def test_context_sets_version(self, mock_using: MagicMock) -> None:
        """Context sets version parameter."""
        with prompt_template_context(
            template="test",
            variables={},
            version="v2.0",
        ):
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["version"] == "v2.0"

    @patch("nohiki_llm_client.observability.tracing.using_prompt_template")
    def test_context_uses_default_version(self, mock_using: MagicMock) -> None:
        """Context uses default version v1 when not specified."""
        with prompt_template_context(template="test", variables={}):
            call_kwargs = mock_using.call_args.kwargs
            assert call_kwargs["version"] == "v1"


class TestSetLlmSpanFeedback:
    """Tests for set_llm_span_feedback function."""

    @patch("nohiki_llm_client.observability.tracing.trace.get_current_span")
    def test_sets_score_attribute(self, mock_get_span: MagicMock) -> None:
        """Sets feedback.score attribute on span."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_get_span.return_value = mock_span

        set_llm_span_feedback(score=0.8)

        mock_span.set_attribute.assert_called_once_with("feedback.score", 0.8)

    @patch("nohiki_llm_client.observability.tracing.trace.get_current_span")
    def test_sets_label_attribute(self, mock_get_span: MagicMock) -> None:
        """Sets feedback.label attribute on span."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_get_span.return_value = mock_span

        set_llm_span_feedback(label="helpful")

        mock_span.set_attribute.assert_called_once_with("feedback.label", "helpful")

    @patch("nohiki_llm_client.observability.tracing.trace.get_current_span")
    def test_sets_explanation_attribute(self, mock_get_span: MagicMock) -> None:
        """Sets feedback.explanation attribute on span."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_get_span.return_value = mock_span

        set_llm_span_feedback(explanation="Very helpful response")

        mock_span.set_attribute.assert_called_once_with(
            "feedback.explanation",
            "Very helpful response",
        )

    @patch("nohiki_llm_client.observability.tracing.trace.get_current_span")
    def test_sets_multiple_attributes(self, mock_get_span: MagicMock) -> None:
        """Sets all feedback attributes when all provided."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_get_span.return_value = mock_span

        set_llm_span_feedback(score=1.0, label="correct", explanation="Good")

        assert mock_span.set_attribute.call_count == 3

    @patch("nohiki_llm_client.observability.tracing.trace.get_current_span")
    def test_skips_when_no_span(self, mock_get_span: MagicMock) -> None:
        """Does nothing when no current span."""
        mock_get_span.return_value = None

        set_llm_span_feedback(score=0.5)

    @patch("nohiki_llm_client.observability.tracing.trace.get_current_span")
    def test_skips_when_not_recording(self, mock_get_span: MagicMock) -> None:
        """Does nothing when span is not recording."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = False
        mock_get_span.return_value = mock_span

        set_llm_span_feedback(score=0.5)

        mock_span.set_attribute.assert_not_called()

    @patch("nohiki_llm_client.observability.tracing.trace.get_current_span")
    def test_skips_none_values(self, mock_get_span: MagicMock) -> None:
        """Does not set attributes for None values."""
        mock_span = MagicMock()
        mock_span.is_recording.return_value = True
        mock_get_span.return_value = mock_span

        set_llm_span_feedback()

        mock_span.set_attribute.assert_not_called()
