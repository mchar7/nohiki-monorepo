"""Semantic representation manifest schema, caching, and validation."""

from __future__ import annotations

from nohiki_ml_manifest.cache import DEFAULT_MANIFEST_PATH, ManifestCache
from nohiki_ml_manifest.calibration import (
    BaseCalibrationConfig,
    DenseCalibrationConfig,
    MaxSimCalibrationConfig,
)
from nohiki_ml_manifest.collections import (
    CollectionConfig,
    CollectionsConfig,
    QdrantCollectionSchema,
    QdrantSparseConfig,
    QdrantVectorDefinition,
)
from nohiki_ml_manifest.encoding import (
    DenseConfig,
    DenseNormalizationConfig,
    InferenceBackend,
    LateInteractionConfig,
    MaxSimNormalizationConfig,
    MuveraConfig,
    SparseConfig,
    SparseNormalizationConfig,
)
from nohiki_ml_manifest.features import (
    CRITICAL_FEATURES,
    FEATURE_COUNT,
    FEATURE_DESCRIPTIONS,
    FEATURE_NAME_LIST,
    FEATURE_NAMES,
    MONOTONE_CONSTRAINTS,
    FeatureIndex,
)
from nohiki_ml_manifest.manifest import SemanticRepresentationManifest
from nohiki_ml_manifest.settings import ManifestMixin
from nohiki_ml_manifest.validation import EmbeddingValidationResult, EmbeddingValidator

__all__ = [
    "CRITICAL_FEATURES",
    "DEFAULT_MANIFEST_PATH",
    "FEATURE_COUNT",
    "FEATURE_DESCRIPTIONS",
    "FEATURE_NAMES",
    "FEATURE_NAME_LIST",
    "MONOTONE_CONSTRAINTS",
    "BaseCalibrationConfig",
    "CollectionConfig",
    "CollectionsConfig",
    "DenseCalibrationConfig",
    "DenseConfig",
    "DenseNormalizationConfig",
    "EmbeddingValidationResult",
    "EmbeddingValidator",
    "FeatureIndex",
    "InferenceBackend",
    "LateInteractionConfig",
    "ManifestCache",
    "ManifestMixin",
    "MaxSimCalibrationConfig",
    "MaxSimNormalizationConfig",
    "MuveraConfig",
    "QdrantCollectionSchema",
    "QdrantSparseConfig",
    "QdrantVectorDefinition",
    "SemanticRepresentationManifest",
    "SparseConfig",
    "SparseNormalizationConfig",
]
