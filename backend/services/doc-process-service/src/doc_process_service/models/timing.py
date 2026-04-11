"""Processing time estimates for progress reporting."""

from __future__ import annotations

from dataclasses import dataclass

from doc_process_service.models.domain import ProcessingLevel


@dataclass(frozen=True, slots=True)
class TimingEstimate:
    """Processing time estimates for a given level."""

    min_seconds: int
    typical_seconds: int
    max_seconds: int


_ESTIMATES: dict[ProcessingLevel, TimingEstimate] = {
    ProcessingLevel.BASIC: TimingEstimate(5, 15, 30),
    ProcessingLevel.TABLES: TimingEstimate(10, 30, 60),
    ProcessingLevel.OCR: TimingEstimate(30, 60, 180),
    ProcessingLevel.IMAGES: TimingEstimate(45, 120, 300),
    ProcessingLevel.FULL: TimingEstimate(60, 180, 600),
}


def get_timing_estimate(level: ProcessingLevel) -> TimingEstimate:
    """Get timing estimate for processing level."""
    return _ESTIMATES.get(level, _ESTIMATES[ProcessingLevel.BASIC])
