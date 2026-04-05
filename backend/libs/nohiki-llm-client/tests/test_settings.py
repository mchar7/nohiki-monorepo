"""Tests for LLM settings."""

from __future__ import annotations

import pytest
from nohiki_core_settings import NohikiBaseSettings
from nohiki_llm_client.config.settings import (
    ApiKeyRegistry,
    LLMMixin,
    LLMModelConfig,
    LLMProviderSettings,
    LLMSettings,
    OllamaSettings,
    _parse_ordered_models,
)
from pydantic import Field, SecretStr, ValidationError


class _BaseTestSettings(NohikiBaseSettings):
    """Base test settings with required fields populated."""

    service_name: str = "test-service"
    service_name_friendly: str = "Test Service"
    service_desc_friendly: str = "Test service for unit tests"
    service_version: str = "0.0.1-test"


class _TestSettingsWithLLM(LLMMixin, _BaseTestSettings):
    """Test settings with LLM mixin."""

    llm: LLMSettings = Field(
        default_factory=lambda: LLMSettings(
            provider=LLMProviderSettings(
                models=[LLMModelConfig(model="openrouter:test/model")],
                api_keys=ApiKeyRegistry.model_validate({"openrouter": "test"}),
            )
        )
    )


class TestParseOrderedModels:
    """Tests for the _parse_ordered_models validator."""

    def test_none_input_returns_empty_list(self) -> None:
        """None input returns an empty list."""
        assert _parse_ordered_models(None) == []

    def test_list_input_returned_as_is(self) -> None:
        """List input is passed through unchanged."""
        items = [{"model": "openai:gpt-4o"}]
        assert _parse_ordered_models(items) == items

    def test_unknown_type_returns_empty_list(self) -> None:
        """Non-dict, non-list, non-None input falls back to empty list."""
        assert _parse_ordered_models(42) == []

    def test_dict_with_numeric_keys_sorted(self) -> None:
        """Dict with numeric string keys is sorted by key and converted to list."""
        result = _parse_ordered_models({"1": "b", "0": "a", "2": "c"})
        assert result == ["a", "b", "c"]


