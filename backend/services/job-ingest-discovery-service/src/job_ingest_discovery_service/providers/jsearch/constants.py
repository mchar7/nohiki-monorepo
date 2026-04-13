"""Constants for JSearch provider.

Centralizes all magic values for maintainability and consistency.
"""

from __future__ import annotations

# Service identification
SERVICE_NAME = "jsearch"

# Rate limiting
RATE_LIMIT_KEY_PREFIX = "jsearch:api"
RATE_LIMIT_BUCKET_KEY = "global"  # Single bucket for all JSearch API calls

# Rate limit tier names
TIER_MONTHLY = "monthly"
TIER_HOURLY = "hourly"

# HTTP client defaults
DEFAULT_BASE_URL = "https://api.openwebninja.com/jsearch"
DEFAULT_TIMEOUT_SECONDS = 30

# API endpoints
ENDPOINT_SEARCH = "/search"
ENDPOINT_JOB_DETAILS = "/job-details"
ENDPOINT_ESTIMATED_SALARY = "/estimated-salary"

# HTTP headers
HEADER_API_KEY = "x-api-key"
HEADER_ACCEPT = "Accept"
CONTENT_TYPE_JSON = "application/json"

# Query parameter names
PARAM_QUERY = "query"
PARAM_PAGE = "page"
PARAM_NUM_PAGES = "num_pages"
PARAM_COUNTRY = "country"
PARAM_LANGUAGE = "language"
PARAM_DATE_POSTED = "date_posted"
PARAM_WORK_FROM_HOME = "work_from_home"
PARAM_EMPLOYMENT_TYPES = "employment_types"
PARAM_JOB_REQUIREMENTS = "job_requirements"
PARAM_RADIUS = "radius"
PARAM_EXCLUDE_PUBLISHERS = "exclude_job_publishers"

# Default values
DEFAULT_COUNTRY = "us"
DEFAULT_PAGE = 1
DEFAULT_NUM_PAGES = 1
