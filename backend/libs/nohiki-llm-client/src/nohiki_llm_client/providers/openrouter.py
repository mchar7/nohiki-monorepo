"""OpenRouter model that closes the embedded-error extraction gap.

PydanticAI's ``OpenRouterModel._validate_completion`` already extracts embedded
errors via ``if error := response.error: raise ModelHTTPError(...)``. However,
when OpenRouter returns HTTP 200 with ``choices: null`` (e.g. data-policy routing
failures), Pydantic validation raises ``ValidationError`` *before* that check runs,
and the error details are lost: the caller gets a generic
``UnexpectedModelBehavior`` instead of a typed ``ModelHTTPError``.

``RobustOpenRouterModel`` calls ``_maybe_raise_embedded_error`` before delegating
to the parent, so the embedded error is surfaced as ``ModelHTTPError`` with the
real status code regardless of field nullity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, override

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openrouter import OpenRouterModel, _OpenRouterChatCompletion

from nohiki_llm_client.config.constants import HTTP_STATUS_RATE_LIMIT

if TYPE_CHECKING:
    from openai.types import chat

_FALLBACK_ERROR_STATUS: int = 500
_MIN_HTTP_STATUS: int = 100
_MAX_HTTP_STATUS: int = 599
_FALLBACK_ERROR_MESSAGE: str = "Unknown provider error"


class RobustOpenRouterModel(OpenRouterModel):
    """OpenRouter model that surfaces embedded errors before Pydantic validation.

    When OpenRouter encounters a routing failure (e.g. data-policy block, model
    not found), it returns HTTP 200 with ``choices: null`` and embeds the real
    error in the response as ``{"error": {"code": 404, "message": "..."}}``.
    The base ``OpenRouterModel._validate_completion`` raises ``UnexpectedModelBehavior``
    because ``choices: null`` fails Pydantic validation before the ``error`` field
    check is reached.

    This subclass calls ``_maybe_raise_embedded_error`` first, so
    ``LLMClient._single_attempt`` receives a typed ``ModelHTTPError`` with the
    actual status code rather than a generic ``UnexpectedModelBehavior``.
    """

    @override
    def _validate_completion(self, response: chat.ChatCompletion) -> _OpenRouterChatCompletion:
        """Extract embedded errors before delegating to parent validation.

        Calls ``_maybe_raise_embedded_error`` first, which is a no-op for any
        response whose ``error`` field is ``null`` or absent. When OpenRouter
        embeds a real error (e.g. ``{"code": 404, ...}``) in a response that
        would otherwise fail Pydantic validation, the error is
        surfaced as a typed ``ModelHTTPError`` rather than lost in an
        ``UnexpectedModelBehavior``.

        Args:
            response: Raw ChatCompletion from the OpenAI client.

        Returns:
            Validated ``_OpenRouterChatCompletion`` instance.

        Raises:
            ModelHTTPError: When the response contains an embedded ``error`` object.
        """
        _maybe_raise_embedded_error(response.model_dump(), model_name=self.model_name)
        return super()._validate_completion(response)


def _maybe_raise_embedded_error(raw: dict[str, object], *, model_name: str) -> None:
    """Extract and raise a ``ModelHTTPError`` if an embedded error object is present.

    This is a no-op when ``raw["error"]`` is absent, ``null``, or not a dict.

    Args:
        raw: Serialised response dict (from ``response.model_dump()``).
        model_name: Model name forwarded to ``ModelHTTPError``.

    Raises:
        ModelHTTPError: When a valid ``error`` dict is found in the response.
    """
    error_data = raw.get("error")
    if not isinstance(error_data, dict):
        return
    # Cast after isinstance check to give ty concrete key/value types for .get() calls.
    typed: dict[str, object] = cast("dict[str, object]", error_data)
    code_val: object = typed.get("code", _FALLBACK_ERROR_STATUS)
    msg_val: object = typed.get("message", _FALLBACK_ERROR_MESSAGE)
    status_code = _parse_error_status(code_val)
    message = str(msg_val) if isinstance(msg_val, str) else _FALLBACK_ERROR_MESSAGE
    if status_code == HTTP_STATUS_RATE_LIMIT:
        raise _EmbeddedRateLimitError(
            model_name=model_name,
            message=message,
            retry_after=_extract_retry_after(typed, raw),
        )
    raise ModelHTTPError(status_code=status_code, model_name=model_name, body=message)


class _EmbeddedRateLimitError(ModelHTTPError):
    """Model error for a rate limit embedded in an HTTP-200 response.

    PydanticAI owns ``retry_after`` as a read-only property that parses the ``Retry-After``
    response header. An HTTP-200 body carries no such header, so the hint recovered from the
    body is injected as one and read back through the library's own property rather than
    shadowed by an attribute.
    """

    def __init__(self, *, model_name: str, message: str, retry_after: int | None) -> None:
        super().__init__(
            status_code=HTTP_STATUS_RATE_LIMIT,
            model_name=model_name,
            body=message,
            headers=None if retry_after is None else {"retry-after": str(retry_after)},
        )


def _extract_retry_after(error_data: dict[str, object], raw: dict[str, object]) -> int | None:
    """Extract a non-negative integer retry hint from an embedded error payload."""
    candidates: list[object] = [error_data.get("retry_after"), error_data.get("retry-after")]
    metadata = error_data.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend([metadata.get("retry_after"), metadata.get("retry-after")])
        headers = metadata.get("headers")
        if isinstance(headers, dict):
            candidates.extend(value for key, value in headers.items() if str(key).lower() == "retry-after")
    candidates.extend([raw.get("retry_after"), raw.get("retry-after")])
    for value in candidates:
        parsed = _parse_retry_after(value)
        if parsed is not None:
            return parsed
    return None


def _parse_retry_after(value: object) -> int | None:
    """Parse a non-negative seconds retry hint, ignoring malformed values."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _parse_error_status(value: object) -> int:
    """Return a valid HTTP status code or the generic provider fallback."""
    if isinstance(value, bool):
        return _FALLBACK_ERROR_STATUS
    if isinstance(value, int):
        return value if _MIN_HTTP_STATUS <= value <= _MAX_HTTP_STATUS else _FALLBACK_ERROR_STATUS
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return _FALLBACK_ERROR_STATUS
        return parsed if _MIN_HTTP_STATUS <= parsed <= _MAX_HTTP_STATUS else _FALLBACK_ERROR_STATUS
    return _FALLBACK_ERROR_STATUS
