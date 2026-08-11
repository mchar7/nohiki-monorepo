"""Structured scores for the residual, subjective portion of job extraction evaluation.

Fields with deterministic gold labels are deliberately excluded from this schema.
"""

from __future__ import annotations

from typing import Annotated, Final

from pydantic import BaseModel, Field

CATEGORY_NAMES: Final[tuple[str, ...]] = (
    "inference_reasonableness",
    "description_quality",
    "downstream_usefulness",
)


class CategoryScore(BaseModel):
    """Score for a single evaluation category with mandatory justification.

    Attributes:
        score: Numeric score from 0-100.
        reasoning: Concise justification referencing specific extraction
            fields and how they compare to the source material.
    """

    score: Annotated[int, Field(ge=0, le=100)]
    reasoning: Annotated[str, Field(min_length=10, max_length=60)]


class PointwiseJudgment(BaseModel):
    """Residual subjective assessment for one blinded extraction output.

    Deterministically verifiable correctness, schema adherence, and critical
    failures belong to the gold evaluator and cannot be decided here.
    """

    inference_reasonableness: CategoryScore
    description_quality: CategoryScore
    downstream_usefulness: CategoryScore
    summary: Annotated[str, Field(min_length=15, max_length=80)]

    @property
    def category_scores(self) -> dict[str, int]:
        """All residual category scores as a flat mapping."""
        return {name: self._get_category_score(name) for name in CATEGORY_NAMES}

    def _get_category_score(self, name: str) -> int:
        """Return one residual category score."""
        field_value: CategoryScore = getattr(self, name)
        return field_value.score

    @property
    def average_score(self) -> float:
        """Mean score across residual categories."""
        return sum(self.category_scores.values()) / len(CATEGORY_NAMES)
