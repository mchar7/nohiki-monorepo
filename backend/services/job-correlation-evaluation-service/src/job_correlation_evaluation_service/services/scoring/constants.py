"""Centralized constants for the scoring subsystem.

ML feature schema (FeatureIndex, FEATURE_COUNT, FEATURE_NAMES, FEATURE_DESCRIPTIONS,
MONOTONE_CONSTRAINTS) is defined in nohiki-ml-manifest and imported here to keep
a single source of truth accessible to both services and shared libraries.

ML model parameters and pipeline configuration are derived from the
SemanticRepresentationManifest loaded via config.get_manifest().

Architecture: ColBERT multi-vector late-interaction system with 4-stage scoring.
MUVERA is used for retrieval only (Stage 1 ANN), not as a scoring feature.

Design Philosophy (Raw Features for L2R):
- Provide RAW values to let LightGBM learn optimal thresholds via tree splits
- Avoid manual normalization to [0,1] which loses information
- Use multiple granular features instead of composite scores
- NaN for missing data with validity flags for explicit missingness signal
- No arbitrary human-defined thresholds (model learns from training data)
"""

from enum import StrEnum
from typing import Final

from nohiki_ml_manifest import (
    CRITICAL_FEATURES as CRITICAL_FEATURES,
)
from nohiki_ml_manifest import (
    FEATURE_COUNT as FEATURE_COUNT,
)
from nohiki_ml_manifest import (
    FEATURE_DESCRIPTIONS as FEATURE_DESCRIPTIONS,
)
from nohiki_ml_manifest import (
    FEATURE_NAME_LIST as FEATURE_NAME_LIST,
)
from nohiki_ml_manifest import (
    FEATURE_NAMES as FEATURE_NAMES,
)
from nohiki_ml_manifest import (
    MONOTONE_CONSTRAINTS as MONOTONE_CONSTRAINTS,
)
from nohiki_ml_manifest import (
    FeatureIndex as FeatureIndex,
)

FEATURE_SCHEMA_VERSION: Final = "v1"

# Pipeline Stage Identifiers


class PipelineStage(StrEnum):
    """Scoring pipeline stages."""

    COLBERT_MAXSIM = "colbert_maxsim"
    LLM_RERANK = "llm_rerank"
    DETERMINISTIC_FINAL = "deterministic_final"


# Error Messages


class ScoringErrorMessage(StrEnum):
    """Parameterized error messages. Use .format() to substitute."""

    COLBERT_TOKENS_NOT_FOUND = "ColBERT tokens not found for entity_id={entity_id} at s3_key={s3_key}"
    PROFILE_EMBEDDING_NOT_FOUND = "Profile embedding not found for pref_id={pref_id}"
    L2R_MODEL_NOT_LOADED = "L2R model not loaded - ensure model file exists at {path}"
    FEATURE_COUNT_MISMATCH = "Feature count mismatch: expected {expected}, got {actual}"
    PIPELINE_STAGE_FAILED = "Pipeline failed at stage '{stage}': {reason}"
    SCORING_SERVICE_NOT_INITIALIZED = "ScoringService not initialized - call initialize() first"
    CORRELATION_NOT_FOUND = "Correlation not found: {correlation_id}"
    SEMANTIC_REPR_NOT_FOUND = "SemanticRepresentationManifest not found: {manifest_id}"
    CONTENT_HASH_MISMATCH = "Content hash mismatch: expected={expected}, got={actual}"
    QDRANT_COLLECTION_NOT_FOUND = "Qdrant collection not found: {collection_name}"
    SNAPSHOT_LEDGER_STALE = "Snapshot ledger entry stale for {entity_type}:{entity_id}"


# Storage Configuration


class StoragePrefix(StrEnum):
    """S3 storage key prefixes for ML artifacts."""

    COLBERT_TOKENS = "colbert_tokens"
    RAW_TEXTS = "raw_texts"
    L2R_MODELS = "l2r_models"


COLBERT_TOKENS_S3_PREFIX: Final[str] = (
    f"{StoragePrefix.COLBERT_TOKENS}/{{entity_type}}/{{entity_id}}/{{content_hash}}.npz"
)
RAW_TEXT_S3_PREFIX: Final[str] = f"{StoragePrefix.RAW_TEXTS}/{{entity_type}}/{{entity_id}}/{{content_hash}}.txt"

REDIS_COLBERT_CACHE_TTL_SECONDS: Final[int] = 21600  # 6 hours
REDIS_COLBERT_CACHE_KEY_PREFIX: Final[str] = "colbert_tokens"


# Entity Types


class EntityType(StrEnum):
    """Entity types for embedding and storage."""

    JOB_LISTING = "job_listing"
    SEARCH_PREF = "search_pref"
    USER_DOCUMENT = "user_document"
