"""Projection handlers package - imports trigger handler registration."""

from bff_service.events.projections import (
    doc_content,
    doc_template,
    job_correlation,
    job_listing,
    skill,
    user_auth,
    user_pref,
    user_upload,
)

__all__ = [
    "doc_content",
    "doc_template",
    "job_correlation",
    "job_listing",
    "skill",
    "user_auth",
    "user_pref",
    "user_upload",
]
