"""Tests for BFF listings router."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException
from nohiki_db_utils.testing import create_mock_session
from pytest_mock import MockerFixture
from sqlalchemy.sql import Select


def _make_listing_projection(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "listing_url": "https://example.com/job",
        "source": "LINKEDIN",
        "title": "Software Engineer",
        "company_name": "Tech Corp",
        "description": "Build things",
        "location_raw": "Remote",
        "work_arrangement": "REMOTE",
        "seniority_level": "MID",
        "language": "en",
        "required_skills": ["python", "go"],
        "posted_at": datetime.now(UTC),
        "discovered_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "salary_frequency": None,
        "company_logo_url": None,
        "experience_years_min": None,
        "experience_years_max": None,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def _make_correlation_projection(**kwargs: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "pref_id": uuid.uuid4(),
        "listing_id": uuid.uuid4(),
        "fit_score": 85,
        "status": "evaluated",
        "score_breakdown": {},
        "fit_ranking_breakdown": {
            "method_version": "deterministic-fit-v1",
            "factors": [
                {
                    "factor": "ROLE_RELEVANCE",
                    "compatibility_score": 82.0,
                    "importance": 100,
                    "contribution_points": 82.0,
                },
                {
                    "factor": "SKILLS",
                    "compatibility_score": 94.0,
                    "importance": 75,
                    "contribution_points": 3.0,
                },
            ],
        },
        "listing_title": "Backend Developer",
        "listing_company": "Startup Inc",
        "listing_url": "https://example.com/job/123",
        "listing_location": "San Francisco",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def _make_scalar_all(items: Sequence[object]) -> SimpleNamespace:
    result = SimpleNamespace()
    result.all = lambda: items
    return result


@pytest.mark.asyncio
async def test_list_job_listings_returns_paginated_results(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import ListingFilters, list_job_listings
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    listing = _make_listing_projection()
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([listing])

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_db.execute.side_effect = [count_result, mock_result]

    result = await list_job_listings(mock_db, user_id, pagination, ListingFilters())

    assert result.total == 1
    assert len(result.items) == 1
    assert result.page == 1
    assert result.page_size == 20


@pytest.mark.asyncio
async def test_list_job_listings_filters_by_source(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import ListingFilters, list_job_listings
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    listing = _make_listing_projection(source="INDEED")
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([listing])

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_db.execute.side_effect = [count_result, mock_result]

    result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(source="INDEED"))

    assert result.total == 1
    assert result.items[0].source == "INDEED"


@pytest.mark.asyncio
async def test_list_job_listings_filters_by_company(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import ListingFilters, list_job_listings
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    listing = _make_listing_projection(company_name="Acme Corp")
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([listing])

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_db.execute.side_effect = [count_result, mock_result]

    result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(company="Acme"))

    assert result.total == 1
    assert result.items[0].company_name is not None
    assert "Acme" in result.items[0].company_name


@pytest.mark.asyncio
async def test_get_job_listing_returns_single_result(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import get_job_listing

    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    mock_db = create_mock_session()

    listing = _make_listing_projection(id=listing_id)
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    mock_db.execute.return_value = mock_result

    result = await get_job_listing(listing_id, mock_db, user_id)

    assert result.id == str(listing_id)
    assert result.title == "Software Engineer"


@pytest.mark.asyncio
async def test_get_job_listing_raises_404_when_not_found(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import get_job_listing

    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    mock_db = create_mock_session()

    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await get_job_listing(listing_id, mock_db, user_id)

    assert exc_info.value.status_code == 404


def test_correlations_mine_route_reaches_mine_handler(mocker: MockerFixture) -> None:
    from bff_service.api.deps.auth import get_current_user_id_from_cookie
    from bff_service.api.routers.listings import get_async_db, router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    auth = mocker.Mock(return_value=user_id)
    paginated = SimpleNamespace(items=[], total=0)

    def override_auth() -> uuid.UUID:
        auth()
        return user_id

    mocker.patch("bff_service.api.routers.listings.paginate_query", new=mocker.AsyncMock(return_value=paginated))

    app = FastAPI()
    app.include_router(router, prefix="/listings")
    app.dependency_overrides[get_current_user_id_from_cookie] = override_auth
    app.dependency_overrides[get_async_db] = lambda: mock_db

    response = TestClient(app).get("/listings/correlations/mine")

    assert response.status_code == 200
    assert response.json()["items"] == []
    auth.assert_called_once_with()


def test_correlation_uuid_route_still_resolves_and_requires_auth(mocker: MockerFixture) -> None:
    from bff_service.api.deps.auth import get_current_user_id_from_cookie
    from bff_service.api.routers.listings import get_async_db, router
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    mock_db = create_mock_session()
    correlation = _make_correlation_projection(id=correlation_id)
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = correlation
    mock_db.execute.return_value = mock_result

    auth = mocker.Mock(return_value=user_id)

    def override_auth() -> uuid.UUID:
        auth()
        return user_id

    app = FastAPI()
    app.include_router(router, prefix="/listings")
    app.dependency_overrides[get_current_user_id_from_cookie] = override_auth
    app.dependency_overrides[get_async_db] = lambda: mock_db

    response = TestClient(app).get(f"/listings/correlations/{correlation_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(correlation_id)
    auth.assert_called_once_with()


@pytest.mark.asyncio
async def test_list_my_correlations_returns_user_matches(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import CorrelationFilters, list_my_correlations
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    correlation = _make_correlation_projection()
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([correlation])

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_db.execute.side_effect = [count_result, mock_result]

    filters = CorrelationFilters(min_score=0)

    result = await list_my_correlations(mock_db, user_id, pagination, filters)

    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].fit_score == 85
    assert result.items[0].score_breakdown == {}
    assert result.items[0].fit_ranking_breakdown is not None
    assert result.items[0].fit_ranking_breakdown.model_dump(mode="json") == correlation.fit_ranking_breakdown


@pytest.mark.asyncio
async def test_list_my_correlations_filters_by_pref_id(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import CorrelationFilters, list_my_correlations
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    pref_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    correlation = _make_correlation_projection(pref_id=pref_id)
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([correlation])

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_db.execute.side_effect = [count_result, mock_result]

    filters = CorrelationFilters(pref_id=pref_id, min_score=0)

    result = await list_my_correlations(mock_db, user_id, pagination, filters)

    assert result.total == 1
    assert result.items[0].pref_id == str(pref_id)


@pytest.mark.asyncio
async def test_list_my_correlations_filters_by_min_score(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import CorrelationFilters, list_my_correlations
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    correlation = _make_correlation_projection(fit_score=90)
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([correlation])

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_db.execute.side_effect = [count_result, mock_result]

    filters = CorrelationFilters(min_score=80)

    result = await list_my_correlations(mock_db, user_id, pagination, filters)

    assert result.total == 1
    assert result.items[0].fit_score == 90


@pytest.mark.asyncio
async def test_get_correlation_returns_single_result(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import get_correlation

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    mock_db = create_mock_session()

    correlation = _make_correlation_projection(id=correlation_id)
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = correlation
    mock_db.execute.return_value = mock_result

    result = await get_correlation(correlation_id, mock_db, user_id)

    assert result.id == str(correlation_id)
    assert result.listing_title == "Backend Developer"
    assert result.score_breakdown == {}
    assert result.fit_ranking_breakdown is not None
    assert result.fit_ranking_breakdown.factors[0].factor.value == "ROLE_RELEVANCE"


@pytest.mark.asyncio
async def test_get_correlation_marks_missing_breakdown_unavailable(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import get_correlation

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    mock_db = create_mock_session()
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = _make_correlation_projection(
        id=correlation_id,
        score_breakdown={},
        fit_ranking_breakdown=None,
    )
    mock_db.execute.return_value = mock_result

    result = await get_correlation(correlation_id, mock_db, user_id)

    assert result.score_breakdown == {}
    assert result.fit_ranking_breakdown is None


@pytest.mark.asyncio
async def test_get_correlation_raises_404_when_not_found(mocker: MockerFixture) -> None:
    from bff_service.api.routers.listings import get_correlation

    user_id = uuid.uuid4()
    correlation_id = uuid.uuid4()
    mock_db = create_mock_session()

    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = mock_result

    with pytest.raises(HTTPException) as exc_info:
        await get_correlation(correlation_id, mock_db, user_id)

    assert exc_info.value.status_code == 404


class TestListJobListingsWithSearch:
    """Tests for list_job_listings with FTS search via `q` parameter."""

    @pytest.fixture(autouse=True)
    def mock_cache(self, mocker: MockerFixture) -> None:
        """Mock cache functions to prevent Redis access."""
        mocker.patch(
            "bff_service.api.routers.listings.get_cached_search_results",
            return_value=None,
        )
        mocker.patch(
            "bff_service.api.routers.listings.set_cached_search_results",
            return_value=None,
        )

    @pytest.mark.asyncio
    async def test_search_returns_matching_results(self, mocker: MockerFixture) -> None:
        """Test list_job_listings with q returns FTS-ranked results."""
        from bff_service.api.routers.listings import ListingFilters, list_job_listings
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=1, page_size=20)

        listing = _make_listing_projection(title="Python Developer")
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = _make_scalar_all([listing])

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 1
        mock_db.execute.side_effect = [count_result, mock_result]

        result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(q="python"))

        assert result.total == 1
        assert len(result.items) == 1
        assert result.page == 1
        assert result.page_size == 20

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_no_matches(self, mocker: MockerFixture) -> None:
        """Test list_job_listings with q returns empty when no FTS matches."""
        from bff_service.api.routers.listings import ListingFilters, list_job_listings
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=1, page_size=20)

        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = _make_scalar_all([])

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 0
        mock_db.execute.side_effect = [count_result, mock_result]

        result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(q="nonexistent"))

        assert result.total == 0
        assert len(result.items) == 0

    @pytest.mark.asyncio
    async def test_search_respects_pagination(self, mocker: MockerFixture) -> None:
        """Test list_job_listings with q respects pagination parameters."""
        from bff_service.api.routers.listings import ListingFilters, list_job_listings
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=3, page_size=10)

        listing = _make_listing_projection()
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = _make_scalar_all([listing])

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 50
        mock_db.execute.side_effect = [count_result, mock_result]

        result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(q="engineer"))

        assert result.total == 50
        assert result.page == 3
        assert result.page_size == 10

    @pytest.mark.asyncio
    async def test_search_multiple_results(self, mocker: MockerFixture) -> None:
        """Test list_job_listings with q returns multiple FTS matches."""
        from bff_service.api.routers.listings import ListingFilters, list_job_listings
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=1, page_size=20)

        listings = [
            _make_listing_projection(title="Senior Python Engineer"),
            _make_listing_projection(title="Python Developer"),
            _make_listing_projection(title="Junior Python Programmer"),
        ]
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = _make_scalar_all(listings)

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 3
        mock_db.execute.side_effect = [count_result, mock_result]

        result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(q="python"))

        assert result.total == 3
        assert len(result.items) == 3

    @pytest.mark.asyncio
    async def test_search_with_source_filter(self, mocker: MockerFixture) -> None:
        """Test list_job_listings with q and source filter combined."""
        from bff_service.api.routers.listings import ListingFilters, list_job_listings
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=1, page_size=20)

        listing = _make_listing_projection(title="Python Dev", source="LINKEDIN")
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = _make_scalar_all([listing])

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 1
        mock_db.execute.side_effect = [count_result, mock_result]

        result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(source="LINKEDIN", q="python"))

        assert result.total == 1
        assert result.items[0].source == "LINKEDIN"

    @pytest.mark.asyncio
    async def test_without_q_returns_browse_mode(self, mocker: MockerFixture) -> None:
        """Test list_job_listings without q returns chronological results."""
        from bff_service.api.routers.listings import ListingFilters, list_job_listings
        from nohiki_fastapi_utils import PaginationParams

        user_id = uuid.uuid4()
        mock_db = create_mock_session()
        pagination = PaginationParams(page=1, page_size=20)

        listing = _make_listing_projection()
        mock_result = mocker.MagicMock()
        mock_result.scalars.return_value = _make_scalar_all([listing])

        count_result = mocker.MagicMock()
        count_result.scalar.return_value = 1
        mock_db.execute.side_effect = [count_result, mock_result]

        result = await list_job_listings(mock_db, user_id, pagination, ListingFilters())

        assert result.total == 1
        assert len(result.items) == 1


@pytest.mark.asyncio
async def test_get_job_listing_includes_language(mocker: MockerFixture) -> None:
    """Job listing response includes IETF BCP 47 language tag."""
    from bff_service.api.routers.listings import get_job_listing

    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    mock_db = create_mock_session()

    listing = _make_listing_projection(id=listing_id, language="fr-CA")
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    mock_db.execute.return_value = mock_result

    result = await get_job_listing(listing_id, mock_db, user_id)

    assert result.id == str(listing_id)
    assert result.language == "fr-CA"


@pytest.mark.asyncio
async def test_get_job_listing_language_none_when_unset(mocker: MockerFixture) -> None:
    """Job listing response has None language when projection has no language."""
    from bff_service.api.routers.listings import get_job_listing

    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    mock_db = create_mock_session()

    listing = _make_listing_projection(id=listing_id, language=None)
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    mock_db.execute.return_value = mock_result

    result = await get_job_listing(listing_id, mock_db, user_id)

    assert result.language is None


@pytest.mark.asyncio
async def test_get_job_listing_includes_salary_fields(mocker: MockerFixture) -> None:
    """Job listing response includes salary fields when present."""
    from bff_service.api.routers.listings import get_job_listing

    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    mock_db = create_mock_session()

    listing = _make_listing_projection(
        id=listing_id,
        salary_min=8000000,
        salary_max=12000000,
        salary_currency="USD",
        salary_frequency="ANNUALLY",
    )
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    mock_db.execute.return_value = mock_result

    result = await get_job_listing(listing_id, mock_db, user_id)

    assert result.salary_min == 8000000
    assert result.salary_max == 12000000
    assert result.salary_currency == "USD"
    assert result.salary_frequency == "ANNUALLY"


@pytest.mark.asyncio
async def test_get_job_listing_salary_none_when_unset(mocker: MockerFixture) -> None:
    """Job listing response has None salary fields when projection has no compensation."""
    from bff_service.api.routers.listings import get_job_listing

    user_id = uuid.uuid4()
    listing_id = uuid.uuid4()
    mock_db = create_mock_session()

    listing = _make_listing_projection(id=listing_id)
    mock_result = mocker.MagicMock()
    mock_result.scalar_one_or_none.return_value = listing
    mock_db.execute.return_value = mock_result

    result = await get_job_listing(listing_id, mock_db, user_id)

    assert result.salary_min is None
    assert result.salary_max is None
    assert result.salary_currency is None
    assert result.salary_frequency is None


@pytest.mark.asyncio
async def test_list_job_listings_has_salary_filter(mocker: MockerFixture) -> None:
    """list_job_listings with has_salary=True filters to listings with salary data."""
    from bff_service.api.routers.listings import ListingFilters, list_job_listings
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    mock_db = create_mock_session()
    pagination = PaginationParams(page=1, page_size=20)

    listing = _make_listing_projection(salary_min=5000000)
    mock_result = mocker.MagicMock()
    mock_result.scalars.return_value = _make_scalar_all([listing])

    count_result = mocker.MagicMock()
    count_result.scalar.return_value = 1
    mock_db.execute.side_effect = [count_result, mock_result]

    result = await list_job_listings(mock_db, user_id, pagination, ListingFilters(has_salary=True))

    assert result.total == 1
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_list_job_listings_filters_and_sorts_before_pagination(mocker: MockerFixture) -> None:
    """Salary/dismissed predicates and match sorting reach pagination as one query."""
    from bff_service.api.routers.listings import ListingFilters, list_job_listings
    from nohiki_fastapi_utils import PaginationParams

    user_id = uuid.uuid4()
    listing = _make_listing_projection(salary_min=9_000_000)
    captured: dict[str, object] = {}

    async def paginate(
        _db: object,
        query: object,
        *,
        offset: int,
        limit: int,
    ) -> SimpleNamespace:
        captured["query"] = query
        captured["offset"] = offset
        captured["limit"] = limit
        return SimpleNamespace(items=[listing], total=5)

    mocker.patch("bff_service.api.routers.listings.paginate_query", side_effect=paginate)

    result = await list_job_listings(
        create_mock_session(),
        user_id,
        PaginationParams(page=2, page_size=2),
        ListingFilters(
            has_salary=True,
            show_dismissed=False,
            sort="match_score",
            dir="desc",
        ),
    )

    query = cast(Select[tuple[object]], captured["query"])
    compiled = str(query.compile(compile_kwargs={"literal_binds": True})).upper()
    assert result.total == 5
    assert result.page == 2
    assert result.items[0].id == str(listing.id)
    assert captured["offset"] == 2
    assert captured["limit"] == 2
    assert "SALARY_MIN IS NOT NULL" in compiled
    assert "ALL_DISMISSED IS FALSE" in compiled
    assert "MATCH_SCORE DESC NULLS LAST" in compiled

    order_start = compiled.index("ORDER BY")
    assert compiled.index("CREATED_AT DESC", order_start) < compiled.index("ID ASC", order_start)


def test_user_correlation_scores_scope_to_authenticated_active_profile() -> None:
    """Correlation joins cannot leak another user's or inactive profile's scores."""
    from bff_service.api.routers.listings import _user_correlation_scores

    user_id = uuid.uuid4()
    statement = _user_correlation_scores(user_id).select()
    compiled = statement.compile()
    sql = str(compiled)

    assert sql.count("user_id") >= 2
    assert [value for value in compiled.params.values() if value == user_id].count(user_id) == 2
    assert "profile_projections.user_id" in sql
    assert "job_correlation_projections.user_id" in sql
    assert "is_active IS true" in sql
