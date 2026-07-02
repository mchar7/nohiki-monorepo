import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from nohiki.common.v1 import CurrencyCode, PaymentFrequency, SeniorityLevel, WorkArrangement
from nohiki_db_utils.testing import create_mock_session
from pytest_mock import MockerFixture


def _build_profiles_client(mock_service: object, user_id: uuid.UUID) -> TestClient:
    from bff_service.api.deps.auth import get_current_user_id_from_cookie
    from bff_service.api.routers.profiles import get_async_db, get_profile_service, router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/profiles")
    app.dependency_overrides[get_current_user_id_from_cookie] = lambda: user_id
    app.dependency_overrides[get_profile_service] = lambda: mock_service
    app.dependency_overrides[get_async_db] = create_mock_session
    return TestClient(app, raise_server_exceptions=False)


def _valid_profile_create_payload() -> dict[str, object]:
    return {
        "pref_name": "Profile",
        "search_keywords": ["python"],
        "work_arrangements": ["HYBRID"],
        "salary_preference": {
            "min_salary": {"minor_units": 80_000_00, "currency": "USD"},
            "target_salary": {"minor_units": 120_000_00, "currency": "USD"},
        },
        "experience_preference": {"experience_years": 5, "seniority_levels": ["MID"]},
    }


@pytest.mark.asyncio
async def test_list_profiles_returns_service_data(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import list_profiles
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_service = mocker.Mock()
    pagination = PaginationParams(page=1, page_size=20)
    mock_service.list_profiles = mocker.AsyncMock(
        return_value=(
            [
                {
                    "id": str(uuid.uuid4()),
                    "user_id": str(user_id),
                    "pref_name": "Profile 1",
                    "search_keywords": ["python"],
                    "disallowed_keywords": [],
                    "work_arrangements": ["REMOTE"],
                    "notification_threshold": 0.7,
                    "auto_tailor_threshold": 0.8,
                    "open_to_relocation": False,
                }
            ],
            1,
        )
    )

    result = await list_profiles(user_id, mock_db, pagination, mock_service)

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].pref_name == "Profile 1"
    mock_service.list_profiles.assert_awaited_once_with(mock_db, user_id, offset=0, limit=20)


