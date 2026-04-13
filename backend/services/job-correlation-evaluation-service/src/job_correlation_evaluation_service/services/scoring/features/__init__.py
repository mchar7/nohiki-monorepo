"""Feature engineering for L2R scoring model."""

from .base import FeatureExtractionContext, FeatureGroup, PipelineScores
from .composer import FeatureComposer
from .groups import (
    ExperienceFeatureGroup,
    JobMetadataFeatureGroup,
    LocationFeatureGroup,
    PipelineFeatureGroup,
    SalaryFeatureGroup,
    SemanticFeatureGroup,
    SkillFeatureGroup,
    ValidityFlagsFeatureGroup,
    WorkArrangementFeatureGroup,
)
from .location_scorer import LocationMatchResult, LocationScenario, LocationScorer, LocationScoringConfig
from .skill_match_quality import SkillMatchQualityCalculator, SkillMatchQualityResult, SkillMatchWeights

__all__ = [
    "ExperienceFeatureGroup",
    "FeatureComposer",
    "FeatureExtractionContext",
    "FeatureGroup",
    "JobMetadataFeatureGroup",
    "LocationFeatureGroup",
    "LocationMatchResult",
    "LocationScenario",
    "LocationScorer",
    "LocationScoringConfig",
    "PipelineFeatureGroup",
    "PipelineScores",
    "SalaryFeatureGroup",
    "SemanticFeatureGroup",
    "SkillFeatureGroup",
    "SkillMatchQualityCalculator",
    "SkillMatchQualityResult",
    "SkillMatchWeights",
    "ValidityFlagsFeatureGroup",
    "WorkArrangementFeatureGroup",
]
