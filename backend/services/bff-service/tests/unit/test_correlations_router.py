import uuid

import pytest
from nohiki.feedback.v1 import ScoreFeedbackType
from nohiki.job.correlation.v1 import FeedbackType
from pytest_mock import MockerFixture


@pytest.mark.asyncio
async def test_record_feedback_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.correlations import RecordFeedbackRequest, record_feedback

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.record_feedback_command = mocker.AsyncMock(return_value=request_id)

    data = RecordFeedbackRequest(feedback_type=FeedbackType.APPLIED)

    result = await record_feedback(correlation_id, data, user_id, mock_service)

    assert result.request_id == request_id
    assert result.status == "accepted"
    mock_service.record_feedback_command.assert_awaited_once_with(
        user_id=user_id,
        correlation_id=correlation_id,
        feedback_type=FeedbackType.APPLIED,
    )


@pytest.mark.asyncio
async def test_record_feedback_handles_viewed_type(mocker: MockerFixture) -> None:
    from bff_service.api.routers.correlations import RecordFeedbackRequest, record_feedback

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.record_feedback_command = mocker.AsyncMock(return_value=request_id)

    data = RecordFeedbackRequest(feedback_type=FeedbackType.VIEWED)

    result = await record_feedback(correlation_id, data, user_id, mock_service)

    assert result.request_id == request_id
    call_args = mock_service.record_feedback_command.call_args
    assert call_args.kwargs["feedback_type"] == FeedbackType.VIEWED


@pytest.mark.asyncio
async def test_record_feedback_handles_dismissed_type(mocker: MockerFixture) -> None:
    from bff_service.api.routers.correlations import RecordFeedbackRequest, record_feedback

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.record_feedback_command = mocker.AsyncMock(return_value=request_id)

    data = RecordFeedbackRequest(feedback_type=FeedbackType.DISMISSED)

    result = await record_feedback(correlation_id, data, user_id, mock_service)

    assert result.request_id == request_id
    call_args = mock_service.record_feedback_command.call_args
    assert call_args.kwargs["feedback_type"] == FeedbackType.DISMISSED


def test_get_correlation_service_returns_instance() -> None:
    from bff_service.api.routers.correlations import get_correlation_service

    service = get_correlation_service()

    assert service is not None


# Score Feedback Endpoint Tests


@pytest.mark.asyncio
async def test_submit_score_feedback_publishes_command(mocker: MockerFixture) -> None:
    """Test that submit_score_feedback publishes command and returns 202 response."""
    from bff_service.api.routers.correlations import ScoreFeedbackRequest, submit_score_feedback

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.submit_score_feedback_command = mocker.AsyncMock(return_value=request_id)

    data = ScoreFeedbackRequest(feedback_type=ScoreFeedbackType.GOOD)

    result = await submit_score_feedback(correlation_id, data, user_id, mock_service)

    assert result.request_id == request_id
    assert result.status == "accepted"
    mock_service.submit_score_feedback_command.assert_awaited_once_with(
        user_id=user_id,
        correlation_id=correlation_id,
        feedback_type=ScoreFeedbackType.GOOD,
    )


@pytest.mark.asyncio
async def test_submit_score_feedback_handles_too_high_type(mocker: MockerFixture) -> None:
    """Test score feedback with TOO_HIGH type."""
    from bff_service.api.routers.correlations import ScoreFeedbackRequest, submit_score_feedback

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.submit_score_feedback_command = mocker.AsyncMock(return_value=request_id)

    data = ScoreFeedbackRequest(feedback_type=ScoreFeedbackType.TOO_HIGH)

    result = await submit_score_feedback(correlation_id, data, user_id, mock_service)

    assert result.request_id == request_id
    call_args = mock_service.submit_score_feedback_command.call_args
    assert call_args.kwargs["feedback_type"] == ScoreFeedbackType.TOO_HIGH


@pytest.mark.asyncio
async def test_submit_score_feedback_handles_too_low_type(mocker: MockerFixture) -> None:
    """Test score feedback with TOO_LOW type."""
    from bff_service.api.routers.correlations import ScoreFeedbackRequest, submit_score_feedback

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.submit_score_feedback_command = mocker.AsyncMock(return_value=request_id)

    data = ScoreFeedbackRequest(feedback_type=ScoreFeedbackType.TOO_LOW)

    result = await submit_score_feedback(correlation_id, data, user_id, mock_service)

    assert result.request_id == request_id
    call_args = mock_service.submit_score_feedback_command.call_args
    assert call_args.kwargs["feedback_type"] == ScoreFeedbackType.TOO_LOW


# Score Adjustment Endpoint Tests


