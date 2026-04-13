"""Scoring Pipeline Stages.

This package contains the individual stage implementations for the
scoring pipeline:

Stage 1+2: Native MaxSim (native_maxsim.py)
    - Combined MUVERA retrieval + ColBERT MaxSim reranking via Qdrant multi-stage
    - Uses Qdrant's SIMD-optimized native MaxSim (no S3/Redis token fetching)
    - Returns ~150 candidates with maxsim_score
    - MUVERA is used for retrieval only, not as a scoring feature

Stage 3: LLM Rerank (llm_rerank.py)
    - Optional contextual reranking via external inference
    - Returns ~50 candidates with rerank_score

Stage 4: Deterministic final ranking (deterministic_final.py)
    - Semantic MaxSim anchor plus available stated-preference factors
    - Returns stable final ranking indices from 0-100
"""

from job_correlation_evaluation_service.services.scoring.stages.deterministic_final import (
    DeterministicFinalStage,
    FactorAttribution,
    ScoredCandidate,
)
from job_correlation_evaluation_service.services.scoring.stages.llm_rerank import (
    LLMRerankStage,
    RerankCandidate,
)
from job_correlation_evaluation_service.services.scoring.stages.native_maxsim import (
    NativeMaxSimCandidate,
    NativeMaxSimQuery,
    NativeMaxSimQueryParams,
    NativeMaxSimStage,
    build_native_maxsim_query,
)

__all__ = [
    "DeterministicFinalStage",
    "FactorAttribution",
    "LLMRerankStage",
    "NativeMaxSimCandidate",
    "NativeMaxSimQuery",
    "NativeMaxSimQueryParams",
    "NativeMaxSimStage",
    "RerankCandidate",
    "ScoredCandidate",
    "build_native_maxsim_query",
]
