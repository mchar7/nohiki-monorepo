"""Unit tests for settings_service module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from nohiki.common.v1 import FeatureImportancePrefs
from nohiki.user.pref.v1 import UserPrefSettingsUpdateRequested
from nohiki_db_utils.testing import create_mock_session
from user_pref_service.db.models import SearchPref
from user_pref_service.db.models import UserPrefSettings as UserPrefSettingsModel
from user_pref_service.services.settings_service import (
    build_settings_snapshot,
    get_user_settings,
    update_profile_feature_importance,
    upsert_user_settings,
)


@pytest.fixture
def sample_user_id() -> uuid.UUID:
    """Sample user ID for tests."""
    return uuid.UUID("123e4567-e89b-12d3-a456-426614174000")


@pytest.fixture
def sample_settings_model(sample_user_id: uuid.UUID) -> UserPrefSettingsModel:
    """Sample UserPrefSettingsModel for tests."""
    model = MagicMock(spec=UserPrefSettingsModel)
    model.id = uuid.uuid4()
    model.user_id = sample_user_id
    model.default_feature_importance = {
        "skill_match_importance": 80,
        "location_importance": 60,
        "work_arrangement_importance": 70,
        "experience_importance": 50,
        "salary_importance": 40,
        "recency_importance": 30,
    }
    model.preferred_timezone = "America/New_York"
    model.preferred_locale = "en-US"
    model.created_at = datetime.now(UTC)
    model.updated_at = datetime.now(UTC)
    return model


class TestBuildSettingsSnapshot:
    """Tests for build_settings_snapshot function."""

    def test_builds_snapshot_with_all_fields(self, sample_settings_model: UserPrefSettingsModel) -> None:
        """Builds complete snapshot from model with all fields."""
        snapshot = build_settings_snapshot(sample_settings_model)

        assert snapshot.user_id == str(sample_settings_model.user_id)
        assert snapshot.preferred_timezone == "America/New_York"
        assert snapshot.preferred_locale == "en-US"
        assert snapshot.default_feature_importance is not None
        assert snapshot.default_feature_importance.skill_match_importance == 80
        assert snapshot.default_feature_importance.location_importance == 60

    def test_builds_snapshot_with_null_importance(self, sample_user_id: uuid.UUID) -> None:
        """Builds snapshot when default_feature_importance is None."""
        model = MagicMock(spec=UserPrefSettingsModel)
        model.id = uuid.uuid4()
        model.user_id = sample_user_id
        model.default_feature_importance = None
        model.preferred_timezone = None
        model.preferred_locale = None
        model.created_at = datetime.now(UTC)
        model.updated_at = datetime.now(UTC)

        snapshot = build_settings_snapshot(model)

        assert snapshot.user_id == str(sample_user_id)
        assert snapshot.default_feature_importance == FeatureImportancePrefs()
        assert snapshot.preferred_timezone is None
        assert snapshot.preferred_locale is None

    def test_builds_snapshot_with_partial_importance(self, sample_user_id: uuid.UUID) -> None:
        """Builds snapshot when only some importance fields are set."""
        model = MagicMock(spec=UserPrefSettingsModel)
        model.id = uuid.uuid4()
        model.user_id = sample_user_id
        model.default_feature_importance = {
            "skill_match_importance": 90,
        }
        model.preferred_timezone = "UTC"
        model.preferred_locale = None
        model.created_at = datetime.now(UTC)
        model.updated_at = datetime.now(UTC)

        snapshot = build_settings_snapshot(model)

        assert snapshot.default_feature_importance is not None
        assert snapshot.default_feature_importance.skill_match_importance == 90
        assert snapshot.default_feature_importance.location_importance is None


class TestGetUserSettings:
    """Tests for get_user_settings function."""

    @pytest.mark.asyncio
    async def test_returns_settings_when_found(
        self, sample_user_id: uuid.UUID, sample_settings_model: UserPrefSettingsModel
    ) -> None:
        """Returns user settings when they exist."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_settings_model
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_user_settings(mock_db, sample_user_id)

        assert result is not None
        assert result.user_id == sample_user_id
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, sample_user_id: uuid.UUID) -> None:
        """Returns None when user settings don't exist."""
        mock_db = create_mock_session()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_user_settings(mock_db, sample_user_id)

        assert result is None


