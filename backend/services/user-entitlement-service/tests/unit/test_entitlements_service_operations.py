"""Unit tests for entitlements service database operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from nohiki.common.v1 import BillingProvider, SubscriptionStatus, SubscriptionTier
from nohiki_common_exceptions import DataNotFoundError
from nohiki_db_utils.testing import create_mock_session
from sqlalchemy.exc import IntegrityError
from user_entitlement_service.db.models import Entitlement
from user_entitlement_service.services.entitlements_service import (
    _apply_tier_config,
    create_default_entitlements,
    delete_entitlements,
    get_entitlements_by_user_id,
)


class TestGetEntitlementsByUserId:
    """Tests for get_entitlements_by_user_id function."""

    @pytest.mark.asyncio
    async def test_returns_entitlements_when_found(self) -> None:
        """Test successful retrieval of entitlements."""
        user_id = uuid4()
        mock_db = create_mock_session()

        mock_entitlement = MagicMock(spec=Entitlement)
        mock_entitlement.user_id = user_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_entitlement
        mock_db.execute.return_value = mock_result

        result = await get_entitlements_by_user_id(mock_db, user_id)

        assert result == mock_entitlement
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(self) -> None:
        """Test DataNotFoundError when entitlements don't exist."""
        user_id = uuid4()
        mock_db = create_mock_session()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(DataNotFoundError) as exc_info:
            await get_entitlements_by_user_id(mock_db, user_id)

        assert "Entitlement" in str(exc_info.value)


class TestCreateDefaultEntitlements:
    """Tests for create_default_entitlements function."""

    @pytest.mark.asyncio
    async def test_creates_entitlements_successfully(self) -> None:
        """Test successful creation of default entitlements."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        result = await create_default_entitlements(mock_db, user_id)

        assert result.user_id == user_id
        assert result.tier == SubscriptionTier.FREE
        assert result.subscription_status == SubscriptionStatus.NONE
        assert result.billing_provider == BillingProvider.NONE
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_existing_on_integrity_error(self) -> None:
        """Test idempotent behavior when entitlements already exist."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock(side_effect=IntegrityError("duplicate", {}, Exception("duplicate key")))
        mock_db.begin_nested = MagicMock(return_value=AsyncMock())

        mock_existing = MagicMock(spec=Entitlement)
        mock_existing.user_id = user_id

        with patch(
            "user_entitlement_service.services.entitlements_service.get_entitlements_by_user_id",
            return_value=mock_existing,
        ) as mock_get:
            result = await create_default_entitlements(mock_db, user_id)

            assert result == mock_existing
            mock_db.begin_nested.assert_called_once()
            mock_get.assert_awaited_once_with(mock_db, user_id)


class TestDeleteEntitlements:
    """Tests for delete_entitlements function."""

    @pytest.mark.asyncio
    async def test_deletes_entitlements_successfully(self) -> None:
        """Test successful deletion of entitlements."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result

        count = await delete_entitlements(mock_db, user_id)

        assert count == 1
        mock_db.execute.assert_awaited_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_entitlements(self) -> None:
        """Test deletion returns 0 when no entitlements exist."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute.return_value = mock_result

        count = await delete_entitlements(mock_db, user_id)

        assert count == 0
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_none_rowcount(self) -> None:
        """Test handling when rowcount is None."""
        user_id = uuid4()
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.rowcount = None
        mock_db.execute.return_value = mock_result

        count = await delete_entitlements(mock_db, user_id)

        assert count == 0


class TestApplyTierConfig:
    """Tests for _apply_tier_config helper function."""

    def test_applies_tier_config_to_entitlement(self) -> None:
        """Test that tier config is correctly applied."""
        from user_entitlement_service.core.tiers import get_tier_config

        mock_entitlement = MagicMock(spec=Entitlement)
        tier_config = get_tier_config(SubscriptionTier.PRO)

        _apply_tier_config(mock_entitlement, tier_config)

        assert mock_entitlement.discovery_frequency_limit == tier_config.discovery_frequency_limit
        assert mock_entitlement.max_prefs == tier_config.max_prefs
        assert mock_entitlement.max_uploads_per_pref == tier_config.max_uploads_per_pref
        assert mock_entitlement.allowed_sources == list(tier_config.allowed_sources)
        assert mock_entitlement.features_enabled == dict(tier_config.features_enabled)
