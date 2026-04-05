"""Unit tests for the model factory."""

import json
from collections.abc import Mapping
from inspect import Parameter, signature
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from nohiki_llm_client.config.settings import (
    ApiKeyRegistry,
    LLMCachingSettings,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    ReasoningEffort,
)
from nohiki_llm_client.providers import factory
from nohiki_llm_client.providers.caching import CachingOpenRouterModel
from nohiki_llm_client.providers.factory import (
    _build_openrouter_reasoning,
    _prepare_openrouter_context,
    _resolve_api_key,
    _resolve_effective_profile,
    create_caching_openrouter,
    create_full_model_chain,
    create_model,
    create_settings_from_model,
    resolve_chain,
)
from nohiki_llm_client.providers.llamacpp import LlamaCppProvider
from nohiki_llm_client.providers.profiles import (
    INLINED_REFS_OPENROUTER_PROFILE,
    META_LLAMA_OPENROUTER_PROFILE,
    OPENROUTER_QUIRKS,
    QWEN_NEXT_OPENROUTER_PROFILE,
    OpenRouterModelQuirks,
    select_openrouter_quirks,
)
from nohiki_llm_client.providers.transformers import (
    InlinedRefsJsonSchemaTransformer,
    OllamaJsonSchemaTransformer,
)
from nohiki_llm_client.transport import (
    LLAMACPP_API_KEY_PLACEHOLDER,
    OLLAMA_API_KEY_PLACEHOLDER,
    OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER,
)
from pydantic import SecretStr
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.models.openrouter import (
    OpenRouterModel,
    OpenRouterModelSettings,
    OpenRouterUsageConfig,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer, OpenAIModelProfile
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider


def _require_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return {key: item for key, item in value.items() if isinstance(key, str)}


class TestModelFactory:
    """Tests for create_model and create_full_model_chain."""

    def test_create_openrouter_model(self, llm_settings: LLMSettings) -> None:
        """Test creation of OpenRouter model."""
        model = create_model(llm_settings.provider.models[0], llm_settings.provider, transport_clients=[])
        assert isinstance(model, OpenRouterModel)
        assert model.model_name == "test/model"

    def test_create_openai_model(self, llm_settings_openai: LLMSettings) -> None:
        """Test creation of OpenAI model."""
        model = create_model(
            llm_settings_openai.provider.models[0],
            llm_settings_openai.provider,
            transport_clients=[],
        )
        assert isinstance(model, OpenAIResponsesModel)
        assert model.model_name == "gpt-4o"

    @pytest.mark.asyncio
    async def test_custom_openai_base_url_uses_registry_key(self) -> None:
        """A custom OpenAI-compatible endpoint retains canonical authentication."""
        base_url = "https://llm-gateway.example.com/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/models"
            assert request.headers["Authorization"] == "Bearer registry-test-key"
            return httpx.Response(200, json={"object": "list", "data": []})

        config = LLMModelConfig(model="openai:test-model", base_url=base_url)
        provider = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"openai": "registry-test-key"}),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(config, provider, transport_clients=[])
                assert isinstance(model, OpenAIResponsesModel)
                response = await model.client.models.list()

        assert response.data == []

    @pytest.mark.asyncio
    async def test_custom_openai_base_url_allows_keyless_endpoint(self) -> None:
        """An explicitly keyless OpenAI-compatible endpoint remains usable."""
        base_url = "https://keyless-llm.example.com/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/models"
            return httpx.Response(200, json={"object": "list", "data": []})

        config = LLMModelConfig(model="openai:test-model", base_url=base_url)
        provider = LLMProviderSettings(models=[config])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(config, provider, transport_clients=[])
                assert isinstance(model, OpenAIResponsesModel)
                response = await model.client.models.list()

        assert response.data == []

    @pytest.mark.parametrize(
        "model_name",
        ["gpt-5.1-chat-latest", "gpt-5.2-chat-latest", "gpt-5.3-chat-latest"],
    )
    def test_fixed_reasoning_chat_medium_uses_provider_default(
        self,
        model_name: str,
    ) -> None:
        """Semantic medium constructs normally without an unsupported override."""
        config = LLMModelConfig(
            model=f"openai:{model_name}",
            api_key=SecretStr("model-key"),
            reasoning_effort="medium",
        )
        provider = LLMProviderSettings(models=[config])
        owned_transport = MagicMock(spec=httpx.AsyncClient)

        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=owned_transport,
            ),
            patch("nohiki_llm_client.providers.factory.OpenAIResponsesModel") as model,
        ):
            create_model(config, provider, transport_clients=[])

        settings = _require_mapping(model.call_args.kwargs["settings"])
        assert "openai_reasoning_effort" not in settings

    @pytest.mark.parametrize(
        "model_name",
        ["gpt-5.1-chat-latest", "gpt-5.2-chat-latest", "gpt-5.3-chat-latest"],
    )
    @pytest.mark.parametrize("effort", ["low", "high", "disabled"])
    def test_fixed_reasoning_chat_rejects_nonfixed_effort_before_request(
        self,
        model_name: str,
        effort: ReasoningEffort,
    ) -> None:
        """A fixed-medium family rejects every semantically false effort."""
        config = LLMModelConfig(
            model=f"openai:{model_name}",
            api_key=SecretStr("model-key"),
            reasoning_effort=effort,
        )
        provider = LLMProviderSettings(models=[config])
        owned_transport = MagicMock(spec=httpx.AsyncClient)

        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=owned_transport,
            ),
            patch("nohiki_llm_client.providers.factory.AsyncOpenAI") as sdk_client,
            patch("nohiki_llm_client.providers.factory.OpenAIResponsesModel") as model,
            pytest.raises(ValueError, match="requires reasoning effort 'medium'"),
        ):
            create_model(config, provider, transport_clients=[])

        model.assert_not_called()
        sdk_client.assert_not_called()

    @pytest.mark.parametrize("effort", ["low", "medium", "high"])
    def test_openai_pro_model_retains_configured_reasoning_effort(
        self,
        effort: ReasoningEffort,
    ) -> None:
        """Effort-capable always-on Pro models retain every valid configured effort."""
        config = LLMModelConfig(
            model="openai:gpt-5.2-pro",
            api_key=SecretStr("model-key"),
            reasoning_effort=effort,
        )
        provider = LLMProviderSettings(models=[config])
        owned_transport = MagicMock(spec=httpx.AsyncClient)

        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=owned_transport,
            ),
            patch("nohiki_llm_client.providers.factory.OpenAIResponsesModel") as model,
        ):
            create_model(config, provider, transport_clients=[])

        settings = _require_mapping(model.call_args.kwargs["settings"])
        assert settings["openai_reasoning_effort"] == effort

    @pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
    def test_direct_cloud_provider_defaults_do_not_inject_an_endpoint(self, provider_name: str) -> None:
        """Direct providers retain their SDK endpoint unless explicitly configured."""
        settings = create_settings_from_model(
            f"{provider_name}:synthetic-model",
            ApiKeyRegistry.model_validate({provider_name: "test-key"}),
        )

        assert settings.provider.models[0].base_url is None

    @pytest.mark.asyncio
    async def test_custom_openai_base_url_uses_only_model_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An explicit model credential wins over registry and process credentials."""
        from unittest.mock import patch

        import httpx

        monkeypatch.setenv("OPENAI_API_KEY", "poisoned-process-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://poisoned-openai.test/v1")
        monkeypatch.setenv("OPENAI_ORG_ID", "attacker-org")
        monkeypatch.setenv("OPENAI_PROJECT_ID", "attacker-project")
        base_url = "https://llm-gateway.example.test/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/models"
            assert request.headers["Authorization"] == "Bearer model-test-key"
            assert "OpenAI-Organization" not in request.headers
            assert "OpenAI-Project" not in request.headers
            return httpx.Response(200, json={"object": "list", "data": []})

        config = LLMModelConfig(
            model="openai:test-model",
            base_url=base_url,
            api_key=SecretStr("model-test-key"),
        )
        provider = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"openai": "registry-test-key"}),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(config, provider, transport_clients=[])
                assert isinstance(model, OpenAIResponsesModel)
                response = await model.client.models.list()

        assert response.data == []

    @pytest.mark.asyncio
    async def test_custom_openai_base_url_ignores_ambient_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A keyless compatible endpoint sends only the explicit harmless placeholder."""
        monkeypatch.setenv("OPENAI_API_KEY", "poisoned-process-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://poisoned-openai.test/v1")
        base_url = "https://keyless-llm.example.test/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/models"
            assert request.headers["Authorization"] == (f"Bearer {OPENAI_COMPATIBLE_API_KEY_PLACEHOLDER}")
            return httpx.Response(200, json={"object": "list", "data": []})

        config = LLMModelConfig(model="openai:test-model", base_url=base_url)
        provider = LLMProviderSettings(models=[config])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(config, provider, transport_clients=[])
                assert isinstance(model, OpenAIResponsesModel)
                response = await model.client.models.list()

        assert response.data == []

    @pytest.mark.asyncio
    async def test_custom_openai_base_url_uses_own_registry_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inference uses the owning chain registry before the keyless placeholder."""
        monkeypatch.setenv("OPENAI_API_KEY", "poisoned-process-secret")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://poisoned-openai.test/v1")
        base_url = "https://chain-openai.example.test/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/models"
            assert request.headers["Authorization"] == "Bearer chain-registry-key"
            return httpx.Response(200, json={"object": "list", "data": []})

        config = LLMModelConfig(model="openai:test-model", base_url=base_url)
        chain = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"openai": "chain-registry-key"}),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(config, chain, transport_clients=[])
                assert isinstance(model, OpenAIResponsesModel)
                response = await model.client.models.list()

        assert response.data == []

    def test_public_openai_still_requires_configured_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The compatible placeholder never relaxes public OpenAI authentication."""
        monkeypatch.setenv("OPENAI_API_KEY", "poisoned-process-secret")

        with pytest.raises(ValueError, match="requires an api_key"):
            LLMProviderSettings(models=[LLMModelConfig(model="openai:gpt-4o")])

    def test_create_ollama_model(self, llm_settings_ollama: LLMSettings) -> None:
        """Test creation of Ollama model."""
        model = create_model(
            llm_settings_ollama.provider.models[0],
            llm_settings_ollama.provider,
            transport_clients=[],
        )
        # OllamaProvider uses OpenAIChatModel under the hood in PydanticAI
        from pydantic_ai.models.openai import OpenAIChatModel

        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "llama3"

    def test_create_google_vertex_model(self, llm_settings_google_vertex: LLMSettings) -> None:
        """Test creation of Google Vertex AI model with registry API key."""
        model = create_model(
            llm_settings_google_vertex.provider.models[0],
            llm_settings_google_vertex.provider,
            transport_clients=[],
        )
        assert isinstance(model, GoogleModel)
        assert model.model_name == "gemini-2.5-flash"

    def test_canonical_llamacpp_config_reaches_explicit_endpoint(self) -> None:
        config = LLMModelConfig(
            model="llamacpp:synthetic-local.gguf",
            base_url="https://llamacpp.example.test/v1",
        )
        provider_settings = LLMProviderSettings(models=[config])

        model = create_model(config, provider_settings, transport_clients=[])

        assert isinstance(model.provider, LlamaCppProvider)
        assert model.provider.base_url == "https://llamacpp.example.test/v1"
        assert model.model_name == "synthetic-local.gguf"

    @pytest.mark.parametrize(
        ("provider_name", "provider_constructor"),
        [
            ("ollama", "OllamaProvider"),
            ("llamacpp", "LlamaCppProvider"),
        ],
    )
    def test_local_provider_does_not_borrow_registry_key(
        self,
        provider_name: str,
        provider_constructor: str,
    ) -> None:
        """Local endpoints authenticate only with their explicit per-model credential."""
        from unittest.mock import patch

        config = LLMModelConfig(
            model=f"{provider_name}:local-model",
            base_url=f"https://{provider_name}.test/v1",
        )
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({provider_name: "unrelated-registry-secret"}),
        )

        with (
            patch(f"nohiki_llm_client.providers.factory.{provider_constructor}") as provider,
            patch("nohiki_llm_client.providers.factory.OpenAIChatModel"),
        ):
            create_model(config, provider_settings, transport_clients=[])

        expected_placeholder = OLLAMA_API_KEY_PLACEHOLDER if provider_name == "ollama" else LLAMACPP_API_KEY_PLACEHOLDER
        assert provider.call_args.kwargs["api_key"] == expected_placeholder

    @pytest.mark.parametrize(
        ("provider_name", "api_key_env", "expected_placeholder"),
        [
            ("ollama", "OLLAMA_API_KEY", OLLAMA_API_KEY_PLACEHOLDER),
            ("llamacpp", "LLAMACPP_API_KEY", LLAMACPP_API_KEY_PLACEHOLDER),
        ],
    )
    @pytest.mark.asyncio
    async def test_local_factory_uses_placeholder_instead_of_poisoned_env(
        self,
        provider_name: str,
        api_key_env: str,
        expected_placeholder: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inference sends the same deterministic placeholder health uses when keyless."""
        monkeypatch.setenv(api_key_env, "poisoned-process-secret")
        base_url = f"https://{provider_name}.test/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/models"
            assert request.headers["Authorization"] == f"Bearer {expected_placeholder}"
            return httpx.Response(200, json={"object": "list", "data": []})

        config = LLMModelConfig(
            model=f"{provider_name}:local-model",
            base_url=base_url,
        )
        provider_settings = LLMProviderSettings(models=[config])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(
                    config,
                    provider_settings,
                    transport_clients=[],
                )
                assert isinstance(model, OpenAIChatModel)
                assert isinstance(model.provider, (LlamaCppProvider, OllamaProvider))
                response = await model.provider.client.models.list()

        assert response.data == []

    def test_create_google_vertex_model_with_explicit_key(self) -> None:
        """Test creation of Google Vertex AI model with per-model API key."""
        config = LLMModelConfig(
            model="google-vertex:gemini-2.5-flash",
            api_key=SecretStr("explicit-vertex-key"),
        )
        provider_settings = LLMProviderSettings(models=[config])
        model = create_model(config, provider_settings, transport_clients=[])
        assert isinstance(model, GoogleModel)
        assert model.model_name == "gemini-2.5-flash"

    @pytest.mark.parametrize(
        ("model_name", "effort", "expected"),
        [
            ("gemini-3-flash", "disabled", {"thinking_level": "MINIMAL"}),
            (
                "gemini-3-flash",
                "low",
                {"thinking_level": "LOW", "include_thoughts": True},
            ),
            (
                "gemini-3-flash",
                "medium",
                {"thinking_level": "MEDIUM", "include_thoughts": True},
            ),
            (
                "gemini-3-flash",
                "high",
                {"thinking_level": "HIGH", "include_thoughts": True},
            ),
            ("gemini-2.5-flash", "disabled", {"thinking_budget": 0}),
            (
                "gemini-2.5-flash",
                "low",
                {"thinking_budget": 2_048, "include_thoughts": True},
            ),
            (
                "gemini-2.5-flash",
                "medium",
                {"thinking_budget": 8_192, "include_thoughts": True},
            ),
            (
                "gemini-2.5-flash",
                "high",
                {"thinking_budget": 24_576, "include_thoughts": True},
            ),
        ],
    )
    def test_google_vertex_reasoning_effort_maps_to_installed_sdk_profile(
        self,
        model_name: str,
        effort: ReasoningEffort,
        expected: dict[str, object],
    ) -> None:
        """Gemini 3 uses levels while Gemini 2.5 receives deterministic budgets."""
        config = LLMModelConfig(
            model=f"google-vertex:{model_name}",
            api_key=SecretStr("vertex-key"),
            reasoning_effort=effort,
        )
        provider = LLMProviderSettings(models=[config])

        with patch("nohiki_llm_client.providers.factory.GoogleModel") as google_model:
            create_model(config, provider, transport_clients=[])

        settings = _require_mapping(google_model.call_args.kwargs["settings"])
        thinking = _require_mapping(settings["google_thinking_config"])
        assert thinking == expected

    @pytest.mark.parametrize(
        ("model_name", "effort"),
        [
            ("gemini-1.5-flash", "high"),
            ("gemini-2.5-pro", "disabled"),
            ("gemini-3-pro-preview", "disabled"),
        ],
    )
    def test_google_vertex_omits_unsupported_or_invalid_thinking_config(
        self,
        model_name: str,
        effort: ReasoningEffort,
    ) -> None:
        """Unsupported models and always-thinking Pro models retain SDK defaults."""
        config = LLMModelConfig(
            model=f"google-vertex:{model_name}",
            api_key=SecretStr("vertex-key"),
            reasoning_effort=effort,
        )
        provider = LLMProviderSettings(models=[config])

        with patch("nohiki_llm_client.providers.factory.GoogleModel") as google_model:
            create_model(config, provider, transport_clients=[])

        settings = _require_mapping(google_model.call_args.kwargs["settings"])
        assert "google_thinking_config" not in settings

    def test_create_google_vertex_model_with_project_location(self) -> None:
        """Test creation of Google Vertex AI model with GCP project and location."""
        config = LLMModelConfig(
            model="google-vertex:gemini-2.5-flash",
            api_key=SecretStr("vertex-key"),
            google_project="my-project",
            google_location="us-east1",
        )
        provider_settings = LLMProviderSettings(models=[config])
        model = create_model(config, provider_settings, transport_clients=[])
        assert isinstance(model, GoogleModel)
        assert model.model_name == "gemini-2.5-flash"

    def test_create_google_vertex_adc_with_project_location(self) -> None:
        """ADC path with project/location dispatches to the credentials overload."""
        from unittest.mock import patch

        config = LLMModelConfig(
            model="google-vertex:gemini-2.5-flash",
            google_project="my-project",
            google_location="us-east1",
        )
        provider_settings = LLMProviderSettings(models=[config])
        with patch("nohiki_llm_client.providers.factory.GoogleCloudProvider") as mock_gp:
            create_model(config, provider_settings, transport_clients=[])
            assert mock_gp.call_args.kwargs["project"] == "my-project"
            assert mock_gp.call_args.kwargs["location"] == "us-east1"

    def test_create_google_vertex_rejects_bare_adc(self) -> None:
        """Factory settings reject ambient-only ADC before provider construction."""
        config = LLMModelConfig(model="google-vertex:gemini-2.5-flash")
        with pytest.raises(ValueError, match=r"explicit api_key|google_project"):
            LLMProviderSettings(models=[config])

    def test_create_vertex_anthropic_rejects_project_without_region(self) -> None:
        """Claude routing requires an explicit project and region pair."""
        config = LLMModelConfig(
            model="google-vertex:claude-sonnet-4-5",
            google_project="my-project",
        )
        with pytest.raises(ValueError, match="google_project and google_location"):
            LLMProviderSettings(models=[config])

    def test_create_vertex_anthropic_rejects_bare_adc(self) -> None:
        """Claude on Vertex cannot borrow ambient project or region settings."""
        config = LLMModelConfig(model="google-vertex:claude-sonnet-4-5")
        with pytest.raises(ValueError, match="google_project and google_location"):
            LLMProviderSettings(models=[config])

    def test_create_vertex_anthropic_claude_model(self) -> None:
        """Claude models on google-vertex route through AsyncAnthropicVertex."""
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(
            model="google-vertex:claude-sonnet-4-5",
            google_project="my-project",
            google_location="us-east1",
        )
        provider_settings = LLMProviderSettings(models=[config])
        with (
            patch("nohiki_llm_client.providers.factory.AsyncAnthropicVertex") as mock_vertex,
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
        ):
            mock_vertex.return_value = MagicMock()
            mock_ap.return_value = MagicMock()
            create_model(config, provider_settings, transport_clients=[])
            assert mock_vertex.call_args.kwargs["project_id"] == "my-project"
            assert mock_vertex.call_args.kwargs["region"] == "us-east1"
            mock_ap.assert_called_once_with(anthropic_client=mock_vertex.return_value)
            mock_am.assert_called_once()

    @pytest.mark.parametrize("route", ["anthropic", "google-vertex"])
    @pytest.mark.parametrize(
        "model_name",
        [
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-opus-4-1",
            "claude-opus-4-5",
            "claude-sonnet-4-6",
        ],
    )
    @pytest.mark.parametrize(
        ("effort", "expected_budget"),
        [
            ("disabled", None),
            ("low", 2_048),
            ("medium", 10_000),
            ("high", 16_384),
        ],
    )
    def test_claude_reasoning_follows_installed_profile_for_direct_and_vertex(
        self,
        route: str,
        model_name: str,
        effort: ReasoningEffort,
        expected_budget: int | None,
    ) -> None:
        """Both transports use profile-backed extended or adaptive reasoning."""
        config_values: dict[str, object] = {
            "model": f"{route}:{model_name}",
            "reasoning_effort": effort,
        }
        if route == "anthropic":
            config_values["api_key"] = SecretStr("model-key")
        else:
            config_values.update(
                google_project="model-project",
                google_location="model-region",
            )
        config = LLMModelConfig.model_validate(config_values)
        provider = LLMProviderSettings(models=[config], temperature=0.2)

        with patch("nohiki_llm_client.providers.factory.AnthropicModel") as model:
            create_model(config, provider, transport_clients=[])

        settings = _require_mapping(model.call_args.kwargs["settings"])
        if effort == "disabled":
            assert "anthropic_thinking" not in settings
            assert "anthropic_effort" not in settings
            assert settings["temperature"] == 0.2
        elif model_name.endswith("4-6"):
            assert settings["anthropic_thinking"] == {"type": "adaptive"}
            assert settings["anthropic_effort"] == effort
            assert settings["temperature"] == 1.0
        else:
            assert settings["anthropic_thinking"] == {
                "type": "enabled",
                "budget_tokens": expected_budget,
            }
            assert settings["temperature"] == 1.0

    @pytest.mark.parametrize(
        ("model_name", "provider_constructor"),
        [
            ("google-vertex:gemini-2.5-flash", "GoogleCloudProvider"),
            ("google-vertex:claude-sonnet-4-5", "AsyncAnthropicVertex"),
        ],
    )
    def test_vertex_constructor_receives_model_scoped_retry_client(
        self,
        model_name: str,
        provider_constructor: str,
    ) -> None:
        """Both Vertex SDK paths use the retry client carrying model CA trust."""
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(
            model=model_name,
            google_project="my-project",
            google_location="us-east1",
            tls_ca_file="/run/model-ca/ca.crt",
        )
        provider_settings = LLMProviderSettings(models=[config])
        http_client = MagicMock()

        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ) as create_http_client,
            patch(f"nohiki_llm_client.providers.factory.{provider_constructor}") as provider,
            patch("nohiki_llm_client.providers.factory.GoogleModel"),
            patch("nohiki_llm_client.providers.factory.AnthropicProvider"),
            patch("nohiki_llm_client.providers.factory.AnthropicModel"),
        ):
            create_model(config, provider_settings, transport_clients=[])

        create_http_client.assert_called_once_with("/run/model-ca/ca.crt")
        assert provider.call_args.kwargs["http_client"] is http_client

    @pytest.mark.asyncio
    async def test_vertex_claude_replaces_ambient_authorization_with_adc(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Vertex strips ambient headers before its SDK installs the ADC bearer."""
        monkeypatch.setenv(
            "ANTHROPIC_CUSTOM_HEADERS",
            "Authorization: Bearer attacker\nX-Ambient: attacker",
        )
        base_url = "https://vertex-gateway.test/anthropic"
        model_name = "claude-sonnet-4-5"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer adc-token"
            assert "x-ambient" not in request.headers
            assert "x-api-key" not in request.headers
            assert model_name in request.url.path
            return httpx.Response(
                200,
                json={
                    "id": "msg_vertex",
                    "type": "message",
                    "role": "assistant",
                    "model": model_name,
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        credentials = MagicMock(expired=False, token="adc-token")
        config = LLMModelConfig(
            model=f"google-vertex:{model_name}",
            base_url=base_url,
            google_project="model-project",
            google_location="model-region",
        )
        provider = LLMProviderSettings(models=[config])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with (
                patch(
                    "nohiki_llm_client.providers.factory._create_retrying_http_client",
                    return_value=http_client,
                ),
                patch(
                    "anthropic.lib.vertex._client.load_auth",
                    return_value=(credentials, "model-project"),
                ) as load_auth,
            ):
                model = create_model(config, provider, transport_clients=[])
                assert isinstance(model, AnthropicModel)
                response = await model.client.messages.create(
                    model=model_name,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "health"}],
                )

        assert response.content[0].type == "text"
        load_auth.assert_called_once_with(project_id="model-project")

    def test_create_full_model_chain_single_no_caching(self, llm_settings: LLMSettings) -> None:
        """Single model with caching disabled returns a plain OpenRouterModel."""
        model = create_full_model_chain(
            llm_settings.provider,
            LLMCachingSettings(enabled=False),
            transport_clients=[],
        )
        assert isinstance(model, OpenRouterModel)

    def test_create_full_model_chain_single_with_caching(self, llm_settings: LLMSettings) -> None:
        """Single OpenRouter model with caching enabled returns CachingOpenRouterModel."""
        model = create_full_model_chain(
            llm_settings.provider,
            LLMCachingSettings(enabled=True),
            transport_clients=[],
        )
        assert isinstance(model, CachingOpenRouterModel)

    def test_create_full_model_chain_with_fallbacks(self, llm_settings: LLMSettings) -> None:
        """Priority chain with multiple models is assembled correctly."""
        provider = llm_settings.provider.model_copy(
            update={
                "models": [
                    llm_settings.provider.models[0],
                    LLMModelConfig(model="openai:gpt-4o"),
                ],
                "api_keys": ApiKeyRegistry.model_validate({"openrouter": "test-key", "openai": "oa-key"}),
            }
        )
        model = create_full_model_chain(provider, LLMCachingSettings(enabled=False), transport_clients=[])
        assert isinstance(model, FallbackModel)
        assert len(model.models) == 2
        assert isinstance(model.models[0], OpenRouterModel)
        assert isinstance(model.models[1], OpenAIResponsesModel)

    @pytest.mark.asyncio
    async def test_chain_failure_rolls_back_only_attempt_transports(self) -> None:
        """A partial chain closes its own clients without consuming prior ownership."""
        preexisting = MagicMock(spec=httpx.AsyncClient)
        preexisting.aclose = AsyncMock()
        primary_client = MagicMock(spec=httpx.AsyncClient)
        primary_client.aclose = AsyncMock()
        failed_client = MagicMock(spec=httpx.AsyncClient)
        failed_client.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
        transports: list[httpx.AsyncClient] = [preexisting]
        provider = LLMProviderSettings(
            models=[
                LLMModelConfig(model="openai:primary"),
                LLMModelConfig(model="openai:fallback"),
            ],
            api_keys=ApiKeyRegistry.model_validate({"openai": "test-key"}),
        )

        def create_primary(
            _config: LLMModelConfig,
            _provider: LLMProviderSettings,
            _caching: LLMCachingSettings,
            transport_clients: list[httpx.AsyncClient],
        ) -> TestModel:
            transport_clients.append(primary_client)
            return TestModel()

        def fail_fallback(
            _config: LLMModelConfig,
            _provider: LLMProviderSettings,
            _caching: LLMCachingSettings | None = None,
            *,
            transport_clients: list[httpx.AsyncClient],
        ) -> TestModel:
            transport_clients.append(failed_client)
            message = "fallback construction failed"
            raise RuntimeError(message)

        with (
            patch.object(factory, "_select_primary_model", side_effect=create_primary),
            patch.object(factory, "create_model", side_effect=fail_fallback),
            pytest.raises(BaseExceptionGroup) as error,
        ):
            create_full_model_chain(
                provider,
                LLMCachingSettings(),
                transport_clients=transports,
            )

        assert [str(exception) for exception in error.value.exceptions] == [
            "fallback construction failed",
            "close failed",
        ]
        preexisting.aclose.assert_not_awaited()
        primary_client.aclose.assert_awaited_once_with()
        failed_client.aclose.assert_awaited_once_with()
        assert transports == [preexisting, failed_client]

    def test_cross_provider_fallback_chain_preserves_declared_order(self) -> None:
        """Fallback attempts retain the configured provider and model priority."""
        provider = LLMProviderSettings(
            models=[
                LLMModelConfig(model="openrouter:qwen/qwen3-vl-30b"),
                LLMModelConfig(model="openrouter:google/gemini-3-flash"),
                LLMModelConfig(model="openai:gpt-5-mini"),
            ],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "or-key", "openai": "oa-key"}),
        )

        model = create_full_model_chain(provider, LLMCachingSettings(enabled=False), transport_clients=[])

        assert isinstance(model, FallbackModel)
        assert [candidate.model_name for candidate in model.models] == [
            "qwen/qwen3-vl-30b",
            "google/gemini-3-flash",
            "gpt-5-mini",
        ]

    def test_unsupported_provider_raises(self, llm_settings: LLMSettings) -> None:
        """Test that unsupported provider raises ValueError."""
        config = LLMModelConfig(model="unsupported:model", api_key=SecretStr("key"))
        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            create_model(config, llm_settings.provider, transport_clients=[])


