"""Tests for doc_process_service.providers.docling.config module."""

from __future__ import annotations

import json

import pytest
from doc_process_service.core.config import DoclingSettings, VLMSettings
from doc_process_service.providers.docling.config import DoclingClientConfig


class TestDoclingClientConfigFromSettings:
    """Tests for from_settings class method."""

    def test_from_settings_without_vlm(self) -> None:
        """Test config creation without VLM enabled."""
        docling_settings = DoclingSettings(
            base_url="http://localhost:5001",
            timeout_seconds=300,
            max_retries=3,
            pipeline="standard",
            pdf_backend="docling_parse",
            ocr_engine="rapidocr",
            table_mode="accurate",
            do_ocr=True,
            force_ocr=False,
            do_table_structure=True,
            include_images=True,
            do_picture_description=False,
            poll_interval_seconds=1.0,
            max_poll_attempts=300,
        )
        vlm_settings = VLMSettings(enabled=False)

        config = DoclingClientConfig.from_settings(docling_settings, vlm_settings)

        assert config.base_url == "http://localhost:5001"
        assert config.timeout == 300
        assert config.api_key is None
        assert config.pipeline == "standard"
        assert config.pdf_backend == "docling_parse"
        assert config.ocr_engine == "rapidocr"
        assert config.table_mode == "accurate"
        assert config.do_ocr is True
        assert config.force_ocr is False
        assert config.do_table_structure is True
        assert config.include_images is True
        assert config.do_picture_description is False
        assert config.picture_description_custom_config is None
        assert config.poll_interval == pytest.approx(1.0)
        assert config.max_poll_attempts == 300

    def test_from_settings_with_vlm(self) -> None:
        """Test config creation with VLM enabled."""
        docling_settings = DoclingSettings(
            base_url="http://localhost:5001",
            timeout_seconds=300,
            max_retries=3,
            pipeline="vlm",
            pdf_backend="docling_parse",
            ocr_engine="rapidocr",
            table_mode="accurate",
            do_ocr=True,
            force_ocr=False,
            do_table_structure=True,
            include_images=True,
            do_picture_description=False,
            poll_interval_seconds=1.0,
            max_poll_attempts=300,
        )
        vlm_settings = VLMSettings(
            enabled=True,
            engine_type="api_ollama",
            api_url="http://localhost:11434/v1/chat/completions",
            model="qwen3-vl:30b",
            timeout_seconds=180,
            max_tokens=4096,
            temperature=0.1,
            thinking_budget=1024,
            prompt="Describe this image.",
        )

        config = DoclingClientConfig.from_settings(docling_settings, vlm_settings)

        assert config.do_picture_description is True
        assert config.picture_description_custom_config is not None

        custom_config = json.loads(config.picture_description_custom_config)
        assert custom_config["model_spec"]["name"] == "qwen3-vl:30b"
        assert custom_config["model_spec"]["default_repo_id"] == "qwen3-vl:30b"
        assert custom_config["model_spec"]["response_format"] == "plaintext"
        assert custom_config["engine_options"]["engine_type"] == "api_ollama"
        assert custom_config["engine_options"]["url"] == "http://localhost:11434/v1/chat/completions"
        assert custom_config["engine_options"]["headers"] == {}
        assert custom_config["engine_options"]["params"]["model"] == "qwen3-vl:30b"
        assert custom_config["engine_options"]["params"]["max_completion_tokens"] == 4096
        assert custom_config["engine_options"]["params"]["temperature"] == pytest.approx(0.1)
        assert custom_config["engine_options"]["params"]["thinking"]["budget_tokens"] == 1024
        assert custom_config["engine_options"]["timeout"] == 180
        assert custom_config["engine_options"]["concurrency"] == 1
        assert custom_config["prompt"] == "Describe this image."
        assert custom_config["picture_area_threshold"] == pytest.approx(0.01)

    def test_from_settings_with_vlm_thinking_disabled(self) -> None:
        """Test config omits thinking params when budget is zero."""
        docling_settings = DoclingSettings(base_url="http://localhost:5001")
        vlm_settings = VLMSettings(
            enabled=True,
            engine_type="api",
            api_url="http://localhost:8888/v1/chat/completions",
            model="test-model.gguf",
            timeout_seconds=180,
            max_tokens=4096,
            temperature=0.1,
            thinking_budget=0,
            prompt="Describe this image.",
        )

        config = DoclingClientConfig.from_settings(docling_settings, vlm_settings)

        assert config.do_picture_description is True
        assert config.picture_description_custom_config is not None

        custom_config = json.loads(config.picture_description_custom_config)
        assert custom_config["engine_options"]["engine_type"] == "api"
        assert custom_config["engine_options"]["url"] == "http://localhost:8888/v1/chat/completions"
        assert "thinking" not in custom_config["engine_options"]["params"]
        assert custom_config["engine_options"]["params"]["model"] == "test-model.gguf"

    def test_from_settings_with_vlm_api_key(self) -> None:
        """Test VLM api_key is converted to Authorization Bearer header."""
        docling_settings = DoclingSettings(base_url="http://localhost:5001")
        vlm_settings = VLMSettings(
            enabled=True,
            api_key="sk-test123",
            thinking_budget=0,
        )

        config = DoclingClientConfig.from_settings(docling_settings, vlm_settings)
        assert config.picture_description_custom_config is not None

        custom_config = json.loads(config.picture_description_custom_config)
        assert custom_config["engine_options"]["headers"]["Authorization"] == "Bearer sk-test123"

    def test_from_settings_with_vlm_explicit_auth_header_not_overridden(self) -> None:
        """Test explicit Authorization header takes precedence over api_key."""
        docling_settings = DoclingSettings(base_url="http://localhost:5001")
        vlm_settings = VLMSettings(
            enabled=True,
            api_key="sk-ignored",
            headers={"Authorization": "Bearer sk-explicit"},
            thinking_budget=0,
        )

        config = DoclingClientConfig.from_settings(docling_settings, vlm_settings)
        assert config.picture_description_custom_config is not None

        custom_config = json.loads(config.picture_description_custom_config)
        assert custom_config["engine_options"]["headers"]["Authorization"] == "Bearer sk-explicit"

    def test_from_settings_with_vlm_extra_params(self) -> None:
        """Test extra_params are merged into engine options params."""
        docling_settings = DoclingSettings(base_url="http://localhost:5001")
        vlm_settings = VLMSettings(
            enabled=True,
            engine_type="api",
            api_url="http://localhost:8888/v1/chat/completions",
            model="test-model.gguf",
            thinking_budget=0,
            extra_params={"chat_template_kwargs": {"enable_thinking": False}},
        )

        config = DoclingClientConfig.from_settings(docling_settings, vlm_settings)
        assert config.picture_description_custom_config is not None

        custom_config = json.loads(config.picture_description_custom_config)
        params = custom_config["engine_options"]["params"]
        assert params["chat_template_kwargs"] == {"enable_thinking": False}
        assert params["model"] == "test-model.gguf"
        assert "thinking" not in params

    def test_from_settings_with_docling_picture_description(self) -> None:
        """Test config creation when docling picture description is enabled."""
        docling_settings = DoclingSettings(
            base_url="http://localhost:5001",
            timeout_seconds=300,
            max_retries=3,
            pipeline="vlm",
            pdf_backend="docling_parse",
            ocr_engine="rapidocr",
            table_mode="accurate",
            do_ocr=True,
            force_ocr=False,
            do_table_structure=True,
            include_images=True,
            do_picture_description=True,
            poll_interval_seconds=1.0,
            max_poll_attempts=300,
        )
        vlm_settings = VLMSettings(enabled=False)

        config = DoclingClientConfig.from_settings(docling_settings, vlm_settings)

        assert config.do_picture_description is True
        assert config.picture_description_custom_config is None
