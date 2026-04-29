"""Unit tests for user_pref_service.services.profile_service module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from nohiki.common.v1 import (
    ExperiencePreference,
    SeniorityLevel,
    TransitMode,
    WorkArrangement,
)
from nohiki.user.pref.v1 import PrefCreateRequested, PrefUpdateRequested
from nohiki_db_utils.testing import create_mock_session
from nohiki_fastapi_utils.errors import NotFoundError
from user_pref_service.db.models import SearchPref, SearchPrefUpload
from user_pref_service.services.profile_service import (
    _build_timestamps,
    _extract_skills_embedding,
    _get_upload_references,
    associate_attachment,
    build_profile_snapshot,
    create_profile,
    delete_profile,
    delete_user_profiles,
    disassociate_attachment,
    get_profile_by_id,
    get_profile_by_request_id,
    list_user_profiles,
    remove_attachment_from_all_profiles,
    update_profile,
)


class TestBuildProfileSnapshot:
    """Tests for build_profile_snapshot function."""

    @pytest.mark.parametrize("experience_years", [0, 5, 50])
    def test_builds_snapshot_from_profile(self, experience_years: int) -> None:
        """Builds SearchPrefSnapshot from SearchPref model without losing experience years."""
        profile = MagicMock(spec=SearchPref)
        profile.id = uuid.uuid4()
        profile.user_id = uuid.uuid4()
        profile.pref_name = "Test Profile"
        profile.search_keywords = ["python", "fastapi"]
        profile.disallowed_keywords = ["java"]
        profile.physical_locations = None
        profile.remote_locations = None
        profile.work_arrangements = [WorkArrangement.REMOTE]
        profile.notification_config = None
        profile.auto_tailor_threshold = 80
        profile.tailoring_schema_id = None
        profile.tailoring_preferences = {}
        profile.is_active = True
        profile.attachments = []
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)
        profile.experience_years = experience_years
        profile.seniority_levels = [1]

        snapshot = build_profile_snapshot(profile)

        assert snapshot.id == str(profile.id)
        assert snapshot.user_id == str(profile.user_id)
        assert snapshot.pref_name == "Test Profile"
        assert list(snapshot.search_keywords) == ["python", "fastapi"]
        assert snapshot.is_active is True
        assert snapshot.experience_preference is not None
        assert snapshot.experience_preference.experience_years == experience_years
        assert snapshot.timestamps is not None
        assert snapshot.timestamps.updated_at == profile.updated_at

    def test_snapshot_skills_embedding_none_when_profile_has_no_embedding(self) -> None:
        """Snapshot user_skills_embedding is None before normalization completes."""
        profile = MagicMock(spec=SearchPref)
        profile.id = uuid.uuid4()
        profile.user_id = uuid.uuid4()
        profile.pref_name = "New Profile"
        profile.search_keywords = []
        profile.disallowed_keywords = []
        profile.physical_locations = None
        profile.remote_locations = None
        profile.work_arrangements = []
        profile.open_to_relocation = False
        profile.commute_preferences = None
        profile.excluded_scrape_sources = []
        profile.min_fit_score_disqualify = None
        profile.auto_tailor_threshold = None
        profile.tailoring_schema_id = None
        profile.tailoring_preferences = {}
        profile.is_active = True
        profile.attachments = []
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)
        profile.user_skills_embedding = None
        profile.collection_version = None
        profile.query_embedding = [0.1, 0.2]
        profile.query_artifacts_data = None

        snapshot = build_profile_snapshot(profile)

        assert snapshot.user_skills_embedding is None


class TestGetProfileById:
    """Tests for get_profile_by_id function."""

    @pytest.mark.asyncio
    async def test_returns_profile_when_found(self) -> None:
        """Returns profile when it exists."""
        mock_db = create_mock_session()
        profile_id = uuid.uuid4()
        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = profile_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_profile_by_id(mock_db, profile_id)

        assert result == mock_profile

    @pytest.mark.asyncio
    async def test_raises_not_found_when_missing(self) -> None:
        """Raises NotFoundError when profile doesn't exist."""
        mock_db = create_mock_session()
        profile_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(NotFoundError):
            await get_profile_by_id(mock_db, profile_id)