class TestModelScopedTransport:
    """Tests for per-model CA trust and provider client ownership."""

    def test_direct_model_creation_requires_transport_registry(self) -> None:
        """Callers cannot construct an owned provider transport without an owner registry."""
        transport_clients = signature(create_model).parameters["transport_clients"]
        assert transport_clients.kind is Parameter.KEYWORD_ONLY
        assert transport_clients.default is Parameter.empty

    def test_unsupported_provider_allocates_no_transport(self, llm_settings: LLMSettings) -> None:
        """Provider validation occurs before any owned HTTP client is allocated."""
        from unittest.mock import patch

        config = LLMModelConfig(model="unsupported:model", api_key=SecretStr("key"))
        transports: list[httpx.AsyncClient] = []

        with (
            patch("nohiki_llm_client.providers.factory._create_retrying_http_client") as create_client,
            pytest.raises(ValueError, match="Unsupported LLM provider"),
        ):
            create_model(config, llm_settings.provider, transport_clients=transports)

        create_client.assert_not_called()
        assert transports == []

    @pytest.mark.parametrize(
        ("model_name", "base_url", "registry", "creator"),
        [
            (
                "openrouter:test/model",
                None,
                {"openrouter": "key"},
                "_create_openrouter",
            ),
            ("openai:test-model", None, {"openai": "key"}, "_create_openai"),
            ("ollama:llama3", "http://ollama.test/v1", {}, "_create_ollama"),
            ("llamacpp:model.gguf", "http://llamacpp.test/v1", {}, "_create_llamacpp"),
            (
                "anthropic:claude-sonnet-4-20250514",
                None,
                {"anthropic": "key"},
                "_create_anthropic",
            ),
            ("google-vertex:gemini-2.5-flash", None, {}, "_create_google_vertex"),
            ("google-vertex:claude-sonnet-4-5", None, {}, "_create_google_vertex"),
        ],
    )
    @pytest.mark.asyncio
    async def test_constructor_failure_keeps_allocated_transport_closable(
        self,
        model_name: str,
        base_url: str | None,
        registry: dict[str, str],
        creator: str,
    ) -> None:
        """Every supported dispatch registers ownership before downstream construction."""
        from unittest.mock import AsyncMock, patch

        from nohiki_llm_client import LLMClient

        config_kwargs: dict[str, object] = {"model": model_name, "base_url": base_url}
        if model_name.startswith("google-vertex:"):
            config_kwargs.update(google_project="model-project", google_location="us-east1")
        config = LLMModelConfig.model_validate(config_kwargs)
        provider = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate(registry),
        )
        owner = LLMClient(LLMSettings(provider=provider))
        http_client = MagicMock(spec=httpx.AsyncClient)
        http_client.aclose = AsyncMock()

        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ),
            patch(
                f"nohiki_llm_client.providers.factory.{creator}",
                side_effect=RuntimeError("constructor failed"),
            ),
            pytest.raises(RuntimeError, match="constructor failed"),
        ):
            create_model(config, provider, transport_clients=owner._transport_clients)

        assert owner._transport_clients == [http_client]
        await owner.close()
        http_client.aclose.assert_awaited_once_with()

    def test_custom_ca_extends_pinned_public_trust_without_ambient_ca(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Poisoned CA variables cannot replace public trust or internal augmentation."""
        from unittest.mock import MagicMock, patch

        from nohiki_llm_client.transport import create_model_ssl_context

        monkeypatch.setenv("SSL_CERT_FILE", "/poisoned/ambient-ca.pem")
        monkeypatch.setenv("SSL_CERT_DIR", "/poisoned/ambient-ca-dir")
        context = MagicMock()
        trust_loads: list[tuple[str, str]] = []

        def create_context(
            *,
            cafile: str,
            capath: str | None = None,
            cadata: str | bytes | None = None,
        ) -> MagicMock:
            assert capath is None
            assert cadata is None
            trust_loads.append(("public", cafile))
            return context

        def load_internal_ca(*, cafile: str) -> None:
            trust_loads.append(("internal", cafile))

        context.load_verify_locations.side_effect = load_internal_ca
        with (
            patch(
                "nohiki_llm_client.transport.certifi.where",
                return_value="/certifi/cacert.pem",
            ),
            patch(
                "nohiki_llm_client.transport.ssl.create_default_context",
                side_effect=create_context,
            ) as create,
        ):
            result = create_model_ssl_context("/run/model-ca/ca.crt")

        assert result is context
        create.assert_called_once_with(cafile="/certifi/cacert.pem")
        context.load_verify_locations.assert_called_once_with(cafile="/run/model-ca/ca.crt")
        assert trust_loads == [
            ("public", "/certifi/cacert.pem"),
            ("internal", "/run/model-ca/ca.crt"),
        ]

    def test_custom_ca_load_failure_propagates(self) -> None:
        """Invalid CA material fails model construction instead of weakening trust."""
        import ssl
        from unittest.mock import MagicMock, patch

        from nohiki_llm_client.transport import create_model_ssl_context

        context = MagicMock()
        context.load_verify_locations.side_effect = ssl.SSLError("invalid CA")

        with (
            patch(
                "nohiki_llm_client.transport.ssl.create_default_context",
                return_value=context,
            ),
            pytest.raises(ssl.SSLError, match="invalid CA"),
        ):
            create_model_ssl_context("/run/model-ca/broken.crt")

    def test_model_ssl_contexts_do_not_share_custom_trust(self) -> None:
        """Loading one model's CA cannot mutate another model's trust context."""
        from unittest.mock import MagicMock, patch

        from nohiki_llm_client.transport import create_model_ssl_context

        custom_context = MagicMock()
        default_context = MagicMock()

        with patch(
            "nohiki_llm_client.transport.ssl.create_default_context",
            side_effect=[custom_context, default_context],
        ):
            first = create_model_ssl_context("/run/model-a/ca.crt")
            second = create_model_ssl_context(None)

        assert first is custom_context
        assert second is default_context
        custom_context.load_verify_locations.assert_called_once_with(cafile="/run/model-a/ca.crt")
        default_context.load_verify_locations.assert_not_called()

    @pytest.mark.parametrize(
        (
            "model_name",
            "base_url",
            "registry",
            "provider_constructor",
            "model_constructor",
        ),
        [
            (
                "openrouter:test/model",
                None,
                {"openrouter": "test-key"},
                "OpenRouterProvider",
                "RobustOpenRouterModel",
            ),
            (
                "openai:test-model",
                None,
                {"openai": "test-key"},
                "OpenAIProvider",
                "OpenAIResponsesModel",
            ),
            (
                "ollama:llama3",
                "http://ollama.test/v1",
                {},
                "OllamaProvider",
                "OpenAIChatModel",
            ),
            (
                "llamacpp:model.gguf",
                "http://llamacpp.test/v1",
                {},
                "LlamaCppProvider",
                "OpenAIChatModel",
            ),
            (
                "anthropic:claude-sonnet-4-20250514",
                None,
                {"anthropic": "test-key"},
                "AnthropicProvider",
                "AnthropicModel",
            ),
        ],
    )
    def test_provider_constructor_receives_model_scoped_retry_client(
        self,
        model_name: str,
        base_url: str | None,
        registry: dict[str, str],
        provider_constructor: str,
        model_constructor: str,
    ) -> None:
        """Every HTTP provider retains the retry client built for that model's CA."""
        from contextlib import ExitStack
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(
            model=model_name,
            base_url=base_url,
            tls_ca_file="/run/model-ca/ca.crt",
        )
        provider = LLMProviderSettings(models=[config], api_keys=ApiKeyRegistry.model_validate(registry))
        http_client = MagicMock()

        sdk_client = None
        sdk_client_kwarg: str | None = None
        with ExitStack() as stack:
            create_http_client = stack.enter_context(
                patch(
                    "nohiki_llm_client.providers.factory._create_retrying_http_client",
                    return_value=http_client,
                )
            )
            provider_mock = stack.enter_context(patch(f"nohiki_llm_client.providers.factory.{provider_constructor}"))
            stack.enter_context(patch(f"nohiki_llm_client.providers.factory.{model_constructor}"))
            if provider_constructor == "OpenRouterProvider":
                sdk_client = stack.enter_context(patch("nohiki_llm_client.providers.factory.AsyncOpenAI"))
                sdk_client_kwarg = "openai_client"
                stack.enter_context(
                    patch(
                        "nohiki_llm_client.providers.factory._resolve_effective_profile",
                        return_value=None,
                    )
                )

            elif provider_constructor == "OpenAIProvider":
                sdk_client = stack.enter_context(patch("nohiki_llm_client.providers.factory.AsyncOpenAI"))
                sdk_client_kwarg = "openai_client"
            elif provider_constructor == "AnthropicProvider":
                sdk_client = stack.enter_context(patch("nohiki_llm_client.providers.factory.AsyncAnthropic"))
                sdk_client_kwarg = "anthropic_client"
            create_model(config, provider, transport_clients=[])

        create_http_client.assert_called_once_with("/run/model-ca/ca.crt")
        if sdk_client is not None:
            assert sdk_client.call_args.kwargs["http_client"] is http_client
            assert sdk_client_kwarg is not None
            assert provider_mock.call_args.kwargs[sdk_client_kwarg] is sdk_client.return_value
        else:
            assert provider_mock.call_args.kwargs["http_client"] is http_client

    def test_openrouter_custom_base_path_uses_scoped_openai_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A gateway subpath reaches AsyncOpenAI unchanged with the model retry client."""
        monkeypatch.setenv("OPENAI_API_KEY", "poisoned-process-key")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://poisoned-openai.test/v1")
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(
            model="openrouter:test/model",
            base_url="https://gateway.test/providers/openrouter/v1",
            tls_ca_file="/run/model-ca/ca.crt",
        )
        provider = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        http_client = MagicMock()

        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ),
            patch("nohiki_llm_client.providers.factory.AsyncOpenAI") as openai_client,
            patch("nohiki_llm_client.providers.factory.OpenRouterProvider") as openrouter_provider,
            patch("nohiki_llm_client.providers.factory.RobustOpenRouterModel"),
            patch(
                "nohiki_llm_client.providers.factory._resolve_effective_profile",
                return_value=None,
            ),
        ):
            create_model(config, provider, transport_clients=[])

        assert openai_client.call_args.kwargs["base_url"] == "https://gateway.test/providers/openrouter/v1"
        assert openai_client.call_args.kwargs["http_client"] is http_client
        assert openai_client.call_args.kwargs["api_key"] == "test-key"
        openrouter_provider.assert_called_once_with(openai_client=openai_client.return_value)

    @pytest.mark.asyncio
    async def test_openrouter_client_ignores_ambient_openai_tenant_headers(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The OpenAI SDK client used by OpenRouter cannot inherit tenant headers."""
        monkeypatch.setenv("OPENAI_ORG_ID", "attacker-org")
        monkeypatch.setenv("OPENAI_PROJECT_ID", "attacker-project")
        base_url = "https://openrouter-gateway.example.test/v1"

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/models"
            assert request.headers["Authorization"] == "Bearer model-test-key"
            assert "OpenAI-Organization" not in request.headers
            assert "OpenAI-Project" not in request.headers
            return httpx.Response(200, json={"object": "list", "data": []})

        config = LLMModelConfig(
            model="openrouter:test/model",
            base_url=base_url,
            api_key=SecretStr("model-test-key"),
        )
        provider = LLMProviderSettings(models=[config])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(config, provider, transport_clients=[])
                assert isinstance(model, OpenRouterModel)
                assert isinstance(model.provider, OpenRouterProvider)
                response = await model.provider.client.models.list()

        assert response.data == []

    @pytest.mark.parametrize("auth_mode", ["api_key", "adc"])
    def test_google_vertex_explicit_config_ignores_provider_environment(
        self, auth_mode: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Vertex gateway, credential, project, and location come only from the model."""
        monkeypatch.setenv("GOOGLE_API_KEY", "poisoned-process-key")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "poisoned-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "poisoned-location")
        base_url = "https://vertex-gateway.test/google/v1"
        config_kwargs: dict[str, object] = {
            "model": "google-vertex:gemini-2.5-flash",
            "base_url": base_url,
        }
        expected: dict[str, object] = {
            "http_client": MagicMock(),
            "base_url": base_url,
        }
        if auth_mode == "api_key":
            config_kwargs["api_key"] = SecretStr("model-key")
            expected["api_key"] = "model-key"
        else:
            config_kwargs["google_project"] = "model-project"
            config_kwargs["google_location"] = "model-location"
            expected["project"] = "model-project"
            expected["location"] = "model-location"

        config = LLMModelConfig.model_validate(config_kwargs)
        provider_settings = LLMProviderSettings(models=[config])
        http_client = expected["http_client"]
        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ),
            patch("nohiki_llm_client.providers.factory.GoogleCloudProvider") as provider,
            patch("nohiki_llm_client.providers.factory.GoogleModel"),
        ):
            create_model(config, provider_settings, transport_clients=[])

        provider.assert_called_once_with(**expected)

    @pytest.mark.parametrize(
        ("auth_mode", "expected_base_url"),
        [
            ("api_key", "https://aiplatform.googleapis.com/"),
            ("adc", "https://model-region-aiplatform.googleapis.com/"),
        ],
    )
    def test_google_vertex_computes_explicit_base_without_config_override(
        self,
        auth_mode: str,
        expected_base_url: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Installed provider always receives an explicit base despite poisoned env."""
        monkeypatch.setenv("GOOGLE_API_KEY", "poisoned-process-key")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "poisoned-project")
        monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "poisoned-region")
        config_kwargs: dict[str, object] = {"model": "google-vertex:gemini-2.5-flash"}
        expected: dict[str, object] = {
            "http_client": MagicMock(),
            "base_url": expected_base_url,
        }
        if auth_mode == "api_key":
            config_kwargs["api_key"] = SecretStr("model-key")
            expected["api_key"] = "model-key"
        else:
            config_kwargs["google_project"] = "model-project"
            config_kwargs["google_location"] = "model-region"
            expected["project"] = "model-project"
            expected["location"] = "model-region"

        config = LLMModelConfig.model_validate(config_kwargs)
        provider_settings = LLMProviderSettings(models=[config])
        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=expected["http_client"],
            ),
            patch("nohiki_llm_client.providers.factory.GoogleCloudProvider") as provider,
            patch("nohiki_llm_client.providers.factory.GoogleModel"),
        ):
            create_model(config, provider_settings, transport_clients=[])

        provider.assert_called_once_with(**expected)

    def test_vertex_claude_explicit_config_ignores_provider_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Claude-on-Vertex receives exact model routing despite poisoned SDK env."""
        monkeypatch.setenv("ANTHROPIC_VERTEX_BASE_URL", "https://poisoned-vertex.test")
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "poisoned-project")
        monkeypatch.setenv("CLOUD_ML_REGION", "poisoned-region")
        base_url = "https://vertex-gateway.test/anthropic"
        config = LLMModelConfig(
            model="google-vertex:claude-sonnet-4-5",
            base_url=base_url,
            google_project="model-project",
            google_location="model-region",
        )
        provider_settings = LLMProviderSettings(models=[config])
        http_client = MagicMock()
        with (
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ),
            patch("nohiki_llm_client.providers.factory.AsyncAnthropicVertex") as vertex,
            patch("nohiki_llm_client.providers.factory.AnthropicProvider"),
            patch("nohiki_llm_client.providers.factory.AnthropicModel"),
        ):
            create_model(config, provider_settings, transport_clients=[])

        vertex.assert_called_once_with(
            project_id="model-project",
            region="model-region",
            base_url=f"{base_url}/v1",
            http_client=http_client,
        )

    @pytest.mark.asyncio
    async def test_provider_public_client_closes_owned_retry_client(self) -> None:
        """Closing the public provider client closes the factory-owned HTTP client."""
        from unittest.mock import MagicMock, patch

        import httpx

        config = LLMModelConfig(model="openai:test-model", tls_ca_file="/run/model-ca/ca.crt")
        provider = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"openai": "test-key"}),
        )
        http_client = MagicMock(spec=httpx.AsyncClient)

        with patch(
            "nohiki_llm_client.providers.factory._create_retrying_http_client",
            return_value=http_client,
        ):
            model = create_model(config, provider, transport_clients=[])
        assert isinstance(model, OpenAIResponsesModel)

        await model.client.close()
        http_client.aclose.assert_awaited_once_with()


class TestAnthropicFactory:
    """Tests for Anthropic model creation via _create_anthropic."""

    def test_create_anthropic_model(self, llm_settings_anthropic: LLMSettings) -> None:
        """Direct Anthropic model creation returns AnthropicModel with correct name."""
        from pydantic_ai.models.anthropic import AnthropicModel

        model = create_model(
            llm_settings_anthropic.provider.models[0],
            llm_settings_anthropic.provider,
            transport_clients=[],
        )
        assert isinstance(model, AnthropicModel)
        assert model.model_name == "claude-sonnet-4-20250514"

    def test_create_anthropic_model_with_base_url(self) -> None:
        """Custom base_url is owned by the explicitly constructed SDK client."""
        config = LLMModelConfig(
            model="anthropic:claude-sonnet-4-20250514",
            base_url="https://anthropic.example.com",
        )
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-key"}),
        )
        with (
            patch("nohiki_llm_client.providers.factory.AsyncAnthropic") as client,
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as provider,
        ):
            create_model(config, provider_settings, transport_clients=[])

        assert client.call_args.kwargs["base_url"] == "https://anthropic.example.com"
        assert client.call_args.kwargs["api_key"] == "test-key"
        assert client.call_args.kwargs["default_headers"] == {}
        provider.assert_called_once_with(anthropic_client=client.return_value)

    @pytest.mark.asyncio
    async def test_custom_anthropic_base_url_uses_native_messages_path_and_model_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit Anthropic endpoint and key override all process environment."""
        from unittest.mock import patch

        import httpx

        base_url = "https://anthropic-gateway.example.test"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "poisoned-process-secret")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://poisoned-anthropic.test")
        monkeypatch.setenv(
            "ANTHROPIC_CUSTOM_HEADERS",
            "x-api-key: attacker-key\n"
            "authorization: Bearer attacker\n"
            "X-Ambient: first\n"
            "x-ambient: second\n"
            "X-Other-Ambient: third",
        )

        def handle_request(request: httpx.Request) -> httpx.Response:
            assert request.url == f"{base_url}/v1/messages"
            assert request.headers["x-api-key"] == "model-test-key"
            assert "Authorization" not in request.headers
            assert "x-ambient" not in request.headers
            assert "x-other-ambient" not in request.headers
            return httpx.Response(
                200,
                json={
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            )

        config = LLMModelConfig(
            model="anthropic:claude-sonnet-4-6",
            base_url=base_url,
            api_key=SecretStr("model-test-key"),
        )
        provider = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "registry-test-key"}),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as http_client:
            with patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=http_client,
            ):
                model = create_model(config, provider, transport_clients=[])
                assert isinstance(model, AnthropicModel)
                response = await model.client.messages.create(
                    model=config.model_name,
                    max_tokens=1,
                    messages=[{"role": "user", "content": "hello"}],
                )

        assert response.content[0].type == "text"

    @pytest.mark.asyncio
    async def test_create_anthropic_model_with_caching_enabled(self) -> None:
        """Caching enabled sets all three AnthropicModelSettings cache fields to the TTL."""
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-key"}),
        )
        caching = LLMCachingSettings(enabled=True, ttl="5m")
        transport = MagicMock(spec=httpx.AsyncClient)
        transport.aclose = AsyncMock()
        transports: list[httpx.AsyncClient] = []
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=transport,
            ),
        ):
            mock_ap.return_value = MagicMock()
            create_model(
                config,
                provider_settings,
                caching=caching,
                transport_clients=transports,
            )
            settings = mock_am.call_args.kwargs["settings"]
            assert settings["anthropic_cache_instructions"] == "5m"
            assert settings["anthropic_cache_tool_definitions"] == "5m"
            assert settings["anthropic_cache_messages"] == "5m"
        assert transports == [transport]
        await transports[0].aclose()
        transport.aclose.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_create_anthropic_model_caching_disabled(self) -> None:
        """Caching disabled does not set any cache fields in settings."""
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-key"}),
        )
        caching = LLMCachingSettings(enabled=False)
        transport = MagicMock(spec=httpx.AsyncClient)
        transport.aclose = AsyncMock()
        transports: list[httpx.AsyncClient] = []
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=transport,
            ),
        ):
            mock_ap.return_value = MagicMock()
            create_model(
                config,
                provider_settings,
                caching=caching,
                transport_clients=transports,
            )
            settings = mock_am.call_args.kwargs["settings"]
            assert "anthropic_cache_instructions" not in settings
            assert "anthropic_cache_tool_definitions" not in settings
            assert "anthropic_cache_messages" not in settings
        assert transports == [transport]
        await transports[0].aclose()
        transport.aclose.assert_awaited_once_with()

    def test_create_anthropic_model_seals_public_base_url(self) -> None:
        """Direct Anthropic routing cannot be redirected by provider SDK environment."""
        config = LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-key"}),
        )
        with (
            patch("nohiki_llm_client.providers.factory.AsyncAnthropic") as client,
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as provider,
        ):
            create_model(config, provider_settings, transport_clients=[])

        assert client.call_args.kwargs["base_url"] == "https://api.anthropic.com"
        assert client.call_args.kwargs["default_headers"] == {}
        provider.assert_called_once_with(anthropic_client=client.return_value)

    def test_create_anthropic_model_with_max_tokens(self) -> None:
        """max_tokens is propagated to AnthropicModelSettings."""
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-key"}),
            max_tokens=4096,
        )
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
        ):
            mock_ap.return_value = MagicMock()
            create_model(config, provider_settings, transport_clients=[])
            settings = mock_am.call_args.kwargs["settings"]
            assert settings["max_tokens"] == 4096

    def test_create_anthropic_api_key_from_registry(self) -> None:
        """The owning registry key is passed only to the explicit SDK client."""
        config = LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "registry-key"}),
        )
        with (
            patch("nohiki_llm_client.providers.factory.AsyncAnthropic") as client,
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as provider,
        ):
            create_model(config, provider_settings, transport_clients=[])

        assert client.call_args.kwargs["api_key"] == "registry-key"
        assert client.call_args.kwargs["default_headers"] == {}
        provider.assert_called_once_with(anthropic_client=client.return_value)

    @pytest.mark.asyncio
    async def test_create_anthropic_caching_ttl_1h(self) -> None:
        """Caching with 1h TTL correctly sets all cache fields to '1h'."""
        from unittest.mock import MagicMock, patch

        config = LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")
        provider_settings = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-key"}),
        )
        caching = LLMCachingSettings(enabled=True, ttl="1h")
        transport = MagicMock(spec=httpx.AsyncClient)
        transport.aclose = AsyncMock()
        transports: list[httpx.AsyncClient] = []
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
            patch(
                "nohiki_llm_client.providers.factory._create_retrying_http_client",
                return_value=transport,
            ),
        ):
            mock_ap.return_value = MagicMock()
            create_model(
                config,
                provider_settings,
                caching=caching,
                transport_clients=transports,
            )
            settings = mock_am.call_args.kwargs["settings"]
            assert settings["anthropic_cache_instructions"] == "1h"
            assert settings["anthropic_cache_tool_definitions"] == "1h"
            assert settings["anthropic_cache_messages"] == "1h"
        assert transports == [transport]
        await transports[0].aclose()
        transport.aclose.assert_awaited_once_with()


