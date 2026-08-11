"""Embedding publisher and state configuration for user-pref-service."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from hashlib import sha256

from nohiki.ml.v1 import EmbeddingType, EncodingMode, EntityType
from nohiki_common_exceptions import ValidationError
from nohiki_embedding_client import EmbeddingPublisher, EmbeddingSpec
from nohiki_kafka_client import CallbackStateMixin, Topics

from user_pref_service.core.config import get_manifest, get_settings

PREF_EMBEDDING_SPEC = EmbeddingSpec(
    requested_types=[EmbeddingType.MUVERA, EmbeddingType.SPARSE, EmbeddingType.COLBERT],
    encoding_mode=EncodingMode.QUERY,
    publish_to_index=False,
)
"""Canonical QUERY embedding spec for profiles used to retrieve DOCUMENT jobs."""

_MAX_SEMANTIC_COMPONENT_LENGTH = 100
_MAX_SEARCH_KEYWORDS = 20
_MAX_CANONICAL_SKILLS = 50


def build_profile_embedding_text(
    pref_name: str,
    search_keywords: list[str],
    canonical_skill_names: list[str] | None = None,
) -> str:
    """Build bounded profile query text in stable semantic-field order."""
    components: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        normalized = " ".join(raw.split())[:_MAX_SEMANTIC_COMPONENT_LENGTH].strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            components.append(normalized)

    add(pref_name)
    for keyword in search_keywords[:_MAX_SEARCH_KEYWORDS]:
        add(keyword)
    for skill_name in (canonical_skill_names or [])[:_MAX_CANONICAL_SKILLS]:
        add(skill_name)

    if not components:
        msg = "Profile has no semantic content to embed"
        raise ValidationError(msg)
    return " ".join(components)


@dataclass(frozen=True, slots=True)
class PrefEnrichmentSagaContext(CallbackStateMixin):
    """Minimal durable saga identity carried across callback boundaries."""

    saga_id: str


def profile_embedding_content_hash(embedded_text: str) -> str:
    """Return the embedding pipeline's normalized content identity."""
    return sha256(embedded_text.strip().lower().encode("utf-8")).hexdigest()


@cache
def get_embedding_publisher() -> EmbeddingPublisher:
    """Get singleton embedding publisher for user-pref-service.

    Returns:
        Configured EmbeddingPublisher for user-pref-service.

    """
    manifest = get_manifest()
    return EmbeddingPublisher(
        callback_topic=Topics.USER_PREF_EMBEDDING_CALLBACK,
        service_name=get_settings().service_name,
        collection_version=manifest.get_entity_version(EntityType.PROFILE),
    )
