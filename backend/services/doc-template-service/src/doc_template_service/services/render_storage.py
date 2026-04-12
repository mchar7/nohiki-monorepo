"""Storage service for rendered documents.

Handles uploading rendered documents to S3 and computing content metadata
(hash, size) for integrity verification.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from nohiki_observability import get_logger
from nohiki_s3_client import S3Client

from doc_template_service.core.config import get_settings

logger = get_logger(__name__)


@lru_cache(maxsize=1)
def _get_s3_client() -> S3Client:
    """Get S3 client configured from service settings."""
    settings = get_settings()
    return S3Client(settings.s3)


# S3 key prefix for rendered documents
RENDERED_DOCS_PREFIX = "rendered"


@dataclass(frozen=True, slots=True)
class StoredRenderResult:
    """Result of storing a rendered document in S3."""

    storage_key: str
    file_size: int
    content_hash: str


def _compute_content_hash(content: bytes) -> str:
    """Compute SHA-256 hash of content, returned as hex string."""
    return hashlib.sha256(content).hexdigest()


_SAFE_KEY_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def _validate_key_component(value: str, field_name: str) -> None:
    if not _SAFE_KEY_COMPONENT.fullmatch(value):
        message = f"Invalid {field_name} for rendered document storage key"
        raise ValueError(message)


def _build_storage_key(correlation_id: str, template_id: str, content_type: str) -> str:
    """Build S3 storage key for rendered document.

    Format: rendered/{correlation_id}/{template_id}.{ext}
    """
    _validate_key_component(correlation_id, "correlation_id")
    _validate_key_component(template_id, "template_id")
    extension = _content_type_to_extension(content_type)
    return f"{RENDERED_DOCS_PREFIX}/{correlation_id}/{template_id}.{extension}"


def _content_type_to_extension(content_type: str) -> str:
    """Map MIME content type to file extension."""
    mapping = {
        "application/pdf": "pdf",
        "image/png": "png",
        "image/jpeg": "jpg",
        "text/html": "html",
        "text/plain": "txt",
    }
    return mapping.get(content_type, "bin")


async def store_rendered_document(
    content: bytes,
    correlation_id: str,
    template_id: str,
    content_type: str,
    s3_client: S3Client | None = None,
) -> StoredRenderResult:
    """Store rendered document in S3 and return storage metadata.

    Args:
        content: The rendered document bytes.
        correlation_id: Correlation ID for the render request.
        template_id: Template ID that was rendered.
        content_type: MIME type of the rendered content.
        s3_client: Optional S3 client (uses singleton if not provided).

    Returns:
        StoredRenderResult with storage_key, file_size, and content_hash.

    Raises:
        S3ConnectionError: If upload fails.
        S3PermissionError: If access is denied.

    """
    client = s3_client or _get_s3_client()
    storage_key = _build_storage_key(correlation_id, template_id, content_type)
    content_hash = _compute_content_hash(content)
    file_size = len(content)

    await client.put_object(
        key=storage_key,
        data=content,
        content_type=content_type,
        metadata={
            "correlation-id": correlation_id,
            "template-id": template_id,
            "content-hash": content_hash,
        },
    )

    logger.info(
        "Stored rendered document in S3",
        storage_key=storage_key,
        file_size=file_size,
        content_type=content_type,
        correlation_id=correlation_id,
    )

    return StoredRenderResult(
        storage_key=storage_key,
        file_size=file_size,
        content_hash=content_hash,
    )
