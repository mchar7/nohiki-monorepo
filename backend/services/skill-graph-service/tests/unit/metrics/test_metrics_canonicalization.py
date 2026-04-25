"""Unit tests for skill canonicalization metrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from skill_graph_service.metrics.skill_canonicalization import (
    BatchCanonicalizationResult,
    SkillCanonicalizationMetrics,
    get_skill_canonicalization_metrics,
)


class TestSkillCanonicalizationMetrics:
    """Tests for SkillCanonicalizationMetrics class."""

    def test_record_skill_processed_with_cache_hit(self) -> None:
        """Test recording skill processing metrics with cache hit."""
        mock_counter = MagicMock()
        mock_histogram = MagicMock()

        with (
            patch.object(SkillCanonicalizationMetrics, "__init__", return_value=None),
            patch.object(SkillCanonicalizationMetrics, "_get_counter", return_value=mock_counter),
            patch.object(SkillCanonicalizationMetrics, "_get_histogram", return_value=mock_histogram),
        ):
            metrics = SkillCanonicalizationMetrics()
            metrics.record_skill_processed("normalization", 0.5, cache_hit=True, success=True)

            mock_counter.add.assert_called()
            mock_histogram.record.assert_called()

    def test_record_skill_processed_with_failure(self) -> None:
        """Test recording skill processing metrics with failure."""
        mock_counter = MagicMock()
        mock_histogram = MagicMock()

        with (
            patch.object(SkillCanonicalizationMetrics, "__init__", return_value=None),
            patch.object(SkillCanonicalizationMetrics, "_get_counter", return_value=mock_counter),
            patch.object(SkillCanonicalizationMetrics, "_get_histogram", return_value=mock_histogram),
        ):
            metrics = SkillCanonicalizationMetrics()
            metrics.record_skill_processed("normalization", 0.5, cache_hit=False, success=False)

            # Should record error counter
            mock_counter.add.assert_called()

    def test_record_feature_extraction_success(self) -> None:
        """Test recording feature extraction metrics on success."""
        mock_counter = MagicMock()
        mock_histogram = MagicMock()

        with (
            patch.object(SkillCanonicalizationMetrics, "__init__", return_value=None),
            patch.object(SkillCanonicalizationMetrics, "_get_counter", return_value=mock_counter),
            patch.object(SkillCanonicalizationMetrics, "_get_histogram", return_value=mock_histogram),
        ):
            metrics = SkillCanonicalizationMetrics()
            metrics.record_feature_extraction(0.8, success=True)

            mock_histogram.record.assert_called_once()
            mock_counter.add.assert_not_called()

    def test_record_feature_extraction_failure(self) -> None:
        """Test recording feature extraction metrics on failure."""
        mock_counter = MagicMock()
        mock_histogram = MagicMock()

        with (
            patch.object(SkillCanonicalizationMetrics, "__init__", return_value=None),
            patch.object(SkillCanonicalizationMetrics, "_get_counter", return_value=mock_counter),
            patch.object(SkillCanonicalizationMetrics, "_get_histogram", return_value=mock_histogram),
        ):
            metrics = SkillCanonicalizationMetrics()
            metrics.record_feature_extraction(0.8, success=False)

            mock_histogram.record.assert_called()
            mock_counter.add.assert_called()

    def test_record_batch_canonicalization(self) -> None:
        """Test recording batch canonicalization metrics."""
        mock_counter = MagicMock()
        mock_histogram = MagicMock()

        with (
            patch.object(SkillCanonicalizationMetrics, "__init__", return_value=None),
            patch.object(SkillCanonicalizationMetrics, "_get_counter", return_value=mock_counter),
            patch.object(SkillCanonicalizationMetrics, "_get_histogram", return_value=mock_histogram),
        ):
            metrics = SkillCanonicalizationMetrics()
            result = BatchCanonicalizationResult(
                batch_size=10,
                duration_seconds=1.5,
                matched_count=8,
                new_skill_count=1,
                needs_review_count=1,
                failed_count=0,
            )

            metrics.record_batch_canonicalization(result)

            mock_counter.add.assert_called()
            mock_histogram.record.assert_called()

    def test_singleton_getter(self) -> None:
        """Test that get_skill_canonicalization_metrics returns a singleton."""
        get_skill_canonicalization_metrics.cache_clear()
        with patch("skill_graph_service.metrics.skill_canonicalization.SkillCanonicalizationMetrics") as mock_class:
            m1 = get_skill_canonicalization_metrics()
            m2 = get_skill_canonicalization_metrics()
            assert m1 is m2
            assert mock_class.call_count == 1
