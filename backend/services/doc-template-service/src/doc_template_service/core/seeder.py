"""Seeder for default templates."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from nohiki_db_utils import OutboxWriter, get_async_sessionmaker
from nohiki_observability import get_logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from doc_template_service.core.auth_helpers import SYSTEM_SERVICE_UUID
from doc_template_service.core.config import get_settings
from doc_template_service.core.metadata import parse_template_metadata
from doc_template_service.events.publishers import publish_template_created_event
from doc_template_service.schemas.templates import TemplateCreateRequest
from doc_template_service.services.template_service import (
    TemplateDuplicateError,
    TemplateNotFoundError,
    create_template,
    get_latest_template,
)

_PACKAGE_PARENT = Path(__file__).parent.parent.parent
_SEED_ROOT = _PACKAGE_PARENT.parent if _PACKAGE_PARENT.name == "src" else _PACKAGE_PARENT
SEED_TEMPLATES_DIR = _SEED_ROOT / "seed_templates"
SEED_SCHEMAS_DIR = _SEED_ROOT / "seed_schemas"
SEED_TIMEOUT_SECONDS: float = 10.0

settings = get_settings()
logger = get_logger(__name__)


def should_run_seeding() -> bool:
    """Return whether template seeding should run on startup."""
    return bool(settings.template_settings.seed_on_startup)


async def seed_default_templates() -> None:
    """Seed default templates idempotently."""
    if not should_run_seeding():
        return

    if not SEED_TEMPLATES_DIR.exists():
        logger.warning("Seed templates directory not found", path=str(SEED_TEMPLATES_DIR))
        return

    template_files = list(SEED_TEMPLATES_DIR.glob("*.html"))
    if not template_files:
        return

    logger.info("Starting template seeding", count=len(template_files))
    sys.stdout.flush()

    sessionmaker = get_async_sessionmaker(settings.database)

    async with asyncio.TaskGroup() as tg:
        for lf in template_files:
            tg.create_task(_seed_template_with_session(sessionmaker, lf))

    logger.info("Template seeding complete")
    sys.stdout.flush()


async def _seed_template_with_session(sessionmaker: async_sessionmaker[AsyncSession], template_file: Path) -> None:
    """Seed a single template file with its own session."""
    async with sessionmaker() as session:
        await _seed_template(session, template_file)
        await session.commit()


async def _seed_template(session: AsyncSession, template_file: Path) -> None:
    """Seed a single template file."""
    template_content = _load_template_file(template_file)
    if template_content is None:
        return

    try:
        metadata = parse_template_metadata(template_content)
    except ValueError, KeyError, TypeError:
        logger.exception("Failed to parse template metadata", file=template_file.name)
        return

    template_name = metadata["name"]
    display_name = metadata["title"]
    namespace = metadata["namespace"]
    access_scope = metadata["access_scope"]
    audience = metadata["audience"]
    version = metadata["version"]
    content_schema = metadata.get("content_schema")
    if content_schema is None and template_name in {"resume", "cover_letter"}:
        content_schema = _load_seed_schema(template_name)
        if content_schema is None:
            return

    try:
        existing = await get_latest_template(session, namespace, template_name, SYSTEM_SERVICE_UUID)
        if existing and existing.version == version and existing.template_content == template_content:
            logger.debug("Template seed is current, skipping", name=template_name, version=version)
            return
    except TemplateNotFoundError:
        pass

    request = TemplateCreateRequest(
        namespace=namespace,
        name=template_name,
        display_name=display_name,
        version=version,
        template_content=template_content,
        description=metadata.get("description"),
        content_schema=content_schema,
        access_scope=access_scope,
        audience=audience,
    )

    try:
        template = await asyncio.wait_for(
            create_template(session, request, SYSTEM_SERVICE_UUID),
            timeout=SEED_TIMEOUT_SECONDS,
        )
        outbox = OutboxWriter(schema=settings.database.schema_name)
        await publish_template_created_event(session, outbox, template)
        logger.info("Template seeded", name=template_name)
    except IntegrityError, TemplateDuplicateError:
        await session.rollback()
        logger.debug("Template exists (race)", name=template_name)
    except TimeoutError:
        await session.rollback()
        logger.warning("Template seed timed out", name=template_name)


def _load_template_file(template_file: Path) -> str | None:
    """Load a template file."""
    try:
        with template_file.open() as f:
            return f.read()
    except OSError:
        logger.exception("Failed to load template file", file=template_file.name)
        return None


def _load_seed_schema(template_name: str) -> dict[str, object] | None:
    """Load the bundled schema paired with a document seed template."""
    schema_file = SEED_SCHEMAS_DIR / f"default_{template_name}_schema.json"
    try:
        content_schema = json.loads(schema_file.read_text())
    except OSError, json.JSONDecodeError:
        logger.exception("Failed to load seed schema", file=schema_file.name)
        return None
    if not isinstance(content_schema, dict):
        logger.error("Seed schema must be a JSON object", file=schema_file.name)
        return None
    return content_schema