class TestGetProfileByRequestId:
    """Tests for get_profile_by_request_id function."""

    @pytest.mark.asyncio
    async def test_returns_profile_when_found(self) -> None:
        """Returns profile when it exists."""
        mock_db = create_mock_session()
        request_id = uuid.uuid4()
        mock_profile = MagicMock(spec=SearchPref)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_profile_by_request_id(mock_db, request_id)

        assert result == mock_profile

    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self) -> None:
        """Returns None when profile doesn't exist."""
        mock_db = create_mock_session()
        request_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await get_profile_by_request_id(mock_db, request_id)

        assert result is None


class TestCreateProfile:
    """Tests for create_profile function."""

    @pytest.mark.parametrize("experience_years", [0, 5, 50])
    @pytest.mark.asyncio
    async def test_creates_profile_from_command(self, experience_years: int) -> None:
        """Creates a profile without changing the requested experience years."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()
        request_id = str(uuid.uuid4())

        command = PrefCreateRequested(
            request_id=request_id,
            user_id=str(user_id),
            pref_name="New Profile",
            search_keywords=["python"],
            is_active=True,
            experience_preference=ExperiencePreference(
                experience_years=experience_years,
                seniority_levels=[SeniorityLevel.MID],
            ),
        )

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = uuid.uuid4()
        mock_profile.user_id = user_id
        mock_profile.pref_name = "New Profile"
        mock_profile.attachments = []

        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await create_profile(mock_db, user_id, command)

        assert result.pref_name == "New Profile"
        mock_db.add.assert_called_once()
        created_profile = mock_db.add.call_args.args[0]
        assert created_profile.experience_years == experience_years
        mock_db.flush.assert_awaited_once()


class TestUpdateProfile:
    """Tests for update_profile function."""

    @pytest.mark.asyncio
    async def test_updates_profile_fields(self) -> None:
        """Updates profile fields from command."""
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = pref_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        command = PrefUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            pref_id=str(pref_id),
            pref_name="Updated Profile",
            updated_fields=["pref_name"],
        )

        result = await update_profile(mock_db, pref_id, command)

        assert result == mock_profile

    @pytest.mark.parametrize("experience_years", [0, 5, 50])
    @pytest.mark.asyncio
    async def test_updates_and_clears_skill_salary_and_experience_fields(self, experience_years: int) -> None:
        """Every declared update field is applied, including exact experience years and clears."""
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        user_skill = str(uuid.uuid4())
        required_skill = str(uuid.uuid4())
        preferred_skill = str(uuid.uuid4())
        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = pref_id
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        salary = MagicMock()
        salary.to_dict.return_value = {"minimum": 100_000}
        experience = MagicMock()
        experience.experience_years = experience_years
        experience.seniority_levels = [1]
        command = MagicMock(spec=PrefUpdateRequested)
        command.updated_fields = [
            "user_skills",
            "required_skills",
            "preferred_skills",
            "salary_preference",
            "experience_preference",
        ]
        command.user_skills = [user_skill]
        command.required_skills = [required_skill]
        command.preferred_skills = [preferred_skill]
        command.salary_preference = salary
        command.experience_preference = experience
        command.pref_name = ""
        command.search_keywords = []
        command.disallowed_keywords = []
        command.physical_locations = []
        command.remote_locations = []
        command.work_arrangements = []
        command.open_to_relocation = False
        command.commute_preferences = None
        command.auto_tailor_threshold = 0
        command.tailoring_schema_id = ""
        command.tailoring_preferences = {}
        command.is_active = False
        command.notification_config = None

        await update_profile(mock_db, pref_id, command)

        assert mock_profile.user_skill_ids == [
            user_skill,
            required_skill,
            preferred_skill,
        ]
        assert len(mock_profile.user_skills_data) == 3
        assert mock_profile.salary_preference == {"minimum": 100_000}
        assert mock_profile.experience_years == experience_years
        assert len(mock_profile.seniority_levels) == 1

        command.user_skills = []
        command.required_skills = []
        command.preferred_skills = []
        command.salary_preference = None
        command.experience_preference = None

        await update_profile(mock_db, pref_id, command)

        assert mock_profile.user_skill_ids == []
        assert mock_profile.user_skills_data == []
        assert mock_profile.salary_preference is None
        assert mock_profile.experience_years is None
        assert mock_profile.seniority_levels == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("updated_fields", "expected_generation"),
        [(["is_active"], 7), (["pref_name"], 8)],
        ids=["unrelated-field", "name-only"],
    )
    async def test_semantic_generation_changes_only_for_semantic_patch_fields(
        self, updated_fields: list[str], expected_generation: int
    ) -> None:
        """Only semantic profile fields advance callback generation."""
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = pref_id
        mock_profile.semantic_content_generation = 7
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        if updated_fields == ["is_active"]:
            command = PrefUpdateRequested(
                request_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                pref_id=str(pref_id),
                updated_fields=updated_fields,
                is_active=False,
            )
        else:
            command = PrefUpdateRequested(
                request_id=str(uuid.uuid4()),
                user_id=str(uuid.uuid4()),
                pref_id=str(pref_id),
                updated_fields=updated_fields,
                pref_name="Renamed Profile",
            )

        await update_profile(mock_db, pref_id, command)

        assert mock_profile.semantic_content_generation == expected_generation


class TestDeleteProfile:
    """Tests for delete_profile function."""

    @pytest.mark.asyncio
    async def test_deletes_profile(self) -> None:
        """Deletes profile by ID."""
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute = AsyncMock(return_value=mock_result)

        await delete_profile(mock_db, pref_id)

        mock_db.execute.assert_awaited()


class TestDeleteUserProfiles:
    """Tests for delete_user_profiles function."""

    @pytest.mark.asyncio
    async def test_deletes_all_user_profiles_via_bulk_delete(self) -> None:
        """Deletes all profiles for a user using bulk DELETE (O(1) DB round-trip)."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await delete_user_profiles(mock_db, user_id)

        assert result == 3
        mock_db.execute.assert_awaited_once()
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_profiles(self) -> None:
        """Returns 0 when user has no profiles to delete."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await delete_user_profiles(mock_db, user_id)

        assert result == 0
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handles_none_rowcount(self) -> None:
        """Handles case when rowcount is None (treated as 0)."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.rowcount = None
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        result = await delete_user_profiles(mock_db, user_id)

        assert result == 0