@pytest.mark.asyncio
async def test_submit_score_adjustment_publishes_command(mocker: MockerFixture) -> None:
    """Test that submit_score_adjustment publishes command and returns 202 response."""
    from bff_service.api.routers.correlations import ScoreAdjustmentRequest, submit_score_adjustment

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.submit_score_adjustment_command = mocker.AsyncMock(return_value=request_id)

    data = ScoreAdjustmentRequest(
        adjusted_score=0.45,
        reasoning="Skills mismatch with job requirements",
    )

    result = await submit_score_adjustment(correlation_id, data, user_id, mock_service)

    assert result.request_id == request_id
    assert result.status == "accepted"
    mock_service.submit_score_adjustment_command.assert_awaited_once_with(
        user_id=user_id,
        correlation_id=correlation_id,
        adjusted_score=0.45,
        reasoning="Skills mismatch with job requirements",
    )


@pytest.mark.asyncio
async def test_submit_score_adjustment_with_edge_case_scores(mocker: MockerFixture) -> None:
    """Test score adjustment with edge case scores (0.0 and 1.0)."""
    from bff_service.api.routers.correlations import ScoreAdjustmentRequest, submit_score_adjustment

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    request_id = str(uuid.uuid4())

    mock_service = mocker.Mock()
    mock_service.submit_score_adjustment_command = mocker.AsyncMock(return_value=request_id)

    # Test minimum score
    data = ScoreAdjustmentRequest(
        adjusted_score=0.0,
        reasoning="Completely irrelevant job listing",
    )
    result = await submit_score_adjustment(correlation_id, data, user_id, mock_service)
    assert result.request_id == request_id

    # Test maximum score
    data = ScoreAdjustmentRequest(
        adjusted_score=1.0,
        reasoning="Perfect match for requirements",
    )
    result = await submit_score_adjustment(correlation_id, data, user_id, mock_service)
    assert result.request_id == request_id


# Request Model Validation Tests


def test_score_feedback_request_valid_types() -> None:
    """Test that ScoreFeedbackRequest accepts valid feedback types."""
    from bff_service.api.routers.correlations import ScoreFeedbackRequest

    for feedback_type in [ScoreFeedbackType.GOOD, ScoreFeedbackType.TOO_HIGH, ScoreFeedbackType.TOO_LOW]:
        request = ScoreFeedbackRequest(feedback_type=feedback_type)
        assert request.feedback_type == feedback_type


def test_score_adjustment_request_validation() -> None:
    """Test ScoreAdjustmentRequest validation rules."""
    from bff_service.api.routers.correlations import ScoreAdjustmentRequest
    from pydantic import ValidationError

    # Valid request
    request = ScoreAdjustmentRequest(
        adjusted_score=0.75,
        reasoning="This is a valid reasoning with enough characters",
    )
    assert request.adjusted_score == pytest.approx(0.75)

    # Score out of range (too high)
    with pytest.raises(ValidationError):
        ScoreAdjustmentRequest(
            adjusted_score=1.5,
            reasoning="Valid reasoning here",
        )

    # Score out of range (too low)
    with pytest.raises(ValidationError):
        ScoreAdjustmentRequest(
            adjusted_score=-0.1,
            reasoning="Valid reasoning here",
        )

    # Reasoning too short
    with pytest.raises(ValidationError):
        ScoreAdjustmentRequest(
            adjusted_score=0.5,
            reasoning="Short",
        )


def test_command_accepted_response_model() -> None:
    """Test CommandAcceptedResponse model structure."""
    from bff_service.api.routers.correlations import CommandAcceptedResponse

    response = CommandAcceptedResponse(request_id="test-uuid-123")
    assert response.request_id == "test-uuid-123"
    assert response.status == "accepted"

    # Test with custom status
    response = CommandAcceptedResponse(request_id="test-uuid-456", status="pending")
    assert response.status == "pending"


def test_score_feedback_request_accepts_proto_enum() -> None:
    """Test that ScoreFeedbackRequest accepts proto enum values directly."""
    from bff_service.api.routers.correlations import ScoreFeedbackRequest

    request = ScoreFeedbackRequest(feedback_type=ScoreFeedbackType.GOOD)
    assert request.feedback_type == ScoreFeedbackType.GOOD

    request = ScoreFeedbackRequest(feedback_type=ScoreFeedbackType.TOO_HIGH)
    assert request.feedback_type == ScoreFeedbackType.TOO_HIGH

    request = ScoreFeedbackRequest(feedback_type=ScoreFeedbackType.TOO_LOW)
    assert request.feedback_type == ScoreFeedbackType.TOO_LOW
