"""Tests for scoring package __getattr__ lazy loading mechanism."""

from __future__ import annotations

import pytest
from job_correlation_evaluation_service.services import scoring


class TestScoringLazyImport:
    """Tests for __getattr__ lazy-loading of heavy modules."""

    def test_lazy_import_resolves_scoring_pipeline(self) -> None:
        """Accessing ScoringPipeline via the package triggers lazy import."""
        cls = scoring.ScoringPipeline
        assert cls is not None
        assert hasattr(cls, "create")

    def test_lazy_import_resolves_pipeline_settings(self) -> None:
        """Accessing PipelineSettings via the package triggers lazy import."""
        cls = scoring.PipelineSettings
        assert cls is not None

    def test_lazy_import_raises_for_unknown_name(self) -> None:
        """Accessing non-existent attribute raises AttributeError."""
        with pytest.raises(AttributeError, match="has no attribute"):
            _ = scoring.NonExistentClassName