class TestUpsertUserSettings:
    """Tests for upsert_user_settings function."""

    @pytest.mark.asyncio
    async def test_creates_new_settings(self, sample_user_id: uuid.UUID) -> None:
        """Creates new settings when none exist."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        # Create a model for the second call (after insert)
        created_model = MagicMock(spec=UserPrefSettingsModel)
        created_model.id = uuid.uuid4()
        created_model.user_id = sample_user_id
        created_model.default_feature_importance = {
            "skill_match_importance": 80,
            "location_importance": 60,
        }
        created_model.preferred_timezone = "America/Los_Angeles"
        created_model.preferred_locale = None
        created_model.created_at = datetime.now(UTC)
        created_model.updated_at = datetime.now(UTC)

        # First query returns None (no existing), second returns created model
        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None
        mock_result_created = MagicMock()
        mock_result_created.scalar_one_or_none.return_value = created_model

        mock_db.execute = AsyncMock(side_effect=[mock_result_none, MagicMock(), mock_result_created])

        cmd = UserPrefSettingsUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(sample_user_id),
            default_feature_importance=FeatureImportancePrefs(
                skill_match_importance=80,
                location_importance=60,
            ),
            preferred_timezone="America/Los_Angeles",
            updated_fields=["default_feature_importance", "preferred_timezone"],
        )

        _, is_new = await upsert_user_settings(mock_db, sample_user_id, cmd)

        assert is_new is True
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_existing_settings(
        self, sample_user_id: uuid.UUID, sample_settings_model: UserPrefSettingsModel
    ) -> None:
        """Updates existing settings when they exist."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        # Query returns existing settings
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_settings_model
        mock_db.execute = AsyncMock(return_value=mock_result)

        cmd = UserPrefSettingsUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(sample_user_id),
            default_feature_importance=FeatureImportancePrefs(
                skill_match_importance=95,
            ),
            updated_fields=["default_feature_importance"],
        )

        _, is_new = await upsert_user_settings(mock_db, sample_user_id, cmd)

        assert is_new is False
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_partial_importance_update(
        self, sample_user_id: uuid.UUID, sample_settings_model: UserPrefSettingsModel
    ) -> None:
        """Handles partial feature importance updates correctly."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_settings_model
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Only update one importance field
        cmd = UserPrefSettingsUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(sample_user_id),
            default_feature_importance=FeatureImportancePrefs(
                location_importance=100,
            ),
            updated_fields=["default_feature_importance"],
        )

        _, is_new = await upsert_user_settings(mock_db, sample_user_id, cmd)

        assert is_new is False

    @pytest.mark.asyncio
    async def test_updates_timezone_and_locale(
        self, sample_user_id: uuid.UUID, sample_settings_model: UserPrefSettingsModel
    ) -> None:
        """Updates timezone and locale fields."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_settings_model
        mock_db.execute = AsyncMock(return_value=mock_result)

        cmd = UserPrefSettingsUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(sample_user_id),
            preferred_timezone="Europe/London",
            preferred_locale="en-GB",
            updated_fields=["preferred_timezone", "preferred_locale"],
        )

        _, is_new = await upsert_user_settings(mock_db, sample_user_id, cmd)

        assert is_new is False
        mock_db.flush.assert_awaited_once()


class TestBuildSettingsSnapshotEdgeCases:
    """Edge case tests for build_settings_snapshot function."""

    def test_raises_on_none_timestamps(self, sample_user_id: uuid.UUID) -> None:
        """Raises ValueError when timestamps are None."""
        model = MagicMock(spec=UserPrefSettingsModel)
        model.id = uuid.uuid4()
        model.user_id = sample_user_id
        model.default_feature_importance = None
        model.preferred_timezone = None
        model.preferred_locale = None
        model.created_at = None
        model.updated_at = None

        with pytest.raises(ValueError, match="created_at and updated_at must be set"):
            build_settings_snapshot(model)

    def test_handles_naive_timestamps(self, sample_user_id: uuid.UUID) -> None:
        """Handles naive timestamps by adding UTC timezone."""
        model = MagicMock(spec=UserPrefSettingsModel)
        model.id = uuid.uuid4()
        model.user_id = sample_user_id
        model.default_feature_importance = None
        model.preferred_timezone = None
        model.preferred_locale = None
        model.created_at = datetime.fromisoformat("2024-01-01T12:00:00")
        model.updated_at = datetime.fromisoformat("2024-01-02T12:00:00")

        snapshot = build_settings_snapshot(model)

        assert snapshot.timestamps is not None
        assert snapshot.timestamps.created_at is not None
        assert snapshot.timestamps.created_at.tzinfo == UTC
        assert snapshot.timestamps.updated_at is not None
        assert snapshot.timestamps.updated_at.tzinfo == UTC


class TestUpdateProfileFeatureImportance:
    """Tests for update_profile_feature_importance function."""

    @pytest.mark.asyncio
    async def test_updates_feature_importance(self) -> None:
        """Updates feature_importance on profile."""
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        user_id = uuid.uuid4()

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = pref_id
        mock_profile.user_id = user_id
        mock_profile.feature_importance = None
        mock_profile.attachments = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        cmd = MagicMock()
        cmd.feature_importance = FeatureImportancePrefs(
            skill_match_importance=95,
            location_importance=85,
        )

        result = await update_profile_feature_importance(mock_db, pref_id, cmd)

        assert result == mock_profile
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_feature_importance_with_none(self) -> None:
        """Sets profile.feature_importance to None when cmd value is None."""
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        user_id = uuid.uuid4()

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = pref_id
        mock_profile.user_id = user_id
        mock_profile.feature_importance = {"existing": "value"}
        mock_profile.attachments = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        cmd = MagicMock()
        cmd.feature_importance = None

        result = await update_profile_feature_importance(mock_db, pref_id, cmd)

        assert result.feature_importance is None
        mock_db.flush.assert_awaited_once()


class TestUpsertUserSettingsErrorCase:
    """Tests for upsert_user_settings error cases."""

    @pytest.mark.asyncio
    async def test_raises_runtime_error_when_settings_not_found_after_upsert(self, sample_user_id: uuid.UUID) -> None:
        """Raises RuntimeError when settings not found after upsert."""
        mock_db = create_mock_session()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        cmd = UserPrefSettingsUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(sample_user_id),
            preferred_timezone="America/New_York",
            updated_fields=["preferred_timezone"],
        )

        with pytest.raises(RuntimeError, match="Failed to upsert user settings"):
            await upsert_user_settings(mock_db, sample_user_id, cmd)
