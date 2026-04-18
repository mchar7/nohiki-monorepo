"""Services module for job-query-composition-service."""

from job_query_composition_service.services.aggregation import recompute_query_aggregates
from job_query_composition_service.services.normalization import (
    canonicalize_locations,
    extract_remote_pref,
    normalize_keywords,
)
from job_query_composition_service.services.query_service import (
    ContributorInput,
    create_or_update_contributor,
    delete_contributor,
    delete_query,
    delete_user_contributions,
    find_or_create_query,
    get_query_by_id,
    set_user_active,
    set_user_inactive,
    update_contributor_frequency,
)

__all__ = [
    "ContributorInput",
    "canonicalize_locations",
    "create_or_update_contributor",
    "delete_contributor",
    "delete_query",
    "delete_user_contributions",
    "extract_remote_pref",
    "find_or_create_query",
    "get_query_by_id",
    "normalize_keywords",
    "recompute_query_aggregates",
    "set_user_active",
    "set_user_inactive",
    "update_contributor_frequency",
]
