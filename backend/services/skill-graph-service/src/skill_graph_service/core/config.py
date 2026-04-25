"""Service configuration using composable mixins."""

from __future__ import annotations

from functools import cache

from nohiki.ml.v1 import EntityType
from nohiki_core_settings import NohikiBaseSettings
from nohiki_db_utils import DatabaseMixin
from nohiki_kafka_client import KafkaConsumerSettings, KafkaMixin, KafkaSettings
from nohiki_ml_manifest import ManifestCache, ManifestMixin, SemanticRepresentationManifest
from nohiki_qdrant_client import QdrantMixin, QdrantVectorClient
from nohiki_redis_utils import RedisMixin
from pydantic import BaseModel, Field
from pydantic_settings import SettingsConfigDict

from skill_graph_service.core.readiness import SkillEmbeddingReadinessGate


class ReadinessGateSettings(BaseModel):
    """Settings for the SkillEmbeddingReadinessGate background poll.

    Controls how long the service waits for initial skill embeddings before
    declaring itself ready. These values are tunable without code changes via
    environment variables (e.g. ``SKILL_GRAPH_READINESS_GATE__MIN_POINT_COUNT``).
    """

    min_point_count: int = Field(
        default=1,
        ge=1,
        description=(
            "Minimum Qdrant point count before /readyz returns 200. "
            "Default 1: service becomes ready as soon as any embedding exists."
        ),
    )

    poll_interval_seconds: float = Field(
        default=5.0,
        gt=0.0,
        description="Seconds between Qdrant count polls in the readiness gate background task.",
    )


class NormalizationThresholds(BaseModel):
    """Model-independent thresholds for skill auto-canonicalization.

    2-STAGE MATCHING STRATEGY (ordered by cost, lowest first):
    1. Exact match (DB lookup) → CONFIDENT
    2. Alias lookup (DB) → CONFIDENT
    3. Jaccard n-gram ≥0.92 → AUTO_MATCH (local computation, catches typos)
    4. Semantic ≥auto_match_threshold → AUTO_MATCH (from manifest)
    5. Semantic uncertain_min..auto_match → UNCERTAIN (LLM decides)
    6. Semantic <uncertain_min → NO_MATCH (propose new skill)

    NOTE: Semantic thresholds are model-dependent and live in the manifest at
    manifest.dense.normalization. This class only contains model-independent
    thresholds. Use get_manifest().dense.normalization for semantic thresholds.

    Calibration: scripts/calibrate_skill_thresholds/
    """

    jaccard_auto_match: float = Field(
        default=0.92,
        ge=0.0,
        le=1.0,
        description=(
            "Jaccard n-gram threshold for auto-canonicalization. "
            "Empirically derived: 0.92 gives zero false positives on 60K distinct pairs."
        ),
    )

    min_skill_length: int = Field(
        default=2,
        ge=1,
        description="Minimum length for valid skill string.",
    )

    top_n_candidates: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of candidate skills to return for LLM clarification.",
    )

    max_jaccard_candidates: int = Field(
        default=1000,
        ge=100,
        description="Maximum skills to fetch for Jaccard comparison (performance limit).",
    )


class Settings(ManifestMixin, QdrantMixin, DatabaseMixin, RedisMixin, KafkaMixin, NohikiBaseSettings):
    """skill-graph-service settings."""

    model_config = SettingsConfigDict(env_prefix="SKILL_GRAPH_")

    service_name: str = "skill-graph-service"
    service_version: str = "0.1.0"
    service_name_friendly: str = "Skill Graph Service"
    service_desc_friendly: str = "Skill normalization and graph management"

    kafka: KafkaSettings = Field(
        default_factory=lambda: KafkaSettings(
            consumer=KafkaConsumerSettings(
                max_concurrent_handlers=5,
            ),
        )
    )
    normalization: NormalizationThresholds = Field(default_factory=NormalizationThresholds)
    readiness_gate: ReadinessGateSettings = Field(default_factory=ReadinessGateSettings)

    @property
    def kafka_consumer_group(self) -> str:
        """Return the Kafka consumer group for this service."""
        return f"{self.service_name}-mention-primary"


@cache
def get_settings() -> Settings:
    """Get cached settings singleton.

    Returns:
        Configured settings instance.

    """
    return Settings()


def get_manifest() -> SemanticRepresentationManifest:
    """Get the cached manifest via shared ManifestCache.

    Returns:
        Loaded semantic representation manifest.

    """
    return ManifestCache.get(get_settings().manifest_path)


@cache
def get_qdrant_client() -> QdrantVectorClient:
    """Construct QdrantVectorClient with settings + manifest schema for skills."""
    manifest = get_manifest()
    return QdrantVectorClient(
        get_settings().qdrant,
        manifest.collections.skills.qdrant,
    )


@cache
def get_readiness_gate() -> SkillEmbeddingReadinessGate:
    """Get cached readiness gate singleton.

    Shared between health probes and normalization handlers so both
    use the same Qdrant polling state.
    """
    s = get_settings()
    rg = s.readiness_gate
    manifest = get_manifest()
    return SkillEmbeddingReadinessGate(
        qdrant_client=get_qdrant_client(),
        collection_name=manifest.get_collection_name(EntityType.SKILL),
        min_point_count=rg.min_point_count,
        poll_interval_seconds=rg.poll_interval_seconds,
    )