class TestOpenRouterRouting:
    """Tests the request routing payload built independently for each model."""

    @pytest.mark.parametrize("allow_fallbacks", [False, True])
    def test_allow_fallbacks_is_preserved_in_request_settings(self, *, allow_fallbacks: bool) -> None:
        provider = LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:synthetic/candidate")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "synthetic-key"}),
        )
        config = LLMModelConfig(
            model="openrouter:synthetic/candidate",
            provider_order=("synthetic-route",),
            provider_allow_fallbacks=allow_fallbacks,
        )

        context = _prepare_openrouter_context(config, provider, MagicMock(spec=httpx.AsyncClient))
        extra_body = _require_mapping(context.settings["extra_body"])
        routing = _require_mapping(extra_body["provider"])

        assert routing == {
            "order": ["synthetic-route"],
            "allow_fallbacks": allow_fallbacks,
        }

    def test_routing_does_not_leak_between_models(self) -> None:
        provider = LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:synthetic/primary")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "synthetic-key"}),
        )
        routed = LLMModelConfig(
            model="openrouter:synthetic/routed",
            provider_order=("route-a",),
            provider_allow_fallbacks=False,
        )
        unrestricted = LLMModelConfig(model="openrouter:synthetic/unrestricted")

        routed_context = _prepare_openrouter_context(routed, provider, MagicMock(spec=httpx.AsyncClient))
        unrestricted_context = _prepare_openrouter_context(unrestricted, provider, MagicMock(spec=httpx.AsyncClient))

        assert "extra_body" in routed_context.settings
        assert "extra_body" not in unrestricted_context.settings


