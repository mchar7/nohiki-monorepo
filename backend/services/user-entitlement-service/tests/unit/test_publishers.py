"""Unit tests for event publishers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from nohiki_db_utils.testing import create_mock_session
from user_entitlement_service.core.tiers import SubscriptionStatus, SubscriptionTier
from user_entitlement_service.db.models import BillingProvider, Entitlement, JobBoardSource
from user_entitlement_service.events.publishers import (
    _build_entitlement_snapshot,
    publish_entitlements_changed_event,
)


class TestBuildEntitlementSnapshot:
    """Tests for _build_entitlement_snapshot helper function."""

    def test_builds_snapshot_from_entitlement(self) -> None:
        """Test building snapshot from entitlement model."""
        user_id = uuid4()
        now = datetime.now(UTC)

        entitlement = Entitlement(
            id=uuid4(),
            user_id=user_id,
            tier=SubscriptionTier.PRO,
            subscription_status=SubscriptionStatus.ACTIVE,
            discovery_frequency_limit=60,
            max_prefs=10,
            max_uploads_per_pref=5,
            allowed_sources=[JobBoardSource.INDEED, JobBoardSource.LINKEDIN],
            features_enabled={"advanced_search": True},
            billing_provider=BillingProvider.STRIPE,
            external_subscription_id="sub_123",
            external_customer_id="cus_123",
            current_period_start=now,
            current_period_end=now,
            created_at=now,
            updated_at=now,
        )

        snapshot = _build_entitlement_snapshot(entitlement)

        assert snapshot.user_id == str(user_id)
        assert snapshot.tier.value == SubscriptionTier.PRO.value
        assert snapshot.subscription_status.value == SubscriptionStatus.ACTIVE.value
        assert snapshot.billing_provider == BillingProvider.STRIPE
        assert snapshot.discovery_frequency_limit == 60
        assert snapshot.max_prefs == 10
        assert snapshot.max_uploads_per_pref == 5
        assert len(snapshot.allowed_sources) == 2
        assert snapshot.features_enabled == {"advanced_search": True}

    def test_handles_empty_features(self) -> None:
        """Test building snapshot with empty features."""
        entitlement = Entitlement(
            id=uuid4(),
            user_id=uuid4(),
            tier=SubscriptionTier.FREE,
            subscription_status=SubscriptionStatus.ACTIVE,
            discovery_frequency_limit=30,
            max_prefs=3,
            max_uploads_per_pref=2,
            allowed_sources=[JobBoardSource.INDEED],
            features_enabled={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        snapshot = _build_entitlement_snapshot(entitlement)

        assert snapshot.features_enabled == {}


class TestPublishEntitlementsChangedEvent:
    """Tests for publish_entitlements_changed_event function."""

    @pytest.mark.asyncio
    async def test_publishes_entitlements_changed_event(self) -> None:
        """Test publishing entitlements changed event via write_event."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock()

        entitlement = Entitlement(
            id=uuid4(),
            user_id=user_id,
            tier=SubscriptionTier.PRO,
            subscription_status=SubscriptionStatus.ACTIVE,
            discovery_frequency_limit=60,
            max_prefs=10,
            max_uploads_per_pref=5,
            allowed_sources=[JobBoardSource.INDEED],
            features_enabled={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        await publish_entitlements_changed_event(mock_db, mock_outbox, entitlement)

        mock_outbox.write_event.assert_awaited_once()
        call_kwargs = mock_outbox.write_event.call_args.kwargs
        assert call_kwargs["params"].aggregate_type == "entitlement"
        assert call_kwargs["params"].aggregate_id == str(user_id)
        assert call_kwargs["params"].event_type == "user-entitlement.cdc.entitlement-changed.v1"

    @pytest.mark.asyncio
    async def test_event_contains_entitlement_snapshot(self) -> None:
        """Test that published event contains correct entitlement snapshot."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_outbox = MagicMock()
        mock_outbox.write_event = AsyncMock()

        entitlement = Entitlement(
            id=uuid4(),
            user_id=user_id,
            tier=SubscriptionTier.FREE,
            subscription_status=SubscriptionStatus.ACTIVE,
            discovery_frequency_limit=30,
            max_prefs=3,
            max_uploads_per_pref=2,
            allowed_sources=[JobBoardSource.INDEED],
            features_enabled={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        await publish_entitlements_changed_event(mock_db, mock_outbox, entitlement)

        call_kwargs = mock_outbox.write_event.call_args.kwargs
        event = call_kwargs["event"]
        assert event.user_id == str(user_id)
        assert event.entitlement_snapshot is not None
        assert event.metadata is not None