class TestLLMModelConfig:
    """Tests for LLMModelConfig."""

    def test_provider_model_extraction(self) -> None:
        """Test provider and model name extraction."""
        config = LLMModelConfig(model="openrouter:google/gemini-3-flash", api_key=SecretStr("key"))
        assert config.provider_name == "openrouter"
        assert config.model_name == "google/gemini-3-flash"

    def test_invalid_format_raises(self) -> None:
        """Test invalid model format raises ValueError."""
        with pytest.raises(ValidationError, match="must use 'provider:model_name'"):
            LLMModelConfig(model="invalid-format", api_key=SecretStr("key"))

    @pytest.mark.parametrize(
        "model",
        ["", " ", "openai:", "openai:   ", ":model", "   :model", " \t: \t"],
    )
    @pytest.mark.parametrize("chain_position", ["primary", "fallback"])
    def test_model_provider_segments_reject_blank_in_every_chain_entry(self, model: str, chain_position: str) -> None:
        """Neither a primary nor fallback may have blank provider/model identity."""
        models: list[LLMModelConfig] = []
        if chain_position == "fallback":
            models.append(
                LLMModelConfig(
                    model="openai:primary",
                    api_key=SecretStr("primary-key"),
                )
            )

        with pytest.raises(ValidationError, match=r"model|provider"):
            LLMProviderSettings(models=[*models, LLMModelConfig(model=model, api_key=SecretStr("key"))])

    @pytest.mark.parametrize("provider_key", ["", " ", "\t", " openai", "openai "])
    def test_registry_provider_key_rejects_blank_or_whitespace(self, provider_key: str) -> None:
        """Registry provider identities are canonical nonblank segments."""
        with pytest.raises(ValidationError, match=r"provider|key"):
            ApiKeyRegistry.model_validate({provider_key: "credential-value"})

    def test_cloud_provider_defers_api_key(self) -> None:
        """Cloud providers allow None api_key at config level (deferred to registry)."""
        config = LLMModelConfig(model="openrouter:model")
        assert config.api_key is None

    @pytest.mark.parametrize(
        "health_url",
        [
            "",
            "   ",
            "gateway.test/healthz",
            "/healthz",
            "ftp://gateway.test/healthz",
            "http:///healthz",
            "https://gateway-user@gateway.test/healthz",
            "https://gateway-user:gateway-password@gateway.test/healthz",
            "https://gateway.example.test/healthz?credential=value",
            "https://gateway.example.test/healthz#ready",
            "https://gateway.example.test:99999/healthz",
        ],
    )
    def test_health_url_rejects_unsafe_endpoint(self, health_url: str) -> None:
        """Health endpoints are absolute credential-free HTTP(S) URLs."""
        with pytest.raises(ValidationError, match="health_url"):
            LLMModelConfig(model="openai:gateway-model", health_url=health_url)

    def test_health_url_allows_valid_path(self) -> None:
        """A valid HTTPS health endpoint may include a non-root path."""
        config = LLMModelConfig(
            model="openai:gateway-model",
            health_url="https://gateway.example.test/readyz",
        )

        assert config.health_url == "https://gateway.example.test/readyz"

    def test_provider_settings_requires_key_for_highest_priority(self) -> None:
        """LLMProviderSettings requires api_key or registry entry for highest-priority model."""
        with pytest.raises(
            ValidationError,
            match=r"requires an api_key on the model or an entry in api_keys",
        ):
            LLMProviderSettings(models=[LLMModelConfig(model="openrouter:model")])

    @pytest.mark.parametrize(
        "model",
        ["google-vertex:gemini-2.5-flash", "google-vertex:claude-sonnet-4-5"],
    )
    @pytest.mark.parametrize(
        ("project", "location"),
        [(None, None), ("project-only", None), (None, "location-only")],
    )
    def test_vertex_rejects_missing_or_partial_explicit_auth(
        self,
        model: str,
        project: str | None,
        location: str | None,
    ) -> None:
        """Vertex cannot silently borrow SDK auth, project, or location environment."""
        with pytest.raises(ValidationError, match=r"api_key|project|location"):
            LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model=model,
                        google_project=project,
                        google_location=location,
                    )
                ]
            )

    def test_vertex_gemini_accepts_explicit_express_key(self) -> None:
        """Express Mode remains valid with an explicit model credential."""
        settings = LLMProviderSettings(
            models=[
                LLMModelConfig(
                    model="google-vertex:gemini-2.5-flash",
                    api_key=SecretStr("express-key"),
                )
            ]
        )

        assert settings.models[0].api_key is not None

    @pytest.mark.parametrize(
        "model",
        ["google-vertex:gemini-2.5-flash", "google-vertex:claude-sonnet-4-5"],
    )
    def test_vertex_accepts_explicit_project_and_location(self, model: str) -> None:
        """ADC mode requires both explicit project and explicit location."""
        settings = LLMProviderSettings(
            models=[
                LLMModelConfig(
                    model=model,
                    google_project="model-project",
                    google_location="us-central1",
                )
            ]
        )

        assert settings.models[0].google_project == "model-project"
        assert settings.models[0].google_location == "us-central1"

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "ollama", "llamacpp"])
    @pytest.mark.parametrize(
        "base_url",
        [
            "https://gateway.example.test",
            "https://gateway.example.test/",
            "https://gateway.example.test/provider",
            "https://gateway.example.test/v2",
        ],
    )
    def test_openai_compatible_provider_requires_terminal_v1(self, provider: str, base_url: str) -> None:
        """OpenAI-compatible SDK bases must identify their terminal API version."""
        with pytest.raises(ValidationError, match=r"base_url|/v1"):
            LLMModelConfig(model=f"{provider}:configured-model", base_url=base_url)

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "ollama", "llamacpp"])
    @pytest.mark.parametrize("suffix", ["", "/"])
    def test_openai_compatible_provider_accepts_prefixed_terminal_v1(self, provider: str, suffix: str) -> None:
        """Gateway prefixes are preserved when the final segment is exactly v1."""
        base_url = f"https://gateway.example.test/provider/v1{suffix}"

        config = LLMModelConfig(model=f"{provider}:configured-model", base_url=base_url)

        assert config.base_url == base_url

    @pytest.mark.parametrize("suffix", ["", "/"])
    def test_anthropic_custom_base_rejects_terminal_v1(self, suffix: str) -> None:
        """Anthropic SDK bases exclude the version segment it appends itself."""
        base_url = f"https://gateway.example.test/anthropic/v1{suffix}"

        with pytest.raises(ValidationError, match=r"base_url|/v1"):
            LLMModelConfig(model="anthropic:configured-model", base_url=base_url)

    def test_anthropic_custom_base_accepts_prefixed_unversioned_root(self) -> None:
        """Anthropic gateway prefixes are valid when they omit terminal v1."""
        base_url = "https://gateway.example.test/anthropic"

        config = LLMModelConfig(model="anthropic:configured-model", base_url=base_url)

        assert config.base_url == base_url

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "anthropic"])
    @pytest.mark.parametrize("api_key", ["", " ", "\t"])
    def test_authenticated_provider_rejects_blank_model_key(self, provider: str, api_key: str) -> None:
        """Blank per-model secrets are absent, never authenticated credentials."""
        with pytest.raises(ValidationError, match=r"api_key|key"):
            LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model=f"{provider}:primary",
                        api_key=SecretStr(api_key),
                    )
                ]
            )

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "anthropic"])
    @pytest.mark.parametrize("api_key", ["", " ", "\t"])
    def test_authenticated_provider_rejects_blank_registry_key(self, provider: str, api_key: str) -> None:
        """Blank registry secrets cannot satisfy an authenticated model chain."""
        with pytest.raises(ValidationError, match=r"api_key|key"):
            LLMProviderSettings(
                models=[LLMModelConfig(model=f"{provider}:primary")],
                api_keys=ApiKeyRegistry.model_validate({provider: api_key}),
            )

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "anthropic"])
    @pytest.mark.parametrize("api_key", ["", " ", "\t"])
    def test_authenticated_fallback_rejects_blank_model_key(self, provider: str, api_key: str) -> None:
        """Every fallback is validated before any provider SDK is constructed."""
        with pytest.raises(ValidationError, match=r"api_key|key"):
            LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="openai:primary",
                        api_key=SecretStr("primary-key"),
                    ),
                    LLMModelConfig(
                        model=f"{provider}:fallback",
                        api_key=SecretStr(api_key),
                    ),
                ]
            )

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "anthropic"])
    @pytest.mark.parametrize("api_key", ["", " ", "\t"])
    def test_authenticated_fallback_rejects_blank_registry_key(self, provider: str, api_key: str) -> None:
        """A blank registry entry cannot authenticate a fallback model."""
        with pytest.raises(ValidationError, match=r"api_key|key"):
            LLMProviderSettings(
                models=[
                    LLMModelConfig(
                        model="openai:primary",
                        api_key=SecretStr("primary-key"),
                    ),
                    LLMModelConfig(model=f"{provider}:fallback"),
                ],
                api_keys=ApiKeyRegistry.model_validate({provider: api_key}),
            )

    def test_provider_settings_accepts_registry_key(self) -> None:
        """Registry key satisfies validation for highest-priority model."""
        settings = LLMProviderSettings(
            models=[LLMModelConfig(model="openrouter:model")],
            api_keys=ApiKeyRegistry.model_validate({"openrouter": "key"}),
        )
        assert len(settings.models) == 1

    def test_provider_settings_empty_models_raises(self) -> None:
        """Empty models list raises ValueError."""
        with pytest.raises(ValidationError, match="At least one model is required"):
            LLMProviderSettings(models=[])

    def test_ollama_is_keyless(self) -> None:
        """Test Ollama doesn't require api_key but requires base_url."""
        config = LLMModelConfig(model="ollama:llama3", base_url="https://model.example.test/v1")
        assert config.provider_name == "ollama"
        assert config.api_key is None

    @pytest.mark.parametrize("provider", ["ollama", "llamacpp"])
    @pytest.mark.parametrize("base_url", [None, "", "   "])
    def test_local_provider_requires_nonblank_base_url(
        self,
        provider: str,
        base_url: str | None,
    ) -> None:
        """Local providers reject missing, empty, and whitespace-only endpoints."""
        with pytest.raises(ValidationError, match="base_url"):
            LLMModelConfig(model=f"{provider}:local-model", base_url=base_url)

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "ollama", "llamacpp"])
    @pytest.mark.parametrize(
        "base_url",
        [
            "",
            "   ",
            "https://provider.example.test",
            "https://provider.example.test/path",
            "ftp://provider.example.test/v1",
            "https:///v1",
            "https://user:credential@provider.example.test/v1",
            "https://provider.example.test/v1?credential=value",
            "https://provider.example.test/v1#models",
            "https://model.example.test:99999/v1",
        ],
    )
    def test_provider_rejects_unsafe_base_url(self, provider: str, base_url: str) -> None:
        """Every explicit provider endpoint uses the robust shared URL boundary."""
        with pytest.raises(ValidationError, match="base_url"):
            LLMModelConfig(model=f"{provider}:model", base_url=base_url)

    @pytest.mark.parametrize("field_name", ["base_url", "health_url"])
    @pytest.mark.parametrize(
        "url",
        [
            "https://-gateway.test/v1",
            "https://gateway-.test/v1",
            "https://gateway..test/v1",
            "https://gate way.test/v1",
            "https://999.1.1.1/v1",
            "https://[gggg::1]/v1",
        ],
    )
    def test_endpoint_rejects_invalid_host_boundary(self, field_name: str, url: str) -> None:
        """Malformed DNS, IPv4, IPv6, and embedded whitespace hosts fail closed."""
        with pytest.raises(ValidationError, match=field_name):
            LLMModelConfig.model_validate({"model": "openai:test-model", field_name: url})

    @pytest.mark.parametrize("field_name", ["base_url", "health_url"])
    @pytest.mark.parametrize(
        "url",
        [
            "https://alpha.model.example.test/v1",
            "https://beta.model.example.test/v1",
            "https://192.0.2.10:8080/v1",
            "https://[2001:db8::1]:8080/v1",
        ],
    )
    def test_endpoint_accepts_valid_public_dns_and_ip_hosts(self, field_name: str, url: str) -> None:
        """Public DNS and documentation IP endpoints remain valid."""
        config = LLMModelConfig.model_validate({"model": "openai:test-model", field_name: url})

        assert getattr(config, field_name) == url

    @pytest.mark.parametrize("provider", ["openai", "openrouter", "ollama", "llamacpp"])
    @pytest.mark.parametrize(
        "base_url",
        ["https://model.example.test/v1", "https://alt-model.example.test/v1"],
    )
    def test_provider_allows_valid_http_base_url(self, provider: str, base_url: str) -> None:
        """Explicit valid HTTP(S) endpoints retain paths and local HTTP support."""
        config = LLMModelConfig(model=f"{provider}:model", base_url=base_url)

        assert config.base_url == base_url

    @pytest.mark.parametrize("provider", ["ollama", "llamacpp"])
    def test_local_provider_rejects_health_url(self, provider: str) -> None:
        """Local readiness must verify the inference API rather than a separate route."""
        with pytest.raises(ValidationError, match="health_url"):
            LLMModelConfig(
                model=f"{provider}:local-model",
                base_url=f"https://{provider}.test/v1",
                health_url=f"https://{provider}.test/healthz",
            )

    def test_google_vertex_provider_extraction(self) -> None:
        """Google Vertex AI model extracts correct provider and model names."""
        config = LLMModelConfig(
            model="google-vertex:gemini-2.5-flash",
            api_key=SecretStr("key"),
        )
        assert config.provider_name == "google-vertex"
        assert config.model_name == "gemini-2.5-flash"

    def test_google_vertex_bare_adc_is_rejected(self) -> None:
        """Vertex cannot implicitly discover ADC identity or routing from process state."""
        with pytest.raises(ValidationError, match=r"explicit api_key|google_project"):
            LLMProviderSettings(
                models=[LLMModelConfig(model="google-vertex:gemini-2.5-flash")],
            )

    def test_google_vertex_with_project_location(self) -> None:
        """Google Vertex AI model config carries google_project and google_location."""
        config = LLMModelConfig(
            model="google-vertex:gemini-2.5-flash",
            google_project="my-gcp-project",
            google_location="europe-west1",
        )
        assert config.google_project == "my-gcp-project"
        assert config.google_location == "europe-west1"

    def test_google_vertex_accepts_registry_key(self) -> None:
        """Google Vertex AI accepts API key from the registry."""
        settings = LLMProviderSettings(
            models=[LLMModelConfig(model="google-vertex:gemini-2.5-flash")],
            api_keys=ApiKeyRegistry.model_validate({"google-vertex": "vertex-key"}),
        )
        key = settings.api_keys.get("google-vertex")
        assert key is not None
        assert key.get_secret_value() == "vertex-key"

    def test_openai_compatible_local_is_keyless_with_base_url(self) -> None:
        """Test OpenAI provider with base_url doesn't require api_key (local llama.cpp, vLLM)."""
        config = LLMModelConfig(
            model="openai:Qwen3.5-35B-A3B-UD-Q4_K_M.gguf",
            base_url="https://model.example.test/v1",
        )
        # Should not raise - base_url makes it keyless
        settings = LLMProviderSettings(models=[config])
        assert settings.models[0].provider_name == "openai"
        assert settings.models[0].base_url == "https://model.example.test/v1"
        assert settings.models[0].api_key is None

    @pytest.mark.parametrize("allow_fallbacks", [False, True])
    def test_provider_fallback_policy_survives_json_round_trip(self, *, allow_fallbacks: bool) -> None:
        config = LLMModelConfig(
            model="openrouter:synthetic/candidate",
            provider_order=("synthetic-route",),
            provider_allow_fallbacks=allow_fallbacks,
        )

        restored = LLMModelConfig.model_validate_json(config.model_dump_json())

        assert restored.provider_order == ("synthetic-route",)
        assert restored.provider_allow_fallbacks is allow_fallbacks

    def test_provider_zdr_defaults_false_and_is_serialized(self) -> None:
        """provider_zdr defaults to False and is emitted in the model dump."""
        config = LLMModelConfig(model="openrouter:synthetic/candidate")

        assert config.provider_zdr is False
        assert config.model_dump()["provider_zdr"] is False

    def test_provider_zdr_true_survives_json_round_trip(self) -> None:
        """An enabled ZDR flag is retained through a JSON serialization round trip."""
        config = LLMModelConfig(model="openrouter:synthetic/candidate", provider_zdr=True)

        restored = LLMModelConfig.model_validate_json(config.model_dump_json())

        assert restored.provider_zdr is True


