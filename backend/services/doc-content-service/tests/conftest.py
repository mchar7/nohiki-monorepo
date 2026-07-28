"""Test configuration and fixtures for doc-content-service (stateless)."""

import os
from collections.abc import Generator

os.environ["TEST_MODE"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ["TESTING"] = "true"

os.environ["DOC_CONTENT_KAFKA__BOOTSTRAP_SERVERS"] = "localhost:29092"

os.environ["DOC_CONTENT_S3__ENDPOINT"] = "http://localhost:9000"
os.environ["DOC_CONTENT_S3__ACCESS_KEY"] = "test"
os.environ["DOC_CONTENT_S3__SECRET_KEY"] = "test"
os.environ["DOC_CONTENT_S3__BUCKET"] = "test-bucket"

os.environ["DOC_CONTENT_LLM__PROVIDER__MODELS__0__MODEL"] = "openai:gpt-4o-mini"
os.environ["DOC_CONTENT_LLM__PROVIDER__MODELS__0__REASONING_EFFORT"] = "low"
os.environ["DOC_CONTENT_LLM__CHAINS__DOC_TAILORING__MODELS__0__MODEL"] = "openai:gpt-5.6-sol"
os.environ["DOC_CONTENT_LLM__CHAINS__DOC_TAILORING__MODELS__0__REASONING_EFFORT"] = "high"
os.environ["DOC_CONTENT_LLM__PROVIDER__API_KEYS__OPENAI"] = "test-key"


import pytest
from nohiki_test_utils import setup_test_secrets

__all__ = ["setup_test_secrets"]


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Generator[None]:
    """Reset settings cache between tests."""
    from doc_content_service.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
