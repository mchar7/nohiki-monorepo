"""Unit tests for LLM health probe."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest
from nohiki_llm_client.config.settings import (
    ApiKeyRegistry,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    ReasoningEffort,
)
from nohiki_llm_client.observability.health import (
    HTTP_OK,
    HTTP_UNAUTHORIZED,
    LLMHealthProbe,
    ensure_llm_ready,
)
from nohiki_llm_client.providers.factory import create_model as create_real_model
from nohiki_llm_client.transport import (
    LLAMACPP_API_KEY_PLACEHOLDER,
    OLLAMA_API_KEY_PLACEHOLDER,
    OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER,
)
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def _stub_exact_model_inference() -> object:
    """Keep endpoint-focused tests isolated from the inference readiness phase."""
    model = MagicMock()
    model.request = AsyncMock(return_value=MagicMock())
    with patch("nohiki_llm_client.observability.health.create_model", return_value=model):
        yield


@pytest.fixture
def openai_settings() -> LLMSettings:
    """OpenAI settings for cloud endpoint tests."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="openai:gpt-4o")],
            api_keys=ApiKeyRegistry.model_validate({"openai": "test-api-key"}),
        )
    )


@pytest.fixture
def ollama_settings() -> LLMSettings:
    """Ollama settings for local provider tests."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[
                LLMModelConfig(
                    model="ollama:llama3",
                    base_url="http://localhost:11434/v1",
                )
            ],
            api_keys=ApiKeyRegistry.model_validate({}),
        )
    )


@pytest.fixture
def mock_settings() -> LLMSettings:
    """Create mock LLMSettings with OpenAI as highest-priority model."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="openai:gpt-4o")],
            api_keys=ApiKeyRegistry.model_validate({"openai": "test-api-key"}),
        )
    )


class TestLLMHealthProbeInit:
    """Tests for LLMHealthProbe initialization."""

    def test_init_stores_settings(self, mock_settings: LLMSettings) -> None:
        """Test that init stores settings."""
        probe = LLMHealthProbe(mock_settings, chains=None)
        assert probe._settings is mock_settings

    def test_init_default_timeout(self, mock_settings: LLMSettings) -> None:
        """Test default timeout value."""
        probe = LLMHealthProbe(mock_settings, chains=None)
        assert probe._timeout_seconds == pytest.approx(10.0)

    def test_init_custom_timeout(self, mock_settings: LLMSettings) -> None:
        """Test custom timeout value."""
        probe = LLMHealthProbe(mock_settings, chains=None, timeout_seconds=30.0)
        assert probe._timeout_seconds == pytest.approx(30.0)

    def test_name_property(self, mock_settings: LLMSettings) -> None:
        """Test name property returns 'llm'."""
        probe = LLMHealthProbe(mock_settings, chains=None)
        assert probe.name == "llm"