class TestApiKeyRegistry:
    """Tests for ApiKeyRegistry model."""

    def test_empty_registry(self) -> None:
        """Empty registry has no keys."""
        registry = ApiKeyRegistry()
        assert not registry
        assert len(registry) == 0
        assert registry.get("openrouter") is None
        assert "openrouter" not in registry

    def test_get_returns_secret_str(self) -> None:
        """Values are coerced to SecretStr and retrievable."""
        registry = ApiKeyRegistry.model_validate({"openrouter": "credential-value"})
        key = registry.get("openrouter")
        assert isinstance(key, SecretStr)
        assert key.get_secret_value() == "credential-value"

    def test_get_missing_returns_none(self) -> None:
        """Missing provider returns None."""
        registry = ApiKeyRegistry.model_validate({"openrouter": "key"})
        assert registry.get("openai") is None

    def test_contains_registered_provider(self) -> None:
        """Registered provider is found via 'in' operator."""
        registry = ApiKeyRegistry.model_validate({"openai": "key"})
        assert "openai" in registry
        assert "openrouter" not in registry

    def test_contains_rejects_non_string(self) -> None:
        """Non-string key always returns False."""
        registry = ApiKeyRegistry.model_validate({"openai": "key"})
        assert 42 not in registry

    def test_bool_truthy_when_populated(self) -> None:
        """Registry is truthy when it has keys."""
        registry = ApiKeyRegistry.model_validate({"openrouter": "key"})
        assert registry

    def test_len_counts_keys(self) -> None:
        """Length reflects number of registered providers."""
        registry = ApiKeyRegistry.model_validate({"openrouter": "k1", "openai": "k2"})
        assert len(registry) == 2

    def test_coerce_passes_through_secret_str(self) -> None:
        """SecretStr values are not double-wrapped."""
        registry = ApiKeyRegistry.model_validate({"openrouter": SecretStr("credential-value")})
        key = registry.get("openrouter")
        assert isinstance(key, SecretStr)
        assert key.get_secret_value() == "credential-value"