@pytest.mark.asyncio
async def test_list_profiles_returns_empty_when_no_profiles(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import list_profiles
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_service = mocker.Mock()
    pagination = PaginationParams(page=1, page_size=20)
    mock_service.list_profiles = mocker.AsyncMock(return_value=([], 0))

    result = await list_profiles(user_id, mock_db, pagination, mock_service)

    assert result.total == 0
    assert result.items == []


@pytest.mark.asyncio
async def test_list_profiles_page_two_slices_items_but_preserves_total(mocker: MockerFixture) -> None:
    """Pagination returns the requested window while total reflects all user profiles."""
    from bff_service.api.routers.profiles import list_profiles
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    page_profiles = [
        {
            "id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "pref_name": f"Profile {index}",
            "search_keywords": ["python"],
            "disallowed_keywords": [],
            "work_arrangements": ["REMOTE"],
            "notification_threshold": 0.7,
            "auto_tailor_threshold": 0.8,
            "open_to_relocation": False,
        }
        for index in (3, 4)
    ]
    mock_service = mocker.Mock()
    mock_service.list_profiles = mocker.AsyncMock(return_value=(page_profiles, 5))
    mock_db = create_mock_session()

    result = await list_profiles(
        user_id,
        mock_db,
        PaginationParams(page=2, page_size=2),
        mock_service,
    )

    assert [profile.pref_name for profile in result.items] == ["Profile 3", "Profile 4"]
    assert result.total == 5
    assert result.page == 2
    assert result.total_pages == 3
    assert result.has_prev is True
    assert result.has_next is True
    mock_service.list_profiles.assert_awaited_once_with(
        mock_db,
        user_id,
        offset=2,
        limit=2,
    )


@pytest.mark.asyncio
async def test_create_profile_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import ProfileCreate, create_profile

    user_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.create_profile_command = mocker.AsyncMock(return_value=request_id)

    from bff_service.api.routers.profiles import (
        ExperiencePreferenceRequest,
        MonetaryAmountRequest,
        SalaryPreferenceRequest,
    )

    data = ProfileCreate(
        pref_name="New Profile",
        search_keywords=["rust"],
        disallowed_keywords=["java"],
        work_arrangements=[WorkArrangement.HYBRID],
        notification_threshold=0.75,
        auto_tailor_threshold=0.85,
        salary_preference=SalaryPreferenceRequest(
            min_salary=MonetaryAmountRequest(minor_units=8000000, currency=CurrencyCode.USD),
            target_salary=MonetaryAmountRequest(minor_units=12000000, currency=CurrencyCode.USD),
        ),
        experience_preference=ExperiencePreferenceRequest(
            experience_years=5,
            seniority_levels=[SeniorityLevel.MID],
        ),
    )

    result = await create_profile(data, user_id, mock_service)

    assert result.request_id == request_id
    assert result.status == "accepted"
    mock_service.create_profile_command.assert_awaited_once()


@pytest.mark.parametrize("experience_years", [0, 5, 50])
@pytest.mark.asyncio
async def test_get_profile_returns_service_data(mocker: MockerFixture, experience_years: int) -> None:
    from bff_service.api.routers.profiles import get_profile

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_service = mocker.Mock()
    mock_service.get_profile = mocker.AsyncMock(
        return_value={
            "id": str(pref_id),
            "user_id": str(user_id),
            "pref_name": "Test Profile",
            "search_keywords": ["go"],
            "disallowed_keywords": [],
            "work_arrangements": ["ON_SITE"],
            "notification_threshold": 0.6,
            "auto_tailor_threshold": None,
            "open_to_relocation": True,
            "experience_preference": {
                "experience_years": experience_years,
                "seniority_levels": ["MID"],
            },
        }
    )

    result = await get_profile(pref_id, user_id, mock_db, mock_service)

    assert result.pref_name == "Test Profile"
    assert result.notification_threshold == pytest.approx(0.6)
    assert result.experience_preference is not None
    assert result.experience_preference.experience_years == experience_years
    mock_service.get_profile.assert_awaited_once_with(mock_db, user_id, pref_id)


def test_get_profile_api_retains_snake_case_salary_values(mocker: MockerFixture) -> None:
    """Response-model serialization retains nested projection salary fields verbatim."""
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_service = mocker.Mock()
    mock_service.get_profile = mocker.AsyncMock(
        return_value={
            "id": str(pref_id),
            "user_id": str(user_id),
            "pref_name": "Salary profile",
            "search_keywords": ["python"],
            "disallowed_keywords": [],
            "work_arrangements": ["REMOTE"],
            "notification_threshold": 0.7,
            "auto_tailor_threshold": 0.8,
            "open_to_relocation": False,
            "salary_preference": {
                "min_salary": {"minor_units": 8_000_000, "currency": CurrencyCode.USD},
                "target_salary": {"minor_units": 12_500_000, "currency": CurrencyCode.EUR},
                "preferred_frequency": PaymentFrequency.ANNUALLY,
            },
            "commute_preferences": {
                "acceptable_modes": ["TRANSIT_MODE_PUBLIC_TRANSIT", "TRANSIT_MODE_CYCLING"],
                "max_commute_minutes": 45,
                "ideal_commute_minutes": 25,
            },
        }
    )

    client = _build_profiles_client(mock_service, user_id)
    response = client.get(f"/api/v1/profiles/{pref_id}")

    assert response.status_code == 200
    assert response.json()["salary_preference"] == {
        "min_salary": {"minor_units": 8_000_000, "currency": "USD"},
        "target_salary": {"minor_units": 12_500_000, "currency": "EUR"},
        "preferred_frequency": "ANNUALLY",
    }


def test_list_profiles_api_maps_snake_protojson_salary_values(mocker: MockerFixture) -> None:
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    profile = {
        "id": str(pref_id),
        "user_id": str(user_id),
        "pref_name": "Salary profile",
        "search_keywords": ["python"],
        "disallowed_keywords": [],
        "work_arrangements": ["REMOTE"],
        "notification_threshold": 0.7,
        "auto_tailor_threshold": 0.8,
        "open_to_relocation": False,
        "salary_preference": {
            "min_salary": {"minor_units": 8_000_000, "currency": CurrencyCode.USD},
            "target_salary": {"minor_units": 12_500_000, "currency": CurrencyCode.EUR},
            "preferred_frequency": PaymentFrequency.ANNUALLY,
        },
        "commute_preferences": {
            "acceptable_modes": ["TRANSIT_MODE_PUBLIC_TRANSIT", "TRANSIT_MODE_CYCLING"],
            "max_commute_minutes": 45,
            "ideal_commute_minutes": 25,
        },
    }
    mock_service = mocker.Mock()
    mock_service.list_profiles = mocker.AsyncMock(return_value=([profile], 1))
    client = _build_profiles_client(mock_service, user_id)

    response = client.get("/api/v1/profiles")

    assert response.status_code == 200
    assert response.json()["items"][0]["salary_preference"] == {
        "min_salary": {"minor_units": 8_000_000, "currency": "USD"},
        "target_salary": {"minor_units": 12_500_000, "currency": "EUR"},
        "preferred_frequency": "ANNUALLY",
    }


@pytest.mark.asyncio
async def test_get_profile_raises_404_when_not_found(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import get_profile

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_service = mocker.Mock()
    mock_service.get_profile = mocker.AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as exc_info:
        await get_profile(pref_id, user_id, mock_db, mock_service)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_update_profile_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import ProfileUpdate, update_profile

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.update_profile_command = mocker.AsyncMock(return_value=request_id)

    data = ProfileUpdate(pref_name="Updated Name", notification_threshold=0.8)

    result = await update_profile(pref_id, data, user_id, mock_service)

    assert result.request_id == request_id
    mock_service.update_profile_command.assert_awaited_once()
    call_args = mock_service.update_profile_command.call_args
    assert call_args[0][0] == user_id
    assert call_args[0][1] == pref_id


def test_patch_profile_rejects_empty_work_arrangements(mocker: MockerFixture) -> None:
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_service = mocker.Mock()
    mock_service.update_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    client = _build_profiles_client(mock_service, user_id)

    response = client.patch(f"/api/v1/profiles/{pref_id}", json={"work_arrangements": []})

    assert response.status_code == 422
    mock_service.update_profile_command.assert_not_awaited()


def test_patch_profile_drops_explicit_null_work_arrangements(mocker: MockerFixture) -> None:
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.update_profile_command = mocker.AsyncMock(return_value=request_id)
    client = _build_profiles_client(mock_service, user_id)

    response = client.patch(f"/api/v1/profiles/{pref_id}", json={"work_arrangements": None})

    assert response.status_code == 202
    assert response.json()["request_id"] == request_id
    mock_service.update_profile_command.assert_awaited_once()
    assert mock_service.update_profile_command.call_args.args == (user_id, pref_id, {})


@pytest.mark.parametrize("method", ["post", "patch"])
def test_profile_writes_reject_malformed_skill_ids(method: str, mocker: MockerFixture) -> None:
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_service = mocker.Mock()
    mock_service.create_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    mock_service.update_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    client = _build_profiles_client(mock_service, user_id)
    path = "/api/v1/profiles" if method == "post" else f"/api/v1/profiles/{pref_id}"
    payload = {"pref_name": "Profile", "user_skills": ["not-a-uuid"]}

    response = getattr(client, method)(path, json=payload)

    assert response.status_code == 422
    mock_service.create_profile_command.assert_not_awaited()
    mock_service.update_profile_command.assert_not_awaited()


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("user_skills", 100),
        ("work_arrangements", 5),
        ("seniority_levels", 10),
    ],
)
@pytest.mark.parametrize(
    ("extra_items", "expected_status"),
    [(0, 202), (1, 422)],
    ids=["exact_maximum", "maximum_plus_one"],
)
def test_profile_write_array_boundaries(
    method: str,
    field: str,
    limit: int,
    extra_items: int,
    expected_status: int,
    mocker: MockerFixture,
) -> None:
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_service = mocker.Mock()
    mock_service.create_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    mock_service.update_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    client = _build_profiles_client(mock_service, user_id)
    path = "/api/v1/profiles" if method == "post" else f"/api/v1/profiles/{pref_id}"
    payload: dict[str, object] = _valid_profile_create_payload() if method == "post" else {}
    size = limit + extra_items

    if field == "user_skills":
        payload[field] = [str(uuid.uuid4()) for _ in range(size)]
    elif field == "work_arrangements":
        payload[field] = ["HYBRID"] * size
    else:
        experience_preference: dict[str, object] = {"experience_years": 5}
        experience_preference[field] = ["MID"] * size
        payload["experience_preference"] = experience_preference

    response = getattr(client, method)(path, json=payload)

    assert response.status_code == expected_status
    command = mock_service.create_profile_command if method == "post" else mock_service.update_profile_command
    if extra_items:
        command.assert_not_awaited()
    else:
        command.assert_awaited_once()


