"""Service configuration using composable Nohiki mixins."""

from __future__ import annotations

from functools import cache
from typing import Literal

from nohiki_core_settings import NohikiBaseSettings
from nohiki_kafka_client import KafkaMixin
from nohiki_redis_utils import RedisMixin
from nohiki_s3_client import S3Mixin
from pydantic import BaseModel, Field, PositiveInt
from pydantic_settings import SettingsConfigDict

type Pipeline = Literal["standard", "vlm"]
type PdfBackend = Literal["pypdfium2", "docling_parse", "dlparse_v1", "dlparse_v2", "dlparse_v4"]
type OcrEngine = Literal[
    "auto",
    "easyocr",
    "kserve_v2_ocr",
    "ocrmac",
    "rapidocr",
    "tesseract",
    "tesserocr",
]
type TableMode = Literal["fast", "accurate"]
type VLMEngineType = Literal["api", "api_ollama", "api_lmstudio", "api_openai"]
type VLMResponseFormat = Literal["doctags", "markdown", "deepseekocr_markdown", "html", "otsl", "plaintext"]


class DoclingSettings(BaseModel):
    """Docling Serve provider settings."""

    base_url: str = Field(default="http://docling-serve:5001")
    api_key: str | None = None
    enabled: bool = True
    timeout_seconds: PositiveInt = Field(default=300)
    max_retries: PositiveInt = Field(default=3)
    max_document_bytes: PositiveInt = Field(default=50 * 1024 * 1024)

    pipeline: Pipeline = "standard"
    pdf_backend: PdfBackend = "docling_parse"
    ocr_engine: OcrEngine = "rapidocr"
    table_mode: TableMode = "accurate"

    do_ocr: bool = True
    force_ocr: bool = False
    do_table_structure: bool = True
    include_images: bool = True
    do_picture_description: bool = False

    poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=10.0)
    max_poll_attempts: PositiveInt = Field(default=300)


class VLMSettings(BaseModel):
    """Vision Language Model settings for image description."""

    enabled: bool = False
    engine_type: VLMEngineType = "api_ollama"
    api_url: str = Field(default="http://ollama:11434/v1/chat/completions")
    api_key: str | None = None
    model: str = "qwen3-vl:30b"
    timeout_seconds: PositiveInt = Field(default=180)
    max_tokens: PositiveInt = Field(default=4096)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    thinking_budget: int = Field(default=1024, ge=0)
    headers: dict[str, str] = Field(default_factory=dict)
    extra_params: dict[str, object] = Field(default_factory=dict)
    prompt: str = "Describe this image in detail."
    response_format: VLMResponseFormat = "plaintext"
    picture_area_threshold: float = Field(default=0.01, ge=0.0, le=1.0)


class CacheSettings(BaseModel):
    """Cache TTL configuration."""

    raw_ttl_seconds: PositiveInt = Field(default=604800)
    processed_ttl_seconds: PositiveInt = Field(default=604800)
    key_prefix: str = Field(default="doc-process")


class CircuitBreakerSettings(BaseModel):
    """Circuit breaker for provider protection."""

    enabled: bool = True
    failure_threshold: PositiveInt = Field(default=5)
    success_threshold: PositiveInt = Field(default=2)
    timeout_seconds: PositiveInt = Field(default=30)


class Settings(KafkaMixin, RedisMixin, S3Mixin, NohikiBaseSettings):
    """doc-process-service settings using Nohiki composable mixins."""

    model_config = SettingsConfigDict(env_prefix="DOC_PROCESS_")

    service_name: str = "doc-process-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Document Processing Service"
    service_desc_friendly: str = "Process documents via Docling Serve with ECST"

    docling: DoclingSettings = Field(default_factory=DoclingSettings)
    vlm: VLMSettings = Field(default_factory=VLMSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    circuit_breaker: CircuitBreakerSettings = Field(default_factory=CircuitBreakerSettings)

    @property
    def kafka_consumer_group(self) -> str:
        """Return the Kafka consumer group for this service."""
        return f"{self.service_name}-primary"


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()