class TestLLMSettingsInheritance:
    """Tests for provider-scoped credentials and endpoints."""

    def test_default_fallbacks_inherit_only_same_provider_base_url(self) -> None:
        settings = LLMSettings.model_validate(
            {
                "provider": {
                    "models": [
                        {
                            "model": "openai:synthetic-primary",
                            "base_url": "https://primary.example.test/v1",
                        },
                        {"model": "openai:synthetic-fallback"},
                        {
                            "model": "openai:synthetic-explicit",
                            "base_url": "https://explicit.example.test/v1",
                        },
                        {"model": "openrouter:synthetic/cross-provider"},
                    ],
                    "api_keys": {"openrouter": "test-openrouter-key"},
                }
            }
        )

        primary, inherited, explicit, cross_provider = settings.provider.models
        assert primary.base_url == "https://primary.example.test/v1"
        assert inherited.base_url == "https://primary.example.test/v1"
        assert explicit.base_url == "https://explicit.example.test/v1"
        assert cross_provider.base_url is None

    def test_named_chains_inherit_provider_values_without_overwriting_explicit_values(
        self,
    ) -> None:
        settings = LLMSettings.model_validate(
            {
                "provider": {
                    "models": [
                        {
                            "model": "openai:synthetic-primary",
                            "base_url": "https://primary.example.test/v1",
                        },
                    ],
                    "api_keys": {
                        "openai": "provider-openai-key",
                        "openrouter": "provider-openrouter-key",
                    },
                },
                "chains": {
                    "inherited": {
                        "models": [
                            {"model": "openai:synthetic-chain"},
                            {"model": "openrouter:synthetic/cross-provider"},
                        ]
                    },
                    "explicit": {
                        "models": [
                            {
                                "model": "openai:synthetic-explicit-chain",
                                "base_url": "https://chain.example.test/v1",
                            }
                        ],
                        "api_keys": {"openai": "chain-openai-key"},
                    },
                },
            }
        )

        inherited = settings.chains["inherited"]
        assert inherited.models[0].base_url == "https://primary.example.test/v1"
        assert inherited.models[1].base_url is None
        inherited_openai = inherited.api_keys.get("openai")
        assert inherited_openai is not None
        assert inherited_openai.get_secret_value() == "provider-openai-key"
        inherited_openrouter = inherited.api_keys.get("openrouter")
        assert inherited_openrouter is not None
        assert inherited_openrouter.get_secret_value() == "provider-openrouter-key"

        explicit = settings.chains["explicit"]
        assert explicit.models[0].base_url == "https://chain.example.test/v1"
        explicit_openai = explicit.api_keys.get("openai")
        assert explicit_openai is not None
        assert explicit_openai.get_secret_value() == "chain-openai-key"