@pytest.mark.parametrize("method", ["post", "patch"])
@pytest.mark.parametrize(
    ("field", "terms"),
    [
        ("search_keywords", []),
        ("search_keywords", [" "]),
        ("search_keywords", ["a"]),
        ("search_keywords", ["x" * 101]),
        ("search_keywords", [f"term-{index}" for index in range(21)]),
        ("search_keywords", ["python", " python "]),
        ("disallowed_keywords", [" "]),
        ("disallowed_keywords", ["a"]),
        ("disallowed_keywords", ["x" * 101]),
        ("disallowed_keywords", [f"term-{index}" for index in range(21)]),
        ("disallowed_keywords", ["java", " java "]),
    ],
)
def test_profile_keyword_boundaries_reject_invalid_terms(
    method: str, field: str, terms: list[str], mocker: MockerFixture
) -> None:
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_service = mocker.Mock()
    mock_service.create_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    mock_service.update_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    client = _build_profiles_client(mock_service, user_id)
    path = "/api/v1/profiles" if method == "post" else f"/api/v1/profiles/{pref_id}"
    payload = _valid_profile_create_payload() if method == "post" else {}
    payload[field] = terms

    response = getattr(client, method)(path, json=payload)

    assert response.status_code == 422
    mock_service.create_profile_command.assert_not_awaited()
    mock_service.update_profile_command.assert_not_awaited()


