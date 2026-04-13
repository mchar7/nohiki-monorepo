"""Scoring subsystem for job-correlation-evaluation-service.

Heavy modules (l2r, pipeline, stages, pipeline_config) are lazy-loaded via
``__getattr__`` to avoid pulling in nohiki-ml-core, LightGBM, NumPy, and
Qdrant client at import time.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from .config import (
    ScoringServiceSettings,
    get_scoring_service_settings,
)
from .constants import (
    COLBERT_TOKENS_S3_PREFIX,
    FEATURE_COUNT,
    FEATURE_DESCRIPTIONS,
    FEATURE_NAMES,
    MONOTONE_CONSTRAINTS,
    RAW_TEXT_S3_PREFIX,
    REDIS_COLBERT_CACHE_KEY_PREFIX,
    REDIS_COLBERT_CACHE_TTL_SECONDS,
    EntityType,
    FeatureIndex,
    PipelineStage,
    ScoringErrorMessage,
    StoragePrefix,
)
from .features import (
    FeatureComposer,
    FeatureExtractionContext,
    FeatureGroup,
    LocationMatchResult,
    LocationScenario,
    LocationScorer,
    LocationScoringConfig,
    PipelineScores,
    SkillMatchQualityCalculator,
    SkillMatchQualityResult,
    SkillMatchWeights,
)
from .schemas import (
    ExtractedSkill,
    FeatureVector,
    JobMetadataExtraction,
    RerankCandidate,
    RerankResult,
    ScoringResult,
    SkillExtractionResult,
    SkillMatchResult,
)

if TYPE_CHECKING:
    from .pipeline import (
        PipelineResult as PipelineResult,
    )
    from .pipeline import (
        QueryEncoding as QueryEncoding,
    )
    from .pipeline import (
        ScoringPipeline as ScoringPipeline,
    )
    from .pipeline import (
        StageTimings as StageTimings,
    )
    from .pipeline_config import (
        PipelineSettings as PipelineSettings,
    )
    from .pipeline_config import (
        get_pipeline_settings as get_pipeline_settings,
    )
    from .stages import (
        DeterministicFinalStage as DeterministicFinalStage,
    )
    from .stages import (
        LLMRerankStage as LLMRerankStage,
    )
    from .stages import (
        NativeMaxSimCandidate as NativeMaxSimCandidate,
    )
    from .stages import (
        NativeMaxSimStage as NativeMaxSimStage,
    )
    from .stages import (
        RerankCandidate as StageRerankCandidate,
    )
    from .stages import (
        ScoredCandidate as ScoredCandidate,
    )

_PKG = __name__.rsplit(".", maxsplit=1)[0] + ".scoring"

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "PipelineResult": (f"{_PKG}.pipeline", "PipelineResult"),
    "QueryEncoding": (f"{_PKG}.pipeline", "QueryEncoding"),
    "ScoringPipeline": (f"{_PKG}.pipeline", "ScoringPipeline"),
    "StageTimings": (f"{_PKG}.pipeline", "StageTimings"),
    "PipelineSettings": (f"{_PKG}.pipeline_config", "PipelineSettings"),
    "get_pipeline_settings": (f"{_PKG}.pipeline_config", "get_pipeline_settings"),
    "DeterministicFinalStage": (f"{_PKG}.stages", "DeterministicFinalStage"),
    "LLMRerankStage": (f"{_PKG}.stages", "LLMRerankStage"),
    "NativeMaxSimCandidate": (f"{_PKG}.stages", "NativeMaxSimCandidate"),
    "NativeMaxSimStage": (f"{_PKG}.stages", "NativeMaxSimStage"),
    "ScoredCandidate": (f"{_PKG}.stages", "ScoredCandidate"),
    "StageRerankCandidate": (f"{_PKG}.stages", "RerankCandidate"),
}


def __getattr__(name: str) -> object:
    """Lazy-load heavy scoring modules on first access."""
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        module = importlib.import_module(module_path)
        return getattr(module, attr_name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "COLBERT_TOKENS_S3_PREFIX",
    "FEATURE_COUNT",
    "FEATURE_DESCRIPTIONS",
    "FEATURE_NAMES",
    "MONOTONE_CONSTRAINTS",
    "RAW_TEXT_S3_PREFIX",
    "REDIS_COLBERT_CACHE_KEY_PREFIX",
    "REDIS_COLBERT_CACHE_TTL_SECONDS",
    "DeterministicFinalStage",
    "EntityType",
    "ExtractedSkill",
    "FeatureComposer",
    "FeatureExtractionContext",
    "FeatureGroup",
    "FeatureIndex",
    "FeatureVector",
    "JobMetadataExtraction",
    "LLMRerankStage",
    "LocationMatchResult",
    "LocationScenario",
    "LocationScorer",
    "LocationScoringConfig",
    "NativeMaxSimCandidate",
    "NativeMaxSimStage",
    "PipelineResult",
    "PipelineScores",
    "PipelineSettings",
    "PipelineStage",
    "QueryEncoding",
    "RerankCandidate",
    "RerankResult",
    "ScoredCandidate",
    "ScoringErrorMessage",
    "ScoringPipeline",
    "ScoringResult",
    "ScoringServiceSettings",
    "SkillExtractionResult",
    "SkillMatchQualityCalculator",
    "SkillMatchQualityResult",
    "SkillMatchResult",
    "SkillMatchWeights",
    "StageRerankCandidate",
    "StageTimings",
    "StoragePrefix",
    "get_pipeline_settings",
    "get_scoring_service_settings",
]
