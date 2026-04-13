"""Unit tests for feedback database models."""

from __future__ import annotations

from uuid import uuid4

import pytest
from job_correlation_evaluation_service.db.feedback_models import (
    FEEDBACK_SCHEMA,
    AsymmetricFeedbackModel,
    ManualAdjustmentModel,
)
from nohiki.feedback.v1 import ScoreFeedbackType


class TestAsymmetricFeedbackModel:
    """Tests for AsymmetricFeedbackModel."""

    def test_table_name(self) -> None:
        """Test table name is correct."""
        assert AsymmetricFeedbackModel.__tablename__ == "asymmetric_feedback"

    def test_schema_name(self) -> None:
        """Test schema name is correct."""
        assert FEEDBACK_SCHEMA == "feedback"
        assert AsymmetricFeedbackModel.__table_args__[1]["schema"] == FEEDBACK_SCHEMA

    def test_has_feedback_type_constraint(self) -> None:
        """Test that feedback_type has a check constraint."""
        constraints = AsymmetricFeedbackModel.__table_args__
        assert any(hasattr(c, "name") and c.name == "ck_feedback_type_valid" for c in constraints if hasattr(c, "name"))

    def test_get_feedback_type_enum_good(self) -> None:
        """Test get_feedback_type_enum returns correct enum for GOOD."""
        model = AsymmetricFeedbackModel(
            correlation_id=uuid4(),
            user_id=uuid4(),
            feedback_type=ScoreFeedbackType.GOOD.name,
        )
        assert model.get_feedback_type_enum() == ScoreFeedbackType.GOOD

    def test_get_feedback_type_enum_too_high(self) -> None:
        """Test get_feedback_type_enum returns correct enum for TOO_HIGH."""
        model = AsymmetricFeedbackModel(
            correlation_id=uuid4(),
            user_id=uuid4(),
            feedback_type=ScoreFeedbackType.TOO_HIGH.name,
        )
        assert model.get_feedback_type_enum() == ScoreFeedbackType.TOO_HIGH

    def test_get_feedback_type_enum_too_low(self) -> None:
        """Test get_feedback_type_enum returns correct enum for TOO_LOW."""
        model = AsymmetricFeedbackModel(
            correlation_id=uuid4(),
            user_id=uuid4(),
            feedback_type=ScoreFeedbackType.TOO_LOW.name,
        )
        assert model.get_feedback_type_enum() == ScoreFeedbackType.TOO_LOW

    def test_repr(self) -> None:
        """Test __repr__ includes key fields."""
        correlation_id = uuid4()
        model = AsymmetricFeedbackModel(
            id=uuid4(),
            correlation_id=correlation_id,
            user_id=uuid4(),
            feedback_type=ScoreFeedbackType.GOOD.name,
        )
        repr_str = repr(model)
        assert "AsymmetricFeedback" in repr_str
        assert str(correlation_id) in repr_str
        assert "feedback_type='GOOD'" in repr_str


class TestManualAdjustmentModel:
    """Tests for ManualAdjustmentModel."""

    def test_table_name(self) -> None:
        """Test table name is correct."""
        assert ManualAdjustmentModel.__tablename__ == "manual_adjustments"

    def test_schema_name(self) -> None:
        """Test schema name is correct."""
        assert ManualAdjustmentModel.__table_args__[0]["schema"] == FEEDBACK_SCHEMA

    def test_repr(self) -> None:
        """Test __repr__ includes key fields."""
        correlation_id = uuid4()
        model = ManualAdjustmentModel(
            id=uuid4(),
            correlation_id=correlation_id,
            user_id=uuid4(),
            original_score=0.75,
            adjusted_score=0.60,
            reasoning="Test reasoning",
        )
        repr_str = repr(model)
        assert "ManualAdjustmentModel" in repr_str
        assert str(correlation_id) in repr_str
        assert "original_score=0.75" in repr_str
        assert "adjusted_score=0.6" in repr_str

    def test_score_precision(self) -> None:
        """Test that scores maintain precision."""
        model = ManualAdjustmentModel(
            correlation_id=uuid4(),
            user_id=uuid4(),
            original_score=0.123456789,
            adjusted_score=0.987654321,
            reasoning="Precision test",
        )
        assert model.original_score == pytest.approx(0.123456789)
        assert model.adjusted_score == pytest.approx(0.987654321)

    def test_score_full_range_low(self) -> None:
        """Test scores at minimum value."""
        model = ManualAdjustmentModel(
            correlation_id=uuid4(),
            user_id=uuid4(),
            original_score=0.0,
            adjusted_score=0.0,
            reasoning="Minimum score test",
        )
        assert model.original_score == pytest.approx(0.0)
        assert model.adjusted_score == pytest.approx(0.0)

    def test_score_full_range_high(self) -> None:
        """Test scores at maximum value."""
        model = ManualAdjustmentModel(
            correlation_id=uuid4(),
            user_id=uuid4(),
            original_score=1.0,
            adjusted_score=1.0,
            reasoning="Maximum score test",
        )
        assert model.original_score == pytest.approx(1.0)
        assert model.adjusted_score == pytest.approx(1.0)