class TestAssociateAttachment:
    """Tests for observable attachment association transitions."""

    @pytest.mark.asyncio
    async def test_new_association_is_persisted_with_requested_type(self) -> None:
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = MagicMock(spec=SearchPref)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(side_effect=[profile_result, existing_result, MagicMock()])

        association = await associate_attachment(mock_db, pref_id, upload_id, "example")

        assert association.pref_id == pref_id
        assert association.upload_id == upload_id
        assert association.upload_type == "example"
        mock_db.add.assert_called_once_with(association)
        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exact_duplicate_is_a_no_op(self) -> None:
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        existing_attachment = SearchPrefUpload(
            pref_id=pref_id,
            upload_id=upload_id,
            upload_type="example",
        )
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = MagicMock(spec=SearchPref)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_attachment
        mock_db.execute = AsyncMock(side_effect=[profile_result, existing_result])

        result = await associate_attachment(mock_db, pref_id, upload_id, "example")

        assert result is existing_attachment
        mock_db.add.assert_not_called()
        mock_db.flush.assert_not_awaited()
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_type_change_returns_refreshed_association(self) -> None:
        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        upload_id = uuid.uuid4()
        existing_attachment = SearchPrefUpload(
            pref_id=pref_id,
            upload_id=upload_id,
            upload_type="example",
        )
        updated_attachment = SearchPrefUpload(
            pref_id=pref_id,
            upload_id=upload_id,
            upload_type="additional_context",
        )
        profile_result = MagicMock()
        profile_result.scalar_one_or_none.return_value = MagicMock(spec=SearchPref)
        existing_result = MagicMock()
        existing_result.scalar_one_or_none.return_value = existing_attachment
        refreshed_result = MagicMock()
        refreshed_result.scalar_one.return_value = updated_attachment
        mock_db.execute = AsyncMock(
            side_effect=[
                profile_result,
                existing_result,
                MagicMock(),
                MagicMock(),
                refreshed_result,
            ]
        )

        result = await associate_attachment(mock_db, pref_id, upload_id, "additional_context")

        assert result is updated_attachment
        assert result.upload_type == "additional_context"
        mock_db.flush.assert_awaited_once()


