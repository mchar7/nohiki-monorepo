"""Tests for JSearch Pydantic models."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from job_ingest_discovery_service.providers.jsearch.models import (
    ApplyOption,
    DatePosted,
    EmploymentType,
    JobHighlights,
    JSearchJob,
    JSearchResponse,
    SalaryPeriod,
)


class TestEnums:
    """Tests for JSearch enum types."""

    def test_date_posted_values(self) -> None:
        """Verify all DatePosted enum values."""
        assert DatePosted.ALL.value == "all"
        assert DatePosted.TODAY.value == "today"
        assert DatePosted.THREE_DAYS.value == "3days"
        assert DatePosted.WEEK.value == "week"
        assert DatePosted.MONTH.value == "month"

    def test_employment_type_values(self) -> None:
        """Verify all EmploymentType enum values."""
        assert EmploymentType.FULLTIME.value == "FULLTIME"
        assert EmploymentType.PARTTIME.value == "PARTTIME"
        assert EmploymentType.CONTRACTOR.value == "CONTRACTOR"
        assert EmploymentType.INTERN.value == "INTERN"

    def test_salary_period_values(self) -> None:
        """Verify all SalaryPeriod enum values."""
        assert SalaryPeriod.YEAR.value == "YEAR"
        assert SalaryPeriod.MONTH.value == "MONTH"
        assert SalaryPeriod.WEEK.value == "WEEK"
        assert SalaryPeriod.DAY.value == "DAY"
        assert SalaryPeriod.HOUR.value == "HOUR"


class TestJSearchJob:
    """Tests for JSearchJob model."""

    def test_minimal_job(self) -> None:
        """Test creating a job with minimal required fields."""
        job = JSearchJob(job_id="test-123")
        assert job.job_id == "test-123"
        assert job.job_title is None
        assert job.employer_name is None
        assert job.job_is_remote is None

    def test_full_job(self) -> None:
        """Test creating a job with all fields."""
        job = JSearchJob(
            job_id="test-456",
            job_title="Software Engineer",
            employer_name="Acme Corp",
            employer_website="https://acme.com",
            employer_logo="https://acme.com/logo.png",
            job_publisher="Indeed",
            job_employment_type="FULLTIME",
            job_employment_types=["FULLTIME", "CONTRACTOR"],
            job_apply_link="https://acme.com/apply",
            job_apply_is_direct=True,
            job_description="Great job opportunity",
            job_is_remote=True,
            job_location="San Francisco, CA",
            job_city="San Francisco",
            job_state="CA",
            job_country="US",
            job_min_salary=100000.0,
            job_max_salary=150000.0,
            job_salary_period=SalaryPeriod.YEAR,
            job_google_link="https://google.com/jobs/123",
        )

        assert job.job_id == "test-456"
        assert job.job_title == "Software Engineer"
        assert job.employer_name == "Acme Corp"
        assert job.job_is_remote is True
        assert job.job_min_salary == pytest.approx(100000.0)
        assert job.job_max_salary == pytest.approx(150000.0)
        assert job.job_salary_period == SalaryPeriod.YEAR

    def test_job_with_datetime(self) -> None:
        """Test job with posted datetime."""
        posted_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        job = JSearchJob(
            job_id="test-789",
            job_posted_at_datetime_utc=posted_at,
            job_posted_at_timestamp=1705320000,
        )

        assert job.job_posted_at_datetime_utc == posted_at
        assert job.job_posted_at_timestamp == 1705320000

    def test_job_with_apply_options(self) -> None:
        """Test job with apply options."""
        job = JSearchJob(
            job_id="test-apply",
            apply_options=[
                ApplyOption(
                    publisher="Indeed",
                    apply_link="https://indeed.com/apply",
                    is_direct=True,
                ),
                ApplyOption(
                    publisher="Company",
                    apply_link="https://company.com/apply",
                    is_direct=False,
                ),
            ],
        )

        assert job.apply_options is not None
        assert len(job.apply_options) == 2
        assert job.apply_options[0].is_direct is True
        assert job.apply_options[1].publisher == "Company"


class TestJSearchResponse:
    """Tests for JSearchResponse model."""

    def test_empty_response(self) -> None:
        """Test response with no jobs."""
        response = JSearchResponse(status="OK", data=[])
        assert response.status == "OK"
        assert response.data == []
        assert response.request_id is None

    def test_response_with_jobs(self) -> None:
        """Test response with job data."""
        response = JSearchResponse(
            status="OK",
            request_id="req-123",
            data=[
                JSearchJob(job_id="job-1", job_title="Engineer"),
                JSearchJob(job_id="job-2", job_title="Designer"),
            ],
        )

        assert response.status == "OK"
        assert response.request_id == "req-123"
        assert len(response.data) == 2
        assert response.data[0].job_title == "Engineer"

    def test_response_validation_from_dict(self) -> None:
        """Test model_validate from dict (simulating API response)."""
        raw_data = {
            "status": "OK",
            "request_id": "abc-123",
            "data": [
                {
                    "job_id": "google-job-1",
                    "job_title": "Senior Developer",
                    "employer_name": "Tech Corp",
                    "job_is_remote": True,
                    "job_location": "Remote",
                },
            ],
        }

        response = JSearchResponse.model_validate(raw_data)
        assert response.status == "OK"
        assert len(response.data) == 1
        assert response.data[0].job_title == "Senior Developer"
        assert response.data[0].job_is_remote is True


class TestNestedModels:
    """Tests for nested JSearch models."""

    def test_job_highlights(self) -> None:
        """Test JobHighlights model."""
        highlights = JobHighlights(
            qualifications=["Python", "AWS"],
            responsibilities=["Build systems", "Code review"],
            benefits=["Health insurance", "401k"],
        )

        assert highlights.qualifications is not None
        assert len(highlights.qualifications) == 2
        assert "Python" in highlights.qualifications
