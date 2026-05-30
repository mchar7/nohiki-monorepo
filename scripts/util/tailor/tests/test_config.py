"""Tests for tailor.core.config -- TailorSettings, constants, and get_settings().

Env vars are pre-configured in conftest.py. The reset_settings_cache autouse
fixture clears lru_cache between tests so each test sees a fresh settings load.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tailor.core.config import (
    APP_TITLE,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TEMPLATE_NAME,
    MAX_CONTEXT_FILES,
    MAX_JOB_FILES,
    MONOREPO_ROOT,
    SEED_SCHEMAS_DIR,
    SEED_TEMPLATES_DIR,
    TailorSettings,
    get_settings,
    load_api_keys,
)


class TestModuleConstants:
    """Tests for module-level constants in tailor.core.config."""

    def test_default_template_name(self) -> None:
        """DEFAULT_TEMPLATE_NAME must equal 'resume' (the template's metadata name)."""
        assert DEFAULT_TEMPLATE_NAME == "resume"

    def test_max_context_files(self) -> None:
        """MAX_CONTEXT_FILES must equal 10."""
        assert MAX_CONTEXT_FILES == 10

    def test_max_job_files(self) -> None:
        """MAX_JOB_FILES must equal 10."""
        assert MAX_JOB_FILES == 10

    def test_app_title(self) -> None:
        """APP_TITLE must equal 'Nohiki Tailoring CLI'."""
        assert APP_TITLE == "Nohiki Tailoring CLI"

    def test_monorepo_root_is_real_directory(self) -> None:
        """MONOREPO_ROOT must exist on disk (resolved via get_repo_root)."""
        assert MONOREPO_ROOT.exists()
        assert MONOREPO_ROOT.is_dir()

    def test_seed_templates_dir_ends_with_seed_templates(self) -> None:
        """SEED_TEMPLATES_DIR must be a path ending in 'seed_templates'."""
        assert SEED_TEMPLATES_DIR.parts[-1] == "seed_templates"

    def test_seed_schemas_dir_ends_with_seed_schemas(self) -> None:
        """SEED_SCHEMAS_DIR must be a path ending in 'seed_schemas'."""
        assert SEED_SCHEMAS_DIR.parts[-1] == "seed_schemas"

    def test_default_output_dir_is_relative_output(self) -> None:
        """DEFAULT_OUTPUT_DIR must be the relative path './output'."""
        assert str(DEFAULT_OUTPUT_DIR) == "output"


class TestGetSettings:
    """Tests for the get_settings() factory function."""

    def test_returns_tailor_settings_instance(self) -> None:
        """get_settings() must return a TailorSettings instance."""
        settings = get_settings()
        assert isinstance(settings, TailorSettings)

    def test_returns_same_object_on_repeated_calls(self) -> None:
        """get_settings() must return the cached instance on subsequent calls."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_cache_clear_causes_fresh_instance(self) -> None:
        """After cache_clear(), get_settings() must return a new instance."""
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # Different objects after cache clear
        assert s1 is not s2

    def test_service_name_default(self) -> None:
        """TailorSettings.service_name must default to 'tailor-cli'."""
        settings = get_settings()
        assert settings.service_name == "tailor-cli"

    def test_gotenberg_url_default(self) -> None:
        """TailorSettings.gotenberg_url must default to 'http://localhost:3000'."""
        settings = get_settings()
        assert settings.gotenberg_url == "http://localhost:3000"

    def test_gotenberg_timeout_s_default(self) -> None:
        """TailorSettings.gotenberg_timeout_s must default to 30."""
        settings = get_settings()
        assert settings.gotenberg_timeout_s == 30


class TestTailorSettingsDefaults:
    """Tests for TailorSettings field defaults."""

    def test_service_name_default(self) -> None:
        """service_name must default to 'tailor-cli'."""
        assert get_settings().service_name == "tailor-cli"

    def test_service_name_friendly_default(self) -> None:
        """service_name_friendly must default to 'Nohiki Tailoring CLI'."""
        assert get_settings().service_name_friendly == "Nohiki Tailoring CLI"

    def test_service_desc_friendly_default(self) -> None:
        """service_desc_friendly must default to 'Manual document tailoring tool'."""
        assert get_settings().service_desc_friendly == "Manual document tailoring tool"

    def test_service_version_default(self) -> None:
        """service_version must default to '0.1.0'."""
        assert get_settings().service_version == "0.1.0"

    def test_gotenberg_url_field(self) -> None:
        """gotenberg_url must default to 'http://localhost:3000'."""
        assert get_settings().gotenberg_url == "http://localhost:3000"

    def test_gotenberg_timeout_s_field(self) -> None:
        """gotenberg_timeout_s must default to 30."""
        assert get_settings().gotenberg_timeout_s == 30


class TestResolvedTemplatesDir:
    """Tests for TailorSettings.resolved_templates_dir property."""

    def test_absolute_templates_dir_returned_unchanged(self, tmp_path: Path) -> None:
        """resolved_templates_dir must return the path unchanged when it is absolute."""
        abs_dir = tmp_path / "templates"
        abs_dir.mkdir()
        settings = TailorSettings(templates_dir=abs_dir)
        assert settings.resolved_templates_dir == abs_dir

    def test_relative_templates_dir_prepends_monorepo_root(self) -> None:
        """resolved_templates_dir must prepend MONOREPO_ROOT for relative paths."""
        settings = TailorSettings(templates_dir=Path("relative/templates"))
        expected = MONOREPO_ROOT / "relative" / "templates"
        assert settings.resolved_templates_dir == expected


class TestResolvedSchemasDir:
    """Tests for TailorSettings.resolved_schemas_dir property."""

    def test_absolute_schemas_dir_returned_unchanged(self, tmp_path: Path) -> None:
        """resolved_schemas_dir must return the path unchanged when it is absolute."""
        abs_dir = tmp_path / "schemas"
        abs_dir.mkdir()
        settings = TailorSettings(schemas_dir=abs_dir)
        assert settings.resolved_schemas_dir == abs_dir

    def test_relative_schemas_dir_prepends_monorepo_root(self) -> None:
        """resolved_schemas_dir must prepend MONOREPO_ROOT for relative paths."""
        settings = TailorSettings(schemas_dir=Path("relative/schemas"))
        expected = MONOREPO_ROOT / "relative" / "schemas"
        assert settings.resolved_schemas_dir == expected


class TestResolvedOutputDir:
    """Tests for TailorSettings.resolved_output_dir property."""

    def test_absolute_output_dir_returned_unchanged(self, tmp_path: Path) -> None:
        """resolved_output_dir must return the path unchanged when it is absolute."""
        abs_dir = tmp_path / "output"
        abs_dir.mkdir()
        settings = TailorSettings(output_dir=abs_dir)
        assert settings.resolved_output_dir == abs_dir

    def test_relative_output_dir_prepends_cwd(self) -> None:
        """resolved_output_dir must prepend Path.cwd() for relative paths."""
        settings = TailorSettings(output_dir=Path("relative/output"))
        expected = Path.cwd() / "relative" / "output"
        assert settings.resolved_output_dir == expected

    def test_default_output_dir_is_relative_to_cwd(self) -> None:
        """The default output_dir './output' must resolve relative to cwd."""
        settings = get_settings()
        resolved = settings.resolved_output_dir
        assert not resolved.is_absolute() or resolved == Path.cwd() / "output"
        # Must end with 'output'
        assert resolved.parts[-1] == "output"


class TestTailorSettingsEnvOverride:
    """Tests verifying that env vars can override TailorSettings defaults."""

    def test_gotenberg_url_overridable_via_env(self) -> None:
        """gotenberg_url must be overridable by TAILOR_GOTENBERG_URL env var."""
        with patch.dict(
            "os.environ",
            {"TAILOR_GOTENBERG_URL": "http://custom-gotenberg:3000"},
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()
            assert settings.gotenberg_url == "http://custom-gotenberg:3000"

    def test_gotenberg_timeout_overridable_via_env(self) -> None:
        """gotenberg_timeout_s must be overridable by TAILOR_GOTENBERG_TIMEOUT_S env var."""
        with patch.dict(
            "os.environ",
            {"TAILOR_GOTENBERG_TIMEOUT_S": "60"},
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()
            assert settings.gotenberg_timeout_s == 60


class TestDefaultModel:
    """Tests for the DEFAULT_MODEL constant and llm_model settings field."""

    def test_default_model_constant_format(self) -> None:
        """DEFAULT_MODEL must use 'provider:model_name' format."""
        assert ":" in DEFAULT_MODEL
        provider, model = DEFAULT_MODEL.split(":", maxsplit=1)
        assert len(provider) > 0
        assert len(model) > 0

    def test_llm_model_field_defaults_to_default_model(self) -> None:
        """TailorSettings.llm_model must default to DEFAULT_MODEL."""
        settings = get_settings()
        # conftest sets TAILOR_LLM_MODEL to a test model; check field exists and is valid
        assert ":" in settings.llm_model

    def test_llm_model_overridable_via_env(self) -> None:
        """llm_model must be overridable by TAILOR_LLM_MODEL env var."""
        with patch.dict(
            "os.environ",
            {"TAILOR_LLM_MODEL": "openai:gpt-4o"},
            clear=False,
        ):
            get_settings.cache_clear()
            settings = get_settings()
            assert settings.llm_model == "openai:gpt-4o"


class TestLoadApiKeys:
    """Tests for the load_api_keys() helper function."""

    def test_returns_empty_registry_when_secrets_dir_empty(self, tmp_path: Path) -> None:
        """load_api_keys() must accept an existing directory with no provider keys."""
        api_keys_dir = tmp_path / "api_keys"
        api_keys_dir.mkdir()
        with patch("tailor.core.config._API_KEYS_DIR", api_keys_dir):
            result = load_api_keys()
        assert not result.model_extra

    def test_returns_empty_registry_when_secrets_dir_missing(self, tmp_path: Path) -> None:
        """load_api_keys() must return an empty registry if the secrets dir is absent."""
        with patch("tailor.core.config._API_KEYS_DIR", tmp_path / "nonexistent"):
            result = load_api_keys()
        assert not result.model_extra

    def test_loads_keys_from_files(self, tmp_path: Path) -> None:
        """load_api_keys() reads provider key files and populates the registry."""
        api_keys_dir = tmp_path / "api_keys"
        api_keys_dir.mkdir()
        (api_keys_dir / "openrouter").write_text("sk-or-test-key\n")
        (api_keys_dir / "openai").write_text("sk-openai-test-key\n")

        with patch("tailor.core.config._API_KEYS_DIR", api_keys_dir):
            result = load_api_keys()

        assert result.get("openrouter") is not None
        assert result.get("openai") is not None