class TestLLMMixin:
    """Tests for LLMMixin."""

    def test_mixin_initialization(self) -> None:
        """Test mixin correctly initializes settings."""
        settings = _TestSettingsWithLLM()
        assert settings.llm.provider.models[0].provider_name == "openrouter"


class TestLLMSettingsEnvironmentVariables:
    """Tests for LLM settings from environment variables."""

    def test_env_variable_llm_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Highest-priority model from environment variable."""
        monkeypatch.setenv("LLM__PROVIDER__MODELS__0__MODEL", "ollama:llama3")
        monkeypatch.setenv("LLM__PROVIDER__MODELS__0__BASE_URL", "http://ollama:11434/v1")
        settings = _TestSettingsWithLLM()
        assert settings.llm.provider.models[0].model == "ollama:llama3"
        assert settings.llm.provider.models[0].provider_name == "ollama"

    def test_env_decodes_model_health_and_tls_transport(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Per-model gateway health and CA settings survive nested env decoding."""
        monkeypatch.setenv("LLM__PROVIDER__MODELS__0__MODEL", "openai:gateway-model")
        monkeypatch.setenv("LLM__PROVIDER__MODELS__0__BASE_URL", "https://gateway.test/v1")
        monkeypatch.setenv(
            "LLM__PROVIDER__MODELS__0__HEALTH_URL",
            "https://gateway.example.test/healthz",
        )
        monkeypatch.setenv("LLM__PROVIDER__MODELS__0__TLS_CA_FILE", "/run/model-ca/ca.crt")

        config = _TestSettingsWithLLM().llm.provider.models[0]

        assert config.health_url == "https://gateway.example.test/healthz"
        assert config.tls_ca_file == "/run/model-ca/ca.crt"

    def test_env_variable_multiple_models_with_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple models with cross-provider api_keys registry from env vars."""
        monkeypatch.setenv("LLM__PROVIDER__MODELS__0__MODEL", "openrouter:google/gemini-pro")
        monkeypatch.setenv("LLM__PROVIDER__MODELS__1__MODEL", "openai:gpt-4o")
        monkeypatch.setenv("LLM__PROVIDER__API_KEYS__OPENROUTER", "credential-value")
        monkeypatch.setenv("LLM__PROVIDER__API_KEYS__OPENAI", "credential-value")
        settings = _TestSettingsWithLLM()
        assert len(settings.llm.provider.models) == 2
        assert settings.llm.provider.models[0].model == "openrouter:google/gemini-pro"
        assert settings.llm.provider.models[1].model == "openai:gpt-4o"

    def test_env_variable_instrumentation_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test instrumentation enabled from environment variable."""
        monkeypatch.setenv("LLM__PROVIDER__MODELS__0__MODEL", "openai:gpt-4o")
        monkeypatch.setenv("LLM__PROVIDER__API_KEYS__OPENAI", "credential-value")
        monkeypatch.setenv("LLM__INSTRUMENTATION__ENABLED", "true")
        settings = _TestSettingsWithLLM()
        assert settings.llm.instrumentation.enabled is True


