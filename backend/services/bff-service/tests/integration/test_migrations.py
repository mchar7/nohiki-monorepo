"""Behavioral checks for the complete BFF Alembic upgrade/downgrade path."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from bff_service.db.models import ProfileProjection, RevokedAccessToken, RevokedSessionFamily, UserRevocationCutoff
from bff_service.db.models.base import SCHEMA_NAME
from sqlalchemy.dialects.postgresql import UUID

pytestmark = [pytest.mark.integration, pytest.mark.requires_docker]

_SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _alembic_config(sync_url: str) -> Config:
    config = Config(str(_SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_SERVICE_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    config.set_main_option("path_separator", "os")
    return config


def test_migrations_match_profile_model_and_reverse_cleanly(
    postgres_container: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Head exposes the indexed/profile schema the ORM needs, and base removes every application table."""
    sync_url = postgres_container.replace("postgresql+asyncpg://", "postgresql+psycopg://")
    monkeypatch.setenv("DATABASE_URL", sync_url)
    config = _alembic_config(sync_url)
    engine = sa.create_engine(sync_url)

    with engine.begin() as connection:
        connection.execute(sa.text(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE"))

    command.upgrade(config, "head")
    inspector = sa.inspect(engine)
    posted_at_indexes = {
        index["name"] for index in inspector.get_indexes("job_listing_projections", schema=SCHEMA_NAME)
    }
    migrated_profile = {
        column["name"]: column for column in inspector.get_columns("profile_projections", schema=SCHEMA_NAME)
    }
    model_profile = ProfileProjection.__table__.columns

    assert "ix_job_listing_projections_posted_at" in posted_at_indexes
    assert isinstance(migrated_profile["tailoring_schema_id"]["type"], UUID)
    assert migrated_profile["tailoring_schema_id"]["nullable"] is model_profile.tailoring_schema_id.nullable
    assert isinstance(migrated_profile["is_active"]["type"], sa.Boolean)
    assert migrated_profile["is_active"]["nullable"] is model_profile.is_active.nullable
    revoked_tokens = {
        column["name"]: column for column in inspector.get_columns("revoked_access_tokens", schema=SCHEMA_NAME)
    }
    revocation_cutoffs = {
        column["name"]: column for column in inspector.get_columns("user_revocation_cutoffs", schema=SCHEMA_NAME)
    }
    revoked_families = {
        column["name"]: column for column in inspector.get_columns("revoked_session_families", schema=SCHEMA_NAME)
    }
    assert inspector.get_pk_constraint("revoked_access_tokens", schema=SCHEMA_NAME)["constrained_columns"] == ["jti"]
    assert inspector.get_pk_constraint("user_revocation_cutoffs", schema=SCHEMA_NAME)["constrained_columns"] == [
        "user_id"
    ]
    assert inspector.get_pk_constraint("revoked_session_families", schema=SCHEMA_NAME)["constrained_columns"] == [
        "family_id"
    ]
    assert {index["name"] for index in inspector.get_indexes("revoked_access_tokens", schema=SCHEMA_NAME)} == {
        "ix_revoked_access_tokens_expires_at"
    }
    assert {index["name"] for index in inspector.get_indexes("user_revocation_cutoffs", schema=SCHEMA_NAME)} == {
        "ix_user_revocation_cutoffs_expires_at"
    }
    assert {index["name"] for index in inspector.get_indexes("revoked_session_families", schema=SCHEMA_NAME)} == {
        "ix_revoked_session_families_expires_at"
    }
    for migrated, model in (
        (revoked_tokens, RevokedAccessToken.__table__.columns),
        (revocation_cutoffs, UserRevocationCutoff.__table__.columns),
        (revoked_families, RevokedSessionFamily.__table__.columns),
    ):
        assert set(migrated) == set(model.keys())
        for name, column in migrated.items():
            assert column["nullable"] is model[name].nullable
            assert isinstance(column["type"], type(model[name].type))
    assert set(revocation_cutoffs) == {"user_id", "revoked_before", "expires_at", "is_permanent"}
    assert isinstance(revoked_tokens["expires_at"]["type"], sa.DateTime)
    assert revoked_tokens["expires_at"]["type"].timezone is True
    assert isinstance(revocation_cutoffs["revoked_before"]["type"], sa.DateTime)
    assert revocation_cutoffs["revoked_before"]["type"].timezone is True
    assert isinstance(revocation_cutoffs["expires_at"]["type"], sa.DateTime)
    assert revocation_cutoffs["expires_at"]["type"].timezone is True
    assert isinstance(revocation_cutoffs["is_permanent"]["type"], sa.Boolean)
    assert isinstance(revoked_families["revoked_before"]["type"], sa.DateTime)
    assert revoked_families["revoked_before"]["type"].timezone is True
    assert isinstance(revoked_families["expires_at"]["type"], sa.DateTime)
    assert revoked_families["expires_at"]["type"].timezone is True

    command.downgrade(config, "001")
    tables_after_revocation_downgrade = set(sa.inspect(engine).get_table_names(schema=SCHEMA_NAME))
    assert "revoked_access_tokens" not in tables_after_revocation_downgrade
    assert "user_revocation_cutoffs" not in tables_after_revocation_downgrade
    assert "revoked_session_families" not in tables_after_revocation_downgrade

    command.downgrade(config, "base")
    remaining_application_tables = set(sa.inspect(engine).get_table_names(schema=SCHEMA_NAME)) - {"alembic_version"}
    engine.dispose()

    assert remaining_application_tables == set()
