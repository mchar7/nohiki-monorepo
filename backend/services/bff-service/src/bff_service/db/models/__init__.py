"""BFF database models: domain-grouped projection tables.

Re-exports all models so existing imports like
``from bff_service.db.models import AccountProjection`` keep working.
"""

from bff_service.db.models.auth_revocation import RevokedAccessToken, RevokedSessionFamily, UserRevocationCutoff
from bff_service.db.models.base import Base
from bff_service.db.models.command_tracking import CommandRequest
from bff_service.db.models.doc_projections import (
    DocumentGenerationStatus,
    SchemaFamilyProjection,
    SchemaVersionProjection,
    TemplateProjection,
)
from bff_service.db.models.job_projections import JobCorrelationProjection, JobListingProjection
from bff_service.db.models.skill_projections import SkillProjection
from bff_service.db.models.user_projections import (
    AccountProjection,
    AttachmentProjection,
    ProfileProjection,
    UserPrefSettingsProjection,
)

__all__ = [
    "AccountProjection",
    "AttachmentProjection",
    "Base",
    "CommandRequest",
    "DocumentGenerationStatus",
    "JobCorrelationProjection",
    "JobListingProjection",
    "ProfileProjection",
    "RevokedAccessToken",
    "RevokedSessionFamily",
    "SchemaFamilyProjection",
    "SchemaVersionProjection",
    "SkillProjection",
    "TemplateProjection",
    "UserPrefSettingsProjection",
    "UserRevocationCutoff",
]