class TestLLMHealthProbeCheck:
    """Tests for LLMHealthProbe.check() method."""

    @pytest.mark.asyncio
    async def test_check_openai_success(self, mock_settings: LLMSettings) -> None:
        """Test successful OpenAI health check."""
        mock_response = MagicMock()
        mock_response.status_code = HTTP_OK

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(mock_settings, chains=None)
            result = await probe.check()

            assert result.is_healthy()
            assert "openai" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_openrouter_success(self) -> None:
        """Test successful OpenRouter health check."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openrouter:google/gemini-pro")],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
            )
        )
        mock_response = MagicMock()
        mock_response.status_code = HTTP_OK

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(settings, chains=None)
            result = await probe.check()

            assert result.is_healthy()
            assert "openrouter" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_ollama_success(self) -> None:
        """Test successful Ollama health check."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="ollama:llama3",
                        base_url="http://localhost:11434/v1",
                    )
                ],
            )
        )
        mock_response = MagicMock()
        mock_response.status_code = HTTP_OK

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(settings, chains=None)
            result = await probe.check()

            assert result.is_healthy()
            assert "ollama" in result.message.lower()
            # Verify URL was correctly transformed from /v1 to /api/tags
            call_args = mock_client.return_value.__aenter__.return_value.get.call_args
            assert call_args[0][0] == "http://localhost:11434/api/tags"

    @pytest.mark.asyncio
    async def test_check_unauthorized_returns_unhealthy(self, mock_settings: LLMSettings) -> None:
        """Test that unauthorized response returns unhealthy."""
        mock_response = MagicMock()
        mock_response.status_code = HTTP_UNAUTHORIZED

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(mock_settings, chains=None)
            result = await probe.check()

            assert not result.is_healthy()
            assert "invalid" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_timeout_returns_unhealthy(self, mock_settings: LLMSettings) -> None:
        """Test that timeout returns unhealthy result."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(side_effect=httpx.TimeoutException("Timeout")))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(mock_settings, chains=None)
            result = await probe.check()

            assert not result.is_healthy()
            assert "timeout" in result.message.lower()


class TestResolveHealthApiKey:
    """Tests for _resolve_health_api_key method."""

    def test_explicit_model_key_preferred(self) -> None:
        """Per-model api_key takes precedence over registry for health checks."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openai:gpt-4o", api_key=SecretStr("model-key"))],
                api_keys=ApiKeyRegistry.model_validate({"openai": "registry-key"}),
            )
        )
        probe = LLMHealthProbe(settings, chains=None)
        result = probe._resolve_health_api_key(settings.provider.models[0])
        assert result == "model-key"

    def test_registry_key_used_when_no_model_key(self, openai_settings: LLMSettings) -> None:
        """Registry key is used when model has no explicit key."""
        probe = LLMHealthProbe(openai_settings, chains=None)
        result = probe._resolve_health_api_key(openai_settings.provider.models[0])
        assert result == "test-api-key"

    def test_returns_none_when_no_key_available(self) -> None:
        """Returns None when neither model nor registry has a key."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="ollama:llama3", base_url="http://localhost:11434/v1")],
            )
        )
        probe = LLMHealthProbe(settings, chains=None)
        config = LLMModelConfig(model="customai:model")
        result = probe._resolve_health_api_key(config)
        assert result is None


class TestLLMHealthProbeEdgeCases:
    """Tests for edge cases and error paths in LLMHealthProbe."""

    @pytest.mark.asyncio
    async def test_check_unsupported_provider_returns_unhealthy(self) -> None:
        """Unknown provider with no registered health endpoint returns unhealthy."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="customai:some-model")],
                api_keys=ApiKeyRegistry.model_validate({"customai": "key"}),
            )
        )
        probe = LLMHealthProbe(settings, chains=None)
        result = await probe.check()

        assert not result.is_healthy()
        assert "customai" in result.message

    @pytest.mark.asyncio
    async def test_check_timeout_error_returns_unhealthy(self, openai_settings: LLMSettings) -> None:
        """TimeoutError from asyncio.timeout propagation returns unhealthy."""
        probe = LLMHealthProbe(openai_settings, chains=None)
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            side_effect=TimeoutError("timed out"),
        ):
            result = await probe.check()

        assert not result.is_healthy()
        assert "timeout" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_os_error_returns_unhealthy(self, openai_settings: LLMSettings) -> None:
        """OSError from the provider check is caught and returned as unhealthy."""
        probe = LLMHealthProbe(openai_settings, chains=None)
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            side_effect=OSError("connection refused"),
        ):
            result = await probe.check()

        assert not result.is_healthy()
        assert "connection" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_unexpected_exception_returns_unhealthy(self, openai_settings: LLMSettings) -> None:
        """Unexpected exceptions are caught and returned as unhealthy without propagating."""
        probe = LLMHealthProbe(openai_settings, chains=None)
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            side_effect=ValueError("unexpected"),
        ):
            result = await probe.check()

        assert not result.is_healthy()
        assert "unexpected" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_cloud_unknown_status_returns_unhealthy(self, openai_settings: LLMSettings) -> None:
        """Non-200/non-401 status triggers the else branch and returns unhealthy."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(openai_settings, chains=None)
            ok, err = await probe._check_cloud_endpoint(
                "https://api.openai.com/v1/models",
                headers={"Authorization": "Bearer test-key"},
            )

        assert ok is False
        assert "503" in (err or "")

    @pytest.mark.asyncio
    async def test_check_cloud_os_error_returns_failure(self, openai_settings: LLMSettings) -> None:
        """OSError during HTTP call in _check_cloud_endpoint returns failure tuple."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(side_effect=OSError("connection refused")))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(openai_settings, chains=None)
            ok, err = await probe._check_cloud_endpoint(
                "https://api.openai.com/v1/models",
                headers={"Authorization": "Bearer test-key"},
            )

        assert ok is False
        assert "connection" in (err or "").lower()

    @pytest.mark.asyncio
    async def test_check_ollama_no_base_url_returns_failure(self) -> None:
        """Ollama config with no base_url returns a failure tuple immediately."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="ollama:llama3",
                        base_url="http://localhost:11434/v1",
                    )
                ],
            )
        )
        probe = LLMHealthProbe(settings, chains=None)
        config = MagicMock()
        config.base_url = None

        ok, err = await probe._check_ollama(config)

        assert ok is False
        assert "base_url" in (err or "").lower()

    @pytest.mark.asyncio
    async def test_check_ollama_os_error_returns_failure(self, ollama_settings: LLMSettings) -> None:
        """OSError during Ollama HTTP call returns failure tuple."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(side_effect=OSError("connection refused")))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(ollama_settings, chains=None)
            ok, err = await probe._check_ollama(ollama_settings.provider.models[0])

        assert ok is False
        assert "ollama" in (err or "").lower()

    @pytest.mark.asyncio
    async def test_check_ollama_unexpected_exception_returns_failure(self, ollama_settings: LLMSettings) -> None:
        """Unexpected exception during Ollama check is caught and returned as failure."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(side_effect=ValueError("unexpected")))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(ollama_settings, chains=None)
            ok, err = await probe._check_ollama(ollama_settings.provider.models[0])

        assert ok is False
        assert "unexpected" in (err or "").lower()

    @pytest.mark.asyncio
    async def test_check_ollama_non_200_status_returns_failure(self, ollama_settings: LLMSettings) -> None:
        """Non-200 Ollama response triggers the else branch and returns failure."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(ollama_settings, chains=None)
            ok, err = await probe._check_ollama(ollama_settings.provider.models[0])

        assert ok is False
        assert "503" in (err or "")


