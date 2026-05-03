"""Benchmarks for service-level utility operations.

Measures cache key building (doc-process-service), processing option
level determination, notification template registry lookup, error code
mapping (bff-service), and BFF response model construction -- pure
functions inlined from service packages to avoid sys.path issues.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

import pytest
from pydantic import BaseModel, Field

# Inlined from doc_process_service.cache.keys


@dataclass(frozen=True, slots=True)
class _CacheKeyBuilder:
    """Inlined from doc_process_service.cache.keys."""

    prefix: str = "doc"
    separator: str = ":"

    def raw_key(self, content_id: str) -> str:
        return f"{self.prefix}{self.separator}raw{self.separator}{content_id}"

    def processed_key(self, content_hash: str, level_suffix: str = "") -> str:
        base = f"{self.prefix}{self.separator}processed{self.separator}{content_hash}"
        return f"{base}{self.separator}{level_suffix}" if level_suffix else base

    def checksum_key(self, content_id: str) -> str:
        return f"{self.prefix}{self.separator}checksum{self.separator}{content_id}"

    def task_key(self, task_id: str) -> str:
        return f"{self.prefix}{self.separator}task{self.separator}{task_id}"


# Inlined from doc_process_service.models.domain


class _ProcessingLevel(IntEnum):
    BASIC = 0
    TABLES = 1
    OCR = 2
    IMAGES = 3
    FULL = 4


@dataclass(frozen=True, slots=True)
class _ProcessingOptions:
    """Inlined from doc_process_service.models.domain."""

    enable_ocr: bool = False
    ocr_languages: tuple[str, ...] = ()
    extract_tables: bool = True
    extract_images: bool = False
    enable_vlm_descriptions: bool = False

    @property
    def level(self) -> _ProcessingLevel:
        if self.enable_vlm_descriptions:
            return _ProcessingLevel.FULL
        if self.extract_images:
            return _ProcessingLevel.IMAGES
        if self.enable_ocr:
            return _ProcessingLevel.OCR
        if self.extract_tables:
            return _ProcessingLevel.TABLES
        return _ProcessingLevel.BASIC

    def to_cache_key_part(self) -> str:
        data = {
            "ocr": self.enable_ocr,
            "ocr_langs": self.ocr_languages,
            "tables": self.extract_tables,
            "images": self.extract_images,
            "vlm": self.enable_vlm_descriptions,
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


# Inlined from notification_service.services.template_registry


@dataclass(frozen=True, slots=True)
class _TemplateConfig:
    """Inlined from notification_service.services.template_registry."""

    template_name: str
    subject_template: str
    uses_threshold: bool = True
    requires_completed_status: bool = False


_EVENT_TYPE_CORRELATION: Final[str] = "nohiki.job.correlation.v1.CorrelationEvaluated"
_EVENT_TYPE_CONTENT_GEN: Final[str] = "nohiki.doc.content.v1.ContentGenerationCompleted"

_TEMPLATE_REGISTRY: dict[str, _TemplateConfig] = {
    _EVENT_TYPE_CORRELATION: _TemplateConfig(
        template_name="job_match",
        subject_template="New Job Match: {listing_title} at {company_name}",
        uses_threshold=True,
    ),
    _EVENT_TYPE_CONTENT_GEN: _TemplateConfig(
        template_name="content_generation_completed",
        subject_template="Your Generated Document for {listing_title}",
        uses_threshold=False,
        requires_completed_status=True,
    ),
}


def _get_template_config(event_type: str) -> _TemplateConfig | None:
    return _TEMPLATE_REGISTRY.get(event_type)


# Inlined from bff_service.api.error_handlers


class _UserFacingErrorResponse(BaseModel):
    """Inlined from bff_service.api.error_handlers."""

    error_code: str
    message: str
    details: dict | None = None
    request_id: str | None = None


_RESOURCE_TYPE_TO_CODE: dict[str, str] = {
    "Profile": "PROFILE.NOT_FOUND",
    "Listing": "LISTING.NOT_FOUND",
    "Correlation": "CORRELATION.NOT_FOUND",
    "Attachment": "ATTACHMENT.NOT_FOUND",
    "Template": "TEMPLATE.NOT_FOUND",
}

_DEFAULT_MESSAGES: dict[str, str] = {
    "PROFILE.NOT_FOUND": "Profile not found",
    "LISTING.NOT_FOUND": "Listing not found",
    "CORRELATION.NOT_FOUND": "Correlation not found",
    "ATTACHMENT.NOT_FOUND": "Attachment not found",
    "TEMPLATE.NOT_FOUND": "Template not found",
    "VALIDATION_ERROR": "Validation error",
    "SERVER_ERROR": "An unexpected error occurred",
}


def _map_resource_to_code(resource_type: str) -> str:
    return _RESOURCE_TYPE_TO_CODE.get(resource_type, "SERVER_ERROR")


def _get_status_code(error_code: str) -> int:
    if error_code.endswith(".NOT_FOUND"):
        return 404
    if error_code == "VALIDATION_ERROR":
        return 400
    return 500


# Inlined from bff_service.services.models


class _ProfileDetail(BaseModel):
    """Inlined from bff_service.services.models."""

    id: str
    user_id: str
    pref_name: str
    search_keywords: list[str] = Field(default_factory=list)
    disallowed_keywords: list[str] = Field(default_factory=list)
    work_arrangements: list[str] = Field(default_factory=list)
    notification_threshold: float = 0.75
    auto_tailor_threshold: float | None = None
    open_to_relocation: bool = False


class _ResolvedImportanceWeights(BaseModel):
    """Inlined from bff_service.services.models."""

    skill_match_importance: int
    location_importance: int
    work_arrangement_importance: int
    experience_importance: int
    salary_importance: int
    recency_importance: int
    source: str


# Inlined from notification_service.services.notification_config


@dataclass(frozen=True, slots=True)
class _ExtractedNotificationConfig:
    user_id: str
    pref_id: str
    threshold: int
    email_address: str | None


# BENCHMARKS

# Doc-process cache key building (every document request)

_BUILDER = _CacheKeyBuilder()
_CONTENT_ID = "550e8400-e29b-41d4-a716-446655440000"
_CONTENT_HASH = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"


def test_bench_cache_key_raw(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building raw document cache key."""
    benchmark(_BUILDER.raw_key, _CONTENT_ID)


