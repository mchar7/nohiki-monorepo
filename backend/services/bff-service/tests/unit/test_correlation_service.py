"""Tests for correlation service."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from nohiki.job.correlation.v1 import FeedbackType

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _import_correlation_service() -> type:
    from bff_service.services.correlation_service import CorrelationService

    return CorrelationService


@pytest.mark.asyncio
async def test_record_feedback_command_publishes_event(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that record_feedback_command publishes FeedbackRecorded event."""
    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    result = await service.record_feedback_command(user_id, correlation_id, FeedbackType.APPLIED)

    assert result == str(request_id)
    mock_publish.assert_awaited_once()

    topic, event = mock_publish.call_args.args
    assert topic == "job-correlation.cmd.feedback-recorded.v1"
    assert mock_publish.call_args.kwargs.get("key") == str(request_id)
    assert event.request_id == str(request_id)
    assert event.correlation_id == str(correlation_id)
    assert event.user_id == str(user_id)
    assert event.feedback_type == FeedbackType.APPLIED
    assert event.metadata.source_service == "bff-service"
    assert event.metadata.correlation_id == str(request_id)
    assert event.metadata.event_id


@pytest.mark.asyncio
async def test_record_feedback_command_with_viewed_type(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test recording feedback with VIEWED type."""
    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    await service.record_feedback_command(user_id, correlation_id, FeedbackType.VIEWED)

    _topic, event = mock_publish.call_args.args
    assert event.feedback_type == FeedbackType.VIEWED


@pytest.mark.asyncio
async def test_record_feedback_command_with_dismissed_type(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test recording feedback with DISMISSED type."""
    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    await service.record_feedback_command(user_id, correlation_id, FeedbackType.DISMISSED)

    _topic, event = mock_publish.call_args.args
    assert event.feedback_type == FeedbackType.DISMISSED


@pytest.mark.asyncio
async def test_record_feedback_command_with_saved_type(mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test recording feedback with SAVED type."""
    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    await service.record_feedback_command(user_id, correlation_id, FeedbackType.SAVED)

    _topic, event = mock_publish.call_args.args
    assert event.feedback_type == FeedbackType.SAVED


# Score Feedback Command Tests


@pytest.mark.asyncio
async def test_submit_score_feedback_command_publishes_event(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that submit_score_feedback_command publishes ScoreFeedbackRequested event."""
    from nohiki.feedback.v1 import ScoreFeedbackType

    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    result = await service.submit_score_feedback_command(user_id, correlation_id, ScoreFeedbackType.GOOD)

    assert result == str(request_id)
    mock_publish.assert_awaited_once()

    topic, event = mock_publish.call_args.args
    assert topic == "feedback.cmd.score-feedback-requested.v1"
    assert mock_publish.call_args.kwargs.get("key") == str(request_id)
    assert event.request_id == str(request_id)
    assert event.correlation_id == str(correlation_id)
    assert event.user_id == str(user_id)
    assert event.feedback_type == ScoreFeedbackType.GOOD


@pytest.mark.asyncio
async def test_submit_score_feedback_command_with_too_high_type(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test score feedback command with TOO_HIGH type."""
    from nohiki.feedback.v1 import ScoreFeedbackType

    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    await service.submit_score_feedback_command(user_id, correlation_id, ScoreFeedbackType.TOO_HIGH)

    _topic, event = mock_publish.call_args.args
    assert event.feedback_type == ScoreFeedbackType.TOO_HIGH


@pytest.mark.asyncio
async def test_submit_score_feedback_command_with_too_low_type(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test score feedback command with TOO_LOW type."""
    from nohiki.feedback.v1 import ScoreFeedbackType

    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    await service.submit_score_feedback_command(user_id, correlation_id, ScoreFeedbackType.TOO_LOW)

    _topic, event = mock_publish.call_args.args
    assert event.feedback_type == ScoreFeedbackType.TOO_LOW


# Score Adjustment Command Tests


@pytest.mark.asyncio
async def test_submit_score_adjustment_command_publishes_event(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that submit_score_adjustment_command publishes ScoreAdjustmentRequested event."""
    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    result = await service.submit_score_adjustment_command(
        user_id, correlation_id, adjusted_score=0.65, reasoning="Skills mismatch"
    )

    assert result == str(request_id)
    mock_publish.assert_awaited_once()

    topic, event = mock_publish.call_args.args
    assert topic == "feedback.cmd.score-adjustment-requested.v1"
    assert mock_publish.call_args.kwargs.get("key") == str(request_id)
    assert event.request_id == str(request_id)
    assert event.correlation_id == str(correlation_id)
    assert event.user_id == str(user_id)
    assert abs(event.adjusted_score - 0.65) < 1e-9
    assert event.reasoning == "Skills mismatch"


@pytest.mark.asyncio
async def test_submit_score_adjustment_command_with_min_score(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test score adjustment command with minimum score (0.0)."""
    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    await service.submit_score_adjustment_command(
        user_id, correlation_id, adjusted_score=0.0, reasoning="Completely irrelevant"
    )

    _topic, event = mock_publish.call_args.args
    assert abs(event.adjusted_score - 0.0) < 1e-9


@pytest.mark.asyncio
async def test_submit_score_adjustment_command_with_max_score(
    mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test score adjustment command with maximum score (1.0)."""
    service = _import_correlation_service()()

    mock_publish = mocker.AsyncMock()
    mock_kafka = mocker.MagicMock()
    mock_kafka.publish = mock_publish
    monkeypatch.setattr("bff_service.services.correlation_service.kafka_client", mock_kafka)

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = uuid.uuid4()
    monkeypatch.setattr("bff_service.services.correlation_service.uuid7", lambda: request_id)

    await service.submit_score_adjustment_command(
        user_id, correlation_id, adjusted_score=1.0, reasoning="Perfect match"
    )

    _topic, event = mock_publish.call_args.args
    assert abs(event.adjusted_score - 1.0) < 1e-9