@pytest.mark.parametrize("method", ["post", "patch"])
def test_profile_keyword_boundaries_trim_terms_and_allow_empty_disallowed(method: str, mocker: MockerFixture) -> None:
    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_service = mocker.Mock()
    mock_service.create_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    mock_service.update_profile_command = mocker.AsyncMock(return_value=str(uuid.uuid4()))
    client = _build_profiles_client(mock_service, user_id)
    path = "/api/v1/profiles" if method == "post" else f"/api/v1/profiles/{pref_id}"
    payload = _valid_profile_create_payload() if method == "post" else {}
    payload.update(search_keywords=["  python  ", "go"], disallowed_keywords=[])

    response = getattr(client, method)(path, json=payload)

    assert response.status_code == 202
    command = mock_service.create_profile_command if method == "post" else mock_service.update_profile_command
    command.assert_awaited_once()
    data = command.call_args.args[-1]
    assert data["search_keywords"] == ["python", "go"]
    assert data["disallowed_keywords"] == []


@pytest.mark.asyncio
async def test_delete_profile_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import delete_profile

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.delete_profile_command = mocker.AsyncMock(return_value=request_id)

    result = await delete_profile(pref_id, user_id, mock_service)

    assert result.request_id == request_id
    mock_service.delete_profile_command.assert_awaited_once_with(user_id, pref_id)


@pytest.mark.asyncio
async def test_associate_attachment_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import associate_attachment

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.associate_attachment_command = mocker.AsyncMock(return_value=request_id)

    result = await associate_attachment(pref_id, upload_id, user_id, mock_service)

    assert result.request_id == request_id
    mock_service.associate_attachment_command.assert_awaited_once_with(user_id, pref_id, upload_id)


@pytest.mark.asyncio
async def test_disassociate_attachment_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import disassociate_attachment

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    upload_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.disassociate_attachment_command = mocker.AsyncMock(return_value=request_id)

    result = await disassociate_attachment(pref_id, upload_id, user_id, mock_service)

    assert result.request_id == request_id
    mock_service.disassociate_attachment_command.assert_awaited_once_with(user_id, pref_id, upload_id)


def test_get_profile_service_returns_instance() -> None:
    from bff_service.api.routers.profiles import get_profile_service

    service = get_profile_service()

    assert service is not None


