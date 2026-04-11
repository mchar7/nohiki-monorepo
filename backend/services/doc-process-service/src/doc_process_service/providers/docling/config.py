"""Configuration for Docling client."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from doc_process_service.core.config import DoclingSettings, VLMSettings


@dataclass(frozen=True, slots=True)
class DoclingClientConfig:
    """Immutable configuration for DoclingClient."""

    base_url: str
    timeout: float
    api_key: str | None
    pipeline: str
    pdf_backend: str
    ocr_engine: str
    table_mode: str
    do_ocr: bool
    force_ocr: bool
    do_table_structure: bool
    include_images: bool
    do_picture_description: bool
    picture_description_custom_config: str | None
    poll_interval: float
    max_poll_attempts: int

    @classmethod
    def from_settings(cls, docling: DoclingSettings, vlm: VLMSettings) -> DoclingClientConfig:
        """Create config from provider and VLM settings.

        Args:
            docling: Docling provider settings.
            vlm: VLM settings for picture descriptions.

        Returns:
            DoclingClientConfig instance.

        """
        picture_description_custom_config = None
        if vlm.enabled:
            params: dict[str, object] = {
                "model": vlm.model,
                "max_completion_tokens": vlm.max_tokens,
                "temperature": vlm.temperature,
                **vlm.extra_params,
            }
            if vlm.thinking_budget > 0:
                params["thinking"] = {"budget_tokens": vlm.thinking_budget}

            # Build headers: explicit headers + api_key as Bearer token
            vlm_headers = dict(vlm.headers)
            if vlm.api_key and "Authorization" not in vlm_headers:
                vlm_headers["Authorization"] = f"Bearer {vlm.api_key}"

            picture_description_custom_config = json.dumps(
                {
                    "model_spec": {
                        "name": vlm.model,
                        "default_repo_id": vlm.model,
                        "prompt": vlm.prompt,
                        "response_format": vlm.response_format,
                    },
                    "engine_options": {
                        "engine_type": vlm.engine_type,
                        "url": vlm.api_url,
                        "headers": vlm_headers,
                        "params": params,
                        "timeout": vlm.timeout_seconds,
                        "concurrency": 1,
                    },
                    "prompt": vlm.prompt,
                    "picture_area_threshold": vlm.picture_area_threshold,
                }
            )

        return cls(
            base_url=docling.base_url,
            timeout=docling.timeout_seconds,
            api_key=docling.api_key,
            pipeline=docling.pipeline,
            pdf_backend=docling.pdf_backend,
            ocr_engine=docling.ocr_engine,
            table_mode=docling.table_mode,
            do_ocr=docling.do_ocr,
            force_ocr=docling.force_ocr,
            do_table_structure=docling.do_table_structure,
            include_images=docling.include_images,
            do_picture_description=docling.do_picture_description or vlm.enabled,
            picture_description_custom_config=picture_description_custom_config,
            poll_interval=docling.poll_interval_seconds,
            max_poll_attempts=docling.max_poll_attempts,
        )