@pytest.fixture
def anthropic_settings() -> LLMSettings:
    """Anthropic settings for direct API health tests."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-anthropic-key"}),
        )
    )


@pytest.fixture
def anthropic_proxy_settings() -> LLMSettings:
    """Anthropic settings with custom base_url for proxy health tests."""
    return LLMSettings(
        provider=LLMProviderSettings(
            models=[
                LLMModelConfig(
                    model="anthropic:claude-sonnet-4-20250514",
                    base_url="https://anthropic.example.com",
                )
            ],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "proxy-key"}),
        )
    )


class TestResolveHealthUrl:
    """Tests for _resolve_health_url module-level helper."""

    def test_anthropic_default_endpoint(self) -> None:
        """Anthropic without base_url returns the default API endpoint."""
        from nohiki_llm_client.observability.health import _resolve_health_url

        url = _resolve_health_url("anthropic", None)
        assert url == "https://api.anthropic.com/v1/models"

    def test_anthropic_custom_base_url(self) -> None:
        """Anthropic with base_url appends /v1/models (SDK convention: base_url excludes /v1)."""
        from nohiki_llm_client.observability.health import _resolve_health_url

        url = _resolve_health_url("anthropic", "https://anthropic.example.com")
        assert url == "https://anthropic.example.com/v1/models"

    def test_openai_custom_base_url(self) -> None:
        """OpenAI-compatible with base_url appends /models (base_url includes /v1)."""
        from nohiki_llm_client.observability.health import _resolve_health_url

        url = _resolve_health_url("openai", "http://localhost:8080/v1")
        assert url == "http://localhost:8080/v1/models"

    def test_unknown_provider_no_base_url_returns_none(self) -> None:
        """Unknown provider without base_url returns None."""
        from nohiki_llm_client.observability.health import _resolve_health_url

        assert _resolve_health_url("unknown", None) is None

    def test_strips_trailing_slash(self) -> None:
        """Trailing slashes are stripped from base_url before appending path."""
        from nohiki_llm_client.observability.health import _resolve_health_url

        url = _resolve_health_url("anthropic", "https://anthropic.example.com/")
        assert url == "https://anthropic.example.com/v1/models"


class TestOpenAICompatibleHealthCheck:
    """Health checks honor a custom OpenAI-compatible endpoint and credentials."""

    @pytest.mark.asyncio
    async def test_custom_base_url_and_registry_key_are_used(self) -> None:
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="openai:test-model",
                        base_url="https://llm-gateway.example.com/v1",
                    )
                ],
                api_keys=ApiKeyRegistry.model_validate({"openai": "registry-test-key"}),
            )
        )
        response = MagicMock(status_code=HTTP_OK)

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await LLMHealthProbe(settings).check()

        assert result.is_healthy()
        mock_get.assert_awaited_once_with(
            "https://llm-gateway.example.com/v1/models",
            headers={"Authorization": "Bearer registry-test-key"},
        )


class TestBuildAuthHeaders:
    """Tests for _build_auth_headers module-level helper."""

    def test_anthropic_uses_required_versioned_key_headers(self) -> None:
        """Anthropic model discovery sends its exact required auth headers."""
        from nohiki_llm_client.observability.health import _build_auth_headers

        assert _build_auth_headers("anthropic", "test-key") == {
            "anthropic-version": "2023-06-01",
            "x-api-key": "test-key",
        }

    def test_openai_uses_bearer(self) -> None:
        """Non-Anthropic providers use Authorization: Bearer format."""
        from nohiki_llm_client.observability.health import _build_auth_headers

        headers = _build_auth_headers("openai", "test-key")
        assert headers == {"Authorization": "Bearer test-key"}

    def test_openrouter_uses_bearer(self) -> None:
        """OpenRouter uses standard Authorization: Bearer format."""
        from nohiki_llm_client.observability.health import _build_auth_headers

        headers = _build_auth_headers("openrouter", "test-key")
        assert headers == {"Authorization": "Bearer test-key"}

    def test_no_api_key_returns_empty(self) -> None:
        """No API key returns empty headers dict."""
        from nohiki_llm_client.observability.health import _build_auth_headers

        assert _build_auth_headers("anthropic", None) == {}


class TestAnthropicHealthCheck:
    """Tests for Anthropic provider health check integration."""

    @pytest.mark.asyncio
    async def test_check_anthropic_success(self, anthropic_settings: LLMSettings) -> None:
        """Successful Anthropic health check returns healthy result."""
        mock_response = MagicMock()
        mock_response.status_code = HTTP_OK

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(anthropic_settings, chains=None)
            result = await probe.check()

            assert result.is_healthy()
            assert "anthropic" in result.message.lower()

    @pytest.mark.asyncio
    async def test_anthropic_uses_x_api_key_header(self, anthropic_settings: LLMSettings) -> None:
        """Anthropic health check sends x-api-key header, not Authorization: Bearer."""
        mock_response = MagicMock()
        mock_response.status_code = HTTP_OK

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(anthropic_settings, chains=None)
            await probe.check()

            headers = mock_get.call_args.kwargs["headers"]
            assert headers == {
                "anthropic-version": "2023-06-01",
                "x-api-key": "test-anthropic-key",
            }

    @pytest.mark.asyncio
    async def test_anthropic_custom_base_url_health_endpoint(self, anthropic_proxy_settings: LLMSettings) -> None:
        """Anthropic with custom base_url constructs health URL from base_url/v1/models."""
        mock_response = MagicMock()
        mock_response.status_code = HTTP_OK

        with patch("httpx.AsyncClient") as mock_client:
            mock_get = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock(get=mock_get))
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            probe = LLMHealthProbe(anthropic_proxy_settings, chains=None)
            result = await probe.check()

            assert result.is_healthy()
            call_url = mock_get.call_args[0][0]
            assert call_url == "https://anthropic.example.com/v1/models"


class TestModelScopedHealthTransport:
    """Tests for explicit gateway health routing and model-scoped trust."""

    @pytest.mark.asyncio
    async def test_explicit_health_precedes_provider_endpoint_without_credentials(
        self,
    ) -> None:
        """Gateway readiness is explicit, unauthenticated, and model-scoped."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="openrouter:test/model",
                        base_url="https://gateway.test/openrouter/v1",
                        health_url="https://gateway.test/healthz",
                        tls_ca_file="/run/model-ca/ca.crt",
                    )
                ],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "provider-secret"}),
            )
        )
        probe = LLMHealthProbe(settings, chains=None)

        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await probe.check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://gateway.test/healthz",
            headers={},
            tls_ca_file="/run/model-ca/ca.crt",
        )

    @pytest.mark.asyncio
    async def test_provider_health_fallback_keeps_derived_url_and_credentials(
        self,
    ) -> None:
        """Absent an override, provider-derived health retains provider authentication."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="openrouter:test/model",
                        base_url="https://gateway.test/openrouter/v1",
                        tls_ca_file="/run/model-ca/ca.crt",
                    )
                ],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "provider-secret"}),
            )
        )
        probe = LLMHealthProbe(settings, chains=None)

        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await probe.check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://gateway.test/openrouter/v1/models",
            headers={"Authorization": "Bearer provider-secret"},
            tls_ca_file="/run/model-ca/ca.crt",
        )

    @pytest.mark.parametrize("tls_ca_file", ["/run/model-ca/ca.crt", None])
    def test_health_client_uses_only_explicit_trust_roots(
        self,
        tls_ca_file: str | None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Health pins public trust and optionally augments it with the model CA."""
        from nohiki_llm_client.observability.health import _create_health_http_client

        monkeypatch.setenv("SSL_CERT_FILE", "/poisoned/attacker-ca.pem")
        monkeypatch.setenv("SSL_CERT_DIR", "/poisoned/attacker-ca-dir")
        context = MagicMock()
        client = MagicMock()

        with (
            patch(
                "nohiki_llm_client.transport.certifi.where",
                return_value="/certifi/cacert.pem",
            ),
            patch(
                "nohiki_llm_client.transport.ssl.create_default_context",
                return_value=context,
            ) as create_context,
            patch(
                "nohiki_llm_client.observability.health.httpx.AsyncClient",
                return_value=client,
            ) as async_client,
        ):
            result = _create_health_http_client(4.5, tls_ca_file)

        assert result is client
        create_context.assert_called_once_with(cafile="/certifi/cacert.pem")
        if tls_ca_file is None:
            context.load_verify_locations.assert_not_called()
        else:
            context.load_verify_locations.assert_called_once_with(cafile=tls_ca_file)
        async_client.assert_called_once_with(timeout=4.5, verify=context)

    @pytest.mark.asyncio
    async def test_ollama_health_uses_model_scoped_ca(self) -> None:
        """The keyless provider path does not bypass model-scoped TLS trust."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="ollama:llama3",
                        base_url="https://ollama.test/v1",
                        tls_ca_file="/run/model-ca/ca.crt",
                    )
                ]
            )
        )
        response = MagicMock(status_code=HTTP_OK)
        owned_client = MagicMock(get=AsyncMock(return_value=response))
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=owned_client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "nohiki_llm_client.observability.health._create_health_http_client",
            return_value=client_context,
        ) as create:
            result = await LLMHealthProbe(settings, chains=None, timeout_seconds=4.5).check()

        assert result.is_healthy()
        create.assert_called_once_with(4.5, "/run/model-ca/ca.crt")
        owned_client.get.assert_awaited_once_with(
            "https://ollama.test/api/tags",
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY_PLACEHOLDER}"},
        )

    @pytest.mark.parametrize(
        ("api_key", "registry_key", "expected_headers"),
        [
            (
                "model-secret",
                "registry-secret",
                {"Authorization": "Bearer model-secret"},
            ),
            (
                None,
                "registry-secret",
                {"Authorization": f"Bearer {OLLAMA_API_KEY_PLACEHOLDER}"},
            ),
            (None, None, {"Authorization": f"Bearer {OLLAMA_API_KEY_PLACEHOLDER}"}),
        ],
    )
    @pytest.mark.asyncio
    async def test_ollama_health_uses_only_model_key(
        self,
        api_key: str | None,
        registry_key: str | None,
        expected_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Ollama checks its native path and never borrow a local registry credential."""
        monkeypatch.setenv("OLLAMA_API_KEY", "poisoned-process-secret")
        config = LLMModelConfig(
            model="ollama:llama3",
            base_url="https://ollama.test/v1/",
            api_key=SecretStr(api_key) if api_key is not None else None,
            tls_ca_file="/run/model-ca/ca.crt",
        )
        registry = (
            ApiKeyRegistry.model_validate({"ollama": registry_key}) if registry_key is not None else ApiKeyRegistry()
        )
        settings = LLMSettings(provider=LLMProviderSettings(models=[config], api_keys=registry))
        response = MagicMock(status_code=HTTP_OK)
        owned_client = MagicMock(get=AsyncMock(return_value=response))
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=owned_client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "nohiki_llm_client.observability.health._create_health_http_client",
            return_value=client_context,
        ) as create:
            result = await LLMHealthProbe(settings, chains=None, timeout_seconds=4.5).check()

        assert result.is_healthy()
        create.assert_called_once_with(4.5, "/run/model-ca/ca.crt")
        owned_client.get.assert_awaited_once_with(
            "https://ollama.test/api/tags",
            headers=expected_headers,
        )
        client_context.__aexit__.assert_awaited_once_with(None, None, None)

    @pytest.mark.parametrize(
        ("api_key", "registry_key", "expected_headers"),
        [
            (
                "model-secret",
                "registry-secret",
                {"Authorization": "Bearer model-secret"},
            ),
            (
                None,
                "registry-secret",
                {"Authorization": f"Bearer {LLAMACPP_API_KEY_PLACEHOLDER}"},
            ),
            (None, None, {"Authorization": f"Bearer {LLAMACPP_API_KEY_PLACEHOLDER}"}),
        ],
    )
    @pytest.mark.asyncio
    async def test_llamacpp_health_uses_models_path_and_only_model_key(
        self,
        api_key: str | None,
        registry_key: str | None,
        expected_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """llama.cpp health matches its explicit endpoint without registry credential leakage."""
        monkeypatch.setenv("LLAMACPP_API_KEY", "poisoned-process-secret")
        config = LLMModelConfig(
            model="llamacpp:model.gguf",
            base_url="https://llamacpp.test/v1/",
            api_key=SecretStr(api_key) if api_key is not None else None,
            tls_ca_file="/run/model-ca/ca.crt",
        )
        registry = (
            ApiKeyRegistry.model_validate({"llamacpp": registry_key}) if registry_key is not None else ApiKeyRegistry()
        )
        settings = LLMSettings(provider=LLMProviderSettings(models=[config], api_keys=registry))
        probe = LLMHealthProbe(settings, chains=None)

        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await probe.check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://llamacpp.test/v1/models",
            headers=expected_headers,
            tls_ca_file="/run/model-ca/ca.crt",
        )

    @pytest.mark.asyncio
    async def test_custom_openai_health_matches_inference_placeholder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Compatible readiness cannot borrow ambient public OpenAI credentials."""
        monkeypatch.setenv("OPENAI_API_KEY", "poisoned-process-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://poisoned-openai.test/v1")
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="openai:test-model",
                        base_url="https://keyless-llm.example.test/v1",
                    )
                ]
            )
        )
        probe = LLMHealthProbe(settings, chains=None)

        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await probe.check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://keyless-llm.example.test/v1/models",
            headers={"Authorization": f"Bearer {OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER}"},
            tls_ca_file=None,
        )

    @pytest.mark.asyncio
    async def test_google_vertex_health_owns_model_scoped_retry_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Vertex readiness uses and closes the same scoped HTTP transport contract."""
        monkeypatch.setenv("GOOGLE_API_KEY", "poisoned-process-key")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "poisoned-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "poisoned-location")
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="google-vertex:gemini-2.5-flash",
                        google_project="my-project",
                        google_location="us-east1",
                        base_url="https://vertex-gateway.test/google/v1",
                        tls_ca_file="/run/model-ca/ca.crt",
                    )
                ]
            )
        )
        owned_client = MagicMock()
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=owned_client)
        client_context.__aexit__ = AsyncMock(return_value=None)
        provider_instance = MagicMock()
        provider_instance.client.aio.models.get = AsyncMock()
        provider_instance.client.aio.models.list = AsyncMock()

        with (
            patch(
                "nohiki_llm_client.observability.health._create_health_http_client",
                return_value=client_context,
            ) as create,
            patch(
                "nohiki_llm_client.observability.health.GoogleCloudProvider",
                return_value=provider_instance,
            ) as provider,
        ):
            result = await LLMHealthProbe(settings, chains=None, timeout_seconds=4.5).check()

        assert result.is_healthy()
        create.assert_called_once_with(4.5, "/run/model-ca/ca.crt")
        provider.assert_called_once_with(
            project="my-project",
            location="us-east1",
            http_client=owned_client,
            base_url="https://vertex-gateway.test/google/v1",
        )
        provider_instance.client.aio.models.get.assert_awaited_once_with(model="gemini-2.5-flash")
        provider_instance.client.aio.models.list.assert_not_awaited()
        client_context.__aexit__.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_vertex_claude_health_matches_inference_transport_and_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Claude readiness verifies the exact model through its Vertex SDK path."""
        monkeypatch.setenv("ANTHROPIC_VERTEX_BASE_URL", "https://poisoned-vertex.test")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "poisoned-project")
        monkeypatch.setenv("CLOUD_ML_REGION", "poisoned-region")
        model_name = "claude-sonnet-4-5"
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model=f"google-vertex:{model_name}",
                        google_project="my-project",
                        google_location="europe-west1",
                        base_url="https://vertex-gateway.test/anthropic",
                        tls_ca_file="/run/model-ca/ca.crt",
                    )
                ]
            )
        )
        owned_client = MagicMock(spec=httpx.AsyncClient)
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=owned_client)
        client_context.__aexit__ = AsyncMock(return_value=None)
        anthropic_client = MagicMock()
        anthropic_client.messages.count_tokens = AsyncMock()

        with (
            patch(
                "nohiki_llm_client.observability.health._create_health_http_client",
                return_value=client_context,
            ) as create,
            patch(
                "nohiki_llm_client.observability.health.AsyncAnthropicVertex",
                return_value=anthropic_client,
            ) as vertex,
            patch.object(LLMHealthProbe, "_resolve_health_api_key") as resolve_api_key,
        ):
            result = await LLMHealthProbe(settings, chains=None, timeout_seconds=4.5).check()

        assert result.is_healthy()
        create.assert_called_once_with(4.5, "/run/model-ca/ca.crt")
        vertex.assert_called_once_with(
            project_id="my-project",
            region="europe-west1",
            base_url="https://vertex-gateway.test/anthropic/v1",
            http_client=owned_client,
        )
        anthropic_client.messages.count_tokens.assert_awaited_once_with(
            model=model_name,
            messages=[{"role": "user", "content": "health"}],
        )
        resolve_api_key.assert_not_called()
        client_context.__aexit__.assert_awaited_once_with(None, None, None)


class TestExactModelReadiness:
    """Endpoint liveness alone never substitutes for exact-model inference."""

    @staticmethod
    def _config(provider: str, *, health_url: bool = False) -> LLMModelConfig:
        kwargs: dict[str, object] = {"model": f"{provider}:configured-model"}
        if provider in {"openai", "openrouter", "anthropic"}:
            kwargs["api_key"] = SecretStr("model-key")
        else:
            kwargs["base_url"] = f"https://{provider}.test/internal/{provider}/v1/"
        if health_url:
            kwargs["health_url"] = f"https://{provider}.test/readyz"
        return LLMModelConfig.model_validate(kwargs)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["openai", "openrouter", "anthropic", "ollama", "llamacpp"])
    async def test_provider_liveness_requires_bounded_exact_model_request(self, provider: str) -> None:
        """A successful native liveness route still performs one-token inference."""
        from unittest.mock import AsyncMock, MagicMock, patch

        config = self._config(provider)
        provider_settings = LLMProviderSettings(models=[config])
        settings = LLMSettings(provider=provider_settings)
        model = MagicMock()
        model.request = AsyncMock(return_value=MagicMock())
        owned_client = MagicMock(spec=httpx.AsyncClient)
        owned_client.aclose = AsyncMock()

        def create_exact(
            received: LLMModelConfig,
            owner: LLMProviderSettings,
            *,
            transport_clients: list[httpx.AsyncClient],
        ) -> MagicMock:
            assert received.model == config.model
            assert owner is provider_settings
            transport_clients.append(owned_client)
            return model

        probe = LLMHealthProbe(settings, chains=None)
        with (
            patch.object(
                LLMHealthProbe,
                "_check_cloud_endpoint",
                new=AsyncMock(return_value=(True, None)),
            ) as cloud,
            patch.object(
                LLMHealthProbe,
                "_check_ollama",
                new=AsyncMock(return_value=(True, None)),
            ) as ollama,
            patch(
                "nohiki_llm_client.observability.health.create_model",
                side_effect=create_exact,
            ),
        ):
            ok, err = await probe._check_model(config, provider_settings)

        assert (ok, err) == (True, None)
        if provider == "ollama":
            ollama.assert_awaited_once_with(config)
            cloud.assert_not_awaited()
        elif provider == "llamacpp":
            cloud.assert_awaited_once_with(
                "https://llamacpp.test/internal/llamacpp/v1/models",
                headers={"Authorization": f"Bearer {LLAMACPP_API_KEY_PLACEHOLDER}"},
                tls_ca_file=None,
            )
        else:
            cloud.assert_awaited_once()
        model.request.assert_awaited_once()
        request = model.request.await_args
        assert request is not None
        request_settings = request.args[1]
        expected_max_tokens = 16 if provider == "openai" else 1
        assert request_settings["max_tokens"] == expected_max_tokens
        owned_client.aclose.assert_awaited_once_with()

    @pytest.mark.parametrize(
        ("model_name", "reasoning_effort", "expected_reasoning"),
        [
            ("gpt-5.6", "high", {"effort": "none"}),
            ("gpt-5.2-pro", "low", {"effort": "low"}),
            ("gpt-5.2-pro", "medium", {"effort": "medium"}),
            ("gpt-5.2-pro", "high", {"effort": "high"}),
            ("gpt-5.1-chat-latest", "medium", None),
            ("gpt-5.2-chat-latest", "medium", None),
            ("gpt-5.3-chat-latest", "medium", None),
            ("configured-model", "high", None),
        ],
    )
    @pytest.mark.asyncio
    async def test_openai_responses_readiness_uses_valid_bounded_output_field(
        self,
        model_name: str,
        reasoning_effort: ReasoningEffort,
        expected_reasoning: dict[str, str] | None,
    ) -> None:
        """Responses readiness emits its supported token field with exact auth and model."""
        import json

        base_url = "https://openai-gateway.test/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/responses"
            assert request.headers["Authorization"] == "Bearer model-key"
            body = json.loads(request.content)
            assert body["model"] == model_name
            assert body["max_output_tokens"] == 16
            assert "max_tokens" not in body
            if expected_reasoning is None:
                assert "reasoning" not in body
            else:
                assert body["reasoning"] == expected_reasoning
            return httpx.Response(
                HTTP_OK,
                json={
                    "id": "resp_health",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "error": None,
                    "incomplete_details": None,
                    "instructions": None,
                    "max_output_tokens": 16,
                    "model": model_name,
                    "output": [
                        {
                            "id": "msg_health",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "ok",
                                    "annotations": [],
                                    "logprobs": [],
                                }
                            ],
                        }
                    ],
                    "parallel_tool_calls": True,
                    "previous_response_id": None,
                    "reasoning": {"effort": None, "summary": None},
                    "store": False,
                    "temperature": 0.0,
                    "tool_choice": "auto",
                    "tools": [],
                    "top_p": 1.0,
                    "truncation": "disabled",
                    "usage": {
                        "input_tokens": 1,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens": 1,
                        "output_tokens_details": {"reasoning_tokens": 0},
                        "total_tokens": 2,
                    },
                    "metadata": {},
                },
            )

        config = LLMModelConfig(
            model=f"openai:{model_name}",
            base_url=base_url,
            api_key=SecretStr("model-key"),
            reasoning_effort=reasoning_effort,
        )
        provider = LLMProviderSettings(models=[config])
        probe = LLMHealthProbe(LLMSettings(provider=provider), chains=None)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with (
                patch(
                    "nohiki_llm_client.providers.factory._create_retrying_http_client",
                    return_value=http_client,
                ),
                patch(
                    "nohiki_llm_client.observability.health.create_model",
                    side_effect=create_real_model,
                ),
            ):
                ok, error = await probe._check_exact_model(config, provider)

        assert (ok, error) == (True, None)

    @pytest.mark.parametrize(
        "model_name",
        ["gpt-5.1-chat-latest", "gpt-5.2-chat-latest", "gpt-5.3-chat-latest"],
    )
    @pytest.mark.parametrize("reasoning_effort", ["low", "high", "disabled"])
    @pytest.mark.asyncio
    async def test_fixed_reasoning_chat_health_rejects_nonmedium_before_request(
        self,
        model_name: str,
        reasoning_effort: ReasoningEffort,
    ) -> None:
        """Health uses normal factory validation and never reaches the provider SDK."""
        config = LLMModelConfig(
            model=f"openai:{model_name}",
            api_key=SecretStr("model-key"),
            reasoning_effort=reasoning_effort,
        )
        provider = LLMProviderSettings(models=[config])
        probe = LLMHealthProbe(LLMSettings(provider=provider), chains=None)
        owned_client = MagicMock(spec=httpx.AsyncClient)
        owned_client.aclose = AsyncMock()

        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=owned_client,
            ),
            patch("nohiki_llm_client.providers.factory.AsyncOpenAI") as sdk_client,
            patch(
                "nohiki_llm_client.observability.health.create_model",
                side_effect=create_real_model,
            ),
        ):
            ok, error = await probe._check_exact_model(config, provider)

        assert not ok
        assert error is not None
        assert "requires reasoning effort 'medium'" in error
        sdk_client.assert_not_called()
        owned_client.aclose.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_prefixed_ollama_base_uses_sibling_native_tags_route(self) -> None:
        """Ollama preliminary readiness removes only terminal v1 before api/tags."""
        from unittest.mock import AsyncMock, MagicMock, patch

        config = self._config("ollama")
        settings = LLMSettings(provider=LLMProviderSettings(models=[config]))
        response = MagicMock(status_code=HTTP_OK)
        owned_client = MagicMock(get=AsyncMock(return_value=response))
        client_context = MagicMock()
        client_context.__aenter__ = AsyncMock(return_value=owned_client)
        client_context.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "nohiki_llm_client.observability.health._create_health_http_client",
            return_value=client_context,
        ):
            ok, err = await LLMHealthProbe(settings, chains=None)._check_ollama(config)

        assert (ok, err) == (True, None)
        owned_client.get.assert_awaited_once_with(
            "https://ollama.test/internal/ollama/api/tags",
            headers={"Authorization": f"Bearer {OLLAMA_API_KEY_PLACEHOLDER}"},
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("provider", ["openai", "openrouter", "anthropic"])
    async def test_explicit_health_url_200_still_requires_exact_model(self, provider: str) -> None:
        """A credential-free gateway readiness response cannot mask missing models."""
        from unittest.mock import AsyncMock, MagicMock, patch

        config = self._config(provider, health_url=True)
        provider_settings = LLMProviderSettings(models=[config])
        probe = LLMHealthProbe(LLMSettings(provider=provider_settings), chains=None)
        model = MagicMock()
        model.request = AsyncMock(side_effect=LookupError("configured model missing"))

        with (
            patch.object(
                LLMHealthProbe,
                "_check_cloud_endpoint",
                new=AsyncMock(return_value=(True, None)),
            ) as liveness,
            patch(
                "nohiki_llm_client.observability.health.create_model",
                return_value=model,
            ),
        ):
            ok, err = await probe._check_model(config, provider_settings)

        assert ok is False
        assert "configured model missing" in (err or "")
        liveness.assert_awaited_once_with(config.health_url, headers={}, tls_ca_file=config.tls_ca_file)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "failure",
        [
            PermissionError("authentication rejected"),
            LookupError("wrong model"),
            LookupError("model not found"),
        ],
        ids=["auth-failure", "wrong-model", "missing-model"],
    )
    async def test_exact_model_failure_is_unhealthy_and_closes_transport(self, failure: Exception) -> None:
        """Inference errors fail readiness and owned probe transport is always closed."""
        from unittest.mock import AsyncMock, MagicMock, patch

        config = self._config("openai")
        provider_settings = LLMProviderSettings(models=[config])
        probe = LLMHealthProbe(LLMSettings(provider=provider_settings), chains=None)
        model = MagicMock()
        model.request = AsyncMock(side_effect=failure)
        owned_client = MagicMock(spec=httpx.AsyncClient)
        owned_client.aclose = AsyncMock()

        def create_exact(
            _received: LLMModelConfig,
            _owner: LLMProviderSettings,
            *,
            transport_clients: list[httpx.AsyncClient],
        ) -> MagicMock:
            transport_clients.append(owned_client)
            return model

        with (
            patch.object(
                LLMHealthProbe,
                "_check_cloud_endpoint",
                new=AsyncMock(return_value=(True, None)),
            ),
            patch(
                "nohiki_llm_client.observability.health.create_model",
                side_effect=create_exact,
            ),
        ):
            ok, err = await probe._check_model(config, provider_settings)

        assert ok is False
        assert str(failure) in (err or "")
        owned_client.aclose.assert_awaited_once_with()


class TestNamedChainHealth:
    """Readiness covers the complete effective model set for selected use cases."""

    @staticmethod
    def _settings() -> LLMSettings:
        def endpoint(name: str) -> LLMModelConfig:
            return LLMModelConfig(
                model=f"openai:{name}",
                api_key=SecretStr(f"{name}-key"),
                health_url=f"https://{name}.gateway.test/readyz",
            )

        default = endpoint("default")
        shared = endpoint("shared")
        extraction = endpoint("extraction")
        clarification = endpoint("clarification")
        return LLMSettings(
            provider=LLMProviderSettings(models=[default]),
            chains={
                "extraction": LLMProviderSettings(models=[extraction, shared, extraction]),
                "skill_clarification": LLMProviderSettings(models=[shared, clarification]),
            },
        )

    @pytest.mark.asyncio
    async def test_selected_chains_probe_all_fallbacks_once(self) -> None:
        """The chain union probes every fallback and deduplicates equal configs."""
        settings = self._settings()
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await LLMHealthProbe(
                settings,
                chains=("extraction", "skill_clarification"),
            ).check()

        assert result.is_healthy()
        assert check.await_args_list == [
            call(
                "https://extraction.gateway.test/readyz",
                headers={},
                tls_ca_file=None,
            ),
            call(
                "https://shared.gateway.test/readyz",
                headers={},
                tls_ca_file=None,
            ),
            call(
                "https://clarification.gateway.test/readyz",
                headers={},
                tls_ca_file=None,
            ),
        ]

    @pytest.mark.asyncio
    async def test_any_unhealthy_fallback_fails_readiness(self) -> None:
        """One failed model makes the selected chain set unhealthy."""
        settings = self._settings()
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(
                side_effect=[
                    (True, None),
                    (False, "shared unavailable"),
                    (True, None),
                ]
            ),
        ) as check:
            result = await LLMHealthProbe(
                settings,
                chains=("extraction", "skill_clarification"),
            ).check()

        assert not result.is_healthy()
        assert "shared unavailable" in result.message
        assert check.await_count == 3

    @pytest.mark.asyncio
    async def test_unknown_chain_uses_default_provider(self) -> None:
        """Missing named chains retain LLMClient's default-provider fallback semantics."""
        settings = self._settings()
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await LLMHealthProbe(
                settings,
                chains=("not_configured",),
            ).check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://default.gateway.test/readyz",
            headers={},
            tls_ca_file=None,
        )

    @pytest.mark.asyncio
    async def test_same_model_with_distinct_chain_keys_probes_each_credential(
        self,
    ) -> None:
        """Equal model configs remain distinct when effective chain credentials differ."""
        model = LLMModelConfig(
            model="anthropic:shared-model",
            base_url="https://anthropic-gateway.test",
        )
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="anthropic:default-model",
                        api_key=SecretStr("default-key"),
                    )
                ],
                api_keys=ApiKeyRegistry.model_validate({"anthropic": "default-registry-key"}),
            ),
            chains={
                "first": LLMProviderSettings(
                    models=[model],
                    api_keys=ApiKeyRegistry.model_validate({"anthropic": "first-chain-key"}),
                ),
                "second": LLMProviderSettings(
                    models=[model],
                    api_keys=ApiKeyRegistry.model_validate({"anthropic": "second-chain-key"}),
                ),
            },
        )
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await LLMHealthProbe(settings, chains=("first", "second")).check()

        assert result.is_healthy()
        assert check.await_args_list == [
            call(
                "https://anthropic-gateway.test/v1/models",
                headers={
                    "anthropic-version": "2023-06-01",
                    "x-api-key": "first-chain-key",
                },
                tls_ca_file=None,
            ),
            call(
                "https://anthropic-gateway.test/v1/models",
                headers={
                    "anthropic-version": "2023-06-01",
                    "x-api-key": "second-chain-key",
                },
                tls_ca_file=None,
            ),
        ]

    @pytest.mark.asyncio
    async def test_identical_effective_chain_entries_deduplicate(self) -> None:
        """Equal configs with equal effective credentials are checked only once."""
        model = LLMModelConfig(
            model="anthropic:shared-model",
            base_url="https://anthropic-gateway.test",
        )
        chain = LLMProviderSettings(
            models=[model],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "shared-key"}),
        )
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="anthropic:default-model",
                        api_key=SecretStr("default-key"),
                    )
                ]
            ),
            chains={"first": chain, "second": chain.model_copy(deep=True)},
        )
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await LLMHealthProbe(settings, chains=("first", "second")).check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://anthropic-gateway.test/v1/models",
            headers={
                "anthropic-version": "2023-06-01",
                "x-api-key": "shared-key",
            },
            tls_ca_file=None,
        )

    @pytest.mark.asyncio
    async def test_named_custom_openai_uses_chain_registry_not_default(self) -> None:
        """A named chain registry key beats both placeholder and default registry."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openai:gpt-4o")],
                api_keys=ApiKeyRegistry.model_validate({"openai": "default-registry-key"}),
            ),
            chains={
                "custom": LLMProviderSettings(
                    models=[
                        LLMModelConfig(
                            model="openai:gateway-model",
                            base_url="https://openai-gateway.test/v1",
                        )
                    ],
                    api_keys=ApiKeyRegistry.model_validate({"openai": "chain-registry-key"}),
                )
            },
        )
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await LLMHealthProbe(settings, chains=("custom",)).check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://openai-gateway.test/v1/models",
            headers={"Authorization": "Bearer chain-registry-key"},
            tls_ca_file=None,
        )

    @pytest.mark.asyncio
    async def test_named_custom_openai_without_explicit_key_uses_placeholder(
        self,
    ) -> None:
        """Default registry credentials never cross into a keyless named chain."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openai:gpt-4o")],
                api_keys=ApiKeyRegistry.model_validate({"openai": "default-registry-key"}),
            ),
            chains={
                "keyless": LLMProviderSettings(
                    models=[
                        LLMModelConfig(
                            model="openai:keyless-model",
                            base_url="https://keyless-gateway.test/v1",
                        )
                    ]
                )
            },
        )
        with patch.object(
            LLMHealthProbe,
            "_check_cloud_endpoint",
            new=AsyncMock(return_value=(True, None)),
        ) as check:
            result = await LLMHealthProbe(settings, chains=("keyless",)).check()

        assert result.is_healthy()
        check.assert_awaited_once_with(
            "https://keyless-gateway.test/v1/models",
            headers={"Authorization": f"Bearer {OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER}"},
            tls_ca_file=None,
        )


class TestEnsureLLMReady:
    """Tests for ensure_llm_ready function."""

    @pytest.mark.asyncio
    async def test_llm_ready_immediately(self, mock_settings: LLMSettings) -> None:
        """Test LLM ready on first check."""
        mock_response = MagicMock()
        mock_response.status_code = HTTP_OK

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            await ensure_llm_ready(mock_settings, chains=None, timeout_seconds=5.0)

    @pytest.mark.asyncio
    async def test_llm_timeout_raises_runtime_error(self, mock_settings: LLMSettings) -> None:
        """Test timeout raises RuntimeError."""
        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_response))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError, match="LLM unavailable"):
                await ensure_llm_ready(
                    mock_settings,
                    chains=None,
                    timeout_seconds=0.3,
                    retry_interval_seconds=0.1,
                )
