"""Unit tests for skill_canonicalization metrics module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from job_correlation_evaluation_service.metrics.skill_canonicalization import (
    SkillCanonicalizationMetrics,
    get_skill_canonicalization_metrics,
)


class TestSkillCanonicalizationMetrics:
    """Tests for SkillCanonicalizationMetrics class."""

    @pytest.fixture
    def metrics(self) -> SkillCanonicalizationMetrics:
        """Create metrics instance."""
        return SkillCanonicalizationMetrics()

    def test_initializes_with_counters_and_histograms(self, metrics: SkillCanonicalizationMetrics) -> None:
        """Test metrics initializes all counters and histograms."""
        assert metrics.skills_processed is not None
        assert metrics.cache_hits is not None
        assert metrics.cache_misses is not None
        assert metrics.latency is not None
        assert metrics.errors is not None
        assert metrics.feature_extraction_latency is not None

    def test_record_skill_processed_success_cache_hit(self, metrics: SkillCanonicalizationMetrics) -> None:
        """Test recording successful skill processing with cache hit."""
        mock_processed = MagicMock()
        mock_latency = MagicMock()
        mock_hits = MagicMock()
        mock_misses = MagicMock()
        mock_errors = MagicMock()
        metrics.skills_processed = mock_processed
        metrics.latency = mock_latency
        metrics.cache_hits = mock_hits
        metrics.cache_misses = mock_misses
        metrics.errors = mock_errors

        metrics.record_skill_processed(
            stage="canonicalization",
            duration_seconds=0.05,
            cache_hit=True,
            success=True,
        )

        mock_processed.add.assert_called_once()
        mock_latency.record.assert_called_once()
        mock_hits.add.assert_called_once()
        mock_misses.add.assert_not_called()
        mock_errors.add.assert_not_called()

    def test_record_skill_processed_success_cache_miss(self, metrics: SkillCanonicalizationMetrics) -> None:
        """Test recording successful skill processing with cache miss."""
        mock_processed = MagicMock()
        mock_latency = MagicMock()
        mock_hits = MagicMock()
        mock_misses = MagicMock()
        mock_errors = MagicMock()
        metrics.skills_processed = mock_processed
        metrics.latency = mock_latency
        metrics.cache_hits = mock_hits
        metrics.cache_misses = mock_misses
        metrics.errors = mock_errors

        metrics.record_skill_processed(
            stage="canonicalization",
            duration_seconds=0.1,
            cache_hit=False,
            success=True,
        )

        mock_misses.add.assert_called_once()
        mock_hits.add.assert_not_called()
        mock_errors.add.assert_not_called()

    def test_record_skill_processed_failure(self, metrics: SkillCanonicalizationMetrics) -> None:
        """Test recording failed skill processing."""
        mock_processed = MagicMock()
        mock_latency = MagicMock()
        mock_hits = MagicMock()
        mock_misses = MagicMock()
        mock_errors = MagicMock()
        metrics.skills_processed = mock_processed
        metrics.latency = mock_latency
        metrics.cache_hits = mock_hits
        metrics.cache_misses = mock_misses
        metrics.errors = mock_errors

        metrics.record_skill_processed(
            stage="canonicalization",
            duration_seconds=0.05,
            cache_hit=False,
            success=False,
        )

        mock_errors.add.assert_called_once()

    def test_record_feature_extraction_success(self, metrics: SkillCanonicalizationMetrics) -> None:
        """Test recording successful feature extraction."""
        mock_latency = MagicMock()
        mock_errors = MagicMock()
        metrics.feature_extraction_latency = mock_latency
        metrics.errors = mock_errors

        metrics.record_feature_extraction(duration_seconds=0.2, success=True)

        mock_latency.record.assert_called_once()
        mock_errors.add.assert_not_called()

    def test_record_feature_extraction_failure(self, metrics: SkillCanonicalizationMetrics) -> None:
        """Test recording failed feature extraction."""
        mock_latency = MagicMock()
        mock_errors = MagicMock()
        metrics.feature_extraction_latency = mock_latency
        metrics.errors = mock_errors

        metrics.record_feature_extraction(duration_seconds=0.2, success=False)

        mock_latency.record.assert_called_once()
        mock_errors.add.assert_called_once()


class TestGetSkillCanonicalizationMetrics:
    """Tests for get_skill_canonicalization_metrics factory."""

    def test_returns_singleton(self) -> None:
        """Test factory returns same instance."""
        get_skill_canonicalization_metrics.cache_clear()

        metrics1 = get_skill_canonicalization_metrics()
        metrics2 = get_skill_canonicalization_metrics()

        assert metrics1 is metrics2

        get_skill_canonicalization_metrics.cache_clear()

    def test_returns_metrics_instance(self) -> None:
        """Test factory returns SkillCanonicalizationMetrics instance."""
        get_skill_canonicalization_metrics.cache_clear()

        metrics = get_skill_canonicalization_metrics()

        assert isinstance(metrics, SkillCanonicalizationMetrics)

        get_skill_canonicalization_metrics.cache_clear()