class TestOpenRouterZdrRouting:
    """Tests that ``provider_zdr`` folds Zero Data Retention into request routing."""

    @staticmethod
    def _provider() -> LLMProviderSettings:
        return LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:synthetic/candidate")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "synthetic-key"}),
        )

    def test_zdr_without_order_emits_provider_zdr_only(self) -> None:
        """ZDR alone produces a provider object holding only ``zdr: True``."""
        config = LLMModelConfig(model="openrouter:synthetic/candidate", provider_zdr=True)

        context = _prepare_openrouter_context(config, self._provider(), MagicMock(spec=httpx.AsyncClient))
        extra_body = _require_mapping(context.settings["extra_body"])
        routing = _require_mapping(extra_body["provider"])

        assert routing == {"zdr": True}

    def test_zdr_with_explicit_order_and_disabled_fallbacks(self) -> None:
        """ZDR merges alongside an explicit pinned order with fallbacks disabled."""
        config = LLMModelConfig(
            model="openrouter:synthetic/candidate",
            provider_order=("zdr-endpoint",),
            provider_allow_fallbacks=False,
            provider_zdr=True,
        )

        context = _prepare_openrouter_context(config, self._provider(), MagicMock(spec=httpx.AsyncClient))
        routing = _require_mapping(_require_mapping(context.settings["extra_body"])["provider"])

        assert routing == {
            "order": ["zdr-endpoint"],
            "allow_fallbacks": False,
            "zdr": True,
        }

    def test_zdr_merge_preserves_unrelated_extra_body_and_provider_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The routing merge preserves unrelated extra_body keys and provider sub-keys."""
        seeded = OpenRouterModelSettings(
            temperature=0.0,
            openrouter_usage=OpenRouterUsageConfig(include=True),
        )
        seeded["extra_body"] = {
            "reasoning": {"effort": "high"},
            "provider": {"sort": "price"},
        }
        monkeypatch.setattr(factory, "_build_openrouter_settings", lambda *_args, **_kwargs: seeded)
        config = LLMModelConfig(
            model="openrouter:synthetic/candidate",
            provider_order=("zdr-endpoint",),
            provider_allow_fallbacks=False,
            provider_zdr=True,
        )

        context = _prepare_openrouter_context(config, self._provider(), MagicMock(spec=httpx.AsyncClient))
        extra_body = _require_mapping(context.settings["extra_body"])

        assert extra_body["reasoning"] == {"effort": "high"}
        routing = _require_mapping(extra_body["provider"])
        assert routing == {
            "sort": "price",
            "order": ["zdr-endpoint"],
            "allow_fallbacks": False,
            "zdr": True,
        }

    def test_non_openrouter_transport_ignores_provider_zdr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-OpenRouter model carries ``provider_zdr`` but never emits ZDR routing."""
        from unittest.mock import MagicMock

        config = LLMModelConfig(model="openai:gpt-4o", provider_zdr=True)
        provider = LLMProviderSettings(
            models=[config],
            api_keys=ApiKeyRegistry.model_validate({"openai": "openai-key"}),
        )

        assert config.provider_zdr is True

        captured = MagicMock(return_value=MagicMock())
        monkeypatch.setattr(factory, "OpenAIResponsesModel", captured)
        create_model(config, provider, transport_clients=[])

        settings = captured.call_args.kwargs["settings"]
        assert "extra_body" not in settings


