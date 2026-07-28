"""Unit tests for LlamaCppProvider."""

from collections.abc import Mapping
from unittest.mock import MagicMock

import httpx
import pytest
from nohiki_llm_client.providers.llamacpp import LlamaCppProvider
from nohiki_llm_client.transport import LLAMACPP_API_KEY_PLACEHOLDER
from openai import AsyncOpenAI


def _require_profile(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _reject_request(request: httpx.Request) -> httpx.Response:
    pytest.fail(f"Unexpected outbound request: {request.url}")


class TestLlamaCppProviderInit:
    """Tests for LlamaCppProvider initialization."""

    def test_init_uses_explicit_base_and_ignores_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ambient endpoint and credential cannot redirect explicit ownership."""
        monkeypatch.setenv("LLAMACPP_BASE_URL", "https://poisoned.test/v1")
        monkeypatch.setenv("LLAMACPP_API_KEY", "poisoned-secret")

        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")

        assert provider.base_url == "http://localhost:8080/v1"
        assert provider.client.api_key == LLAMACPP_API_KEY_PLACEHOLDER
        assert provider.name == "llamacpp"
        assert isinstance(provider.client, AsyncOpenAI)

    def test_init_requires_explicit_base_despite_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ambient endpoint cannot satisfy the explicit constructor contract."""
        monkeypatch.setenv("LLAMACPP_BASE_URL", "https://poisoned.test/v1")

        with pytest.raises(ValueError, match="base_url"):
            LlamaCppProvider(base_url="")

    @pytest.mark.parametrize("base_url", ["", " ", "\t"])
    def test_init_rejects_blank_explicit_base(self, base_url: str) -> None:
        """Empty and whitespace-only explicit endpoints fail closed."""
        with pytest.raises(ValueError, match="base_url"):
            LlamaCppProvider(base_url=base_url)

    @pytest.mark.parametrize(
        "base_url",
        [
            "localhost:8080/v1",
            "/v1",
            "ftp://localhost/v1",
            "http:///v1",
            "http://user:secret@localhost/v1",
            "http://localhost/v1?token=secret",
            "http://localhost/v1#models",
        ],
    )
    def test_init_rejects_unsafe_explicit_base(self, base_url: str) -> None:
        """Direct construction enforces the same endpoint boundary as settings."""
        with pytest.raises(ValueError, match="base_url"):
            LlamaCppProvider(base_url=base_url)

    def test_init_allows_loopback_http(self) -> None:
        """A local llama.cpp server may intentionally use plain HTTP."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")

        assert provider.base_url == "http://localhost:8080/v1"

    def test_explicit_api_key_wins_over_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Only the explicit per-model credential reaches the SDK client."""
        monkeypatch.setenv("LLAMACPP_API_KEY", "poisoned-secret")

        provider = LlamaCppProvider(
            base_url="http://localhost:8080/v1",
            api_key="model-secret",
        )

        assert provider.client.api_key == "model-secret"

    @pytest.mark.asyncio
    async def test_absent_key_sends_harmless_placeholder_not_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The actual request authenticates with the harmless local placeholder."""
        monkeypatch.setenv("LLAMACPP_API_KEY", "poisoned-secret")

        async def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == "http://localhost:8080/v1/models"
            assert request.headers["Authorization"] == (f"Bearer {LLAMACPP_API_KEY_PLACEHOLDER}")
            return httpx.Response(200, json={"data": []})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            provider = LlamaCppProvider(
                base_url="http://localhost:8080/v1",
                http_client=http_client,
            )
            response = await provider.client.models.list()

        assert response.data == []

    @pytest.mark.asyncio
    async def test_custom_http_client_still_rejects_blank_explicit_base(self) -> None:
        """Supplying transport ownership does not relax endpoint validation."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(_reject_request), timeout=60.0) as http_client:
            with pytest.raises(ValueError, match="base_url"):
                LlamaCppProvider(base_url="", http_client=http_client)

    @pytest.mark.asyncio
    async def test_init_with_custom_http_client(self) -> None:
        """Provider accepts a custom client alongside an explicit endpoint."""
        async with httpx.AsyncClient(transport=httpx.MockTransport(_reject_request), timeout=60.0) as http_client:
            provider = LlamaCppProvider(
                base_url="http://localhost:8080/v1",
                http_client=http_client,
            )

            assert provider.client._client == http_client

    @pytest.mark.parametrize(
        "client_base_url",
        [
            "relative/v1",
            "ftp://gateway.test/v1",
            "http:///v1",
            "http://user:secret@gateway.test/v1",
            "http://gateway.test/v1?token=secret",
            "http://gateway.test/v1#models",
            "http://gateway.test:99999/v1",
        ],
    )
    def test_prebuilt_client_rejects_unsafe_actual_base(self, client_base_url: str) -> None:
        """A prebuilt SDK client cannot bypass endpoint validation."""
        openai_client = MagicMock(spec=AsyncOpenAI)
        openai_client.base_url = client_base_url

        with pytest.raises(ValueError, match=r"base_url|client"):
            LlamaCppProvider(
                base_url="https://gateway.test/v1",
                openai_client=openai_client,
            )

    def test_prebuilt_client_rejects_mismatched_explicit_base(self) -> None:
        """Explicit and prebuilt-client endpoints must identify the same server."""
        openai_client = AsyncOpenAI(
            base_url="https://other-gateway.test/v1",
            api_key="custom-key",
        )

        with pytest.raises(ValueError, match=r"base_url|match"):
            LlamaCppProvider(
                base_url="https://gateway.test/v1",
                openai_client=openai_client,
            )

    def test_prebuilt_client_accepts_normalized_equal_base(self) -> None:
        """SDK trailing-slash normalization does not create a false mismatch."""
        openai_client = AsyncOpenAI(
            base_url="https://gateway.test/internal/v1/",
            api_key="custom-key",
        )

        provider = LlamaCppProvider(
            base_url="https://gateway.test/internal/v1",
            openai_client=openai_client,
        )

        assert provider.client is openai_client
        assert provider.base_url == "https://gateway.test/internal/v1/"

    def test_init_with_openai_client(self) -> None:
        """Provider accepts a pre-configured client with explicit endpoint ownership."""
        openai_client = AsyncOpenAI(
            base_url="http://custom:8080/v1",
            api_key="custom-key",
        )
        provider = LlamaCppProvider(
            base_url="http://custom:8080/v1",
            openai_client=openai_client,
        )

        assert provider.client == openai_client
        assert provider.base_url == "http://custom:8080/v1/"


class TestLlamaCppProviderProperties:
    """Tests for LlamaCppProvider properties."""

    def test_name_returns_llamacpp(self) -> None:
        """Provider name is 'llamacpp'."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        assert provider.name == "llamacpp"

    def test_base_url_returns_configured_url(self) -> None:
        """base_url property returns the configured URL."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        assert provider.base_url == "http://localhost:8080/v1"

    def test_client_returns_async_openai_instance(self) -> None:
        """Client property returns AsyncOpenAI instance."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        assert isinstance(provider.client, AsyncOpenAI)


class TestLlamaCppProviderModelProfile:
    """Tests for LlamaCppProvider.model_profile."""

    def test_model_profile_sets_reasoning_content_field(self) -> None:
        """model_profile configures reasoning_content as thinking field."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        profile = _require_profile(provider.model_profile("model.gguf"))
        assert profile["openai_chat_thinking_field"] == "reasoning_content"

    def test_model_profile_sets_send_back_thinking_parts(self) -> None:
        """model_profile configures 'field' for send_back_thinking_parts."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        profile = _require_profile(provider.model_profile("model.gguf"))
        assert profile["openai_chat_send_back_thinking_parts"] == "field"

    def test_model_profile_disables_strict_tool_definition(self) -> None:
        """model_profile disables strict tool definition support."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        profile = _require_profile(provider.model_profile("model.gguf"))
        assert profile["openai_supports_strict_tool_definition"] is False

    def test_model_profile_enables_json_object_output(self) -> None:
        """model_profile enables JSON object output support."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        profile = _require_profile(provider.model_profile("model.gguf"))
        assert profile["supports_json_object_output"] is True

    def test_model_profile_same_for_all_models(self) -> None:
        """model_profile returns same profile regardless of model name."""
        provider = LlamaCppProvider(base_url="http://localhost:8080/v1")
        profile1 = _require_profile(provider.model_profile("model-a.gguf"))
        profile2 = _require_profile(provider.model_profile("model-b.gguf"))
        assert profile1["openai_chat_thinking_field"] == profile2["openai_chat_thinking_field"]
        assert profile1["openai_chat_send_back_thinking_parts"] == profile2["openai_chat_send_back_thinking_parts"]
