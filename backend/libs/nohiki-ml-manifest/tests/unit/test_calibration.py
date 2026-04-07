"""Unit tests for calibration provenance models."""

from __future__ import annotations

from datetime import date

import pytest
from nohiki_ml_manifest.calibration import (
    BaseCalibrationConfig,
    DenseCalibrationConfig,
    MaxSimCalibrationConfig,
)
from nohiki_ml_manifest.encoding import DenseNormalizationConfig
from pydantic import ValidationError


class TestBaseCalibrationConfig:
    """Tests for BaseCalibrationConfig shared behavior."""

    def test_accepts_iso_date_string(self) -> None:
        """Test that ISO format date strings are coerced to date objects."""
        config = BaseCalibrationConfig.model_validate(
            {
                "calibration_model_id": "test/model",
                "calibration_pairs_count": 100,
                "calibration_date": "2025-06-15",
            }
        )
        assert config.calibration_date == date(2025, 6, 15)
        assert isinstance(config.calibration_date, date)

    def test_rejects_invalid_date_string(self) -> None:
        """Test that invalid date strings are rejected."""
        with pytest.raises(ValidationError):
            BaseCalibrationConfig.model_validate(
                {
                    "calibration_model_id": "test/model",
                    "calibration_pairs_count": 100,
                    "calibration_date": "not-a-date",
                }
            )

    def test_rejects_invalid_calendar_date(self) -> None:
        """Test that invalid calendar dates like Feb 30 are rejected."""
        with pytest.raises(ValidationError):
            BaseCalibrationConfig.model_validate(
                {
                    "calibration_model_id": "test/model",
                    "calibration_pairs_count": 100,
                    "calibration_date": "2025-02-30",
                }
            )

    def test_json_serialization_uses_iso_format(self) -> None:
        """Test that JSON serialization produces ISO format strings."""
        config = BaseCalibrationConfig(
            calibration_model_id="test/model",
            calibration_pairs_count=100,
            calibration_date=date(2025, 6, 15),
        )
        data = config.model_dump(mode="json")
        assert data["calibration_date"] == "2025-06-15"


class TestMaxSimCalibrationConfig:
    """Tests for MaxSimCalibrationConfig."""

    def test_construction(self) -> None:
        """Test basic construction with all required fields."""
        config = MaxSimCalibrationConfig(
            calibration_model_id="mixedbread-ai/mxbai-edge-colbert-v0-17m",
            calibration_pairs_count=10000,
            calibration_date=date(2025, 12, 1),
        )
        assert config.calibration_model_id == "mixedbread-ai/mxbai-edge-colbert-v0-17m"
        assert config.calibration_pairs_count == 10000
        assert config.calibration_date == date(2025, 12, 1)

    def test_calibration_pairs_count_minimum_valid(self) -> None:
        """Test that calibration_pairs_count accepts 1."""
        MaxSimCalibrationConfig(
            calibration_model_id="m",
            calibration_pairs_count=1,
            calibration_date=date(2026, 1, 1),
        )

    def test_calibration_pairs_count_zero_invalid(self) -> None:
        """Test that calibration_pairs_count rejects 0."""
        with pytest.raises(ValidationError):
            MaxSimCalibrationConfig(
                calibration_model_id="m",
                calibration_pairs_count=0,
                calibration_date=date(2026, 1, 1),
            )

    def test_round_trip_serialization(self) -> None:
        """Test model_dump / model_validate round-trip."""
        config = MaxSimCalibrationConfig(
            calibration_model_id="model/id",
            calibration_pairs_count=500,
            calibration_date=date(2026, 1, 15),
        )
        data = config.model_dump()
        restored = MaxSimCalibrationConfig.model_validate(data)
        assert restored == config

    def test_inherits_from_base(self) -> None:
        """Test that MaxSimCalibrationConfig inherits from BaseCalibrationConfig."""
        assert issubclass(MaxSimCalibrationConfig, BaseCalibrationConfig)


