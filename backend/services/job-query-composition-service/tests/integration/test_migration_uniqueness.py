"""Fresh-schema regression for canonical query location persistence."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from job_query_composition_service.db.models import IngestionQuery as DBIngestionQuery
from sqlalchemy.exc import IntegrityError

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

_SERVICE_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = "job_query_schema"


def _config(sync_url: str) -> Config:
    config = Config(str(_SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    config.set_main_option("path_separator", "os")
    return config


def test_fresh_upgrade_enforces_canonical_location_shape_and_uniqueness(
    postgres_container: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The initial schema requires a location array and rejects an exact duplicate."""
    sync_url = postgres_container.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    monkeypatch.setenv("DATABASE_URL", sync_url)
    engine = sa.create_engine(sync_url)
    config = _config(sync_url)

    with engine.begin() as connection:
        connection.execute(sa.text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
    command.upgrade(config, "head")

    canonical_index = next(
        index
        for index in sa.inspect(engine).get_indexes("ingestion_queries", schema=_SCHEMA)
        if index["name"] == "uq_ingestion_queries_canonical"
    )
    assert canonical_index["unique"] is True
    assert canonical_index["column_names"] == ["search_keywords", "locations"]

    table = cast("sa.Table", DBIngestionQuery.__table__)
    model_check = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint) and constraint.name == "chk_locations_json_array"
    )
    assert str(model_check.sqltext) == "locations IS JSON ARRAY"

    insert = sa.text(
        f"""
        INSERT INTO {_SCHEMA}.ingestion_queries (id, search_keywords, locations)
        VALUES (:id, ARRAY['python', 'backend'], CAST(:locations AS jsonb))
        """
    )
    locations = '[{"country":"USA","city":"new york"}]'
    with engine.begin() as connection:
        connection.execute(insert, {"id": uuid.uuid4(), "locations": locations})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(insert, {"id": uuid.uuid4(), "locations": locations})
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert,
            {"id": uuid.uuid4(), "locations": '{"country":"USA","city":"new york"}'},
        )

    engine.dispose()
