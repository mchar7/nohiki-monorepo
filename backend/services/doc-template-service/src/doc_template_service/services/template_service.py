"""Service layer for document template management with access control.

Single-table design: Each DocumentTemplate row is a complete, immutable version.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING
from uuid import UUID

from nohiki.common.v1 import AccessScope
from nohiki_observability import get_logger
from nohiki_redis_utils import RedisCache, cached, create_cache
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from doc_template_service.core.auth_helpers import SYSTEM_SERVICE_UUID, can_access_resource
from doc_template_service.core.config import get_settings
from doc_template_service.core.semver_validation import validate_semantic_version
from doc_template_service.db.models import DocumentTemplate
from doc_template_service.schemas.templates import (
    TemplateCreateRequest,
    TemplateListQuery,
    TemplateListResponse,
    TemplateResponse,
    TemplateVersionsResponse,
)

logger = get_logger(__name__)

settings = get_settings()
cache = create_cache(settings.service_name, redis_url=settings.redis_url)


def _get_cache() -> RedisCache:
    return cache


_TEMPLATE_CACHE_TTL: int = 7200


class TemplateDuplicateError(Exception):
    """Raised when attempting to create a duplicate template."""

    def __init__(self, name: str, version: str) -> None:
        """Initialize with template name and version."""
        self.name = name
        self.version = version
        super().__init__(f"Template '{name}' version '{version}' already exists")


class TemplateNotFoundError(Exception):
    """Raised when a template is not found."""

    def __init__(self, identifier: str) -> None:
        """Initialize with template identifier."""
        self.identifier = identifier
        super().__init__(f"Template '{identifier}' not found")


class TemplateVersionError(Exception):
    """Raised for template version validation failures."""

    def __init__(self, message: str) -> None:
        """Initialize with error message."""
        self.message = message
        super().__init__(message)


def generate_etag(template: DocumentTemplate) -> str:
    """Generate ETag for template data using secure hash."""
    data = {
        "id": str(template.id),
        "name": template.name,
        "display_name": template.display_name,
        "namespace": template.namespace,
        "version": template.version,
        "created_at": str(template.created_at),
    }
    content = json.dumps(data, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


def _template_to_response(template: DocumentTemplate) -> TemplateResponse:
    """Convert SQLAlchemy model to Pydantic response."""
    return TemplateResponse(
        id=template.id,
        namespace=template.namespace,
        name=template.name,
        display_name=template.display_name,
        version=template.version,
        template_content=template.template_content,
        content_schema=template.content_schema,
        description=template.description,
        access_scope=template.access_scope,
        audience=template.audience,
        owner_id=template.owner_id,
        created_at=template.created_at,
    )


@cached(key_prefix="template_by_id", ttl=_TEMPLATE_CACHE_TTL, cache_factory=_get_cache)
async def get_template_by_id(db: AsyncSession, template_id: UUID, user_id: UUID) -> TemplateResponse:
    """Get template by ID with access control and caching."""
    stmt = select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()

    if template is None or not can_access_resource(template.access_scope, template.owner_id, user_id):
        raise TemplateNotFoundError(str(template_id))

    logger.debug("Retrieved template", template_id=template_id, name=template.name, version=template.version)
    return _template_to_response(template)


@cached(key_prefix="template_by_name_version", ttl=_TEMPLATE_CACHE_TTL, cache_factory=_get_cache)
async def get_template_by_name_version(
    db: AsyncSession,
    namespace: str,
    name: str,
    version: str,
    user_id: UUID,
) -> TemplateResponse:
    """Get a specific template by namespace, name, and version."""
    stmt = select(DocumentTemplate).where(
        and_(
            DocumentTemplate.namespace == namespace,
            DocumentTemplate.name == name,
            DocumentTemplate.version == version,
        )
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()

    if template is None or not can_access_resource(template.access_scope, template.owner_id, user_id):
        msg = f"{namespace}/{name}@{version}"
        raise TemplateNotFoundError(msg)

    return _template_to_response(template)


def _access_conditions(user_id: UUID) -> list:
    conditions = [
        DocumentTemplate.access_scope == AccessScope.PUBLIC,
        and_(DocumentTemplate.access_scope == AccessScope.PRIVATE, DocumentTemplate.owner_id == user_id),
    ]
    if user_id == SYSTEM_SERVICE_UUID:
        conditions.append(DocumentTemplate.access_scope == AccessScope.SYSTEM)
    return conditions


@cached(key_prefix="template_latest", ttl=_TEMPLATE_CACHE_TTL, cache_factory=_get_cache)
async def get_latest_template(
    db: AsyncSession,
    namespace: str,
    name: str,
    user_id: UUID,
) -> TemplateResponse:
    """Get the latest version of a template by namespace and name."""
    access_conditions = _access_conditions(user_id)

    stmt = (
        select(DocumentTemplate)
        .where(
            and_(
                DocumentTemplate.namespace == namespace,
                DocumentTemplate.name == name,
                or_(*access_conditions),
            )
        )
        .order_by(DocumentTemplate.created_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()

    if template is None:
        msg = f"{namespace}/{name}"
        raise TemplateNotFoundError(msg)

    logger.debug("Retrieved latest template", namespace=namespace, name=name, version=template.version)
    return _template_to_response(template)


async def list_templates(
    db: AsyncSession,
    filters: TemplateListQuery,
    user_id: UUID,
) -> TemplateListResponse:
    """List templates with filtering, pagination, and access control."""
    conditions: list = []
    if filters.namespace:
        conditions.append(DocumentTemplate.namespace == filters.namespace)
    if filters.name:
        conditions.append(DocumentTemplate.name.ilike(f"%{filters.name}%"))

    access_conditions = _access_conditions(user_id)
    conditions.append(or_(*access_conditions))

    filter_condition = and_(*conditions) if conditions else None

    if filters.latest_only:
        base_subq = select(
            DocumentTemplate.namespace,
            DocumentTemplate.name,
            DocumentTemplate.owner_id,
            func.max(DocumentTemplate.created_at).label("max_created"),
        )
        if filter_condition is not None:
            base_subq = base_subq.where(filter_condition)
        subq = base_subq.group_by(
            DocumentTemplate.namespace, DocumentTemplate.name, DocumentTemplate.owner_id
        ).subquery()
        stmt = select(DocumentTemplate).join(
            subq,
            and_(
                DocumentTemplate.namespace == subq.c.namespace,
                DocumentTemplate.name == subq.c.name,
                DocumentTemplate.owner_id == subq.c.owner_id,
                DocumentTemplate.created_at == subq.c.max_created,
            ),
        )
        count_stmt = select(func.count()).select_from(subq)
    else:
        stmt = (
            select(DocumentTemplate).where(filter_condition)
            if filter_condition is not None
            else select(DocumentTemplate)
        )
        count_stmt = select(func.count(DocumentTemplate.id))
        if filter_condition is not None:
            count_stmt = count_stmt.where(filter_condition)

    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    offset = (filters.page - 1) * filters.page_size
    stmt = (
        stmt.order_by(DocumentTemplate.name, DocumentTemplate.created_at.desc()).offset(offset).limit(filters.page_size)
    )

    result = await db.execute(stmt)
    templates = result.scalars().all()

    logger.debug("Listed templates", total=total, page=filters.page, latest_only=filters.latest_only)

    return TemplateListResponse(
        templates=[_template_to_response(template) for template in templates],
        total=total,
        page=filters.page,
        page_size=filters.page_size,
    )


async def list_template_versions(
    db: AsyncSession,
    namespace: str,
    name: str,
    user_id: UUID,
) -> TemplateVersionsResponse:
    """List all versions of a template."""
    access_conditions = _access_conditions(user_id)

    stmt = (
        select(DocumentTemplate)
        .where(
            and_(
                DocumentTemplate.namespace == namespace,
                DocumentTemplate.name == name,
                or_(*access_conditions),
            )
        )
        .order_by(DocumentTemplate.created_at.desc())
    )
    result = await db.execute(stmt)
    templates = list(result.scalars().all())

    if not templates:
        msg = f"{namespace}/{name}"
        raise TemplateNotFoundError(msg)

    logger.debug("Listed template versions", namespace=namespace, name=name, count=len(templates))

    return TemplateVersionsResponse(
        namespace=namespace,
        name=name,
        versions=[_template_to_response(template) for template in templates],
        total=len(templates),
    )


class SystemScopeNotAllowedError(Exception):
    """Raised when a non-seeder user attempts to create a SYSTEM template."""

    def __init__(self) -> None:
        """Initialize error."""
        super().__init__("Only the system seeder can create SYSTEM-scoped templates")


async def create_template(
    db: AsyncSession,
    request: TemplateCreateRequest,
    user_id: UUID,
    *,
    commit: bool = True,
) -> DocumentTemplate:
    """Create a new template (version).

    Strict validation:
    - SYSTEM scope is ONLY allowed for the internal seeder service
    - PRIVATE scope sets owner_id to user_id
    - PUBLIC scope has no owner_id
    """
    validate_semantic_version(request.version)

    access_scope = request.access_scope

    if access_scope == AccessScope.SYSTEM and user_id != SYSTEM_SERVICE_UUID:
        raise SystemScopeNotAllowedError

    owner_id = user_id if access_scope == AccessScope.PRIVATE else None

    try:
        template = DocumentTemplate(
            namespace=request.namespace,
            name=request.name,
            display_name=request.display_name,
            version=request.version,
            template_content=request.template_content,
            content_schema=request.content_schema or {},
            description=request.description,
            access_scope=access_scope,
            audience=request.audience,
            owner_id=owner_id,
        )
        db.add(template)
        if commit:
            await db.commit()
        else:
            await db.flush()
        await db.refresh(template)
    except IntegrityError as e:
        await db.rollback()
        if "uq_template_name_version_owner" in str(e):
            raise TemplateDuplicateError(request.name, request.version) from e
        raise
    else:
        if commit:
            await _prime_template_cache(template)

        logger.info(
            "Created template",
            template_id=template.id,
            name=template.name,
            version=template.version,
            access_scope=access_scope.name,
        )
        return template


async def delete_template(db: AsyncSession, template_id: UUID, user_id: UUID, *, commit: bool = True) -> None:
    """Delete a specific template (version), optionally within the caller's transaction."""
    stmt = select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    result = await db.execute(stmt)
    template = result.scalar_one_or_none()

    if template is None:
        raise TemplateNotFoundError(str(template_id))

    if not can_access_resource(template.access_scope, template.owner_id, user_id):
        raise TemplateNotFoundError(str(template_id))

    if template.owner_id != user_id:
        raise TemplateNotFoundError(str(template_id))

    namespace, name, version = template.namespace, template.name, template.version

    await db.execute(delete(DocumentTemplate).where(DocumentTemplate.id == template_id))
    if commit:
        await db.commit()
    else:
        await db.flush()

    await _invalidate_template_cache(template_id, namespace, name, version)
    logger.info("Deleted template", template_id=str(template_id), name=name, version=version)