class TestApiKeyResolution:
    """Tests for _resolve_api_key."""

    def test_resolve_explicit_key(self, llm_settings: LLMSettings) -> None:
        """Per-model api_key takes precedence over registry."""
        config = LLMModelConfig(model="openai:gpt-4o", api_key=SecretStr("explicit"))
        key = _resolve_api_key(config, llm_settings.provider)
        assert key == "explicit"

    def test_resolve_key_from_registry(self, llm_settings: LLMSettings) -> None:
        """Keys from the api_keys registry resolve for any model with that provider."""
        config = LLMModelConfig(model="openrouter:other-model")
        key = _resolve_api_key(config, llm_settings.provider)
        assert key == "test-key"

    def test_resolve_never_returns_empty_for_local_provider(self, llm_settings: LLMSettings) -> None:
        """The authenticated-provider resolver never returns an empty string."""
        config = LLMModelConfig(model="ollama:llama3", base_url="http://local/v1")

        with pytest.raises(ValueError, match="No API key for model"):
            _resolve_api_key(config, llm_settings.provider)

    def test_resolve_missing_key_raises(self, llm_settings: LLMSettings) -> None:
        """Provider not in registry and no explicit key raises ValueError."""
        config = LLMModelConfig(model="openai:gpt-4o")
        with pytest.raises(ValueError, match="No API key for model"):
            _resolve_api_key(config, llm_settings.provider)

    @pytest.mark.parametrize("api_key", ["", " ", "\t"])
    def test_resolve_rejects_blank_explicit_key(self, api_key: str) -> None:
        """The final resolver never returns an empty explicit credential."""
        config = LLMModelConfig.model_construct(
            model="openai:gpt-4o",
            api_key=SecretStr(api_key),
            base_url=None,
        )
        provider = LLMProviderSettings.model_construct(
            models=[config],
            api_keys=ApiKeyRegistry(),
        )

        with pytest.raises(ValueError, match=r"API key|api_key"):
            _resolve_api_key(config, provider)

    @pytest.mark.parametrize("api_key", ["", " ", "\t"])
    def test_resolve_rejects_blank_registry_key(self, api_key: str) -> None:
        """The final resolver never returns an empty registry credential."""
        config = LLMModelConfig.model_construct(
            model="openai:gpt-4o",
            api_key=None,
            base_url=None,
        )
        registry = ApiKeyRegistry.model_construct(openai=SecretStr(api_key))
        provider = LLMProviderSettings.model_construct(
            models=[config],
            api_keys=registry,
        )

        with pytest.raises(ValueError, match=r"API key|api_key"):
            _resolve_api_key(config, provider)

    def test_explicit_key_overrides_registry(self) -> None:
        """Per-model api_key wins over registry entry for same provider."""
        provider = LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:m")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "registry-key"}),
        )
        config = LLMModelConfig(model="openrouter:other", api_key=SecretStr("explicit-key"))
        assert _resolve_api_key(config, provider) == "explicit-key"


