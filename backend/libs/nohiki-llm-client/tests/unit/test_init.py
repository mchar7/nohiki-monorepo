"""Tests for nohiki_llm_client package initialization and lazy imports."""

from __future__ import annotations

import subprocess
import sys

import pytest


def test_root_import_defers_runtime_components() -> None:
    """Root import leaves provider SDKs and evaluations unloaded until first use."""
    script = """
import sys
import nohiki_llm_client

assert "anthropic" not in sys.modules
assert "openai" not in sys.modules
assert "pydantic_evals" not in sys.modules
assert "nohiki_llm_client.client.core" not in sys.modules
assert "nohiki_llm_client.evals" not in sys.modules

assert nohiki_llm_client.LLMClient.__name__ == "LLMClient"
assert "nohiki_llm_client.client.core" in sys.modules
assert nohiki_llm_client.LLMClient is nohiki_llm_client.LLMClient
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_factory_imports_only_selected_provider_sdk() -> None:
    """Model construction imports the selected provider SDK and not its peers."""
    cases = [
        ("openai", "gpt-4o", "anthropic"),
        ("anthropic", "claude-sonnet-4-20250514", "openai"),
    ]
    for provider, model_name, excluded_module in cases:
        script = f"""
import asyncio
import sys
from nohiki_llm_client.config.settings import ApiKeyRegistry, LLMModelConfig, LLMProviderSettings
from nohiki_llm_client.providers.factory import create_model

config = LLMModelConfig(model=\"{provider}:{model_name}\")
settings = LLMProviderSettings(
    models=[config],
    api_keys=ApiKeyRegistry.model_validate({{\"{provider}\": \"test-key\"}}),
)
transports = []
create_model(config, settings, transport_clients=transports)
assert \"{provider}\" in sys.modules
assert \"{excluded_module}\" not in sys.modules
asyncio.run(transports[0].aclose())
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            check=False,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, result.stderr


def test_observability_lazy_surface_resolves_all_exports() -> None:
    """Every observability lazy export resolves and unknown names fail normally."""
    from nohiki_llm_client import observability

    for name in observability._LAZY_IMPORTS:
        assert getattr(observability, name) is not None

    with pytest.raises(AttributeError, match="has no attribute 'NonExistent'"):
        _result = observability.NonExistent


def test_provider_lazy_surface_resolves_all_exports() -> None:
    """Every provider lazy export resolves and unknown names fail normally."""
    from nohiki_llm_client import providers

    for name in providers._LAZY_IMPORTS:
        assert getattr(providers, name) is not None

    with pytest.raises(AttributeError, match="has no attribute 'NonExistent'"):
        _result = providers.NonExistent
