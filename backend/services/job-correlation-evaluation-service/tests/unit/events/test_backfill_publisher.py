"""Unit tests for events/backfill_publisher.py module."""

import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session


class TestPublishBackfillRequest:
    """Tests for deterministic transactional backfill commands."""

    @pytest.mark.asyncio
    async def test_writes_stable_operation_to_transactional_wal(self) -> None:
        from job_correlation_evaluation_service.events.backfill_publisher import (
            BackfillRequest,
            publish_backfill_request,
        )
        from nohiki.job.listing.v1 import BackfillRequested
        from nohiki_kafka_client import Topics

        db = create_mock_session()
        operation_id = str(uuid4())

        with patch("job_correlation_evaluation_service.events.backfill_publisher.settings") as settings:
            settings.service_name = "test-service"
            settings.backfill.callback_topic = "test.callback.topic"
            settings.backfill.max_listings = 100
            settings.backfill.since_days = 14

            returned = await publish_backfill_request(
                db,
                BackfillRequest(
                    pref_id="pref-id",
                    user_id="user-id",
                    correlation_id="correlation-id",
                    operation_id=operation_id,
                ),
            )

        assert returned == operation_id
        db.execute.assert_awaited_once()
        assert db.execute.await_args is not None
        statement, params = db.execute.await_args.args
        assert "pg_logical_emit_message(true" in str(statement)
        assert isinstance(params, dict)
        prefix = json.loads(params["prefix"])
        assert prefix["topic"] == Topics.JOB_LISTING_BACKFILL_REQUESTED
        assert prefix["aggregate_id"] == operation_id
        assert prefix["aggregate_type"] == "profile_backfill"
        event = BackfillRequested().parse(params["content"])
        assert event.command.operation_id == operation_id
        assert event.command.callback_topic == "test.callback.topic"
        assert event.pref_id == "pref-id"
        assert event.user_id == "user-id"
        assert event.max_listings == 100
        assert event.since_days == 14
        db.commit.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("force_rescore", [False, True])
    async def test_force_rescore_intent_round_trips(self, *, force_rescore: bool) -> None:
        from job_correlation_evaluation_service.events.backfill_publisher import (
            BackfillCallerContext,
            BackfillRequest,
            publish_backfill_request,
        )
        from nohiki.job.listing.v1 import BackfillRequested

        db = create_mock_session()
        await publish_backfill_request(
            db,
            BackfillRequest(
                pref_id="pref-id",
                user_id="user-id",
                correlation_id="correlation-id",
                operation_id=str(uuid4()),
                force_rescore=force_rescore,
            ),
        )

        assert db.execute.await_args is not None
        params = db.execute.await_args.args[1]
        assert isinstance(params, dict)
        event = BackfillRequested().parse(params["content"])
        state = BackfillCallerContext.from_bytes(event.command.caller_context)
        assert state.force_rescore is force_rescore
