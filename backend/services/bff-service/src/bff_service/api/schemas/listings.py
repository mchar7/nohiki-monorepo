"""Listings API response schemas."""

from pydantic import BaseModel


class JobListingResponse(BaseModel):
    """Response for a single job listing."""

    id: str
    listing_url: str
    source: str
    title: str
    company_name: str
    description: str
    location_raw: str
    work_arrangement: str | None
    seniority_level: str | None
    language: str | None
    required_skills: list[str]
    posted_at: str | None
    discovered_at: str
    created_at: str
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    salary_frequency: str | None = None
    company_logo_url: str | None = None
    experience_years_min: int | None = None
    experience_years_max: int | None = None
