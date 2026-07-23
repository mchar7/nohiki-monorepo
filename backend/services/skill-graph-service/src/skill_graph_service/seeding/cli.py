"""CLI entrypoint for skill graph seeding.

Reads configuration from environment variables, seeds the skill graph using
the service's own models and seeding logic, and publishes SkillGraphSeeded
when complete. Designed to be run as a Kubernetes Job using the service's
container image.

Usage:
    python -m skill_graph_service.seeding.cli
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Final

from nohiki.skill.v1 import SkillGraphSeeded
from nohiki_db_utils import create_event_metadata, get_async_engine
from nohiki_kafka_client import KafkaClientConfig, KafkaProducer, Topics
from nohiki_observability import get_logger
from sqlalchemy import text

from skill_graph_service.core.config import get_settings
from skill_graph_service.seeding import SkillGraphSeeder, TabiyaDataSource

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine
logger = get_logger(__name__)

_ENV_TABIYA_SKILLS_CSV: Final[str] = "TABIYA_SKILLS_CSV"
_ENV_TABIYA_RELATIONSHIPS_CSV: Final[str] = "TABIYA_RELATIONSHIPS_CSV"
_ENV_TABIYA_OCCUPATION_CSV: Final[str] = "TABIYA_OCCUPATION_SKILLS_CSV"
_ENV_TABIYA_OCCUPATIONS_CSV: Final[str] = "TABIYA_OCCUPATIONS_CSV"
_ENV_TABIYA_SKILL_GROUPS_CSV: Final[str] = "TABIYA_SKILL_GROUPS_CSV"
_ENV_TABIYA_SKILLS_HIERARCHY_CSV: Final[str] = "TABIYA_SKILLS_HIERARCHY_CSV"
_ENV_TABIYA_VERSION: Final[str] = "TABIYA_SOURCE_VERSION"

_SERVICE_NAME: Final[str] = "bootstrap-skill-graph"


def _require_env(name: str) -> str:
    """Read a required environment variable, exiting on absence.

    Args:
        name: Environment variable name.

    Returns:
        Non-empty value of the variable.

    """
    value = os.environ.get(name, "").strip()
    if not value:
        logger.error("Required environment variable not set", var=name)
        sys.exit(1)
    return value


def _resolve_optional_csv(env_name: str) -> Path | None:
    """Resolve an optional CSV path from an environment variable.

    Logs an info message and returns None when the variable is unset or the
    file does not exist, allowing graceful degradation for optional data files.

    Args:
        env_name: Environment variable name holding the path.

    Returns:
        Resolved Path when the file exists, None otherwise.

    """
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        logger.info("Optional CSV env var not set - feature disabled", env_var=env_name)
        return None
    path = Path(raw)
    if not path.is_file():
        logger.info(
            "Optional CSV file not found -- feature disabled",
            env_var=env_name,
            path=str(path),
        )
        return None
    return path


def _validate_csv_paths(paths: dict[str, Path]) -> None:
    """Validate all required CSV paths exist and are readable, exiting on failure.

    Args:
        paths: Mapping of env var name to resolved Path for error reporting.

    """
    for env_var, path in paths.items():
        if not path.is_file():
            logger.error("CSV file not found", env_var=env_var, path=str(path))
            sys.exit(1)


async def _publish_seeded_event(
    bootstrap_servers: str,
    source_version: str,
    skills_seeded: int,
    aliases_seeded: int,
    occupations_seeded: int,
) -> None:
    """Publish SkillGraphSeeded to trigger batch embedding in skill-graph-service.

    Args:
        bootstrap_servers: Kafka bootstrap servers.
        source_version: ESCO data version that was seeded (e.g. "1.2.0").
        skills_seeded: Total canonical skills upserted across all sources.
        aliases_seeded: Total aliases upserted across all sources.
        occupations_seeded: Total occupations upserted across all sources.

    """
    config = KafkaClientConfig(
        bootstrap_servers=bootstrap_servers,
        client_id=_SERVICE_NAME,
    )
    event = SkillGraphSeeded(
        metadata=create_event_metadata(source_service=_SERVICE_NAME),
        source_version=source_version,
        skills_seeded=skills_seeded,
        aliases_seeded=aliases_seeded,
        occupations_seeded=occupations_seeded,
    )
    async with KafkaProducer(config) as producer:
        await producer.publish(Topics.SKILL_GRAPH_SEEDED, event, key=source_version)
    logger.info(
        "Published SkillGraphSeeded event",
        source_version=source_version,
        skills_seeded=skills_seeded,
        aliases_seeded=aliases_seeded,
        occupations_seeded=occupations_seeded,
    )


async def _wait_for_schema(engine: AsyncEngine, schema: str, *, max_wait: float = 300.0) -> None:
    """Block until the service schema has been initialized by Alembic.

    Polls for the ``alembic_version`` table in the target schema so the
    seeding job can run safely in parallel with service startup. Raises
    ``RuntimeError`` if the schema is not ready within *max_wait* seconds.

    Args:
        engine: Async SQLAlchemy engine.
        schema: PostgreSQL schema name to check.
        max_wait: Maximum seconds to wait.

    """
    deadline = time.monotonic() + max_wait
    while True:
        try:
            async with engine.connect() as conn:
                row = await conn.execute(
                    text(f"SELECT 1 FROM {schema}.alembic_version LIMIT 1"),  # noqa: S608
                )
                if row.scalar():
                    logger.info("Schema ready", schema=schema)
                    return
        except Exception:  # noqa: BLE001
            logger.debug("Schema not yet available", schema=schema)
        now = time.monotonic()
        if now > deadline:
            msg = f"Schema {schema} not ready after {max_wait}s"
            raise RuntimeError(msg)
        logger.debug("Waiting for schema", schema=schema)
        await asyncio.sleep(min(3, max(0.0, deadline - now)))


async def _check_already_seeded(
    engine: AsyncEngine,
    schema: str,
    *,
    source_version: str | None = None,
) -> bool:
    """Return whether a completed Tabiya seed batch already exists.

    Skill rows alone do not prove that aliases, relationships, and occupations
    finished loading. Failed or interrupted batches must be rerun.
    """
    version_clause = " AND source_version = :source_version" if source_version is not None else ""
    stmt = text(
        f"SELECT COUNT(*) FROM {schema}.seed_batch_record "  # noqa: S608
        f"WHERE source_name = 'tabiya' AND status = 'completed'{version_clause}"
    )
    async with engine.connect() as conn:
        row = await conn.execute(stmt, {"source_version": source_version} if source_version is not None else {})
        count = row.scalar() or 0
    if count > 0:
        logger.info("Skill graph source version already seeded", source_version=source_version)
        return True
    return False


async def _count_seeded(engine: AsyncEngine, schema: str) -> tuple[int, int, int]:
    """Count existing skills, aliases, and occupations.

    Used when seeding is skipped to populate the SkillGraphSeeded event.

    Args:
        engine: Async SQLAlchemy engine.
        schema: PostgreSQL schema name.

    Returns:
        Tuple of (skills, aliases, occupations) counts.

    """
    async with engine.connect() as conn:
        skills = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.skill_node"))).scalar() or 0  # noqa: S608
        aliases = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.skill_alias"))).scalar() or 0  # noqa: S608
        occupations = (await conn.execute(text(f"SELECT COUNT(*) FROM {schema}.occupation_node"))).scalar() or 0  # noqa: S608
    return skills, aliases, occupations


async def _run() -> None:
    """Orchestrate seeding from all configured sources.

    Waits for the database schema to be initialized (Alembic migration
    run by skill-graph-service during startup), checks whether seeding
    has already been completed (idempotent on restart), then seeds from
    all configured Tabiya CSV sources and publishes SkillGraphSeeded.
    """
    settings = get_settings()
    tabiya_version = _require_env(_ENV_TABIYA_VERSION)

    skills_csv = Path(_require_env(_ENV_TABIYA_SKILLS_CSV))
    _validate_csv_paths({_ENV_TABIYA_SKILLS_CSV: skills_csv})

    tabiya = TabiyaDataSource(
        skills_csv_path=skills_csv,
        skill_relations_csv_path=_resolve_optional_csv(_ENV_TABIYA_RELATIONSHIPS_CSV),
        occupation_skills_csv_path=_resolve_optional_csv(_ENV_TABIYA_OCCUPATION_CSV),
        occupations_csv_path=_resolve_optional_csv(_ENV_TABIYA_OCCUPATIONS_CSV),
        skill_groups_csv_path=_resolve_optional_csv(_ENV_TABIYA_SKILL_GROUPS_CSV),
        skills_hierarchy_csv_path=_resolve_optional_csv(_ENV_TABIYA_SKILLS_HIERARCHY_CSV),
        source_version=tabiya_version,
    )

    engine = get_async_engine(settings.database)
    try:
        schema = settings.database.schema_name
        await _wait_for_schema(engine, schema)

        already_seeded = await _check_already_seeded(engine, schema, source_version=tabiya_version)

        if already_seeded:
            # DB has skills but Qdrant may be empty (e.g., volume wipe).
            # Always publish the seeded event so skill-graph-service
            # triggers embedding generation on startup.
            total_skills, total_aliases, total_occupations = await _count_seeded(engine, schema)
        else:
            results = await SkillGraphSeeder(sources=[tabiya], engine=engine).seed()

            total_skills = sum(r.stats.skills_added for r in results)
            total_aliases = sum(r.stats.aliases_added for r in results)
            total_occupations = sum(r.stats.occupations_added for r in results)

            for result in results:
                logger.info(
                    "Source seeding complete",
                    source_name=result.source_name,
                    source_version=result.source_version,
                    skills_added=result.stats.skills_added,
                    aliases_added=result.stats.aliases_added,
                    occupations_added=result.stats.occupations_added,
                    error_count=result.stats.error_count,
                )

        await _publish_seeded_event(
            bootstrap_servers=settings.kafka.bootstrap_servers,
            source_version=tabiya_version,
            skills_seeded=total_skills,
            aliases_seeded=total_aliases,
            occupations_seeded=total_occupations,
        )
    except Exception:
        logger.exception("Bootstrap seeding failed")
        sys.exit(1)
    finally:
        await engine.dispose()


def main() -> None:
    """CLI entrypoint."""
    logger.info("Starting skill graph seeding CLI")
    asyncio.run(_run())
    logger.info("Skill graph seeding completed")


if __name__ == "__main__":
    main()
