"""Shared factory helpers for BFF service unit tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from nohiki_test_utils.sample_data import SENIOR_PYTHON_REMOTE

# Database result mock helpers


def make_scalar_all(items: list[object]) -> SimpleNamespace:
    """Create a mock scalars result with an ``all()`` method."""
    result = SimpleNamespace()
    result.all = lambda: items
    return result


def make_scalar_one_or_none(item: object | None) -> MagicMock:
    """Create a mock result with ``scalar_one_or_none`` returning *item*."""
    mock = MagicMock()
    mock.scalar_one_or_none.return_value = item
    return mock


def make_scalar(value: object | None) -> MagicMock:
    """Create a mock result with ``scalar`` returning *value*."""
    mock = MagicMock()
    mock.scalar.return_value = value
    return mock


# Projection factories


def make_listing_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock listing projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "listing_url": SENIOR_PYTHON_REMOTE.listing_url,
        "source": "LINKEDIN",
        "title": SENIOR_PYTHON_REMOTE.title,
        "company_name": SENIOR_PYTHON_REMOTE.company_name,
        "description": SENIOR_PYTHON_REMOTE.description,
        "location_raw": "Remote",
        "work_arrangement": "REMOTE",
        "seniority_level": "SENIOR",
        "required_skills": list(SENIOR_PYTHON_REMOTE.required_skills),
        "posted_at": datetime.now(UTC),
        "discovered_at": datetime.now(UTC),
        "created_at": datetime.now(UTC),
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_correlation_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock correlation projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "pref_id": uuid.uuid4(),
        "listing_id": uuid.uuid4(),
        "fit_score": 85,
        "status": "evaluated",
        "score_breakdown": {"semantic": "0.9"},
        "listing_title": "Backend Developer",
        "listing_company": "Startup Inc",
        "listing_url": "https://example.com/job/123",
        "listing_location": "San Francisco",
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_profile_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock profile projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "profile_name": "Test Profile",
        "search_keywords": ["python", "remote"],
        "disallowed_keywords": [],
        "work_arrangements": ["remote"],
        "user_skills": [],
        "notification_threshold": 0.70,
        "auto_tailor_threshold": 0.8,
        "open_to_relocation": True,
        "salary_preference": None,
        "experience_preference": None,
        "created_at": None,
        "updated_at": None,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_upload_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock upload projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "filename": "file.pdf",
        "content_type": "application/pdf",
        "file_size": 123,
        "created_at": None,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_command_status_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock command status projection."""
    defaults: dict[str, object] = {
        "request_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "command_type": "create_profile",
        "status": "completed",
        "created_at": None,
        "completed_at": None,
        "error_message": None,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_skill_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock skill projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "normalized_text": "Python",
        "display_name": "Python Programming",
        "description": "A language",
        "category": "Programming",
        "job_count": 100,
        "profile_count": 50,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_template_version_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock template version projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "namespace": "default",
        "name": "test-template",
        "display_name": "Test Template",
        "version": "1.0.0",
        "template_content": "<!DOCTYPE html><html><head></head><body>{{ name }}</body></html>",
        "content_schema": None,
        "description": "Test description",
        "is_active": True,
        "created_at": datetime.now(UTC),
        "access_scope": 1,
        "owner_id": None,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_template_family_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock template family projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "namespace": "default",
        "name": "test-template",
        "display_name": "Test Template",
        "description": "Test description",
        "is_active": True,
        "latest_version_id": None,
        "updated_at": datetime.now(UTC),
        "access_scope": 1,
        "owner_id": None,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_document_status_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock document status projection."""
    defaults: dict[str, object] = {
        "request_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "template_version_id": uuid.uuid4(),
        "output_format": "pdf",
        "status": "pending",
        "storage_key": None,
        "error_message": None,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_schema_family_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock schema family projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "name": "resume-v1",
        "description": "Resume schema version 1",
        "is_active": True,
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_schema_version_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock schema version projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "schema_content": {"type": "object"},
        "version": 1,
        "created_at": datetime.now(UTC),
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)


def make_attachment_projection(**kwargs: object) -> SimpleNamespace:
    """Create a mock attachment projection."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "pref_id": uuid.uuid4(),
        "upload_id": uuid.uuid4(),
        "filename": "resume.pdf",
        "content_type": "application/pdf",
        "file_size": 1024,
        "created_at": datetime.now(UTC),
    }
    defaults |= kwargs
    return SimpleNamespace(**defaults)