class TestProtoImports:
    """Tests verifying proto imports work correctly."""

    def test_score_feedback_type_enum_values(self) -> None:
        """Test ScoreFeedbackType enum has correct values."""
        assert ScoreFeedbackType.UNSPECIFIED.value == 0
        assert ScoreFeedbackType.GOOD.value == 1
        assert ScoreFeedbackType.TOO_HIGH.value == 2
        assert ScoreFeedbackType.TOO_LOW.value == 3

    def test_score_feedback_type_from_value(self) -> None:
        """Test ScoreFeedbackType can be created from int value."""
        assert ScoreFeedbackType(1) == ScoreFeedbackType.GOOD
        assert ScoreFeedbackType(2) == ScoreFeedbackType.TOO_HIGH
        assert ScoreFeedbackType(3) == ScoreFeedbackType.TOO_LOW

    def test_asymmetric_feedback_proto_import(self) -> None:
        """Test AsymmetricFeedback proto message can be imported."""
        from nohiki.feedback.v1 import AsymmetricFeedback

        feedback = AsymmetricFeedback(
            id=str(uuid4()),
            correlation_id=str(uuid4()),
            user_id=str(uuid4()),
            feedback_type=ScoreFeedbackType.GOOD,
        )
        assert feedback.feedback_type == ScoreFeedbackType.GOOD

    def test_manual_score_adjustment_proto_import(self) -> None:
        """Test ManualScoreAdjustment proto message can be imported."""
        from nohiki.feedback.v1 import ManualScoreAdjustment

        adjustment = ManualScoreAdjustment(
            id=str(uuid4()),
            correlation_id=str(uuid4()),
            user_id=str(uuid4()),
            original_score=0.75,
            adjusted_score=0.60,
            reasoning="Test reasoning with minimum length",
        )
        assert adjustment.original_score == pytest.approx(0.75)
        assert adjustment.adjusted_score == pytest.approx(0.60)

    def test_feedback_events_import(self) -> None:
        """Test feedback event messages can be imported."""
        from nohiki.feedback.v1 import (
            AsymmetricFeedback,
            AsymmetricFeedbackCreated,
            ManualAdjustmentCreated,
            ManualScoreAdjustment,
        )

        feedback = AsymmetricFeedback(
            id=str(uuid4()),
            correlation_id=str(uuid4()),
            user_id=str(uuid4()),
            feedback_type=ScoreFeedbackType.TOO_HIGH,
        )
        event = AsymmetricFeedbackCreated(feedback=feedback)
        assert event.feedback is not None
        assert event.feedback.feedback_type == ScoreFeedbackType.TOO_HIGH

        adjustment = ManualScoreAdjustment(
            id=str(uuid4()),
            correlation_id=str(uuid4()),
            user_id=str(uuid4()),
            original_score=0.8,
            adjusted_score=0.5,
            reasoning="Test reasoning for adjustment",
        )
        adj_event = ManualAdjustmentCreated(adjustment=adjustment)
        assert adj_event.adjustment is not None
        assert adj_event.adjustment.original_score == pytest.approx(0.8)
