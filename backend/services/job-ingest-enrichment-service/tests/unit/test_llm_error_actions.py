"""Kafka retry classification for LLM failures used by job ingest."""

import pytest
from nohiki_common_exceptions import DataNotFoundError
from nohiki_kafka_client import ErrorAction, classify_error_action
from nohiki_llm_client import (
    LLMConfigurationError,
    LLMContentFilterError,
    LLMError,
    LLMRateLimitError,
    LLMTransientError,
    LLMUsageLimitError,
)


@pytest.mark.parametrize(
    "error_type",
    [LLMContentFilterError, LLMConfigurationError, LLMUsageLimitError],
)
def test_fatal_llm_errors_send_to_dlq(error_type: type[LLMError]) -> None:
    """Fatal LLM failures do not consume the Kafka replay budget."""
    assert classify_error_action(error_type("fatal")) is ErrorAction.SEND_TO_DLQ


def test_transient_llm_error_retries() -> None:
    """Transient LLM failures retain Kafka retry behavior."""
    assert classify_error_action(LLMTransientError("temporary")) is ErrorAction.RETRY
    assert classify_error_action(LLMRateLimitError("rate limited")) is ErrorAction.RETRY


def test_existing_common_error_classification_is_unchanged() -> None:
    """The generic NohikiError branch preserves explicit domain mappings."""
    error = DataNotFoundError(resource_type="Listing", resource_id="listing-1")
    assert classify_error_action(error) is ErrorAction.SEND_TO_DLQ
