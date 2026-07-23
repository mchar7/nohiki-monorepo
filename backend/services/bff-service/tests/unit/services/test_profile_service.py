"""Tests for profile_service module.

This module consolidates all profile service tests following SOLID principles:
- Single Responsibility: Each test class focuses on one aspect of the service
- DRY: Uses shared factories from ``_helpers.py``
- Organized: Test classes group related functionality
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from nohiki.common.v1 import CurrencyCode, PaymentFrequency, SeniorityLevel, WorkArrangement
from nohiki_db_utils.testing import create_mock_session

from .._helpers import (
    make_command_status_projection,
    make_profile_projection,
    make_scalar_all,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def _import_profile_service(_monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    """Import ProfileService with required stubbing for tests."""
    from bff_service.services.profile_service import ProfileService

    return ProfileService


# Profile Query Tests


class TestProfileQueries:
    """Tests for profile query operations (list, get)."""

    @pytest.mark.asyncio
    async def test_list_profiles_returns_projection_data(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_db = create_mock_session()

        profile = make_profile_projection()
        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 1
        page_result = mocker.MagicMock()
        page_result.scalars.return_value = make_scalar_all([profile])
        mock_db.execute.side_effect = [count_result, page_result]

        items, total = await service.list_profiles(
            mock_db,
            profile.user_id,
            offset=20,
            limit=10,
        )

        assert total == 1
        assert len(items) == 1
        p = items[0]
        assert p.id == str(profile.id)
        assert p.user_id == str(profile.user_id)
        assert p.pref_name == "Test Profile"
        assert p.search_keywords == ["python", "remote"]
        assert p.disallowed_keywords == []
        assert p.notification_threshold == pytest.approx(0.70)
        assert p.auto_tailor_threshold == pytest.approx(0.8)
        assert p.open_to_relocation is True
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_list_profiles_maps_snake_protojson_nested_preferences(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_db = create_mock_session()
        profile = make_profile_projection()
        profile.salary_preference = {
            "min_salary": {"minor_units": "8000000", "currency": "CURRENCY_CODE_USD"},
            "target_salary": {"minor_units": "12500000", "currency": "CURRENCY_CODE_EUR"},
            "preferred_frequency": "PAYMENT_FREQUENCY_ANNUALLY",
        }
        profile.commute_preferences = {
            "acceptable_modes": ["TRANSIT_MODE_PUBLIC_TRANSIT", "TRANSIT_MODE_CYCLING"],
            "max_commute_minutes": 45,
            "ideal_commute_minutes": 25,
        }
        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 1
        page_result = mocker.MagicMock()
        page_result.scalars.return_value = make_scalar_all([profile])
        mock_db.execute.side_effect = [count_result, page_result]

        items, total = await service.list_profiles(mock_db, profile.user_id, offset=0, limit=20)

        assert total == 1
        assert items[0].salary_preference == {
            "min_salary": {"minor_units": 8_000_000, "currency": CurrencyCode.USD},
            "target_salary": {"minor_units": 12_500_000, "currency": CurrencyCode.EUR},
            "preferred_frequency": PaymentFrequency.ANNUALLY,
        }

    @pytest.mark.asyncio
    async def test_get_profile_returns_none_when_missing(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_db = create_mock_session()

        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.get_profile(mock_db, uuid.uuid4(), uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_profile_returns_data_when_found(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_db = create_mock_session()

        profile = make_profile_projection(profile_name="Test Profile")
        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = profile
        mock_db.execute.return_value = mock_result

        result = await service.get_profile(mock_db, profile.user_id, profile.id)

        assert result is not None
        assert result.id == str(profile.id)
        assert result.pref_name == "Test Profile"


# Profile Command Tests


class TestProfileCommands:
    """Tests for profile command operations (create, update, delete)."""

    @pytest.mark.asyncio
    async def test_create_profile_command_publishes_event(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)
        payload = {
            "pref_name": "Test",
            "auto_tailor_threshold": 0.8,
            "open_to_relocation": True,
        }

        request_id = await service.create_profile_command(user_id, payload)

        assert request_id == str(rid)
        mock_publish.assert_awaited_once()
        topic, event = mock_publish.call_args.args
        assert topic == "user-pref.cmd.create-requested.v1"
        assert mock_publish.call_args.kwargs.get("key") == str(rid)
        assert event.request_id == str(rid)
        assert event.user_id == str(user_id)
        assert event.pref_name == "Test"
        assert event.auto_tailor_threshold == 80
        assert event.open_to_relocation is True

    @pytest.mark.asyncio
    async def test_create_profile_command_preserves_arrangements_and_notification_threshold(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.patch("bff_service.services.profile_service.kafka_client.publish")
        user_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)
        payload = {
            "pref_name": "Remote hybrid",
            "work_arrangements": ["REMOTE", "HYBRID"],
            "notification_threshold": 0.7,
        }

        request_id = await service.create_profile_command(user_id, payload)

        assert request_id == str(rid)
        mock_publish.assert_awaited_once()
        _, event = mock_publish.call_args.args
        assert list(event.work_arrangements) == [WorkArrangement.REMOTE, WorkArrangement.HYBRID]
        assert event.notification_config.threshold == 70

    @pytest.mark.asyncio
    async def test_update_profile_command_sets_updated_fields(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)
        payload = {
            "pref_name": "Renamed",
            "auto_tailor_threshold": 0.6,
            "open_to_relocation": False,
        }

        request_id = await service.update_profile_command(user_id, pref_id, payload)

        assert request_id == str(rid)
        topic, event = mock_publish.call_args.args
        assert topic == "user-pref.cmd.update-requested.v1"
        assert mock_publish.call_args.kwargs.get("key") == str(rid)
        assert set(event.updated_fields) == {"pref_name", "auto_tailor_threshold", "open_to_relocation"}
        assert event.pref_name == "Renamed"
        assert event.auto_tailor_threshold == 60
        assert event.open_to_relocation is False

    @pytest.mark.asyncio
    async def test_update_profile_command_preserves_arrangements_and_notification_threshold_when_present(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.patch("bff_service.services.profile_service.kafka_client.publish")
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)
        payload = {
            "work_arrangements": ["REMOTE", "HYBRID"],
            "notification_threshold": 0.7,
        }

        request_id = await service.update_profile_command(user_id, pref_id, payload)

        assert request_id == str(rid)
        _, event = mock_publish.call_args.args
        assert set(event.updated_fields) == {"work_arrangements", "notification_config"}
        assert list(event.work_arrangements) == [WorkArrangement.REMOTE, WorkArrangement.HYBRID]
        assert event.notification_config.threshold == 70

    @pytest.mark.asyncio
    async def test_update_profile_command_leaves_arrangements_and_notification_unset_when_absent(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.patch("bff_service.services.profile_service.kafka_client.publish")
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)

        request_id = await service.update_profile_command(user_id, pref_id, {"pref_name": "Renamed"})

        assert request_id == str(rid)
        _, event = mock_publish.call_args.args
        assert list(event.work_arrangements) == []
        assert event.notification_config is None

    @pytest.mark.asyncio
    async def test_delete_profile_command_publishes(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)

        request_id = await service.delete_profile_command(user_id, pref_id)

        assert request_id == str(rid)
        topic, event = mock_publish.call_args.args
        assert topic == "user-pref.cmd.delete-requested.v1"
        assert mock_publish.call_args.kwargs.get("key") == str(rid)
        assert event.pref_id == str(pref_id)

    @pytest.mark.asyncio
    async def test_create_profile_command_without_optional_fields(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        user_id = uuid.uuid4()

        mock_publish = mocker.patch("bff_service.services.profile_service.kafka_client.publish")

        data = {"pref_name": "Minimal Profile"}
        request_id = await service.create_profile_command(user_id, data)

        assert request_id is not None
        _, event = mock_publish.call_args.args
        assert event.pref_name == "Minimal Profile"

    @pytest.mark.asyncio
    async def test_update_profile_command_with_search_and_disallowed_keywords(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)

        payload = {
            "pref_name": "Updated",
            "search_keywords": ["python", "async"],
            "disallowed_keywords": ["java", "legacy"],
        }

        request_id = await service.update_profile_command(user_id, pref_id, payload)

        assert request_id == str(rid)
        _, event = mock_publish.call_args.args
        assert event.pref_name == "Updated"
        assert list(event.search_keywords) == ["python", "async"]
        assert list(event.disallowed_keywords) == ["java", "legacy"]


# Profile Attachment Command Tests


class TestProfileAttachmentCommands:
    """Tests for profile attachment commands (associate, disassociate)."""

    @pytest.mark.asyncio
    async def test_associate_and_disassociate_attachment_commands_publish(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        upload_id = uuid.uuid4()

        rid1 = uuid.uuid4()
        rid2 = uuid.uuid4()
        rid_iter = iter([rid1, rid2])
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: next(rid_iter))

        req_attach = await service.associate_attachment_command(user_id, pref_id, upload_id)
        topic1, event1 = mock_publish.call_args_list[0].args
        assert req_attach == str(rid1)
        assert topic1 == "user-pref.cmd.attach-upload.v1"
        assert mock_publish.call_args_list[0].kwargs.get("key") == str(rid1)
        assert event1.upload_id == str(upload_id)

        req_detach = await service.disassociate_attachment_command(user_id, pref_id, upload_id)
        topic2, event2 = mock_publish.call_args_list[1].args
        assert req_detach == str(rid2)
        assert topic2 == "user-pref.cmd.detach-upload.v1"
        assert mock_publish.call_args_list[1].kwargs.get("key") == str(rid2)
        assert event2.pref_id == str(pref_id)


# Feature Importance Command Tests


class TestFeatureImportanceCommands:
    """Tests for feature importance command operations."""

    @pytest.mark.asyncio
    async def test_set_default_feature_importance_command_publishes_event(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)

        importance_prefs = {
            "skill_match_importance": 80,
            "location_importance": 70,
            "work_arrangement_importance": 60,
            "experience_importance": 50,
            "salary_importance": 40,
            "recency_importance": 30,
        }

        request_id = await service.set_default_feature_importance_command(user_id, importance_prefs)

        assert request_id == str(rid)
        topic, event = mock_publish.call_args.args
        assert topic == "user-pref.cmd.settings-update-requested.v1"
        assert event.default_feature_importance.skill_match_importance == 80
        assert event.default_feature_importance.location_importance == 70

    @pytest.mark.asyncio
    async def test_set_pref_feature_importance_command_publishes_event(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)

        importance_prefs = {
            "skill_match_importance": 90,
            "location_importance": 80,
        }

        request_id = await service.set_pref_feature_importance_command(user_id, pref_id, importance_prefs)

        assert request_id == str(rid)
        topic, event = mock_publish.call_args.args
        assert topic == "user-pref.cmd.pref-importance-update-requested.v1"
        assert event.feature_importance.skill_match_importance == 90
        assert event.pref_id == str(pref_id)


# Command Status Tests


class TestCommandStatus:
    """Tests for command status tracking."""

    @pytest.mark.asyncio
    async def test_get_command_status_returns_mapping(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_db = create_mock_session()

        cmd = make_command_status_projection()
        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = cmd
        mock_db.execute.return_value = mock_result

        out = await service.get_command_status(mock_db, cmd.user_id, cmd.request_id)
        assert out is not None
        assert out.request_id == str(cmd.request_id)
        assert out.command_type == "create_profile"
        assert out.status == "completed"

    @pytest.mark.asyncio
    async def test_get_command_status_returns_none_when_not_found(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_db = create_mock_session()

        mock_result = mocker.MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        result = await service.get_command_status(mock_db, uuid.uuid4(), uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_track_command_inserts_and_commits(
        self, mocker: MockerFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_db = create_mock_session()
        request_id = str(uuid.uuid4())
        user_id = uuid.uuid4()

        await service._track_command(mock_db, request_id, user_id, "create_profile")

        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()


# Helper Function Tests - Importance Fields


class TestImportanceFieldHelpers:
    """Tests for importance field helper functions."""

    def test_importance_fields_defined(self) -> None:
        from bff_service.services.profile_service import _IMPORTANCE_FIELDS

        assert "skill_match_importance" in _IMPORTANCE_FIELDS
        assert "location_importance" in _IMPORTANCE_FIELDS
        assert "work_arrangement_importance" in _IMPORTANCE_FIELDS
        assert "experience_importance" in _IMPORTANCE_FIELDS
        assert "salary_importance" in _IMPORTANCE_FIELDS
        assert "recency_importance" in _IMPORTANCE_FIELDS

    def test_has_any_importance_field_with_values(self) -> None:
        from bff_service.services.profile_service import _has_any_importance_field

        importance = {"skill_match_importance": 75, "location_importance": None}
        assert _has_any_importance_field(importance) is True

    def test_has_any_importance_field_all_none(self) -> None:
        from bff_service.services.profile_service import _has_any_importance_field

        importance = {
            "skill_match_importance": None,
            "location_importance": None,
            "work_arrangement_importance": None,
            "experience_importance": None,
            "salary_importance": None,
            "recency_importance": None,
        }
        assert _has_any_importance_field(importance) is False

    def test_has_any_importance_field_empty_dict(self) -> None:
        from bff_service.services.profile_service import _has_any_importance_field

        assert _has_any_importance_field({}) is False

    def test_has_any_importance_field_none_input(self) -> None:
        from bff_service.services.profile_service import _has_any_importance_field

        assert _has_any_importance_field(None) is False

    def test_has_any_importance_field_zero_values(self) -> None:
        from bff_service.services.profile_service import _has_any_importance_field

        importance = {"skill_match_importance": 0, "location_importance": 50}
        assert _has_any_importance_field(importance) is True

    def test_has_any_importance_field_partial_fields(self) -> None:
        from bff_service.services.profile_service import _has_any_importance_field

        importance = {"skill_match_importance": 80}
        assert _has_any_importance_field(importance) is True


# Profile Command Tests - Complex Payloads


class TestProfileCommandsComplexPayloads:
    """Tests for profile commands with complex nested payloads."""

    @pytest.mark.parametrize("experience_years", [0, 5, 50])
    @pytest.mark.asyncio
    async def test_create_profile_command_with_salary_preference(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        experience_years: int,
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)

        payload = {
            "pref_name": "Test",
            "salary_preference": {
                "min_salary": {"minor_units": 8000000, "currency": CurrencyCode.USD},
                "target_salary": {"minor_units": 12000000, "currency": CurrencyCode.USD},
                "preferred_frequency": PaymentFrequency.ANNUALLY,
            },
            "experience_preference": {
                "experience_years": experience_years,
                "seniority_levels": [SeniorityLevel.SENIOR, SeniorityLevel.STAFF],
            },
        }

        request_id = await service.create_profile_command(user_id, payload)

        assert request_id == str(rid)
        mock_publish.assert_awaited_once()
        _, event = mock_publish.call_args.args
        assert event.salary_preference is not None
        assert event.salary_preference.min_salary.minor_units == 8000000
        assert event.salary_preference.target_salary.minor_units == 12000000
        assert event.experience_preference is not None
        assert event.experience_preference.experience_years == experience_years
        assert len(event.experience_preference.seniority_levels) == 2

    @pytest.mark.parametrize("experience_years", [0, 5, 50])
    @pytest.mark.asyncio
    async def test_update_profile_command_with_salary_preference(
        self,
        mocker: MockerFixture,
        monkeypatch: pytest.MonkeyPatch,
        experience_years: int,
    ) -> None:
        profile_service_cls = _import_profile_service(monkeypatch)
        service = profile_service_cls()
        mock_publish = mocker.AsyncMock()
        mock_kafka = mocker.MagicMock()
        mock_kafka.publish = mock_publish
        monkeypatch.setattr("bff_service.services.profile_service.kafka_client", mock_kafka)
        user_id = uuid.uuid4()
        pref_id = uuid.uuid4()
        rid = uuid.uuid4()
        monkeypatch.setattr("bff_service.services.profile_service.uuid7", lambda: rid)

        payload = {
            "salary_preference": {
                "min_salary": {"minor_units": 9000000, "currency": CurrencyCode.EUR},
                "target_salary": {"minor_units": 15000000, "currency": CurrencyCode.EUR},
                "preferred_frequency": PaymentFrequency.MONTHLY,
            },
            "experience_preference": {
                "experience_years": experience_years,
                "seniority_levels": [SeniorityLevel.DIRECTOR],
            },
        }

        request_id = await service.update_profile_command(user_id, pref_id, payload)

        assert request_id == str(rid)
        _, event = mock_publish.call_args.args
        assert event.salary_preference is not None
        assert event.salary_preference.min_salary.minor_units == 9000000
        assert event.experience_preference is not None
        assert event.experience_preference.experience_years == experience_years
        assert len(event.experience_preference.seniority_levels) == 1