class TestResolveChain:
    """Tests for resolve_chain."""

    def test_none_returns_default(self, llm_settings: LLMSettings) -> None:
        """None chain_name returns the default provider."""
        result = resolve_chain(None, llm_settings)
        assert result is llm_settings.provider

    def test_unknown_name_returns_default(self, llm_settings: LLMSettings) -> None:
        """Unknown chain name falls back to default provider."""
        result = resolve_chain("nonexistent", llm_settings)
        assert result is llm_settings.provider

    def test_named_chain_returned(self) -> None:
        """Named chain is returned when present."""
        skill_chain = LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:small/model")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "k"}),
        )
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openrouter:big/model")],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "k"}),
            ),
            chains={"skill_clarification": skill_chain},
        )
        result = resolve_chain("skill_clarification", settings)
        assert result is skill_chain
        assert result.models[0].model == "openrouter:small/model"

    def test_provider_fallback_inherits_same_provider_base_url(self) -> None:
        """A same-provider fallback stays on the explicitly configured endpoint."""
        settings = LLMSettings.model_validate(
            {
                "provider": {
                    "models": [
                        {
                            "model": "openai:primary",
                            "base_url": "https://gateway.example.com/v1",
                        },
                        {"model": "openai:fallback"},
                    ]
                }
            }
        )

        assert [model.base_url for model in settings.provider.models] == [
            "https://gateway.example.com/v1",
            "https://gateway.example.com/v1",
        ]

    def test_named_chain_inherits_default_provider_base_url(self) -> None:
        """Named chains inherit an endpoint from the matching default provider."""
        settings = LLMSettings.model_validate(
            {
                "provider": {
                    "models": [
                        {
                            "model": "anthropic:primary",
                            "base_url": "https://anthropic.example.com",
                        }
                    ],
                    "api_keys": {"anthropic": "test-key"},
                },
                "chains": {"judge": {"models": [{"model": "anthropic:fallback"}]}},
            }
        )

        assert settings.chains["judge"].models[0].base_url == "https://anthropic.example.com"

    def test_explicit_base_urls_are_preserved_for_same_provider_models(self) -> None:
        """Inheritance never overwrites explicit endpoints, and the first endpoint is inherited."""
        settings = LLMSettings.model_validate(
            {
                "provider": {
                    "models": [
                        {
                            "model": "openai:primary",
                            "base_url": "https://first.example.com/v1",
                        },
                        {
                            "model": "openai:alternate",
                            "base_url": "https://second.example.com/v1",
                        },
                        {"model": "openai:inherited"},
                    ]
                }
            }
        )

        assert [model.base_url for model in settings.provider.models] == [
            "https://first.example.com/v1",
            "https://second.example.com/v1",
            "https://first.example.com/v1",
        ]

    def test_indexed_dict_models_participate_in_base_url_inheritance(self) -> None:
        """Nested-settings indexed dictionaries behave like ordered model lists."""
        settings = LLMSettings.model_validate(
            {
                "provider": {
                    "models": {
                        "0": {
                            "model": "openai:primary",
                            "base_url": "http://localhost:8000/v1",
                        },
                        "1": {"model": "openai:fallback"},
                    }
                }
            }
        )

        assert [model.model for model in settings.provider.models] == [
            "openai:primary",
            "openai:fallback",
        ]
        assert settings.provider.models[1].base_url == "http://localhost:8000/v1"