class TestDenseCalibrationConfig:
    """Tests for DenseCalibrationConfig."""

    def test_construction(self) -> None:
        """Test basic construction with all required fields."""
        config = DenseCalibrationConfig(
            calibration_model_id="TechWolf/JobBERT-v2",
            calibration_pairs_count=85,
            calibration_date=date(2025, 1, 7),
            max_fp_similarity=0.8266,
        )
        assert config.calibration_model_id == "TechWolf/JobBERT-v2"
        assert config.calibration_pairs_count == 85
        assert config.calibration_date == date(2025, 1, 7)
        assert config.max_fp_similarity == pytest.approx(0.8266)

    def test_max_fp_similarity_bounds_valid(self) -> None:
        """Test max_fp_similarity accepts boundary values."""
        DenseCalibrationConfig(
            calibration_model_id="m",
            calibration_pairs_count=1,
            calibration_date=date(2026, 1, 1),
            max_fp_similarity=0.0,
        )
        DenseCalibrationConfig(
            calibration_model_id="m",
            calibration_pairs_count=1,
            calibration_date=date(2026, 1, 1),
            max_fp_similarity=1.0,
        )

    def test_max_fp_similarity_invalid_high(self) -> None:
        """Test max_fp_similarity rejects values above 1.0."""
        with pytest.raises(ValidationError):
            DenseCalibrationConfig(
                calibration_model_id="m",
                calibration_pairs_count=1,
                calibration_date=date(2026, 1, 1),
                max_fp_similarity=1.01,
            )

    def test_max_fp_similarity_invalid_low(self) -> None:
        """Test max_fp_similarity rejects values below 0.0."""
        with pytest.raises(ValidationError):
            DenseCalibrationConfig(
                calibration_model_id="m",
                calibration_pairs_count=1,
                calibration_date=date(2026, 1, 1),
                max_fp_similarity=-0.1,
            )

    def test_calibration_pairs_count_minimum(self) -> None:
        """Test calibration_pairs_count minimum validation."""
        DenseCalibrationConfig(
            calibration_model_id="m",
            calibration_pairs_count=1,
            calibration_date=date(2026, 1, 1),
            max_fp_similarity=0.5,
        )
        with pytest.raises(ValidationError):
            DenseCalibrationConfig(
                calibration_model_id="m",
                calibration_pairs_count=0,
                calibration_date=date(2026, 1, 1),
                max_fp_similarity=0.5,
            )

    def test_round_trip_serialization(self) -> None:
        """Test model_dump / model_validate round-trip."""
        config = DenseCalibrationConfig(
            calibration_model_id="model/id",
            calibration_pairs_count=100,
            calibration_date=date(2026, 2, 1),
            max_fp_similarity=0.75,
        )
        data = config.model_dump()
        restored = DenseCalibrationConfig.model_validate(data)
        assert restored == config

    def test_inherits_from_base(self) -> None:
        """Test that DenseCalibrationConfig inherits from BaseCalibrationConfig."""
        assert issubclass(DenseCalibrationConfig, BaseCalibrationConfig)


class TestCalibrationIntegration:
    """Tests for calibration nested inside normalization configs."""

    def test_dense_calibration_round_trips_through_dense_normalization(self) -> None:
        """Test calibration nested inside DenseNormalizationConfig."""
        config = DenseNormalizationConfig(
            auto_match_threshold=0.83,
            calibration=DenseCalibrationConfig(
                calibration_model_id="TechWolf/JobBERT-v2",
                calibration_pairs_count=85,
                calibration_date=date(2025, 1, 7),
                max_fp_similarity=0.8266,
            ),
        )
        assert config.calibration is not None
        assert config.calibration.calibration_model_id == "TechWolf/JobBERT-v2"
        assert config.calibration.calibration_pairs_count == 85
        assert config.calibration.calibration_date == date(2025, 1, 7)
        assert config.calibration.max_fp_similarity == pytest.approx(0.8266)

    def test_calibration_optional(self) -> None:
        """Test calibration field is optional."""
        config = DenseNormalizationConfig(auto_match_threshold=0.85)
        assert config.calibration is None
