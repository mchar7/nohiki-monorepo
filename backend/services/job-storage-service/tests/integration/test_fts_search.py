"""Integration tests for full-text search."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from job_storage_service.db.models import Listing
from job_storage_service.services.bank_service import JobStoreService
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.requires_docker


@pytest.fixture
def job_store_service() -> JobStoreService:
    """Create job store service."""
    return JobStoreService()


@pytest.fixture
async def sample_jobs(async_session: AsyncSession, setup_database_schema: None) -> list[Listing]:
    """Create sample jobs for FTS testing."""
    _ = setup_database_schema  # Ensure schema is set up before creating jobs
    from nohiki.common.v1 import JobBoardSource

    location = {"city": "San Francisco", "state_province": "CA"}
    jobs_data = [
        {
            "listing_url": f"https://example.com/job/{uuid4()}",
            "job_board_source": JobBoardSource.COMPANY_WEBSITE,
            "title": "Senior Python Developer",
            "company_name": "Tech Corp",
            "description": (
                "Looking for experienced Python developer with FastAPI and "
                "PostgreSQL skills. Must have 5+ years experience working on "
                "high-throughput backend systems and event-driven services. "
                "Strong async/await fluency and a track record of shipping "
                "production-grade Python required."
            ),
            "required_skills": ["python", "fastapi", "postgresql", "docker"],
            "language": "en",
            "location": location,
            "raw_content_hash": uuid4().hex,
            "dedup_hash": uuid4().hex,
            "discovered_at": datetime.now(UTC),
        },
        {
            "listing_url": f"https://example.com/job/{uuid4()}",
            "job_board_source": JobBoardSource.COMPANY_WEBSITE,
            "title": "Full Stack JavaScript Engineer",
            "company_name": "Web Inc",
            "description": (
                "Join our team building modern web applications with React and "
                "Node.js. We ship a high-traffic SaaS dashboard and need someone "
                "comfortable across the stack: TypeScript on the frontend, "
                "Node services on the backend, and a Postgres + Redis data layer. "
                "Strong product sense and code review hygiene expected."
            ),
            "required_skills": ["javascript", "react", "nodejs", "typescript"],
            "language": "en",
            "location": location,
            "raw_content_hash": uuid4().hex,
            "dedup_hash": uuid4().hex,
            "discovered_at": datetime.now(UTC),
        },
        {
            "listing_url": f"https://example.com/job/{uuid4()}",
            "job_board_source": JobBoardSource.COMPANY_WEBSITE,
            "title": "Data Engineer",
            "company_name": "Data Systems",
            "description": (
                "Building data pipelines with Python, Spark, and PostgreSQL. "
                "ETL experience required, plus comfort with Airflow DAG authoring "
                "and operating production batch jobs. Bonus points for dbt, "
                "warehouse modeling, and a track record of shipping reliable "
                "data products in collaboration with analytics teams."
            ),
            "required_skills": ["python", "spark", "postgresql", "airflow"],
            "language": "en",
            "location": location,
            "raw_content_hash": uuid4().hex,
            "dedup_hash": uuid4().hex,
            "discovered_at": datetime.now(UTC),
        },
    ]

    jobs = []
    for data in jobs_data:
        job = Listing(**data)
        async_session.add(job)
        jobs.append(job)

    await async_session.commit()

    for job in jobs:
        await async_session.refresh(job)

    return jobs


@pytest.mark.integration
class TestFTSSearch:
    """Test full-text search functionality."""

    @pytest.mark.asyncio
    async def test_search_vector_populated(
        self,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Verify search_vector generated column is populated."""
        _ = sample_jobs  # Ensure fixture runs
        result = await async_session.execute(
            text("""
                SELECT id, search_vector IS NOT NULL AS has_vector
                FROM job_storage_schema.listings
                WHERE job_board_source = 'COMPANY_WEBSITE'
            """)
        )

        rows = result.fetchall()
        assert len(rows) == 3
        assert all(row.has_vector for row in rows)

    @pytest.mark.asyncio
    async def test_fts_search_python(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test FTS search for 'python' keyword."""
        _ = sample_jobs
        results = await job_store_service.search_jobs_fts(async_session, "python")

        assert len(results) == 2
        titles = {job.title for job in results}
        assert "Senior Python Developer" in titles
        assert "Data Engineer" in titles

    @pytest.mark.asyncio
    async def test_fts_search_javascript(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test FTS search for 'javascript' keyword."""
        _ = sample_jobs
        results = await job_store_service.search_jobs_fts(async_session, "javascript")

        assert len(results) == 1
        assert results[0].title == "Full Stack JavaScript Engineer"

    @pytest.mark.asyncio
    async def test_fts_search_multiple_keywords(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test FTS search with multiple keywords."""
        _ = sample_jobs
        results = await job_store_service.search_jobs_fts(async_session, "python postgresql")

        assert len(results) >= 1
        # Both "Senior Python Developer" and "Data Engineer" correlation python+postgresql
        titles = {job.title for job in results}
        assert "Senior Python Developer" in titles or "Data Engineer" in titles

    @pytest.mark.asyncio
    async def test_fts_search_no_results(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test FTS search with no matching results."""
        _ = sample_jobs
        results = await job_store_service.search_jobs_fts(async_session, "cobol mainframe")

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_fts_ranking(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test that FTS results are ranked by relevance."""
        _ = sample_jobs
        results = await job_store_service.search_jobs_fts(async_session, "python developer")

        assert results[0].title == "Senior Python Developer"

    @pytest.mark.asyncio
    async def test_gin_index_skills_search(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test skills search using GIN index."""
        _ = sample_jobs
        results = await job_store_service.search_jobs_by_skills(async_session, ["python"])

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_gin_index_skills_search_all(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test skills search with match_all=True."""
        _ = sample_jobs
        results = await job_store_service.search_jobs_by_skills(
            async_session,
            ["python", "postgresql"],
            match_all=True,
        )

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_recent_jobs_brin_index(
        self,
        job_store_service: JobStoreService,
        async_session: AsyncSession,
        sample_jobs: list[Listing],
    ) -> None:
        """Test recent jobs query using BRIN index."""
        _ = sample_jobs
        results = await job_store_service.get_recent_jobs(async_session, hours=1)

        assert len(results) == 3


@pytest.mark.integration
class TestIndexUsage:
    """Test that queries use appropriate indexes."""

    @pytest.mark.asyncio
    async def test_gin_index_exists(
        self,
        async_session: AsyncSession,
        setup_database_schema: None,
    ) -> None:
        """Verify GIN index exists on search_vector column."""
        _ = setup_database_schema
        result = await async_session.execute(
            text("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'job_storage_schema'
                AND tablename = 'listings'
                AND indexname LIKE '%search_vector%'
            """)
        )

        indexes = result.fetchall()
        assert len(indexes) > 0
        # Verify it's a GIN index
        assert any("gin" in idx.indexdef.lower() for idx in indexes)

    @pytest.mark.asyncio
    async def test_brin_index_on_discovered_at(
        self,
        async_session: AsyncSession,
    ) -> None:
        """Verify BRIN index exists on discovered_at column."""
        result = await async_session.execute(
            text("""
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'job_storage_schema'
                AND tablename = 'listings'
                AND indexname LIKE '%brin%'
            """)
        )

        indexes = result.fetchall()
        assert len(indexes) > 0
        index_names = [idx.indexname for idx in indexes]
        assert any("discovered" in name for name in index_names)