class TestOllamaJsonSchemaTransformer:
    """Tests for OllamaJsonSchemaTransformer."""

    def test_init_forces_strict_mode(self) -> None:
        """Transformer can be instantiated with a valid schema without raising."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        }
        transformer = OllamaJsonSchemaTransformer(schema)
        assert isinstance(transformer, OllamaJsonSchemaTransformer)

    def test_strict_param_ignored(self) -> None:
        """Explicit strict=False is silently overridden to True for Ollama compatibility."""
        schema: dict[str, object] = {"type": "object"}
        transformer = OllamaJsonSchemaTransformer(schema, strict=False)
        assert isinstance(transformer, OllamaJsonSchemaTransformer)


_SCHEMA_WITH_DEFS: dict[str, object] = {
    "type": "object",
    "$defs": {
        "Address": {
            "type": "object",
            "properties": {
                "city": {"type": "string"},
                "country": {"type": "string"},
            },
            "required": ["city", "country"],
            "additionalProperties": False,
        }
    },
    "properties": {
        "name": {"type": "string"},
        "home": {"$ref": "#/$defs/Address"},
        "work": {"$ref": "#/$defs/Address"},
    },
    "required": ["name", "home", "work"],
}


class TestInlinedRefsJsonSchemaTransformer:
    """Tests for InlinedRefsJsonSchemaTransformer."""

    def test_is_subclass_of_openai_transformer(self) -> None:
        """InlinedRefsJsonSchemaTransformer extends OpenAIJsonSchemaTransformer."""
        assert issubclass(InlinedRefsJsonSchemaTransformer, OpenAIJsonSchemaTransformer)

    def test_instantiation_succeeds(self) -> None:
        """Transformer instantiates without raising."""
        schema: dict[str, object] = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }
        transformer = InlinedRefsJsonSchemaTransformer(schema)
        assert isinstance(transformer, InlinedRefsJsonSchemaTransformer)

    def test_kwargs_absorbed_without_error(self) -> None:
        """Arbitrary kwargs (e.g. strict=True) are silently ignored."""
        schema: dict[str, object] = {"type": "object"}
        transformer = InlinedRefsJsonSchemaTransformer(schema, strict=True)
        assert isinstance(transformer, InlinedRefsJsonSchemaTransformer)

    def test_strict_is_none_preserves_constraints(self) -> None:
        """strict=None is used so schema constraints are preserved as model guidance."""
        schema: dict[str, object] = {"type": "object"}
        transformer = InlinedRefsJsonSchemaTransformer(schema)
        assert transformer.strict is None

    def test_prefer_inlined_defs_is_true(self) -> None:
        """prefer_inlined_defs is True to trigger $ref resolution."""
        schema: dict[str, object] = {"type": "object"}
        transformer = InlinedRefsJsonSchemaTransformer(schema)
        assert transformer.prefer_inlined_defs is True

    def test_walk_eliminates_defs_section(self) -> None:
        """Transformed schema has no $defs key."""
        transformer = InlinedRefsJsonSchemaTransformer(_SCHEMA_WITH_DEFS)
        result = transformer.walk()
        assert "$defs" not in result

    def test_walk_eliminates_all_refs(self) -> None:
        """Transformed schema has no $ref pointers anywhere."""
        transformer = InlinedRefsJsonSchemaTransformer(_SCHEMA_WITH_DEFS)
        result = transformer.walk()
        result_str = json.dumps(result)
        assert "$ref" not in result_str

    def test_walk_inlines_nested_object_at_usage_site(self) -> None:
        """Properties that were $ref-backed now carry the inline object schema."""
        transformer = InlinedRefsJsonSchemaTransformer(_SCHEMA_WITH_DEFS)
        result = transformer.walk()
        props = result.get("properties", {})
        assert isinstance(props, dict)
        for key in ("home", "work"):
            nested = props[key]
            assert isinstance(nested, dict)
            assert nested.get("type") == "object", f"'{key}' should be an inlined object"
            assert "$ref" not in nested

    def test_constraints_preserved_in_transformed_schema(self) -> None:
        """MinLength / maxLength constraints survive the walk (strict=None, not stripped)."""
        constrained: dict[str, object] = {
            "type": "object",
            "properties": {"title": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["title"],
        }
        result = InlinedRefsJsonSchemaTransformer(constrained).walk()
        props = result.get("properties", {})
        assert isinstance(props, dict)
        title_schema = props["title"]
        assert isinstance(title_schema, dict)
        assert title_schema.get("minLength") == 1
        assert title_schema.get("maxLength") == 200

    def test_walk_inlined_schema_not_larger_than_standard_for_unique_refs(self) -> None:
        """When each $defs entry is referenced exactly once, inlining does not bloat."""
        unique_ref_schema: dict[str, object] = {
            "type": "object",
            "$defs": {
                "A": {
                    "type": "object",
                    "properties": {"x": {"type": "string"}},
                    "required": ["x"],
                },
                "B": {
                    "type": "object",
                    "properties": {"y": {"type": "integer"}},
                    "required": ["y"],
                },
            },
            "properties": {
                "a": {"$ref": "#/$defs/A"},
                "b": {"$ref": "#/$defs/B"},
            },
            "required": ["a", "b"],
        }
        std_result = json.dumps(OpenAIJsonSchemaTransformer(unique_ref_schema, strict=None).walk())
        inlined_result = json.dumps(InlinedRefsJsonSchemaTransformer(unique_ref_schema).walk())
        assert len(inlined_result) <= len(std_result) + 50

    def test_walk_inlined_schema_is_larger_for_shared_refs(self) -> None:
        """When one $defs entry is referenced multiple times, inlining causes expected bloat."""
        transformer = InlinedRefsJsonSchemaTransformer(_SCHEMA_WITH_DEFS)
        std_transformer = OpenAIJsonSchemaTransformer(_SCHEMA_WITH_DEFS, strict=None)
        xfr_result = json.dumps(transformer.walk())
        std_result = json.dumps(std_transformer.walk())
        assert len(xfr_result) > len(std_result)

    def test_flat_schema_unchanged_by_inlining(self) -> None:
        """Schemas without $defs/$ref are not affected by inlining mode."""
        flat_schema: dict[str, object] = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name", "age"],
        }
        result = InlinedRefsJsonSchemaTransformer(flat_schema).walk()
        assert result.get("type") == "object"
        assert "$defs" not in result
        assert "$ref" not in json.dumps(result)


class TestSelectOpenRouterQuirks:
    """Tests for select_openrouter_quirks."""

    def test_xiaomi_model_returns_inlined_refs_profile(self) -> None:
        """Any xiaomi/* model slug returns quirks with the inlined-refs profile."""
        quirks = select_openrouter_quirks("xiaomi/mimo-v2-flash")
        assert quirks.profile is INLINED_REFS_OPENROUTER_PROFILE

    def test_xiaomi_other_model_returns_inlined_refs_profile(self) -> None:
        """Profile selection applies to the whole xiaomi provider, not one specific model."""
        quirks = select_openrouter_quirks("xiaomi/mimo-v3-ultra")
        assert quirks.profile is INLINED_REFS_OPENROUTER_PROFILE

    def test_meta_llama_suppresses_reasoning(self) -> None:
        """meta-llama models have supports_openrouter_reasoning=False."""
        quirks = select_openrouter_quirks("meta-llama/llama-4-maverick")
        assert quirks.supports_openrouter_reasoning is False

    def test_meta_llama_has_tool_choice_required_false(self) -> None:
        """meta-llama quirks carry a profile that disables forced tool_choice."""
        quirks = select_openrouter_quirks("meta-llama/llama-4-maverick")
        assert quirks.profile is META_LLAMA_OPENROUTER_PROFILE

    def test_qwen_vl_suppresses_reasoning(self) -> None:
        """qwen/qwen3-vl models have supports_openrouter_reasoning=False."""
        quirks = select_openrouter_quirks("qwen/qwen3-vl-30b-a3b-thinking")
        assert quirks.supports_openrouter_reasoning is False

    def test_qwen_next_suppresses_reasoning(self) -> None:
        """qwen/qwen3-next models have supports_openrouter_reasoning=False."""
        quirks = select_openrouter_quirks("qwen/qwen3-next-80b-a3b-thinking")
        assert quirks.supports_openrouter_reasoning is False

    def test_qwen_next_uses_native_output_profile(self) -> None:
        """qwen/qwen3-next models use native structured output to bypass Hermes wrapper."""
        quirks = select_openrouter_quirks("qwen/qwen3-next-80b-a3b-thinking")
        assert quirks.profile is QWEN_NEXT_OPENROUTER_PROFILE

    def test_gpt_oss_exacto_returns_inlined_refs_profile(self) -> None:
        """openai/gpt-oss-120b:exacto has the inlined-refs profile for DeepInfra $ref bug."""
        quirks = select_openrouter_quirks("openai/gpt-oss-120b:exacto")
        assert quirks.profile is INLINED_REFS_OPENROUTER_PROFILE

    def test_google_model_returns_default_quirks(self) -> None:
        """Google provider has no registered quirks entry."""
        assert select_openrouter_quirks("google/gemini-3-flash") == OpenRouterModelQuirks()

    def test_anthropic_model_returns_default_quirks(self) -> None:
        """Anthropic provider has no registered quirks entry."""
        assert select_openrouter_quirks("anthropic/claude-3-5-sonnet") == OpenRouterModelQuirks()

    def test_openai_gpt4o_returns_default_quirks(self) -> None:
        """openai/gpt-4o has no registered quirks (only the specific gpt-oss-exacto slug does)."""
        assert select_openrouter_quirks("openai/gpt-4o") == OpenRouterModelQuirks()

    def test_unknown_provider_returns_default_quirks(self) -> None:
        """Unrecognised provider prefix returns the default quirks instance."""
        assert select_openrouter_quirks("unknown-provider/some-model") == OpenRouterModelQuirks()

    def test_model_slug_without_slash_returns_default_quirks(self) -> None:
        """Model slug without '/' prefix produces no match."""
        assert select_openrouter_quirks("solo-model") == OpenRouterModelQuirks()

    def test_longer_prefix_wins_over_shorter(self) -> None:
        """qwen/qwen3-next prefix wins over qwen/qwen3-vl for a next-series model."""
        next_quirks = select_openrouter_quirks("qwen/qwen3-next-80b-a3b-thinking")
        vl_quirks = select_openrouter_quirks("qwen/qwen3-vl-30b-a3b-instruct")
        assert next_quirks.profile is QWEN_NEXT_OPENROUTER_PROFILE
        assert vl_quirks.profile is None


class TestInlinedRefsProfileConstants:
    """Tests for INLINED_REFS_OPENROUTER_PROFILE constant."""

    def test_profile_uses_inlined_refs_transformer(self) -> None:
        """json_schema_transformer is InlinedRefsJsonSchemaTransformer (inlined $defs, strict=None)."""
        assert INLINED_REFS_OPENROUTER_PROFILE["json_schema_transformer"] is InlinedRefsJsonSchemaTransformer


class TestMetaLlamaProfileConstants:
    """Tests for META_LLAMA_OPENROUTER_PROFILE constant."""

    def test_profile_disables_tool_choice_required(self) -> None:
        """openai_supports_tool_choice_required is False to avoid HTTP 400 from Llama backends."""
        assert META_LLAMA_OPENROUTER_PROFILE["openai_supports_tool_choice_required"] is False


class TestQwenNextProfileConstants:
    """Tests for QWEN_NEXT_OPENROUTER_PROFILE constant."""

    def test_profile_uses_native_output_mode(self) -> None:
        """default_structured_output_mode is 'native' to bypass Hermes tool wrapping."""
        assert QWEN_NEXT_OPENROUTER_PROFILE["default_structured_output_mode"] == "native"

    def test_profile_enables_json_schema_output(self) -> None:
        """supports_json_schema_output is True (native mode requires it)."""
        assert QWEN_NEXT_OPENROUTER_PROFILE["supports_json_schema_output"] is True


class TestOpenRouterQuirksRegistry:
    """Tests for OPENROUTER_QUIRKS registry dict."""

    def test_registry_is_dict(self) -> None:
        """Registry is a plain dict."""
        assert isinstance(OPENROUTER_QUIRKS, dict)

    def test_registry_contains_xiaomi_key(self) -> None:
        """Registry has an entry for the 'xiaomi' provider."""
        assert "xiaomi" in OPENROUTER_QUIRKS

    def test_registry_xiaomi_maps_to_inlined_refs_profile(self) -> None:
        """'xiaomi' entry uses the inlined-refs profile."""
        assert OPENROUTER_QUIRKS["xiaomi"].profile is INLINED_REFS_OPENROUTER_PROFILE

    def test_registry_contains_meta_llama_key(self) -> None:
        """Registry has an entry for the 'meta-llama' provider."""
        assert "meta-llama" in OPENROUTER_QUIRKS

    def test_registry_meta_llama_suppresses_reasoning(self) -> None:
        """'meta-llama' entry disables the reasoning parameter."""
        assert OPENROUTER_QUIRKS["meta-llama"].supports_openrouter_reasoning is False

    def test_registry_meta_llama_has_profile(self) -> None:
        """'meta-llama' entry has a profile with openai_supports_tool_choice_required=False."""
        assert OPENROUTER_QUIRKS["meta-llama"].profile is META_LLAMA_OPENROUTER_PROFILE

    def test_registry_contains_qwen_next_key(self) -> None:
        """Registry has an entry for the 'qwen/qwen3-next' series."""
        assert "qwen/qwen3-next" in OPENROUTER_QUIRKS

    def test_registry_qwen_next_has_native_profile(self) -> None:
        """'qwen/qwen3-next' entry uses the native output mode profile."""
        assert OPENROUTER_QUIRKS["qwen/qwen3-next"].profile is QWEN_NEXT_OPENROUTER_PROFILE

    def test_registry_qwen_next_suppresses_reasoning(self) -> None:
        """'qwen/qwen3-next' entry also suppresses the reasoning parameter."""
        assert OPENROUTER_QUIRKS["qwen/qwen3-next"].supports_openrouter_reasoning is False

    def test_registry_contains_gpt_oss_exacto_key(self) -> None:
        """Registry has an entry for 'openai/gpt-oss-120b:exacto'."""
        assert "openai/gpt-oss-120b:exacto" in OPENROUTER_QUIRKS

    def test_registry_gpt_oss_exacto_uses_inlined_refs_profile(self) -> None:
        """'openai/gpt-oss-120b:exacto' uses inlined-refs profile for DeepInfra $ref bug."""
        assert OPENROUTER_QUIRKS["openai/gpt-oss-120b:exacto"].profile is INLINED_REFS_OPENROUTER_PROFILE


class TestResolveEffectiveProfile:
    """Tests for _resolve_effective_profile."""

    def _make_provider(self) -> tuple[object, LLMProviderSettings]:
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider(api_key="dummy")
        settings = LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:test/model")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "dummy"}),
        )
        return provider, settings

    def test_none_quirk_returns_none(self) -> None:
        """When no quirk profile is set, None is returned so the model uses provider callable."""
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider(api_key="dummy")
        result = _resolve_effective_profile(provider, "google/gemini-3-flash", None)
        assert result is None

    def test_quirk_profile_merged_with_provider_base(self) -> None:
        """Provider's base profile fields are preserved when a quirk profile is merged."""
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider(api_key="dummy")
        quirk = OpenAIModelProfile(json_schema_transformer=InlinedRefsJsonSchemaTransformer)
        result = _resolve_effective_profile(provider, "xiaomi/mimo-v2-flash", quirk)
        profile = _require_mapping(result)
        assert profile["json_schema_transformer"] is InlinedRefsJsonSchemaTransformer
        assert profile["openai_chat_send_back_thinking_parts"] == "field"
        assert profile["openai_chat_thinking_field"] == "reasoning"

    def test_quirk_profile_overrides_base_field(self) -> None:
        """A quirk profile field takes precedence over the provider's base profile value."""
        from pydantic_ai.providers.openrouter import OpenRouterProvider

        provider = OpenRouterProvider(api_key="dummy")
        quirk = OpenAIModelProfile(openai_supports_tool_choice_required=False)
        result = _resolve_effective_profile(provider, "meta-llama/llama-4-maverick", quirk)
        profile = _require_mapping(result)
        assert profile["openai_supports_tool_choice_required"] is False
        assert profile["openai_chat_send_back_thinking_parts"] == "field"


class TestCreateOpenRouterWithProfile:
    """Tests that _create_openrouter applies the correct profile per model."""

    def _make_settings(self, model: str) -> tuple[LLMModelConfig, LLMProviderSettings]:
        provider_settings = LLMProviderSettings(
            models=[LLMModelConfig(model=f"openrouter:{model}")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        return provider_settings.models[0], provider_settings

    def test_xiaomi_model_has_inlined_refs_transformer(self) -> None:
        """Xiaomi model uses InlinedRefsJsonSchemaTransformer via merged profile."""
        config, settings = self._make_settings("xiaomi/mimo-v2-flash")
        model = create_model(config, settings, transport_clients=[])
        assert isinstance(model, OpenRouterModel)
        profile = _require_mapping(model._profile)
        assert profile["json_schema_transformer"] is InlinedRefsJsonSchemaTransformer

    def test_xiaomi_model_preserves_provider_thinking_field(self) -> None:
        """Merged profile retains provider-level thinking field settings."""
        config, settings = self._make_settings("xiaomi/mimo-v2-flash")
        model = create_model(config, settings, transport_clients=[])
        profile = _require_mapping(model._profile)
        assert profile["openai_chat_send_back_thinking_parts"] == "field"
        assert profile["openai_chat_thinking_field"] == "reasoning"

    def test_gpt_oss_exacto_has_inlined_refs_transformer(self) -> None:
        """openai/gpt-oss-120b:exacto uses InlinedRefsJsonSchemaTransformer to fix DeepInfra $ref bug."""
        config, settings = self._make_settings("openai/gpt-oss-120b:exacto")
        model = create_model(config, settings, transport_clients=[])
        assert isinstance(model, OpenRouterModel)
        profile = _require_mapping(model._profile)
        assert profile["json_schema_transformer"] is InlinedRefsJsonSchemaTransformer

    def test_meta_llama_has_tool_choice_required_false(self) -> None:
        """meta-llama model profile has openai_supports_tool_choice_required=False."""
        config, settings = self._make_settings("meta-llama/llama-4-maverick")
        model = create_model(config, settings, transport_clients=[])
        assert isinstance(model, OpenRouterModel)
        profile = _require_mapping(model._profile)
        assert profile["openai_supports_tool_choice_required"] is False

    def test_meta_llama_preserves_provider_thinking_field(self) -> None:
        """meta-llama merged profile retains provider-level thinking field settings."""
        config, settings = self._make_settings("meta-llama/llama-4-maverick")
        model = create_model(config, settings, transport_clients=[])
        profile = _require_mapping(model._profile)
        assert profile["openai_chat_send_back_thinking_parts"] == "field"
        assert profile["openai_chat_thinking_field"] == "reasoning"

    def test_qwen_next_has_native_output_mode(self) -> None:
        """qwen/qwen3-next model uses native output mode to bypass Hermes tool wrapping."""
        config, settings = self._make_settings("qwen/qwen3-next-80b-a3b-thinking")
        model = create_model(config, settings, transport_clients=[])
        assert isinstance(model, OpenRouterModel)
        profile = _require_mapping(model._profile)
        assert profile["default_structured_output_mode"] == "native"


class TestCreateCachingOpenRouterWithProfile:
    """Tests that create_caching_openrouter propagates the profile."""

    def _make_caching_config(self, model: str) -> tuple[LLMModelConfig, LLMProviderSettings]:
        provider_settings = LLMProviderSettings(
            models=[LLMModelConfig(model=f"openrouter:{model}")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "test-key"}),
        )
        return provider_settings.models[0], provider_settings

    def test_xiaomi_caching_model_has_inlined_refs_transformer(self) -> None:
        """CachingOpenRouterModel for xiaomi uses InlinedRefsJsonSchemaTransformer."""
        from nohiki_llm_client.config.settings import LLMCachingSettings

        config, settings = self._make_caching_config("xiaomi/mimo-v2-flash")
        model = create_caching_openrouter(config, settings, LLMCachingSettings(enabled=True), transport_clients=[])
        assert isinstance(model, CachingOpenRouterModel)
        profile = _require_mapping(model._profile)
        assert profile["json_schema_transformer"] is InlinedRefsJsonSchemaTransformer


class TestBuildOpenRouterReasoning:
    """Tests for _build_openrouter_reasoning."""

    def test_disabled_returns_none(self) -> None:
        """Disabled reasoning effort returns None (no reasoning block sent to provider)."""
        result = _build_openrouter_reasoning("disabled")
        assert result is None


class TestModelMaxTokens:
    """Tests for max_tokens propagation across all provider builders."""

    def test_openrouter_model_with_max_tokens(self) -> None:
        """OpenRouter model is created successfully when max_tokens is set."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openrouter:test/model")],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "key"}),
                max_tokens=1000,
            )
        )
        model = create_model(settings.provider.models[0], settings.provider, transport_clients=[])
        assert isinstance(model, OpenRouterModel)

    def test_openai_model_with_max_tokens(self) -> None:
        """OpenAI model is created successfully when max_tokens is set."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openai:gpt-4o")],
                api_keys=ApiKeyRegistry.model_validate({"openai": "key"}),
                max_tokens=2048,
            )
        )
        model = create_model(settings.provider.models[0], settings.provider, transport_clients=[])
        from pydantic_ai.models.openai import OpenAIResponsesModel

        assert isinstance(model, OpenAIResponsesModel)

    def test_ollama_model_with_max_tokens(self) -> None:
        """Ollama model is created successfully when max_tokens is set."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="ollama:llama3",
                        base_url="http://localhost:11434/v1",
                    )
                ],
                max_tokens=4096,
            )
        )
        from pydantic_ai.models.openai import OpenAIChatModel

        model = create_model(settings.provider.models[0], settings.provider, transport_clients=[])
        assert isinstance(model, OpenAIChatModel)

    def test_google_vertex_model_with_max_tokens(self) -> None:
        """Google Vertex model is created successfully when max_tokens is set."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="google-vertex:gemini-2.5-flash")],
                api_keys=ApiKeyRegistry.model_validate({"google-vertex": "key"}),
                max_tokens=8192,
            )
        )
        model = create_model(settings.provider.models[0], settings.provider, transport_clients=[])
        assert isinstance(model, GoogleModel)

    def test_anthropic_model_with_max_tokens(self) -> None:
        """Anthropic model is created successfully when max_tokens is set."""
        from pydantic_ai.models.anthropic import AnthropicModel

        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="anthropic:claude-sonnet-4-20250514")],
                api_keys=ApiKeyRegistry.model_validate({"anthropic": "key"}),
                max_tokens=16384,
            )
        )
        model = create_model(settings.provider.models[0], settings.provider, transport_clients=[])
        assert isinstance(model, AnthropicModel)

    def test_openrouter_reasoning_disabled_creates_model(self) -> None:
        """OpenRouter model with reasoning_effort='disabled' is created without reasoning settings."""
        settings = LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openrouter:test/model", reasoning_effort="disabled")],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "key"}),
            )
        )
        model = create_model(settings.provider.models[0], settings.provider, transport_clients=[])
        assert isinstance(model, OpenRouterModel)


class TestAnthropicThinkingProfileOverride:
    """Tests for the profile override that prevents grammar-compilation timeouts.

    When Anthropic thinking is active, PydanticAI's prepare_request hook resolves
    output_mode='auto' to 'native' for models where supports_json_schema_output=True.
    Native mode sends the full JSON schema to Anthropic's grammar compiler, which times
    out on complex schemas (e.g. JobExtractionSchema with nested models and validators).

    The fix: pass a custom ModelProfile with supports_json_schema_output=False when
    thinking is active. This causes prepare_request to resolve 'auto' to 'prompted'
    instead, bypassing the grammar compiler entirely. Claude models with thinking are
    highly capable at following JSON schema instructions in prompted mode.

    When thinking is disabled, no profile override is needed: the model handles the
    default native mode fine without the grammar compilation pressure.
    """

    def _make_provider(self, model: str, effort: ReasoningEffort) -> LLMProviderSettings:
        return LLMProviderSettings(
            models=[LLMModelConfig(model=f"anthropic:{model}", reasoning_effort=effort)],
            api_keys=ApiKeyRegistry.model_validate({"anthropic": "test-key"}),
        )

    def test_adaptive_thinking_passes_prompted_profile(self) -> None:
        """Adaptive thinking model gets supports_json_schema_output=False profile override.

        This is the core fix: AnthropicModel must be called with a profile that disables
        native structured output when thinking is active, forcing prompted mode and
        avoiding Anthropic's grammar compiler entirely.
        """
        from unittest.mock import MagicMock, patch

        provider = self._make_provider("claude-sonnet-4-6", "high")
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
        ):
            mock_ap.return_value = MagicMock()
            create_model(provider.models[0], provider, transport_clients=[])
            profile = mock_am.call_args.kwargs.get("profile")

        assert profile is not None, "profile must be passed to AnthropicModel when thinking is active"
        assert profile["supports_json_schema_output"] is False

    def test_extended_thinking_passes_prompted_profile(self) -> None:
        """Extended thinking model also gets supports_json_schema_output=False profile override.

        Haiku uses enabled thinking (budget_tokens), which also triggers the native mode
        selection in prepare_request. Same fix applies.
        """
        from unittest.mock import MagicMock, patch

        provider = self._make_provider("claude-haiku-4-5", "high")
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
        ):
            mock_ap.return_value = MagicMock()
            create_model(provider.models[0], provider, transport_clients=[])
            profile = mock_am.call_args.kwargs.get("profile")

        assert profile is not None, "profile must be passed to AnthropicModel when thinking is active"
        assert profile["supports_json_schema_output"] is False

    def test_effort_disabled_passes_no_profile(self) -> None:
        """No profile override when thinking is disabled.

        When effort='disabled', thinking is not active so prepare_request does not
        force native mode. The default Anthropic profile is fine: no override needed.
        """
        from unittest.mock import MagicMock, patch

        provider = self._make_provider("claude-sonnet-4-6", "disabled")
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
        ):
            mock_ap.return_value = MagicMock()
            create_model(provider.models[0], provider, transport_clients=[])
            profile = mock_am.call_args.kwargs.get("profile")

        assert profile is None, "no profile override when thinking is disabled"

    def test_opus_46_low_effort_gets_prompted_profile(self) -> None:
        """All non-disabled effort levels on adaptive models get the profile override."""
        from unittest.mock import MagicMock, patch

        provider = self._make_provider("claude-opus-4-6", "low")
        with (
            patch("nohiki_llm_client.providers.factory.AnthropicProvider") as mock_ap,
            patch("nohiki_llm_client.providers.factory.AnthropicModel") as mock_am,
        ):
            mock_ap.return_value = MagicMock()
            create_model(provider.models[0], provider, transport_clients=[])
            profile = mock_am.call_args.kwargs.get("profile")

        assert profile is not None
        assert profile["supports_json_schema_output"] is False
