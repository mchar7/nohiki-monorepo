"""Skill normalization package.

Public API for skill normalization workflows. Handlers should import only from
this module, not from internal submodules.
"""

from skill_graph_service.services.normalization.codec import (
    deserialize_deterministic_match_result,
    deserialize_skill_result,
    serialize_skill_result,
)
from skill_graph_service.services.normalization.models import (
    BatchNormalizationResult,
    DeterministicMatchResult,
    NormalizationEmbeddingState,
    SkillNormalizationResult,
)
from skill_graph_service.services.normalization.workflow import (
    assemble_batch_normalization_result,
    resolve_canonical_skill_ids,
    run_deterministic_matching,
    run_semantic_qdrant_search,
)

__all__ = [
    "BatchNormalizationResult",
    "DeterministicMatchResult",
    "NormalizationEmbeddingState",
    "SkillNormalizationResult",
    "assemble_batch_normalization_result",
    "deserialize_deterministic_match_result",
    "deserialize_skill_result",
    "resolve_canonical_skill_ids",
    "run_deterministic_matching",
    "run_semantic_qdrant_search",
    "serialize_skill_result",
]
