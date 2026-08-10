"""Unit tests for RobustOpenRouterModel and OpenRouter error extraction helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from nohiki_llm_client.providers.openrouter import (
    RobustOpenRouterModel,
    _EmbeddedRateLimitError,
    _maybe_raise_embedded_error,
)
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError


class TestMaybeRaiseEmbeddedError:
    """Tests for _maybe_raise_embedded_error helper."""

    def test_raises_model_http_error_with_error_dict(self) -> None:
        """Extracts code and message from embedded error dict and raises ModelHTTPError."""
        raw: dict[str, object] = {
            "id": None,
            "error": {"code": 404, "message": "No endpoints found"},
        }
        with pytest.raises(ModelHTTPError) as exc_info:
            _maybe_raise_embedded_error(raw, model_name="test/model")
        assert exc_info.value.status_code == 404
        assert exc_info.value.body == "No endpoints found"
        assert exc_info.value.model_name == "test/model"

    @pytest.mark.parametrize(
        ("code", "expected_status"),
        [
            pytest.param(404, 404, id="integer"),
            pytest.param("429", 429, id="numeric-string"),
            pytest.param("not-a-code", 500, id="nonnumeric-string"),
            pytest.param(None, 500, id="null"),
            pytest.param(True, 500, id="bool"),
            pytest.param(404.5, 500, id="float"),
            pytest.param({"status": 404}, 500, id="object"),
            pytest.param([404], 500, id="list"),
            pytest.param(99, 500, id="out-of-range-low"),
            pytest.param(600, 500, id="out-of-range-high"),
        ],
    )
    def test_code_values_raise_typed_provider_error_without_raw_conversion_exception(
        self, code: object, expected_status: int
    ) -> None:
        """Malformed codes use the generic provider status; valid codes are preserved."""
        raw: dict[str, object] = {
            "error": {"code": code, "message": "Provider failure"},
        }
        with pytest.raises(ModelHTTPError) as exc_info:
            _maybe_raise_embedded_error(raw, model_name="test/model")
        assert exc_info.value.status_code == expected_status
        assert exc_info.value.body == "Provider failure"

    def test_uses_fallback_status_when_code_missing(self) -> None:
        """Falls back to 500 when error dict has no 'code' key."""
        raw: dict[str, object] = {"error": {"message": "Unknown"}}
        with pytest.raises(ModelHTTPError) as exc_info:
            _maybe_raise_embedded_error(raw, model_name="test/model")
        assert exc_info.value.status_code == 500

    def test_uses_fallback_message_when_message_missing(self) -> None:
        """Falls back to generic message when error dict has no 'message' key."""
        raw: dict[str, object] = {"error": {"code": 503}}
        with pytest.raises(ModelHTTPError) as exc_info:
            _maybe_raise_embedded_error(raw, model_name="test/model")
        assert exc_info.value.body == "Unknown provider error"

    def test_no_raise_when_error_field_absent(self) -> None:
        """Does not raise when there is no 'error' key."""
        raw: dict[str, object] = {"id": None, "choices": None}
        _maybe_raise_embedded_error(raw, model_name="test/model")

    def test_no_raise_when_error_not_dict(self) -> None:
        """Does not raise when 'error' is not a dict (e.g., None or string)."""
        raw_none: dict[str, object] = {"error": None}
        _maybe_raise_embedded_error(raw_none, model_name="test/model")
        raw_str: dict[str, object] = {"error": "some error string"}
        _maybe_raise_embedded_error(raw_str, model_name="test/model")

    @pytest.mark.parametrize(
        ("raw", "expected", "why"),
        [
            pytest.param({"error": {"code": 429, "message": "slow down", "retry_after": 12}}, 12.0, "error field"),
            pytest.param(
                {"error": {"code": 429, "message": "slow down", "metadata": {"headers": {"Retry-After": "34"}}}},
                34.0,
                "nested metadata headers",
            ),
            pytest.param({"error": {"code": 429, "message": "slow down"}, "retry_after": "56"}, 56.0, "top level"),
            pytest.param({"error": {"code": 429, "message": "slow down"}}, None, "no hint anywhere"),
        ],
    )
    def test_body_embedded_retry_hint_reaches_the_library_property(
        self, raw: dict[str, object], expected: float | None, why: str
    ) -> None:
        """A retry hint found in an HTTP-200 body is readable via ``ModelHTTPError.retry_after``.

        PydanticAI owns ``retry_after`` as a read-only property over the ``Retry-After``
        response header, which an HTTP-200 body does not have. Nohiki recovers the hint from
        the JSON body, which the library does not do, and must inject it as a header for the
        property to return it. Without that injection the hint is silently lost and
        ``LLMClient`` falls back to blind exponential backoff.
        """
        with pytest.raises(_EmbeddedRateLimitError) as exc_info:
            _maybe_raise_embedded_error(raw, model_name="test/model")
        assert exc_info.value.retry_after == expected, why


class TestRobustOpenRouterModelValidateCompletion:
    """Tests for RobustOpenRouterModel._validate_completion."""

    def _make_model(self) -> RobustOpenRouterModel:
        """Create a RobustOpenRouterModel with a mocked provider."""
        mock_provider = MagicMock()
        mock_provider.name = "openrouter"
        return RobustOpenRouterModel("test/model", provider=mock_provider)

    def test_null_field_response_with_error_raises_model_http_error(self) -> None:
        """Null-field response with embedded error raises ModelHTTPError before validation."""
        model = self._make_model()
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": None,
            "choices": None,
            "model": None,
            "object": None,
            "error": {"code": 404, "message": "No endpoints found matching your data policy"},
        }
        with pytest.raises(ModelHTTPError) as exc_info:
            model._validate_completion(mock_response)
        assert exc_info.value.status_code == 404

    def test_null_field_response_without_error_delegates_to_super(self) -> None:
        """Without an embedded error, classification is the library's.

        PydanticAI recognises a body with null ``choices`` and no error envelope and raises
        ``ModelAPIError`` for it, so the wrapper must delegate rather than pre-empt. This
        pins delegation, not the library's choice of message.
        """
        model = self._make_model()
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {
            "id": None,
            "choices": None,
            "model": None,
            "object": None,
        }
        with pytest.raises(ModelAPIError) as exc_info:
            model._validate_completion(mock_response)
        assert not isinstance(exc_info.value, ModelHTTPError)
