"""Pydantic models for JSearch API responses.

Generated based on the JSearch OpenAPI specification.
These models are spec-driven - do not modify manually unless the API spec changes.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class DatePosted(StrEnum):
    """Time filter for job postings."""

    ALL = "all"
    TODAY = "today"
    THREE_DAYS = "3days"
    WEEK = "week"
    MONTH = "month"


class EmploymentType(StrEnum):
    """Employment type filter values."""

    FULLTIME = "FULLTIME"
    CONTRACTOR = "CONTRACTOR"
    PARTTIME = "PARTTIME"
    INTERN = "INTERN"


class SalaryPeriod(StrEnum):
    """Salary period values."""

    YEAR = "YEAR"
    MONTH = "MONTH"
    WEEK = "WEEK"
    DAY = "DAY"
    HOUR = "HOUR"


class ApplyOption(BaseModel):
    """Application option for a job listing."""

    model_config = ConfigDict(extra="ignore")

    publisher: str | None = None
    apply_link: str | None = None
    is_direct: bool | None = None


class JobHighlights(BaseModel):
    """Highlighted sections from job description."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    qualifications: Annotated[list[str] | None, Field(alias="Qualifications")] = None
    responsibilities: Annotated[list[str] | None, Field(alias="Responsibilities")] = None
    benefits: Annotated[list[str] | None, Field(alias="Benefits")] = None


class JSearchJob(BaseModel):
    """Job listing from JSearch API response."""

    model_config = ConfigDict(extra="ignore")

    job_id: str
    job_title: str | None = None
    employer_name: str | None = None
    employer_logo: str | None = None
    employer_website: str | None = None
    job_publisher: str | None = None
    job_employment_type: str | None = None
    job_employment_types: list[str] | None = None
    job_apply_link: str | None = None
    job_apply_is_direct: bool | None = None
    apply_options: list[ApplyOption] | None = None
    job_description: str | None = None
    job_is_remote: bool | None = None
    job_posted_at: str | None = None
    job_posted_at_timestamp: int | None = None
    job_posted_at_datetime_utc: datetime | None = None
    job_location: str | None = None
    job_city: str | None = None
    job_state: str | None = None
    job_country: str | None = None
    job_latitude: float | None = None
    job_longitude: float | None = None
    job_benefits: list[str] | None = None
    job_google_link: str | None = None
    job_salary: str | None = None
    job_min_salary: float | None = None
    job_max_salary: float | None = None
    job_salary_period: SalaryPeriod | None = None
    job_highlights: JobHighlights | None = None
    job_onet_soc: str | None = None
    job_onet_job_zone: str | None = None


class SearchParameters(BaseModel):
    """Parameters echoed back in search response."""

    model_config = ConfigDict(extra="ignore")

    query: str | None = None
    page: int | None = None
    num_pages: int | None = None
    date_posted: str | None = None
    country: str | None = None
    language: str | None = None


class JSearchResponse(BaseModel):
    """Response from JSearch /search endpoint."""

    model_config = ConfigDict(extra="ignore")

    status: str
    request_id: str | None = None
    parameters: SearchParameters | None = None
    data: list[JSearchJob] = Field(default_factory=list)