class TestDisassociateAttachment:
    """Tests for observable attachment removal transitions."""

    @pytest.mark.asyncio
    async def test_existing_association_is_removed(self) -> None:
        mock_db = create_mock_session()
        deleted = MagicMock(rowcount=1)
        mock_db.execute = AsyncMock(side_effect=[deleted, MagicMock()])

        await disassociate_attachment(mock_db, uuid.uuid4(), uuid.uuid4())

        mock_db.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_missing_association_raises_without_advancing_revision(self) -> None:
        mock_db = create_mock_session()
        mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=0))

        with pytest.raises(NotFoundError):
            await disassociate_attachment(mock_db, uuid.uuid4(), uuid.uuid4())

        mock_db.flush.assert_not_awaited()
        mock_db.execute.assert_awaited_once()


class TestRemoveAttachmentFromAllProfiles:
    """Tests for bulk attachment removal."""

    @pytest.mark.asyncio
    async def test_returns_deleted_association_count(self) -> None:
        mock_db = create_mock_session()
        deleted = MagicMock(rowcount=5)
        mock_db.execute = AsyncMock(side_effect=[MagicMock(), deleted])

        result = await remove_attachment_from_all_profiles(mock_db, uuid.uuid4())

        assert result == 5
        mock_db.flush.assert_awaited_once()