async def delete_all_template_versions(
    db: AsyncSession,
    namespace: str,
    name: str,
    user_id: UUID,
) -> int:
    """Delete all versions of a template by namespace and name. Returns count deleted."""
    stmt = select(DocumentTemplate).where(
        and_(
            DocumentTemplate.namespace == namespace,
            DocumentTemplate.name == name,
            DocumentTemplate.owner_id == user_id,
        )
    )
    result = await db.execute(stmt)
    templates = list(result.scalars().all())

    if not templates:
        msg = f"{namespace}/{name}"
        raise TemplateNotFoundError(msg)

    delete_stmt = delete(DocumentTemplate).where(
        and_(
            DocumentTemplate.namespace == namespace,
            DocumentTemplate.name == name,
            DocumentTemplate.owner_id == user_id,
        )
    )
    await db.execute(delete_stmt)
    await db.commit()

    async with asyncio.TaskGroup() as tg:
        for template in templates:
            tg.create_task(_invalidate_template_cache(template.id, namespace, name, template.version))

    logger.info("Deleted all template versions", namespace=namespace, name=name, count=len(templates))
    return len(templates)


async def template_exists(db: AsyncSession, template_id: UUID) -> bool:
    """Check if a template exists by ID."""
    stmt = select(DocumentTemplate.id).where(DocumentTemplate.id == template_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def template_version_exists(
    db: AsyncSession,
    namespace: str,
    name: str,
    version: str,
) -> bool:
    """Check if a specific template version exists."""
    stmt = select(DocumentTemplate.id).where(
        and_(
            DocumentTemplate.namespace == namespace,
            DocumentTemplate.name == name,
            DocumentTemplate.version == version,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_template_model_by_id(db: AsyncSession, template_id: UUID) -> DocumentTemplate | None:
    """Get raw DocumentTemplate model by ID (for internal use / event publishing)."""
    stmt = select(DocumentTemplate).where(DocumentTemplate.id == template_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _prime_template_cache(template: DocumentTemplate) -> None:
    """Prime cache with template data."""
    response = _template_to_response(template)
    async with asyncio.TaskGroup() as tg:
        tg.create_task(cache.set(f"template_by_id:{template.id}", response, ttl=_TEMPLATE_CACHE_TTL))
        tg.create_task(
            cache.set(
                f"template_by_name_version:{template.namespace}:{template.name}:{template.version}",
                response,
                ttl=_TEMPLATE_CACHE_TTL,
            )
        )
    logger.debug("Primed template cache", template_id=str(template.id))


async def _invalidate_template_cache(template_id: UUID, namespace: str, name: str, version: str) -> None:
    """Invalidate template cache entries."""
    async with asyncio.TaskGroup() as tg:
        tg.create_task(cache.delete(f"template_by_id:{template_id}"))
        tg.create_task(cache.delete(f"template_by_name_version:{namespace}:{name}:{version}"))
        tg.create_task(cache.delete(f"template_latest:{namespace}:{name}"))
    logger.debug("Invalidated template cache", template_id=str(template_id))