class TestOllamaSettings:
    """Tests for OllamaSettings."""

    def test_custom_values(self) -> None:
        """Test OllamaSettings with custom values."""
        settings = OllamaSettings(
            num_ctx=16384,
            top_k=60,
            repeat_penalty=1.2,
            think=False,
        )
        assert settings.num_ctx == 16384
        assert settings.top_k == 60
        assert abs(settings.repeat_penalty - 1.2) < 1e-9
        assert settings.think is False

    def test_to_options_dict(self) -> None:
        """Test OllamaSettings.to_options_dict() produces correct format.

        Note: think is NOT included in options dict - it's a top-level
        request parameter per Ollama API spec, handled separately in factory.
        """
        settings = OllamaSettings(
            num_ctx=4096,
            top_k=50,
            repeat_penalty=1.15,
            think=True,
        )
        options = settings.to_options_dict()

        assert options == {
            "num_ctx": 4096,
            "top_k": 50,
            "repeat_penalty": 1.15,
        }
        assert "think" not in options

    def test_validation_num_ctx_bounds(self) -> None:
        """Test num_ctx validation bounds."""
        with pytest.raises(ValidationError):
            OllamaSettings(num_ctx=100)  # Below min (512)

        with pytest.raises(ValidationError):
            OllamaSettings(num_ctx=200000)  # Above max (131072)

    def test_validation_top_k_bounds(self) -> None:
        """Test top_k validation bounds."""
        with pytest.raises(ValidationError):
            OllamaSettings(top_k=0)  # Below min (1)

        with pytest.raises(ValidationError):
            OllamaSettings(top_k=101)  # Above max (100)

    def test_validation_repeat_penalty_bounds(self) -> None:
        """Test repeat_penalty validation bounds."""
        with pytest.raises(ValidationError):
            OllamaSettings(repeat_penalty=-0.1)  # Below min (0.0)

        with pytest.raises(ValidationError):
            OllamaSettings(repeat_penalty=2.1)  # Above max (2.0)

    def test_frozen_immutability(self) -> None:
        """Test OllamaSettings is frozen (immutable)."""
        settings = OllamaSettings()
        with pytest.raises(ValidationError):
            settings.num_ctx = 4096

    def test_provider_settings_custom_ollama(self) -> None:
        """Test LLMProviderSettings with custom OllamaSettings."""
        custom_ollama = OllamaSettings(num_ctx=32768, think=False)
        settings = LLMProviderSettings(
            models=[LLMModelConfig(model="ollama:llama3", base_url="https://model.example.test/v1")],
            ollama=custom_ollama,
        )
        assert settings.ollama.num_ctx == 32768
        assert settings.ollama.think is False


