"""Behavioral checks for the initial template schema."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

_SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(sync_url: str) -> Config:
    config = Config(str(_SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    config.set_main_option("path_separator", "os")
    return config


def test_initial_migration_schema_contract(postgres_container: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline creates the enum and required presentation columns with defaults."""
    sync_url = postgres_container.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    monkeypatch.setenv("DATABASE_URL", sync_url)
    config = _alembic_config(sync_url)
    engine = sa.create_engine(sync_url)

    try:
        command.downgrade(config, "base")
        command.upgrade(config, "head")
        with engine.begin() as connection:
            enum_values = (
                connection.execute(
                    sa.text("""
                    SELECT e.enumlabel
                    FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = 'doc_template_schema'
                      AND t.typname = 'template_audience_enum'
                    ORDER BY e.enumsortorder
                """)
                )
                .scalars()
                .all()
            )
            columns = connection.execute(
                sa.text("""
                    SELECT column_name, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = 'doc_template_schema'
                      AND table_name = 'document_templates'
                      AND column_name IN ('display_name', 'audience')
                    ORDER BY column_name
                """)
            ).all()
            connection.execute(
                sa.text("""
                    INSERT INTO doc_template_schema.document_templates
                        (namespace, name, display_name, version, template_content, access_scope)
                    VALUES ('default', 'fresh-template', 'Fresh Template', '1.0.0', '<html/>', 'PUBLIC')
                """)
            )
            fresh_audience = connection.scalar(
                sa.text("""
                    SELECT audience::text
                    FROM doc_template_schema.document_templates
                    WHERE name = 'fresh-template'
                """)
            )
    finally:
        command.upgrade(config, "head")
        engine.dispose()

    assert enum_values == ["UNSPECIFIED", "DOCUMENT", "INTERNAL"]
    assert columns == [
        ("audience", "NO", "'DOCUMENT'::doc_template_schema.template_audience_enum"),
        ("display_name", "NO", None),
    ]
    assert fresh_audience == "DOCUMENT"