def test_bench_cache_key_processed(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building processed document cache key."""
    benchmark(_BUILDER.processed_key, _CONTENT_HASH)


def test_bench_cache_key_processed_with_suffix(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark building processed cache key with level suffix."""
    benchmark(_BUILDER.processed_key, _CONTENT_HASH, "tables")


def test_bench_cache_key_checksum(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building checksum cache key."""
    benchmark(_BUILDER.checksum_key, _CONTENT_ID)


def test_bench_cache_key_task(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark building task state cache key."""
    benchmark(_BUILDER.task_key, "task-abc-123")


# Processing options (every document processing request)

_OPTS_DEFAULT = _ProcessingOptions()
_OPTS_FULL = _ProcessingOptions(
    enable_ocr=True,
    ocr_languages=("en", "de"),
    extract_tables=True,
    extract_images=True,
    enable_vlm_descriptions=True,
)


def test_bench_processing_options_create(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating default ProcessingOptions."""
    benchmark(_ProcessingOptions)


def test_bench_processing_options_create_full(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark creating full ProcessingOptions."""
    benchmark(
        _ProcessingOptions,
        enable_ocr=True,
        ocr_languages=("en", "de"),
        extract_tables=True,
        extract_images=True,
        enable_vlm_descriptions=True,
    )


def test_bench_processing_level_basic(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark level determination for BASIC (default options)."""
    opts = _ProcessingOptions(extract_tables=False)
    benchmark(lambda: opts.level)


def test_bench_processing_level_full(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark level determination for FULL (all options enabled)."""
    benchmark(lambda: _OPTS_FULL.level)


def test_bench_processing_cache_key_part(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark cache key part generation (SHA256 of options)."""
    benchmark(_OPTS_DEFAULT.to_cache_key_part)


def test_bench_processing_cache_key_part_full(
    benchmark: pytest.BenchmarkFixture,
) -> None:
    """Benchmark cache key part for full options (more JSON to hash)."""
    benchmark(_OPTS_FULL.to_cache_key_part)


# Notification template registry (every notification event)


def test_bench_template_registry_hit(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark template config lookup (hit)."""
    benchmark(_get_template_config, _EVENT_TYPE_CORRELATION)


def test_bench_template_registry_miss(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark template config lookup (miss)."""
    benchmark(_get_template_config, "nohiki.unknown.v1.UnknownEvent")


def test_bench_template_config_create(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating a TemplateConfig dataclass."""
    benchmark(
        _TemplateConfig,
        template_name="job_match",
        subject_template="New Match: {title}",
    )


def test_bench_notification_config_create(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating ExtractedNotificationConfig."""
    benchmark(
        _ExtractedNotificationConfig,
        user_id="user-123",
        pref_id="pref-456",
        threshold=75,
        email_address="user@example.com",
    )


def test_bench_subject_format(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark subject template string formatting."""
    config = _get_template_config(_EVENT_TYPE_CORRELATION)
    if config is None:
        msg = "Template config not found"
        raise RuntimeError(msg)
    benchmark(
        config.subject_template.format,
        listing_title="Senior Python Engineer",
        company_name="Acme Corp",
    )


# BFF error code mapping (every error response)


def test_bench_map_resource_to_code_hit(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark resource type → error code mapping (hit)."""
    benchmark(_map_resource_to_code, "Profile")


def test_bench_map_resource_to_code_miss(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark resource type → error code mapping (miss)."""
    benchmark(_map_resource_to_code, "Unknown")


def test_bench_get_status_code_404(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark status code resolution (404)."""
    benchmark(_get_status_code, "PROFILE.NOT_FOUND")


def test_bench_get_status_code_500(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark status code resolution (500 fallback)."""
    benchmark(_get_status_code, "SERVER_ERROR")


def test_bench_error_response_create(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating UserFacingErrorResponse."""
    benchmark(
        _UserFacingErrorResponse,
        error_code="PROFILE.NOT_FOUND",
        message="Profile not found",
        request_id="req-abc-123",
    )


def test_bench_error_response_model_dump(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark serializing error response to dict."""
    resp = _UserFacingErrorResponse(
        error_code="PROFILE.NOT_FOUND",
        message="Profile not found",
        request_id="req-abc-123",
    )
    benchmark(resp.model_dump, exclude_none=True)


# BFF response models (every API response)


def test_bench_profile_detail_create(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating ProfileDetail response model."""
    benchmark(
        _ProfileDetail,
        id="pref-123",
        user_id="user-456",
        pref_name="My Search",
        search_keywords=["python", "backend", "distributed systems"],
        work_arrangements=["REMOTE", "HYBRID"],
        notification_threshold=0.80,
    )


def test_bench_profile_detail_model_dump(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark serializing ProfileDetail to dict."""
    detail = _ProfileDetail(
        id="pref-123",
        user_id="user-456",
        pref_name="My Search",
        search_keywords=["python", "backend"],
        work_arrangements=["REMOTE"],
    )
    benchmark(detail.model_dump)


def test_bench_importance_weights_create(benchmark: pytest.BenchmarkFixture) -> None:
    """Benchmark creating ResolvedImportanceWeights."""
    benchmark(
        _ResolvedImportanceWeights,
        skill_match_importance=80,
        location_importance=60,
        work_arrangement_importance=70,
        experience_importance=50,
        salary_importance=40,
        recency_importance=30,
        source="search_pref_override",
    )
