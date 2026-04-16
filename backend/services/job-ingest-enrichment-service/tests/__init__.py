"""Tests for job-ingest-enrichment-service.

Environment setup for integration tests happens here, before any conftest.py
files are loaded, ensuring settings are properly configured.
"""

import os

from nohiki_test_utils import get_repo_root


def _configure_test_environment() -> None:
    """Configure environment variables for integration tests."""
    secrets_base = get_repo_root() / "infrastructure" / "secrets"
    openrouter_key_path = secrets_base / "llm" / "provider" / "api_keys" / "openrouter"

    if openrouter_key_path.exists():
        os.environ["SECRETS_DIR"] = "/nonexistent"
        os.environ["JOB_INGEST_ENRICHMENT_LLM__PROVIDER__API_KEYS__OPENROUTER"] = (
            openrouter_key_path.read_text().strip()
        )
        os.environ["JOB_INGEST_ENRICHMENT_LLM__PROVIDER__MODELS__0__MODEL"] = "openrouter:openai/gpt-5-nano"
        os.environ["JOB_INGEST_ENRICHMENT_LLM__INSTRUMENTATION__ENABLED"] = "false"


_configure_test_environment()
