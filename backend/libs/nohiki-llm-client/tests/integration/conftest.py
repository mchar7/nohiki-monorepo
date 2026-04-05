"""Integration test fixtures for nohiki-llm-client.

Configures pytest to handle integration tests with real Ollama server.
"""

from __future__ import annotations

import pytest

# Mark all tests in this directory as integration tests
pytestmark = pytest.mark.integration