@pytest.mark.asyncio
async def test_set_default_feature_importance_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import (
        FeatureImportanceRequest,
        set_default_feature_importance,
    )

    user_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.set_default_feature_importance_command = mocker.AsyncMock(return_value=request_id)

    data = FeatureImportanceRequest(
        skill_match_importance=80,
        location_importance=60,
        work_arrangement_importance=70,
    )

    result = await set_default_feature_importance(data, user_id, mock_service)

    assert result.request_id == request_id
    assert result.status == "accepted"
    mock_service.set_default_feature_importance_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_default_feature_importance_with_all_fields(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import (
        FeatureImportanceRequest,
        set_default_feature_importance,
    )

    user_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.set_default_feature_importance_command = mocker.AsyncMock(return_value=request_id)

    data = FeatureImportanceRequest(
        skill_match_importance=100,
        location_importance=90,
        work_arrangement_importance=80,
        experience_importance=70,
        salary_importance=60,
        recency_importance=50,
    )

    result = await set_default_feature_importance(data, user_id, mock_service)

    assert result.request_id == request_id
    mock_service.set_default_feature_importance_command.assert_awaited_once()
    call_args = mock_service.set_default_feature_importance_command.call_args
    assert call_args[1]["user_id"] == user_id


@pytest.mark.asyncio
async def test_set_pref_feature_importance_publishes_command(mocker: MockerFixture) -> None:
    from bff_service.api.routers.profiles import (
        FeatureImportanceRequest,
        set_pref_feature_importance,
    )

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    request_id = str(uuid.uuid4())
    mock_service = mocker.Mock()
    mock_service.set_pref_feature_importance_command = mocker.AsyncMock(return_value=request_id)

    data = FeatureImportanceRequest(
        location_importance=100,
    )

    result = await set_pref_feature_importance(pref_id, data, user_id, mock_service)

    assert result.request_id == request_id
    assert result.status == "accepted"
    mock_service.set_pref_feature_importance_command.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_resolved_feature_importance_returns_search_pref_source(
    mocker: MockerFixture,
) -> None:
    from bff_service.api.routers.profiles import get_resolved_feature_importance

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_service = mocker.Mock()
    mock_service.get_resolved_importance = mocker.AsyncMock(
        return_value={
            "skill_match_importance": 80,
            "location_importance": 60,
            "work_arrangement_importance": 70,
            "experience_importance": 50,
            "salary_importance": 40,
            "recency_importance": 30,
            "source": "search_pref",
        }
    )

    result = await get_resolved_feature_importance(pref_id, user_id, mock_db, mock_service)

    assert result.skill_match_importance == 80
    assert result.location_importance == 60
    assert result.source == "search_pref"
    mock_service.get_resolved_importance.assert_awaited_once_with(mock_db, user_id, pref_id)


@pytest.mark.asyncio
async def test_get_resolved_feature_importance_returns_user_settings_source(
    mocker: MockerFixture,
) -> None:
    from bff_service.api.routers.profiles import get_resolved_feature_importance

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_service = mocker.Mock()
    mock_service.get_resolved_importance = mocker.AsyncMock(
        return_value={
            "skill_match_importance": 70,
            "location_importance": 50,
            "work_arrangement_importance": 60,
            "experience_importance": 55,
            "salary_importance": 45,
            "recency_importance": 35,
            "source": "user_settings",
        }
    )

    result = await get_resolved_feature_importance(pref_id, user_id, mock_db, mock_service)

    assert result.source == "user_settings"


@pytest.mark.asyncio
async def test_get_resolved_feature_importance_returns_system_defaults_source(
    mocker: MockerFixture,
) -> None:
    from bff_service.api.routers.profiles import get_resolved_feature_importance

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_service = mocker.Mock()
    mock_service.get_resolved_importance = mocker.AsyncMock(
        return_value={
            "skill_match_importance": 50,
            "location_importance": 50,
            "work_arrangement_importance": 50,
            "experience_importance": 50,
            "salary_importance": 50,
            "recency_importance": 50,
            "source": "system_defaults",
        }
    )

    result = await get_resolved_feature_importance(pref_id, user_id, mock_db, mock_service)

    assert result.source == "system_defaults"
    assert result.skill_match_importance == 50


def test_get_profile_rejects_revoked_auth_before_handler(mocker: MockerFixture) -> None:
    from bff_service.api.deps.auth import get_current_user_id_from_cookie
    from bff_service.api.routers.profiles import get_async_db, get_profile_service, router

    async def reject_revoked_token() -> None:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")

    service = mocker.Mock()
    service.get_profile = mocker.AsyncMock()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/profiles")
    app.dependency_overrides[get_current_user_id_from_cookie] = reject_revoked_token
    app.dependency_overrides[get_profile_service] = lambda: service
    app.dependency_overrides[get_async_db] = create_mock_session

    response = TestClient(app, raise_server_exceptions=False).get(f"/api/v1/profiles/{uuid.uuid4()}")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or expired access token"}
    service.get_profile.assert_not_awaited()