class TestListUserProfiles:
    """Tests for list_user_profiles function."""

    @pytest.mark.asyncio
    async def test_lists_all_user_profiles(self) -> None:
        """Lists all profiles for a user."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()

        mock_profiles = [MagicMock(), MagicMock()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_profiles
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_user_profiles(mock_db, user_id)

        assert len(result) == 2
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_filters_active_only_profiles(self) -> None:
        """Filters to only active profiles when active_only=True."""
        mock_db = create_mock_session()
        user_id = uuid.uuid4()

        mock_profiles = [MagicMock()]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = mock_profiles
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await list_user_profiles(mock_db, user_id, active_only=True)

        assert len(result) == 1
        mock_db.execute.assert_awaited_once()


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_get_upload_references_separates_types(self) -> None:
        """Separates example and context uploads."""
        att1 = MagicMock(spec=SearchPrefUpload)
        att1.upload_id = uuid.uuid4()
        att1.upload_type = "example"

        att2 = MagicMock(spec=SearchPrefUpload)
        att2.upload_id = uuid.uuid4()
        att2.upload_type = "context"

        example_uploads, context_uploads = _get_upload_references([att1, att2])

        assert len(example_uploads) == 1
        assert len(context_uploads) == 1

    def test_build_timestamps_with_valid_dates(self) -> None:
        """Builds EntityTimestamps from profile with valid dates."""
        profile = MagicMock(spec=SearchPref)
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)

        result = _build_timestamps(profile)

        assert result.created_at is not None
        assert result.updated_at is not None

    def test_build_timestamps_raises_on_none(self) -> None:
        """Raises ValueError when timestamps are None."""
        profile = MagicMock(spec=SearchPref)
        profile.created_at = None
        profile.updated_at = None

        with pytest.raises(ValueError, match="created_at and updated_at must be set"):
            _build_timestamps(profile)

    def test_extract_skills_embedding_returns_none_when_no_embedding(self) -> None:
        """Returns None when profile has no user_skills_embedding (DB NULL)."""
        profile = MagicMock(spec=SearchPref)
        profile.user_skills_embedding = None

        result = _extract_skills_embedding(profile)

        assert result is None

    def test_extract_skills_embedding_returns_none_for_empty_list(self) -> None:
        """Returns None when profile has empty user_skills_embedding list."""
        profile = MagicMock(spec=SearchPref)
        profile.user_skills_embedding = []

        result = _extract_skills_embedding(profile)

        assert result is None

    def test_extract_skills_embedding_returns_vector_when_populated(self) -> None:
        """Returns EmbeddingVector with correct values when embedding exists."""
        from nohiki.ml.v1 import EmbeddingType

        profile = MagicMock(spec=SearchPref)
        profile.user_skills_embedding = [0.1, 0.2, 0.3]
        profile.collection_version = "v2"

        result = _extract_skills_embedding(profile)

        assert result is not None
        assert result.embedding_type == EmbeddingType.DENSE
        assert result.dense is not None
        assert list(result.dense.values) == [0.1, 0.2, 0.3]
        assert result.collection_version == "v2"


class TestBuildProfileSnapshotWithLocationFields:
    """Tests for build_profile_snapshot with open_to_relocation and commute_preferences."""

    def test_includes_open_to_relocation_false(self) -> None:
        """Includes open_to_relocation=False in snapshot."""
        profile = MagicMock(spec=SearchPref)
        profile.id = uuid.uuid4()
        profile.user_id = uuid.uuid4()
        profile.pref_name = "Test Profile"
        profile.search_keywords = ["python"]
        profile.disallowed_keywords = []
        profile.physical_locations = []
        profile.remote_locations = []
        profile.work_arrangements = []
        profile.open_to_relocation = False
        profile.commute_preferences = None
        profile.excluded_scrape_sources = []
        profile.min_fit_score_disqualify = None
        profile.auto_tailor_threshold = None
        profile.tailoring_schema_id = None
        profile.tailoring_preferences = {}
        profile.is_active = True
        profile.attachments = []
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)

        snapshot = build_profile_snapshot(profile)

        assert snapshot.open_to_relocation is False
        assert snapshot.commute_preferences is None

    def test_includes_open_to_relocation_true(self) -> None:
        """Includes open_to_relocation=True in snapshot."""
        profile = MagicMock(spec=SearchPref)
        profile.id = uuid.uuid4()
        profile.user_id = uuid.uuid4()
        profile.pref_name = "Test Profile"
        profile.search_keywords = ["python"]
        profile.disallowed_keywords = []
        profile.physical_locations = []
        profile.remote_locations = []
        profile.work_arrangements = []
        profile.open_to_relocation = True
        profile.commute_preferences = None
        profile.excluded_scrape_sources = []
        profile.min_fit_score_disqualify = None
        profile.auto_tailor_threshold = None
        profile.tailoring_schema_id = None
        profile.tailoring_preferences = {}
        profile.is_active = True
        profile.attachments = []
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)

        snapshot = build_profile_snapshot(profile)

        assert snapshot.open_to_relocation is True

    def test_includes_commute_preferences(self) -> None:
        """Includes commute_preferences in snapshot when set."""
        profile = MagicMock(spec=SearchPref)
        profile.id = uuid.uuid4()
        profile.user_id = uuid.uuid4()
        profile.pref_name = "Test Profile"
        profile.search_keywords = ["python"]
        profile.disallowed_keywords = []
        profile.physical_locations = []
        profile.remote_locations = []
        profile.work_arrangements = []
        profile.open_to_relocation = False
        profile.commute_preferences = {
            "acceptable_modes": [1, 2],
            "max_commute_minutes": 45,
            "ideal_commute_minutes": 20,
        }
        profile.excluded_scrape_sources = []
        profile.min_fit_score_disqualify = None
        profile.auto_tailor_threshold = None
        profile.tailoring_schema_id = None
        profile.tailoring_preferences = {}
        profile.is_active = True
        profile.attachments = []
        profile.created_at = datetime.now(UTC)
        profile.updated_at = datetime.now(UTC)

        snapshot = build_profile_snapshot(profile)

        assert snapshot.commute_preferences is not None
        assert list(snapshot.commute_preferences.acceptable_modes) == [
            TransitMode.DRIVING,
            TransitMode.PUBLIC_TRANSIT,
        ]
        assert snapshot.commute_preferences.max_commute_minutes == 45
        assert snapshot.commute_preferences.ideal_commute_minutes == 20


class TestCreateProfileGeocoding:
    """Tests for geocoding integration in create_profile."""

    @pytest.mark.asyncio
    @patch("user_pref_service.services.profile_service.get_settings")
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_create_profile_geocodes_when_enabled(
        self, mock_get_geocoder: MagicMock, mock_get_settings: MagicMock
    ) -> None:
        """Coordinates present in JSONB when geocoding_enabled=True."""
        from nohiki.common.v1 import CountryCode, GeoCoordinates, Location

        mock_settings = MagicMock()
        mock_settings.geocoding_enabled = True
        mock_get_settings.return_value = mock_settings

        geocoded_loc = Location(
            city="Toronto",
            country=CountryCode.CAN,
            coordinates=GeoCoordinates(latitude=43.65, longitude=-79.38),
        )
        mock_geocoder = AsyncMock(return_value=geocoded_loc)
        mock_get_geocoder.return_value = mock_geocoder

        mock_db = create_mock_session()
        user_id = uuid.uuid4()
        request_id = str(uuid.uuid4())

        command = PrefCreateRequested(
            request_id=request_id,
            user_id=str(user_id),
            pref_name="Geocoded Profile",
            search_keywords=["python"],
            physical_locations=[Location(city="Toronto", country=CountryCode.CAN)],
            is_active=True,
        )

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = uuid.uuid4()
        mock_profile.user_id = user_id
        mock_profile.pref_name = "Geocoded Profile"
        mock_profile.attachments = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        await create_profile(mock_db, user_id, command)

        # Verify geocoder was called
        mock_geocoder.assert_awaited_once()

        # Verify the profile was created with geocoded data
        add_call_args = mock_db.add.call_args[0][0]
        locs = add_call_args.physical_locations
        assert len(locs) == 1
        assert locs[0]["coordinates"]["latitude"] == 43.65
        assert locs[0]["coordinates"]["longitude"] == -79.38

    @pytest.mark.asyncio
    @patch("user_pref_service.services.profile_service.get_settings")
    async def test_create_profile_skips_geocoding_when_disabled(self, mock_get_settings: MagicMock) -> None:
        """No coordinates when geocoding_enabled=False."""
        from nohiki.common.v1 import CountryCode, Location

        mock_settings = MagicMock()
        mock_settings.geocoding_enabled = False
        mock_get_settings.return_value = mock_settings

        mock_db = create_mock_session()
        user_id = uuid.uuid4()
        request_id = str(uuid.uuid4())

        command = PrefCreateRequested(
            request_id=request_id,
            user_id=str(user_id),
            pref_name="No Geocode Profile",
            search_keywords=["python"],
            physical_locations=[Location(city="Toronto", country=CountryCode.CAN)],
            is_active=True,
        )

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = uuid.uuid4()
        mock_profile.user_id = user_id
        mock_profile.attachments = []

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()

        with patch("user_pref_service.services.geo_integration._get_cached_geocoder") as mock_get_geocoder:
            await create_profile(mock_db, user_id, command)
            mock_get_geocoder.assert_not_called()


class TestUpdateProfileGeocoding:
    """Tests for geocoding integration in update_profile."""

    @pytest.mark.asyncio
    @patch("user_pref_service.services.profile_service.get_settings")
    @patch("user_pref_service.services.geo_integration._get_cached_geocoder")
    async def test_update_profile_geocodes_physical_locations(
        self, mock_get_geocoder: MagicMock, mock_get_settings: MagicMock
    ) -> None:
        """Geocodes when physical_locations in updated_fields and enabled."""
        from nohiki.common.v1 import CountryCode, GeoCoordinates, Location

        mock_settings = MagicMock()
        mock_settings.geocoding_enabled = True
        mock_get_settings.return_value = mock_settings

        geocoded_loc = Location(
            city="Vancouver",
            country=CountryCode.CAN,
            coordinates=GeoCoordinates(latitude=49.28, longitude=-123.12),
        )
        mock_geocoder = AsyncMock(return_value=geocoded_loc)
        mock_get_geocoder.return_value = mock_geocoder

        mock_db = create_mock_session()
        pref_id = uuid.uuid4()
        raw_loc_dict = Location(city="Vancouver", country=CountryCode.CAN).to_dict()

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = pref_id
        mock_profile.physical_locations = [raw_loc_dict]

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        command = PrefUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            pref_id=str(pref_id),
            physical_locations=[Location(city="Vancouver", country=CountryCode.CAN)],
            updated_fields=["physical_locations"],
        )

        await update_profile(mock_db, pref_id, command)

        mock_geocoder.assert_awaited_once()
        # physical_locations should be updated with geocoded data
        assert mock_profile.physical_locations[0]["coordinates"]["latitude"] == 49.28

    @pytest.mark.asyncio
    @patch("user_pref_service.services.profile_service.get_settings")
    async def test_update_profile_skips_geocoding_when_locations_not_updated(
        self, mock_get_settings: MagicMock
    ) -> None:
        """Geocoder NOT called when physical_locations not in updated_fields."""
        mock_settings = MagicMock()
        mock_settings.geocoding_enabled = True
        mock_get_settings.return_value = mock_settings

        mock_db = create_mock_session()
        pref_id = uuid.uuid4()

        mock_profile = MagicMock(spec=SearchPref)
        mock_profile.id = pref_id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_profile
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()

        command = PrefUpdateRequested(
            request_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
            pref_id=str(pref_id),
            pref_name="Updated Name",
            updated_fields=["pref_name"],
        )

        with patch("user_pref_service.services.geo_integration._get_cached_geocoder") as mock_get_geocoder:
            await update_profile(mock_db, pref_id, command)
            mock_get_geocoder.assert_not_called()