class TestProviderOrderValidator:
    """Tests for LLMModelConfig._coerce_provider_order contract enforcement."""

    def test_dict_with_contiguous_indices_returns_ordered_tuple(self) -> None:
        """Numeric-keyed dict from env var parsing produces a properly ordered tuple."""
        config = LLMModelConfig.model_validate(
            {
                "model": "openrouter:foo/bar",
                "provider_order": {"1": "B", "0": "A", "2": "C"},
            }
        )
        assert config.provider_order == ("A", "B", "C")

    def test_tuple_input_passes_through(self) -> None:
        """Tuple inputs from direct construction bypass the dict coercion path."""
        config = LLMModelConfig(model="openrouter:foo/bar", provider_order=("A", "B"))
        assert config.provider_order == ("A", "B")

    def test_non_numeric_keys_raise(self) -> None:
        """A non-numeric key is a misconfigured env var name, not a recoverable input."""
        with pytest.raises(ValidationError, match="non-numeric key"):
            LLMModelConfig.model_validate(
                {
                    "model": "openrouter:foo/bar",
                    "provider_order": {"0": "A", "foo": "B"},
                }
            )

    def test_gapped_indices_raise(self) -> None:
        """Missing index 1 between 0 and 2 signals a config bug; reject rather than silently reorder."""
        with pytest.raises(ValidationError, match="contiguous starting at 0"):
            LLMModelConfig.model_validate({"model": "openrouter:foo/bar", "provider_order": {"0": "A", "2": "C"}})

    def test_indices_not_starting_at_zero_raise(self) -> None:
        """Indices starting at 1 instead of 0 are rejected for the same reason as gaps."""
        with pytest.raises(ValidationError, match="contiguous starting at 0"):
            LLMModelConfig.model_validate({"model": "openrouter:foo/bar", "provider_order": {"1": "A", "2": "B"}})

    def test_duplicate_values_warn_but_succeed(self, caplog: pytest.LogCaptureFixture) -> None:
        """Duplicates likely indicate copy-paste error but OpenRouter tolerates them."""
        with caplog.at_level("WARNING", logger="nohiki_llm_client.config.settings"):
            config = LLMModelConfig.model_validate(
                {"model": "openrouter:foo/bar", "provider_order": {"0": "A", "1": "A"}}
            )
        assert config.provider_order == ("A", "A")
        assert any("duplicate" in rec.message.lower() for rec in caplog.records)
